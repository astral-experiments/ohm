"""Counterbalance the ordinary Ruff 29697 editor workflow on the registered source pair."""
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess as sp
import sys
from pathlib import Path

here=Path(__file__).resolve().parent
sys.path.insert(0,str(here.parent.parent/"ruff-foreign-span-observer"))
sys.path.insert(0,str(here))
import worker as w
from kit import acquire

old="157caa55a51ebae4fa541d31697e3af9a6c32ccf"
new="bfa2407e98ee1343caeefd02b4b69043509baa8c"
lock="b9cbcf372621bf3aa25ba0985e0b066b8c70624d51ecc50cc2f29b98712e6f40"
command=["cargo","+ohm","test","-p","ty_server","--test","e2e","--no-run","--locked","--offline","-j4","--message-format=json"]
focus={"ty_project","ty_ide","ty_server","e2e"}
test_names="34acb828168117d5f9e50edf4baa07e4153bd2f86d3e48514c1ae8cb21cc1f2f"
def require(ok, why):
    if not ok:raise ValueError(why)
def state(revision):
    w.git("switch","--detach",revision)
    require(w.git("rev-parse","HEAD")==revision and not w.git("status","--porcelain") and w.hf(w.work/"Cargo.lock")==lock,"wrong source or lock")
def remove_outputs():
    for path in (w.target,w.shared):
        require(path.parent==w.root and not path.is_symlink(),"unsafe output path")
        if path.exists():shutil.rmtree(path)
def keep(path):
    path=Path(path);sha=w.hf(path);body=w.proof/"native"/(sha+".zst");body.parent.mkdir(exist_ok=True)
    if not body.exists():
        with body.open("xb")as f:sp.run(["zstd","-q","-c","-3",path],stdout=f,check=True)
    return {"sha256":sha,"bytes":path.stat().st_size}
def record_file(path):
    p=Path(path);s=p.stat();return dict(sha256=w.hf(p),bytes=s.st_size,dev=s.st_dev,ino=s.st_ino,mtime_ns=s.st_mtime_ns)
def corpus(rows):
    return sorted((r["package_id"],r["target"]["name"],r["target"]["kind"],sorted(r["features"]))for r in rows)
def result_rows(td,ok):
    docs=[json.loads(line)for line in (td/"stdout.jsonl").read_bytes().splitlines()]
    require(docs[-1]=={"reason":"build-finished","success":ok},"Cargo verdict")
    return [r for r in docs if r["reason"]=="compiler-artifact"],docs
def test(exe,td,env,expected):
    td.mkdir();e=env|{"INSTA_UPDATE":"no","CI":"true"};cw=w.work/"crates/ty_server"
    p=sp.run([exe,"--list"],cwd=cw,env=e,check=True,capture_output=True)
    (td/"list").write_bytes(p.stdout);require(not p.stderr,"unexpected test list stderr")
    names=sorted(s.removesuffix(": test")for s in p.stdout.decode().splitlines()if s.endswith(": test"))
    require(len(names)==len(set(names))==200,"original 200-test roster");target,=(s for s in names if s.endswith("::debug_command"))
    p=sp.run([exe,"--exact",target,"--nocapture"],cwd=cw,env=e,capture_output=True,timeout=90)
    (td/"stdout").write_bytes(p.stdout);(td/"stderr").write_bytes(p.stderr)
    require(p.returncode==expected and (b"1 passed;"if expected==0 else b"1 failed;")in p.stdout,("native test verdict",p.returncode))
    if expected:require(b"snapshot" in (p.stderr+p.stdout).lower()and b"debug_command" in p.stderr+p.stdout,"old ELF must fail for changed snapshot")
    roster=hashlib.sha256(p0names(names)).hexdigest()
    require(roster==test_names,"test roster differs from independent signed full 200-name set")
    return roster
def p0names(names):return ("\n".join(names)+"\n").encode()
def projection(rows,td,env,changed):
    # Compile an independent use of the exact new public inherent method against this producer's true metadata.
    member,=(r for r in rows if r["target"]["name"]=="ty_project" and "lib"in r["target"]["kind"])
    meta,=(Path(f)for f in member["filenames"]if f.endswith(".rmeta"))
    code=td/"project_consumer.rs";code.write_text("extern crate ty_project; pub fn project() { let _ = ty_project::Project::scripts_to_synchronize; }\n")
    dirs=sorted({str(Path(name).parent)for row in rows for name in row["filenames"]})
    argv=["rustc","+ohm",str(code),"--edition=2024","--crate-name=project_consumer","--crate-type=lib","--emit=metadata","--error-format=json","--extern","ty_project="+str(meta)]
    argv.extend("-Ldependency="+s for s in dirs);argv+=["-o",str(td/"project_consumer.rmeta")]
    p=sp.run(argv,cwd=w.work,env=env,capture_output=True)
    (td/"interface.stderr").write_bytes(p.stderr);w.put(td/"interface-argv.json",argv)
    require(p.returncode==(0 if changed else 1),"expected the new project method only on edited source")
    if not changed:
        diags=[json.loads(l)for l in p.stderr.splitlines()]
        require(any((r.get("code")or {}).get("code")=="E0599" and "scripts_to_synchronize" in r.get("message","")for r in diags),"old method failed for another reason")
    return keep(meta)
