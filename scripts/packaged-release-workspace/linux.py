"""Replay the preserved 50-output Linux enrollment without mutating the public Ruff checkout."""
from __future__ import annotations
import gzip
import json
import mmap
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from linux_common import *
from packages import RELEASES,save,sha

def gz(path,body):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        with path.open("xb") as f:f.write(gzip.compress(body,compresslevel=1,mtime=0))
    return digest(body)

def room(root,minimum):
    free=shutil.disk_usage(root).free
    need(free>=minimum*2**30,f"STOP: native runner free bytes {free} < {minimum} GiB")
    return free

def command(args,**kw):return subprocess.check_output(args,**kw)
def git(repo,*args):return command(["git","-C",repo,*args])
def selected(root):
    p=root/"source";need(p.is_dir() and git(p,"rev-parse","HEAD").decode().strip()==RUFF,"unknown source root");return p

def environment(root,role,slot):
    home=slot/"home";tmp=slot/"tmp"
    home.mkdir(parents=True,exist_ok=True);tmp.mkdir(exist_ok=True)
    up=Path(shutil.which("rustup")).absolute()
    u=root/("rustup-"+role)/"toolchains";u.mkdir(parents=True,exist_ok=True)
    if not (u/"ohm").exists():(u/"ohm").symlink_to(root/("sdk-"+role),target_is_directory=True)
    need((u/"ohm").samefile(root/("sdk-"+role)),"wrong rustup alias")
    return {"HOME":str(home),"USER":os.environ.get("USER","runner"),"PATH":os.pathsep.join([str(up.parent),"/usr/local/bin","/usr/bin","/bin"]),
            "CARGO_TARGET_DIR":str(slot/"target"),"CARGO_BUILD_BUILD_DIR":str(slot/"shared"),"CARGO_HOME":str(slot/"cargo-home"),
            "RUSTUP_HOME":str(u.parent),"RUSTUP_AUTO_INSTALL":"0","CARGO_BUILD_JOBS":"8","GIT_OPTIONAL_LOCKS":"0",
            "CARGO_NET_OFFLINE":"true","CARGO_TERM_COLOR":"never","LANG":"C.UTF-8","LC_ALL":"C.UTF-8","TMPDIR":str(tmp)}

def replace(repo,state):
    git(repo,"restore","--source=HEAD","--worktree","--",".")
    if state=="reversed":git(repo,"apply","--reverse",str(FIX/"historical.patch"))
    expected=ORACLE["source"]
    paths=set(git(repo,"diff","--name-only").decode().splitlines())
    need(paths==(set(expected) if state=="reversed" else set()),"different actual historical source edit")
    for p,h in expected.items():
        f=repo/p;need((sha(f) if f.is_file() else None)==h[state],"wrong real source bytes "+p)
    need(sha(repo/"Cargo.lock")==LOCK,"Cargo.lock changed")

