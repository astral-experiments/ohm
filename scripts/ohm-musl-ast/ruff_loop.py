"""Trace the ordinary Ruff endpoint and read linked products in a separate validation command."""
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sdk as s

sys.path.insert(0, str(s.SCRIPTS / "ohm-gnu-ty-input-census"))
import census

T = s.MUSL
W = s.DEST / "work"
R = W / "ruff"
LOG = s.LOG
REV = "93526150df078af7dd8fc4226cdcc469539d2001"
TREE = "62d3f106c5e41f6022847f26ff8c7dc00139f7b1"
LOCK = "c9e345325bec5ff08dbbe3916edd39ad0c3d1c7797a8c241ae32f62754e764bf"
FILES = ["crates/ruff_python_ast/src/visitor.rs","crates/ruff_python_ast/src/visitor/transformer.rs"]
PATCH = s.HERE / "ruff-27404.patch"
BAD = "OHM_MUSL_AST_UNDEFINED_VISITOR"
N = "ruff_python_ast"
TEST = "identifier::tests::extract_global_names"
WANT = {"old": "elif predicates 2, elif/else clauses 0\n", "new": "elif predicates 1, elif/else clauses 2\n"}


def call(argv, env, cwd=R, rc=0):
    p = subprocess.run(argv, cwd=cwd, env=env, capture_output=True)
    if p.returncode != rc:
        raise RuntimeError(f"{argv} returned {p.returncode}: {p.stderr[-3000:]}")
    return p.stdout


def prepare():
    W.mkdir()
    home = W/"home"
    home.mkdir()
    proxy = Path(shutil.which("rustup")).resolve(strict=True)
    shims = W/"proxies"
    shims.mkdir()
    for name in ("cargo","rustc","rustdoc","rustup"):
        (shims/name).symlink_to(proxy)
    e = {"HOME": str(home), "PATH":f"{shims}:/usr/local/bin:/usr/bin:/bin","RUSTUP_HOME":str(s.rt.ROOT/"rustup"),
         "RUSTUP_AUTO_INSTALL":"0","CARGO_HOME":str(W/"cargo-home"),"CARGO_TARGET_DIR":str(W/"target"),
         "CARGO_BUILD_BUILD_DIR":str(W/"shared"),"CARGO_TERM_COLOR":"never","CARGO_CACHE_AUTO_CLEAN_FREQUENCY":"never",
         "GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":os.devnull,"LC_ALL":"C","TZ":"UTC"}
    tools = {}
    for name,flags in (("rustc","-vV"),("cargo","-Vv"),("rustdoc","-vV")):
        path = Path(call(["rustup","which","--toolchain","ohm",name],e,W).decode().strip())
        assert path.samefile(s.rt.SDK/"bin"/name)
        tools[name] = [str(path),s.sha(path),call([name,"+ohm",flags],e,W).decode()]
    assert s.SEAL["cargo"]["git"] in tools["cargo"][2]
    sysroot = Path(call(["rustc","+ohm","--print","sysroot"],e,W).decode().strip())
    assert sysroot.samefile(s.rt.SDK)
    cfg = call(["rustc","+ohm","--target",T,"--print","cfg"],e,W).decode().splitlines()
    assert {'target_arch="x86_64"','target_env="musl"','target_feature="crt-static"'}<=set(cfg)
    f=W/"sdk_smoke.rs"
    f.write_text('/// The cross SDK can document real std.\npub fn answer() -> String { String::from("musl") }\n')
    call(["rustdoc","+ohm","--target",T,"--crate-name","musl_sdk",f,"-o",W/"docs"],e,W)
    assert (W/"docs/musl_sdk/fn.answer.html").is_file()
    call(["git","init","--quiet",R],e,W)
    call(["git","fetch","--depth=1","--no-tags","https://github.com/astral-sh/ruff.git",REV],e)
    call(["git","checkout","--quiet","--detach","FETCH_HEAD"],e)
    assert call(["git","rev-parse","HEAD^{tree}"],e).decode().strip()==TREE and s.sha(R/"Cargo.lock")==LOCK
    assert s.sha(PATCH)=="0b8aa38cc0ed6d4c59dd640467e6cb1fc301c422fc830e2750799165baf654d4"
    assert s.sha(s.HERE/"PLAN.md")=="f5d5776020bee6e1d08980e891aa38410a8c4b6fe1fb39746784e9a438eba57a"
    call(["git","apply","--reverse","--check",PATCH],e)
    call(["cargo","+ohm","fetch","--locked","--target",T],e)
    src = W/"client.rs"; shutil.copyfile(s.HERE/"client.rs",src)
    archives = {f.name:s.sha(f) for f in (W/"cargo-home/registry/cache").glob("*/*.crate")}
    assert archives and s.sha(R/"Cargo.lock")==LOCK
    s.save(LOG/"subjects.json",{"source":REV,"tree":TREE,"lock":LOCK,"registry":archives,
        "fixed_env":e,"tools":tools,"cfg":cfg,"rustdoc_smoke":s.sha(W/"docs/musl_sdk/fn.answer.html"),
        "client":s.sha(src),"plan":s.sha(s.HERE/"PLAN.md"),"compiler_sdk":s.sha(LOG/"sdk.json"),
        "ordinary_linker_configuration":call(["git","show","HEAD:.cargo/config.toml"],e).decode()})
    e["CARGO_NET_OFFLINE"]="true"
    return e