def sessions():
    ds=sorted((w.target/"debug/incremental").glob("*/ty_ide-*/s-*/work-products.bin"))
    return {str(p.parent):p.parent for p in ds if p.parent.is_dir()and not p.parent.name.endswith("-working") and (p.parent/"dep-graph.bin").is_file()}
def objects(artifacts,td,before):
    current=sessions();delta=set(current)-set(before);require(len(delta)==1,("missing or ambiguous new ty_ide session",sorted(current),sorted(before)))
    directory=current[delta.pop()];objects={p.name:record_file(p)for p in sorted(directory.glob("*.o"))if p.is_file()and not p.is_symlink()}
    require(len(objects)>=100 and all(re.fullmatch(r"[0-9a-z]+\.o",v)for v in objects),"incomplete ty_ide objects")
    row,=(r for r in artifacts if r["target"]["name"]=="ty_ide" and "lib"in r["target"]["kind"])
    outputs={p.suffix:keep(p)for n in row["filenames"]if (p:=Path(n)).suffix in (".rmeta",".rlib")};require(set(outputs)=={".rmeta",".rlib"},"actual ty_ide output set")
    st={p.name:record_file(p)for p in sorted(directory.glob("*.bin"))}
    if td.parent.name in ("0P","1C") and td.name in ("old","edit"):
        for n in ("dep-graph.bin","work-products.bin"):
            require(keep(directory/n)["sha256"]==st[n]["sha256"],"changed graph during acquisition")
            st[n]["body"]=st[n]["sha256"]+".zst"
    w.put(td/"ty-ide-objects.json",dict(session=str(directory),objects=objects,index_files=st,outputs=outputs))
    return objects
def classifier(a,b):
    require(a.keys()==b.keys(),"different ty_ide CGUs across source states")
    retained=[];regenerated=[]
    for name,prior in a.items():
        current=b[name];require((prior["bytes"],prior["sha256"])==(current["bytes"],current["sha256"]),("different physical ty_ide native body",name))
        if (prior["dev"],prior["ino"])==(current["dev"],current["ino"]):
            require(prior["mtime_ns"]==current["mtime_ns"],("shared artifact changed",name));retained.append(name)
        else:regenerated.append(name)
    return dict(retained=sorted(retained),regenerated=sorted(regenerated))
def footprint():
    seen=set();logical=disk=0;classes=collections.Counter()
    for root in (w.target,w.shared):
        for base,dirs,files in os.walk(root,followlinks=False):
            for leaf in files:
                p=Path(base)/leaf
                if p.is_symlink() or not p.is_file():continue
                st=p.stat();key=(st.st_dev,st.st_ino)
                if key in seen:continue
                seen.add(key);logical+=st.st_size;disk+=st.st_blocks*512
                if leaf in ("dep-graph.bin","work-products.bin","query-cache.bin"):classes[leaf]+=st.st_size
    return dict(physical_files=len(seen),logical_unique_bytes=logical,allocated_unique_bytes=disk,incremental_classes=classes)
def count(exe,path,cmd,env,original_dir):
    with (path/"stdout.jsonl").open("xb")as out,(path/"stderr").open("xb")as err:
        p=sp.run([exe,path/"hardware.json",*cmd],env=env,cwd=original_dir,stdout=out,stderr=err)
    h=json.loads((path/"hardware.json").read_bytes());require(p.returncode==0 and h["status"]==0 and h["instructions"]>0 and h["enabled"]==h["running"]>0,"invalid complete Cargo PMU")
    return h["instructions"]
def census(path,env):
    ids=lambda p:(p.stat().st_dev,p.stat().st_ino)
    rust=ids(w.sdk/"bin/rustc");ld=ids(w.sdk/"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd")
    imgs={};by=collections.Counter();unknown_clock=collections.Counter();runs=[]
    for line in (path/"tasks/epochs.tsv").read_text().splitlines():
        r=line.split()
        if r[0]=="I":
            i=int(r[1]);cells=(path/"tasks"/f"{i:05}.nul").read_bytes().split(b"\0");require(cells.pop()==b"" and cells[0]==r[2].encode(),"kernel image identity")
            dev,ino=map(int,cells[1:3]);argv=cells[4:];owner=Path(os.fsdecode(cells[3])).name
            if (dev,ino)==rust and b"--crate-name"in argv:owner="rustc:"+argv[argv.index(b"--crate-name")+1].decode()
            if (dev,ino)==ld:owner="wild"
            imgs[i]=owner
            if r[5]=="exec" and (owner.startswith("rustc:") or owner=="wild"):runs.append(owner)
        elif r[0]=="C":
            i,pid,tid,n,en,active=map(int,r[1:7]);require(en==active and n>=0,"multiplexed exec PMU")
            by[imgs[i]]+=n
            if n and not active:unknown_clock[imgs[i]]+=n
    # This is the off-clock execution census. Only fully clocked per-process groups can be priced.
    return dict(real_execs=runs,process_instructions=dict(by),positive_instructions_without_clock=dict(unknown_clock))