def seed(root):
    room(root,65)
    repo=root/"source";subprocess.run(["git","init","-q",repo],check=True)
    for depth,rev in ((1,RUFF),(2,HISTORY)):
        git(repo,"fetch","-q","--no-tags","--depth="+str(depth),"https://github.com/astral-sh/ruff.git",rev)
    git(repo,"switch","-q","--detach",RUFF)
    patch=git(repo,"diff","--binary","--abbrev=10",HISTORY+"^",HISTORY)
    need(git(repo,"rev-parse","HEAD^{tree}").decode().strip()==TREE and patch==(FIX/"historical.patch").read_bytes() and
         digest(patch)==ORACLE["patch_sha256"] and sha(repo/"Cargo.lock")==LOCK,"public Git fixture differs from the frozen original")
    replace(repo,"reversed");replace(repo,"original")
    donor=root/"donor";env=environment(root,"20",donor);env.pop("CARGO_NET_OFFLINE")
    subprocess.run(["cargo","+ohm","fetch","--locked"],cwd=repo,env=env,check=True,timeout=1200)
    reg=donor/"cargo-home"/"registry"
    locks={v["name"]+"-"+v["version"]+".crate":v["checksum"] for v in tomllib.loads((repo/"Cargo.lock").read_text())["package"] if "checksum" in v}
    actual={p.name:sha(p) for p in reg.glob("cache/*/*.crate")}
    need(len(locks)==498 and actual==locks,"the 498 frozen Ruff registry archives differ")
    shared=root/"receipts/shared";shared.mkdir(exist_ok=True)
    snapshot=(repo/SNAPSHOT).read_bytes()
    need(snapshot==git(repo,"show","HEAD:"+SNAPSHOT) and digest(snapshot)==SNAPSHOT_SHA and
         digest(snapshot.split(b"\n---\n",1)[1])==SNAPSHOT_BODY_SHA,"unexpected pinned e2e snapshot")
    gz(shared/"e2e-snapshot.snap.gz",snapshot)
    save(shared/"source.json",{"head":RUFF,"tree":TREE,"historical_commit":HISTORY,"lock":LOCK,"patch":digest(patch),"registry":actual,
                              "historical_fifty":sha(FIX/"fifty.json"),"original_archive":ENROLL["source_archive_sha256"]})
    gz(shared/"historical.patch.gz",patch)
    for f in ("ordinary.rs","ill-typed.rs","ret505.py","fifty.json","source-oracles.json"):
        gz(shared/(f+".gz"),(FIX/f).read_bytes())

def inode(p):
    s=p.stat();return [s.st_dev,s.st_ino]
def fx(p):
    p=p.resolve(strict=True);return {"physical":str(p),"sha256":sha(p),"dev_ino":inode(p)}
def tools(root,role,env):
    sdk=root/("sdk-"+role);dist=json.loads((root/"receipts"/role/"installed.json").read_bytes())
    p={"cargo":sdk/"bin/cargo","rustc":sdk/"bin/rustc","wild":sdk/"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd",
       "system_ld":Path("/usr/bin/ld.bfd")}
    out={k:fx(v) for k,v in p.items()};loaded={}
    for k in ("rustc","cargo","wild"):need(out[k]["sha256"]==dist[str(p[k].relative_to(sdk))],"different installed "+k)
    for k,cmd in (("rustc",["rustc","+ohm","-vV"]),("cargo",["cargo","+ohm","-Vv"]),("sysroot",["rustc","+ohm","--print","sysroot"])):
        loaded[k]=command(cmd,env=env,text=True).strip()
    need(REAL_RUST[role] in loaded["rustc"] and "2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c" in loaded["cargo"] and
         Path(loaded["sysroot"]).samefile(sdk),"wrong actually invoked package")
    lib,=(sdk/"lib").glob("librustc_driver*.so");rec=root/"receipts"/role
    obj=rec/"driver-proof.o";proc=subprocess.run(["rustc","+ohm","--crate-name","qa_native_owner","--crate-type=lib","--emit=obj","-o",obj,"-"],
            env={**env,"LD_DEBUG":"libs"},input=b"pub fn witness(n:u32)->u32 { n.wrapping_add(29) }\n",capture_output=True,timeout=100)
    locs=[Path(q.decode().strip()) for q in re.findall(rb"calling init:\s*([^\r\n]*librustc_driver[^\r\n]*?\.so)\s*\n",proc.stderr)]
    need(proc.returncode==0 and len(locs)==1 and locs[0].samefile(lib) and fx(lib)["sha256"]==dist[str(lib.relative_to(sdk))],
         "actual ELF loader did not initialize the enrolled compiler driver")
    gz(rec/"driver-loader.log.gz",proc.stderr);save(rec/"tools.json",{"tools":out,"versions":loaded,"physical_driver":fx(lib),"object":sha(obj)})
    return out