def tree_bytes():
    seen=set(); totals=collections.Counter(); extra=collections.Counter(); paths=0
    for name in ("target","shared"):
        for parent,_,files in os.walk(W/name):
            for child in files:
                p=Path(parent)/child
                st=p.lstat()
                k=(st.st_dev,st.st_ino)
                paths+=1
                if k not in seen:
                    totals[name]+=st.st_blocks*512
                    seen.add(k)
                else:
                    extra[name]+=1
    return {"allocated_bytes_once":sum(totals.values()),"private_then_shared":dict(totals),
            "duplicate_hardlink_paths":dict(extra),"paths":paths,"file_inodes":len(seen)}


def elf(path):
    buf=path.read_bytes()
    assert buf[:7]==b"\x7fELF\x02\x01\x01" and int.from_bytes(buf[18:20],"little")==62
    programs=subprocess.check_output(["readelf","-lW",path],text=True)
    dynamic=subprocess.check_output(["readelf","-dW",path],text=True)
    assert "INTERP" not in programs and "(NEEDED)" not in dynamic, (path,programs,dynamic)
    dest=LOG/"images"/(hashlib.sha256(buf).hexdigest()+".zst")
    if not dest.exists():
        dest.parent.mkdir(exist_ok=True)
        subprocess.run(["zstd","-q","-3",path,"-o",dest],check=True)
    return {"sha256":s.sha(path),"bytes":len(buf),"compressed":s.sha(dest)}


def training(rustcs):
    x,=[r for r in rustcs if r["crate"]==N and not r["link_only"] and "--test" not in r["argv"]]
    a=x["argv"]
    out,=census.flags(a,"--out-dir")
    postfix,=[v.split("=",1)[1] for v in census.flags(a,"-C") if v.startswith("extra-filename=")]
    return Path(out)/("lib"+N+postfix+".rlib"),list(census.flags(a,"-L"))


def client(trained, typed, out, e, expected):
    archive,search=trained
    assert typed.samefile(archive) or s.sha(typed)==s.sha(archive)
    args=["rustc","+ohm","--edition","2024","--crate-name","qa_musl_ast","--target",T,"-Cdebuginfo=0",
          "--extern",N+"="+str(archive),"--extern",N+"="+str(archive.with_suffix(".rmeta"))]
    for d in search: args+=["-L",d]
    exe=W/"qa-musl-ast"
    args.extend([str(W/"client.rs"),"-o",str(exe)])
    call(["strace","-f","-qq","-s","131072","-e","trace=execve,execveat","-o",str(out/"client.exec"),*args],e)
    trace=(out/"client.exec").read_bytes();census.blob(out/"client-exec.gz",trace);(out/"client.exec").unlink()
    got=call([exe],e).decode()
    assert got==expected,(got,expected)
    return {"client":elf(exe),"stdout":got,"argv":args,"rlib_sha256":s.sha(archive),"rmeta_sha256":s.sha(archive.with_suffix(".rmeta"))}