def main():
    cfg=json.loads((here/"binding.json").read_bytes());w.guard();require(os.environ["GITHUB_SHA"]==os.environ["REVIEWED_HEAD"]and os.environ["GITHUB_RUN_ATTEMPT"]=="1","unregistered worker")
    qa=Path(os.environ["GITHUB_WORKSPACE"])/"qa"
    require(sp.check_output(["git","-C",qa,"rev-parse","HEAD"],text=True).strip()==os.environ["GITHUB_SHA"] and os.environ["GITHUB_REF_NAME"]=="charlie/qa-ruff-ty-ide-profile-29697-20261103","unregistered exact receiver")
    require(w.git("rev-parse","HEAD")==new and w.git("rev-parse","HEAD^")==old and not w.git("diff","--name-only",old,new,"--","crates/ty_ide"),"different real Ruff edit")
    w.put(w.proof/"registration.json",dict(old=old,new=new,lock=lock,command=command,order=list("PCCP"),factory=cfg,source_sha256=w.hf(Path(__file__)),gate="Both mirrored primary edit pairs must save at least 2%, increase physically retained byte-identical ty_ide objects, retain the real native/metadata verdict and exact within-role clean ELF."))
    env=w.install();roots=acquire(w,cfg);w.sdk.rename(w.root/"original-signed-reference")
    whole=w.root/"whole_count";trace=w.root/"exec_count"
    for tool in (whole,trace):sp.run(["cc","-O2","-Wall","-Wextra","-Werror",here.parent/(tool.name+".c"),"-o",tool],check=True)
    source=w.root/"counter.c";source.write_text('#include <stdint.h>\n#include <stdlib.h>\nint main(int c,char **v){uint64_t n=strtoull(v[1],0,10);volatile uint64_t x=1;for(uint64_t i=0;i<n;i++)x=x*3+i;return c!=2;}\n')
    actor=w.root/"calibration";sp.run(["cc","-O2",source,"-o",actor],check=True)
    preflight={}
    for n in (1000000,4000000):
        td=w.proof/("calibration-"+str(n));td.mkdir();preflight[n]=count(whole,td,[actor,str(n)],env,w.work)
    require(3.8<preflight[4000000]/preflight[1000000]<4.2,"nonlinear whole-command counter calibration")
    reports=[];master=None
    for idx,role in enumerate("PCCP"):
        w.guard();remove_outputs();state(old);roots[role].rename(w.sdk)
        hist=w.proof/(str(idx)+role);hist.mkdir()
        try:
            tool={k:sp.check_output([k,"+ohm","-vV"],cwd=w.work,env=env,text=True)for k in ("rustc","cargo")}
            require("7024b0d2d"in tool["cargo"] and ("LLVM version:" in tool["rustc"]),"different tools")
            physical,=(w.sdk/"lib").glob("librustc_driver-*.so");require(w.hf(physical)==cfg["driver"][role],"different source-built driver")
            identities={name:record_file(path)for name,path in {"rustc":w.sdk/"bin/rustc","cargo":w.sdk/"bin/cargo","wild":w.sdk/"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd","driver":physical}.items()}
            for name in ("rustc","cargo"):
                picked=Path(sp.check_output(["rustup","which","--toolchain","ohm",name],cwd=w.work,env=env,text=True).strip())
                require(picked.samefile(w.sdk/"bin"/name),"rustup did not select the admitted physical executable")
            w.put(hist/"role.json",dict(role=role,driver=w.hf(physical),versions=tool,physical=identities))
            if idx==0:
                sp.run(["cargo","+ohm","fetch","--locked","--target","x86_64-unknown-linux-gnu"],cwd=w.work,env=env,check=True)
            env["CARGO_NET_OFFLINE"]="true"
            def phase(name,kind="whole",snapshot=False,method=None):
                nonlocal master
                w.guard();td=hist/name;td.mkdir();pre=sessions()if snapshot else {}
                if kind=="whole":n=count(whole,td,command,env,w.work);obs=None
                else:
                    tasks=td/"tasks";tasks.mkdir()
                    with (td/"stdout.jsonl").open("xb")as out,(td/"stderr").open("xb")as err:sp.run([trace,tasks,*command],cwd=w.work,env=env,stdout=out,stderr=err,check=True)
                    n=None;obs=census(td,env)
                a,_=result_rows(td,True);u=corpus(a);require(len(u)==289 and (master is None or u==master),"different real test target/feature roster");master=u
                item,=(r for r in a if r["target"]["name"]=="e2e"and r["target"]["kind"]==["test"]);exe=Path(item["executable"]);native=keep(exe)
                dirty=sorted(r["target"]["name"]for r in a if not r["fresh"]);unique=test(exe,td/"test",env,0)
                o=objects(a,td,pre)if snapshot else None
                meta=projection(a,td,env,method)if method is not None else None
                d=dict(instructions=n,observed=obs,elf=native,test_roster_sha=unique,dirty=dirty,units=len(u),source=w.git("rev-parse","HEAD"),producer_metadata=meta,executable=str(exe))
                w.put(td/"result.json",d);return d,o,exe
            initial,before,exe=phase("old",snapshot=True,method=False);require(len(initial["dirty"])==289,"old not fully cold")
            held=w.root/("held-old-"+str(idx));shutil.copy2(exe,held);state(new);require(test(held,hist/"stale-old",env,101)==initial["test_roster_sha"],"stale roster changed")
            edited,after,_=phase("edit",snapshot=True,method=True);warm,_,_=phase("unchanged")
            require(set(edited["dirty"])==focus and not warm["dirty"],"edit/noop compiler-artifact roster")
            contact=classifier(before,after);w.put(hist/"old-to-new-objects.json",contact);w.put(hist/"settled-storage.json",footprint())
            target=w.work/"crates/ty_server/src/session.rs";source=target.read_bytes();invalid=hist/"invalid";invalid.mkdir()
            try:
                target.write_bytes(source+b'\nconst _: u8 = "invalid";\n')
                with (invalid/"stdout.jsonl").open("xb")as out,(invalid/"stderr").open("xb")as err:p=sp.run(command,cwd=w.work,env=env,stdout=out,stderr=err)
                _,diags=result_rows(invalid,False);require(p.returncode==101 and any((r.get("message",{}).get("code")or {}).get("code")=="E0308"for r in diags if r["reason"]=="compiler-message"),"real Rust type error")
            finally:target.write_bytes(source)
            fixed,_,_=phase("repair")
            state(old);op,ob,_=phase("observed-old","trace",True);state(new);oc,oa,_=phase("observed-edit","trace",True)
            check=classifier(ob,oa);w.put(hist/"observed-old-to-new-objects.json",check)
            require(op["elf"]==initial["elf"] and oc["elf"]==edited["elf"] and sorted(oc["observed"]["real_execs"])==sorted(["rustc:"+x for x in ("ty_project","ty_ide","ty_server","e2e")]+["wild"]),"wrong real observer roster or ELF")
            unchanged,_,_=phase("observed-unchanged","trace");require(not unchanged["observed"]["real_execs"] and not unchanged["dirty"],"real unchanged compile/link")
            remove_outputs();fresh,fo,_=phase("independent-clean",snapshot=True,method=True);require(len(fresh["dirty"])==289,"clean target was populated")
            require(initial["elf"]!=edited["elf"] and all(j["elf"]==edited["elf"] for j in (warm,fixed,oc,unchanged,fresh)),"warm, repaired or independent empty native mismatch")
            require(before.keys()==fo.keys() and all(after[name]["sha256"]==fo[name]["sha256"]for name in after),"independent clean ty_ide objects differ")
            # Ordinary hardware is the primary. A distinct prior incremental state in the off-clock
            # execution census cannot be used to price the ordinary per-compiler or per-CGU workload.
            observer_matches_primary=(check==contact)
            rep=dict(role=role,index=idx,primary=edited["instructions"],noop=warm["instructions"],cold=initial["instructions"],clean=fresh["instructions"],objects=len(after),retained=len(contact["retained"]),old=initial["elf"],new=edited["elf"],observed=oc["observed"],observer_matches_primary=observer_matches_primary,storage=json.loads((hist/"settled-storage.json").read_bytes()))
            w.put(hist/"qualified.json",rep);reports.append(rep)
        finally:w.sdk.rename(roots[role])
    require(len({r["old"]["sha256"]for r in reports})==len({r["new"]["sha256"]for r in reports})==1,"complete native ELFs differ across roles or order")
    reductions=[]
    for p,c in ((reports[0],reports[1]),(reports[3],reports[2])):
        reductions.append(dict(reduction=1-c["primary"]/p["primary"],additional_objects=c["retained"]-p["retained"]))
    w.put(w.proof/"terminal.json",dict(roles=reports,pairs=reductions,gate=all(r["reduction"]>=.02 and r["additional_objects"]>0 for r in reductions)))
if __name__=="__main__":main()