class Vault:
    def __init__(self,p):
        self.p=p;self.p.mkdir();self.bytes=0
    def add(self,path,info):
        dst=self.p/info["sha256"]
        new=not dst.exists()
        if new:
            need(self.bytes+info["size"]<=33*2**30,"STOP: original-ELF scratch custody exceeds 33 GiB")
            room(self.p,60)
            shutil.copyfile(path,dst);self.bytes+=info["size"]
        result=subprocess.run(["/usr/bin/cmp","-s","--",path,dst])
        need(result.returncode==0 and path.stat().st_size==dst.stat().st_size==info["size"],"captured full ELF differs")
        return {"physical_cmp":0,"first_vault_copy":new}
    def archive(self,out,h):
        index=out/"images"/(h+".json")
        if index.exists():return
        orig=self.p/h;need(orig.is_file() and sha(orig)==h,"missing retained physical ELF")
        chunks=[]
        with orig.open("rb") as f:
            while body:=f.read(CHUNK):
                v=digest(body);gz(out/"blocks"/(v+".gz"),body);chunks.append([v,len(body)])
        save(index,{"sha256":h,"size":orig.stat().st_size,"chunks":chunks})

def inspect(path):
    s=path.stat()
    with path.open("rb") as f:
        with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m:info=elf_bytes(m)
    h=command(["/usr/bin/sha256sum","--",path],text=True).split()[0]
    now=path.stat();need(h==info["sha256"] and
         (now.st_dev,now.st_ino,now.st_size,now.st_mtime_ns,now.st_ctime_ns)==(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns),
         "independent complete ELF readers disagree")
    return {**info,"gnu_sha256":h,"path":str(path),"physical":str(path.resolve(strict=True)),"dev_ino":inode(path)}

def real_program(exe,argv,env,cwd,out,name):
    proc=subprocess.run([str(exe),*argv],env=env,cwd=cwd,capture_output=True,timeout=240)
    gz(out/(name+".stdout.gz"),proc.stdout);gz(out/(name+".stderr.gz"),proc.stderr)
    save(out/(name+".json"),{"exe":str(exe),"sha256":sha(exe),"argv":argv,"exit":proc.returncode})
    need(proc.returncode==0,"actual native reader failed "+name)
    return proc.stdout