def study(mode,e):
    cmd=["cargo","+ohm",mode,"--locked","--offline","-p",N,"--lib",*(["--no-run"] if mode=="test" else []),
         "--target",T,"-j4","--message-format=json"]
    out=LOG/mode;out.mkdir()
    census.qualify.rt.SDK=s.rt.SDK
    trace_work=W/(mode+"-observer");trace_work.mkdir()
    assert not (W/"target").exists() and not (W/"shared").exists()
    sources=[]; validations={}; counts={}; trained=None
    def visit(phase, expected):
        nonlocal trained
        dest,messages,k=census.trace_build(phase,trace_work,out,R,e,cmd,101 if not expected else 0)
        typed=[m for m in messages if m["reason"]=="compiler-artifact"]
        owners=collections.defaultdict(set)
        for m in typed:owners[m["target"]["name"]].add(m["target"]["src_path"])
        roster=[]
        for row in k["rustcs"]:
            if "--out-dir" not in row["argv"]:continue
            _,facts=census.describe(row,R,(W/"target",W/"shared"),dest,owners)
            roster.append(facts)
        s.save(dest/"emitted.json",roster)
        s.save(dest/"trust-markers.json",{str(p):p.read_bytes()[:4096].hex()
            for n in ("target","shared") for p in (W/n).rglob(".ohm-worktree-seed*") if p.is_file()})
        counts[phase]={"typed":len(typed),"typed_fresh":sum(x["fresh"] for x in typed),
            "emitted":[[x["crate"],x["target"],x["marker"],x["link_only"]] for x in roster],
            "link_tools":[[r["path"],r["argv"]] for r in k["link_tools"]],"disk":tree_bytes()}
        if not expected:
            errors=[m["message"] for m in messages if m["reason"]=="compiler-message" and m["message"].get("level")=="error"]
            assert any((m.get("code") or {}).get("code")=="E0425" and BAD in m["rendered"] for m in errors)
            return
        assert all(r["terminal"]==[0] for r in k["rustcs"])
        if phase in ("old","empty"):
            assert not any(x["fresh"] for x in typed), "independent trees were not empty"
        unit,=[m for m in typed if m["target"]["name"]==N and m["profile"]["test"]==(mode=="test")]
        if mode=="build":
            arc,=[Path(p) for p in unit["filenames"] if p.endswith(".rlib")]
            if phase in ("old","empty"):trained=training(k["rustcs"])
            validations[phase]=client(trained,arc,dest,e,WANT[expected])
        else:
            exe=Path(unit["executable"])
            listed=call([exe,"--list","--format","terse"],e)
            names=sorted(l.removesuffix(": test") for l in listed.decode().splitlines() if l.endswith(": test"))
            assert TEST in names and len(names)==len(set(names)) and len(names)>1
            result=call([exe,"--exact",TEST,"--test-threads=1"],e)
            assert b"1 passed; 0 failed" in result
            census.blob(dest/"test-list.gz",listed);census.blob(dest/"test-control.gz",result)
            validations[phase]={"client":elf(exe),"stdout":names}
        print(mode,phase,"full",[(x["crate"],x["target"],x["marker"]) for x in roster if not x["link_only"]] if phase not in ("old","empty") else len(roster),
              "link tools",[Path(r["path"]).name for r in k["link_tools"]],flush=True)
    def park(label):
        where=W/"closed"/(mode+"-"+label);where.mkdir(parents=True)
        for key in ("target","shared"):
            p=W/key
            assert p.is_dir() and not p.is_symlink()
            p.rename(where/key)
    def snapshot(phase):
        sources.append([phase,{n:s.sha(R/n) for n in FILES},call(["git","diff","--name-only"],e).decode().splitlines()])
    call(["git","apply","--reverse",PATCH],e)
    assert sorted(call(["git","diff","--name-only"],e).decode().splitlines())==sorted(FILES)
    snapshot("old");visit("old","old")
    call(["git","apply",PATCH],e);assert call(["git","diff","--name-only"],e)==b""
    snapshot("edited");visit("edited","new");visit("unchanged","new");visit("second-unchanged","new")
    with (R/FILES[0]).open("a") as f:f.write("\nconst _: usize = "+BAD+";\n")
    snapshot("invalid");visit("invalid",None)
    call(["git","restore","--worktree","--",FILES[0]],e)
    snapshot("repair");visit("repair","new")
    park("warm");visit("empty","new");park("empty")
    assert len({json.dumps(v["stdout"],sort_keys=True) for k,v in validations.items() if k!="old"})==1
    same={k:v["client"]==validations["empty"]["client"] for k,v in validations.items() if k!="old"}
    assert mode!="build" or validations["old"]["stdout"]!=validations["empty"]["stdout"]
    s.save(out/"terminal.json",{"cmd":cmd,"sources":sources,"outputs":validations,"visits":counts,"same_entire_elf":same,
        "full_byte_gate_passed":all(same.values()),"independent_edit_behavior":mode=="build"})
    return all(same.values())


if __name__=="__main__":
    e=prepare()
    # Enroll both roles before opening either result. Keep a failed byte gate visible after the other role completes.
    results={role:study(role,e) for role in ("build","test")}
    import native
    results["native"]=native.screen(e)
    s.save(LOG/"terminal.json",{"endpoints":results})
    assert all(results.values()),results