def behaviors(repo,out,env,arts,returned,state):
    lib={Path(p) for a in arts if a["target"]["name"]=="ruff_python_trivia" and a["target"]["kind"]==["lib"]
         for p in a["filenames"] if p.endswith(".rlib")}
    deps={Path(p).parent for a in arts for p in a["filenames"] if p.endswith((".rlib",".rmeta",".so"))}
    need(len(lib)==2 and deps,"different physical trivia readers")
    check=[]
    with tempfile.TemporaryDirectory(dir=env["TMPDIR"]) as t:
        for i,archive in enumerate(sorted(lib)):
            args=["rustc","+ohm","--edition=2024","--extern","ruff_python_trivia="+str(archive)]
            for directory in sorted(deps):args+=["-L","dependency="+str(directory)]
            exe=Path(t)/("reader-"+str(i))
            compiled=subprocess.run(args+[str(FIX/"ordinary.rs"),"-o",str(exe)],env=env,cwd=repo,capture_output=True,timeout=180)
            gz(out/f"ordinary-{i}.compile.stdout.gz",compiled.stdout);gz(out/f"ordinary-{i}.compile.stderr.gz",compiled.stderr)
            need(compiled.returncode==0,"actual trivia consumer did not compile")
            body=real_program(exe,[],env,repo,out,f"ordinary-{i}")
            need(body.decode()==ORACLE["oracles"][state],"actual constant source behavior is stale")
            invalid=subprocess.run(args+[str(FIX/"ill-typed.rs"),"--crate-name","invalid_consumer","--emit=metadata","--error-format=json","-o",str(exe)+".rmeta"],
                       env=env,cwd=repo,capture_output=True,timeout=180)
            gz(out/f"ordinary-{i}.invalid.stderr.gz",invalid.stderr)
            codes=[j["code"]["code"] for l in invalid.stderr.splitlines() if l.startswith(b"{") and (j:=json.loads(l)).get("code")]
            need(invalid.returncode==1 and codes==["E0308"],"invalid actual trivia consumer did not reject")
            check.append({"archive":str(archive),"archive_sha256":sha(archive),"ordinary_sha256":sha(exe),"stdout":digest(body),
                          "invalid_code":codes,"invalid_status":invalid.returncode})
    p=Path(returned[PARSER]["executable"])
    listing=real_program(p,["--list"],env,repo,out,"parser-list")
    choices=[v.decode().removesuffix(": test") for v in listing.splitlines() if v.endswith(b"::test_modes: test")]
    need(len(choices)==1 and b"1 passed; 0 failed" in real_program(p,["--exact",choices[0]],env,repo,out,"parser-case"),
         "wrong original parser test inventory or selected native verdict")
    e=Path(returned[E2E]["executable"]);cwd=repo/"crates/ty_server"
    # Only the separately-executed e2e reader needs Insta's real workspace.
    # Running its ordinary nested Cargo metadata would choose the repo's stock Rust.
    snapshot_env=env|{"INSTA_WORKSPACE_ROOT":str(repo),"INSTA_UPDATE":"no"}
    case_args=["--exact",RUN_CASE,"--test-threads=1"]
    cases=real_program(e,["--list","--format","terse"],snapshot_env,cwd,out,"e2e-list")
    need((RUN_CASE+": test").encode() in cases.splitlines() and
         b"1 passed; 0 failed" in real_program(e,case_args,snapshot_env,cwd,out,"e2e-case") and sha(repo/SNAPSHOT)==SNAPSHOT_SHA,
         "wrong real ty_server integration test or observable native verdict")
    with tempfile.TemporaryDirectory(dir=env["TMPDIR"]) as missing:
        negative=subprocess.run([str(e),*case_args],env=snapshot_env|{"INSTA_WORKSPACE_ROOT":missing},cwd=cwd,capture_output=True,timeout=240)
        gz(out/"e2e-missing.stdout.gz",negative.stdout);gz(out/"e2e-missing.stderr.gz",negative.stderr)
        need(negative.returncode==101 and b"0 passed; 1 failed" in negative.stdout and
             missing_snapshot_body(negative.stdout)==(repo/SNAPSHOT).read_bytes().split(b"\n---\n",1)[1] and
             not any(p.is_file() for p in Path(missing).rglob("*")),"real e2e did not refuse the empty snapshot root")
    save(out/"e2e-snapshot.json",{"source":SNAPSHOT,"sha256":SNAPSHOT_SHA,"native_test":RUN_CASE,"argv":case_args,"exe":str(e),"program_sha256":sha(e),
         "positive_runtime_env_changes":{"INSTA_WORKSPACE_ROOT":str(repo),"INSTA_UPDATE":"no"},"missing_root_exit":negative.returncode,"missing_root_body_sha256":SNAPSHOT_BODY_SHA})
    save(out/"behavior.json",{"libraries":check,"parser_case":choices[0],"parser_list":digest(listing),"e2e_case":RUN_CASE,
                             "e2e_list":digest(cases),"e2e_sha256":sha(e)})

def visit(root,role,slot,repo,out,phase,state,env,tool,vault):
    room(root,65);out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(dir=slot/"tmp") as t:
        temp=Path(t);trace=temp/"events";trace.mkdir()
        with (temp/"stdout").open("xb") as stdout,(temp/"stderr").open("xb") as stderr:
            proc=subprocess.Popen(["strace","-ff","-q","-s","262144","-e","trace=execve,execveat","-o",str(trace/"exec"),*CMD],
                                  env=env,cwd=repo,stdout=stdout,stderr=stderr,start_new_session=True)
            try:
                while proc.poll() is None:
                    room(root,60)
                    try:proc.wait(5)
                    except subprocess.TimeoutExpired:pass
            except BaseException:
                if proc.poll() is None:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                raise
        stream=(temp/"stdout").read_bytes();err=(temp/"stderr").read_bytes()
        gz(out/"cargo.stdout.gz",stream);gz(out/"cargo.stderr.gz",err);save(out/"exit.json",proc.returncode)
        lines=[]; aliases={}
        for tracefile in sorted(trace.glob("exec.*")):
            pid=int(tracefile.suffix[1:])
            for line in tracefile.read_bytes().splitlines():
                if line.startswith(b"execveat(") and line.endswith(b"= 0"):raise RuntimeError("successful execveat requires separate enrollment")
                if not line.startswith(b"execve(") or not line.endswith(b"= 0"):continue
                literal,args=event(line)
                if Path(literal).name in RELEVANT:
                    if literal not in aliases:aliases[literal]=fx(Path(literal))
                    lines.append([pid,line.decode()])
        gz(out/"kernel.json.gz",json.dumps(lines,separators=(",",":")).encode());save(out/"exec-aliases.json",aliases)
    need(proc.returncode==0,"real Cargo failed: "+err[-900:].decode(errors="replace"))
    arts,returned=outputs(stream);actual=native(lines,tool,aliases)
    physical={};by_output={};by_inode={}
    for u,entry in sorted(returned.items()):
        path=Path(entry["executable"])
        need(path.is_absolute() and str(path.resolve()).startswith(str(slot.resolve())+"/"),"returned executable outside owned roots")
        q=inspect(path)
        if u in SUBJECTS:q["vault"]=vault.add(path,q)
        by_output[str(path)]=u
        for name in entry["filenames"]:
            a=Path(name)
            if a.is_file() and a.samefile(path):by_output[str(a)]=u
        by_inode.setdefault(tuple(q["dev_ino"]),[]).append(u)
        physical[u]=q
    bind=[]
    for row in actual["wild"]:
        p=Path(row["output"]);u=by_output.get(str(p))
        if not u and p.is_file():
            matches=by_inode.get(tuple(inode(p)),[]);need(len(matches)<2,"ambiguous returned ELF inode")
            if matches:u=matches[0]
        if u:
            need(p.is_file() and p.samefile(physical[u]["path"]),"Wild output does not name that actual returned ELF")
        elif p.is_file() and p.is_relative_to(slot) and not(p.suffix==".so" or p.name.startswith("build_script_") or
                 p.name.startswith("build-script-")):
            # Some dependency tools are real final binaries outside Cargo's returned runnable programs.
            # Do not silently treat a same-named historical application as skipped.
            stem=re.sub(r"-[0-9a-f]{12,16}$","",p.name).replace("-","_")
            need(stem not in {returned[k]["target"]["name"].replace("-","_") for k in SUBJECTS},
                 "unmapped output with the name of a historical ELF: "+str(p))
        bind.append({**row,"unit":u,"dev_ino":inode(p) if p.is_file() else None})
    save(out/"observed.json",{"phase":phase,"state":state,"argv":CMD,"env":env,"source":{p:(sha(repo/p) if (repo/p).is_file() else None) for p in ORACLE["source"]},
                             "actual":actual,"bound_wild":bind,"outputs":physical,"available":room(root,60)})
    behaviors(repo,out,env,arts,returned,state)
    print(role,phase,"native counts",actual["counts"],"historical links",sum(x["unit"] in SUBJECTS for x in bind),flush=True)
    return physical

def fresh(root,role):
    slot=root/"slot";need(not slot.exists(),"foreign or previously warmed slot")
    slot.mkdir();(slot/".owned-by-release-50").write_text(role)
    for n in ("target","shared"):(slot/n).mkdir()
    home=slot/"cargo-home";home.mkdir()
    for n in ("registry","git"):
        src=root/"donor/cargo-home"/n
        if src.is_dir():subprocess.run(["cp","-a","--reflink=auto",src,home/n],check=True)
    env=environment(root,role,slot)
    need(all(not list((slot/n).iterdir()) for n in ("target","shared")),"nonempty original reference")
    return slot,env

def retire(root,role,slot):
    need(slot==root/"slot" and not slot.is_symlink() and (slot/".owned-by-release-50").read_text()==role,"unsafe private storage retirement")
    shutil.rmtree(slot)

def run(root,role):
    root=root.resolve(strict=True);repo=selected(root);out=root/"receipts"/role
    preflight=room(root,65)
    vault=Vault(root/("ephemeral-elf-compare-"+role))
    sources={}
    for seq,steps in (("visit",STEPS),("empty-original",(("clean-original","original"),)),("empty-reversed",(("clean-reversed","reversed"),))):
        slot,env=fresh(root,role)
        if seq=="visit":tool=tools(root,role,env)
        prev=None
        for phase,state in steps:
            if state!=prev:replace(repo,state)
            prev=state
            sources[phase]=visit(root,role,slot,repo,out/"native"/phase,phase,state,env,tool,vault)
        retire(root,role,slot)
    replace(repo,"original")
    pairs={};preserve=set()
    for phase,state in STEPS:
        actual=sources[phase];ref=sources["clean-"+state];table={}
        for u in SUBJECTS:
            ah=actual[u]["sha256"];bh=ref[u]["sha256"]
            cmp=subprocess.run(["/usr/bin/cmp","-s","--",vault.p/ah,vault.p/bh])
            need(cmp.returncode in (0,1) and (cmp.returncode==0)==(ah==bh),"independent physical cmp disagrees with complete hashes")
            if cmp.returncode or u in SENTINELS:preserve.update((ah,bh))
            table[u]={"actual":ah,"clean":bh,"whole_file_cmp_exit":cmp.returncode,"size":actual[u]["size"],
                      "different_allocated_sections":sorted(k for k in actual[u]["file_backed_allocated"].keys()|ref[u]["file_backed_allocated"].keys()
                                                           if actual[u]["file_backed_allocated"].get(k)!=ref[u]["file_backed_allocated"].get(k))}
        pairs[phase]=table
    for h in sorted(preserve):
        vault.archive(out/"portable-elfs",h)
        wire=sum(p.stat().st_size for p in (out/"portable-elfs/blocks").glob("*.gz"))
        need(wire<3*2**30,"STOP: portable original ELF packet exceeded 3 GiB; no partial admission")
    save(out/"own-clean-full-cmp.json",pairs)
    save(out/"terminal.json",{"room_before":preflight,"complete_file_comparisons":sum(map(len,pairs.values())),
         "vault_unique_bytes":vault.bytes,"full_exceptions_and_controls":sorted(preserve),"initial_source_states":STEPS,
         "relay":"actual packaged Wild observes each real linker without wrappers","native_call_count_excludes_consumers":True})
    need(vault.p.parent==root and vault.p.name=="ephemeral-elf-compare-"+role and not vault.p.is_symlink(),"wrong private ELF scratch")
    shutil.rmtree(vault.p)

if __name__=="__main__":
    action=sys.argv[1];root=Path(sys.argv[2]).resolve(strict=True)
    need(root.name=="packaged-linux-50" and root.parent==Path(os.environ["RUNNER_TEMP"]).resolve(strict=True),"foreign developer root")
    try:
        if action=="seed":seed(root)
        else:need(action in ("20","21"),"unknown release");run(root,action)
    except Exception as exc:
        import traceback
        save(root/"receipts"/("failure-"+action+".json"),{"type":type(exc).__name__,"message":str(exc),"traceback":traceback.format_exc()})
        raise
