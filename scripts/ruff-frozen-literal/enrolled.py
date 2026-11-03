"""A fixed-input Ruff pilot with original whole-Cargo and inherited per-rustc PMU events."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import study as s
import prep as p
import tree_clock

if any(Path(module.__file__).resolve()!=HERE/name for module,name in ((s,"study.py"),(p,"prep.py"),(tree_clock,"tree_clock.py"))):
    raise RuntimeError("different authenticated worker module")

w,ROOT,BASE=p.w,p.ROOT,p.BASE
A,B=p.A,p.B
need,save,env=p.need,p.save,p.env
REG=json.loads((HERE/"inherited-registration.json").read_bytes())


def discard(path):
    need(path.is_dir() and not path.is_symlink() and path.resolve().is_relative_to(ROOT.resolve()) and path!=ROOT,"private cleanup")
    shutil.rmtree(path)


def copy(src,dest):
    need(not dest.exists() and not dest.is_symlink(),"destination already exists")
    subprocess.run(["cp","-a","--reflink=auto",src,dest],check=True)


class Switch:
    def __init__(self):
        self.roles=json.loads((BASE/"scope-sdks.json").read_bytes());self.current="P";self.states={}
        copy(Path(self.roles["inline-C"]["sdk"]),ROOT/"sdk-idle-C")

    def activate(self,role):
        if self.current!=role:
            previous=ROOT/("sdk-idle-"+self.current);new=ROOT/("sdk-idle-"+role)
            need(w.SDK.is_dir()and new.is_dir()and not previous.exists()and not any(x.is_symlink() for x in (w.SDK,new)),"physical compiler switch")
            w.SDK.rename(previous);new.rename(w.SDK);self.current=role
        r=self.roles["inline-"+role];d,=(w.SDK/"lib").glob("librustc_driver-*.so")
        facts={}
        for key,f in (("cargo",w.SDK/"bin/cargo"),("rustc",w.SDK/"bin/rustc"),("driver",d),("rustdoc",w.SDK/"bin/rustdoc")):
            st=f.stat();facts[key]=[p.sha(f),st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns]
            if key!="rustdoc":need(facts[key][0]==r[key],"wrong active compiler")
        need(self.states.setdefault(role,facts)==facts,"reinstalled same-role native tool")
        run=lambda cmd:subprocess.check_output(cmd,env=env(),text=True)
        rs,cs=run(["rustc","+ohm","-vV"]),run(["cargo","+ohm","-Vv"])
        need(Path(run(["rustc","+ohm","--print","sysroot"]).strip()).samefile(w.SDK),"different rustup alias")
        return dict(config=r,active=str(w.SDK),driver=facts["driver"][0],rustc=facts["rustc"][0],cargo=facts["cargo"][0],rustc_version=rs,cargo_version=cs)


def image_clock(dest,mode,identity,crate,argv,expected,auth=None,cargo=True):
    trace=dest.with_suffix(".epochs");trace.mkdir()
    real=auth if auth is not None else w.SDK/"bin/rustc"
    w.run([ROOT/"target-count",mode,trace,real,crate,*argv],env(),dest)
    info,images=tree_clock.decode(trace,mode,identity,crate)
    need(info["status"]==0 and bool(info["owner"])==expected,"owner eligibility at "+str(dest))
    if cargo:
        actual=[im for im in images.values()if im["trigger"]=="exec" and im["ino"]==identity["cargo_inode"]]
        need(len(actual)==1 and actual[0]["argv"][1:]==list(argv)[2:],"wrong complete Cargo argv")
    if expected and cargo:
        args=info["argv"]
        need((str(w.SRC/"crates"/crate/"src/lib.rs")in args or "crates/"+crate+"/src/lib.rs"in args) and len(info["owner_tasks"])>=2,"wrong original root source")
        extern=tree_clock.externs(args)
        if crate=="ty_vendored":need(set(extern)=={"ruff_db","static_assertions","zip"},"unexpected full producer dependencies")
        for r in extern.values():
            need(s.store(Path(r["path"]).read_bytes())==r["sha256"],"required rmeta transport")
        info["extern"]=extern
    save(dest/"physical.json",info);return info


def controls():
    for name,src,flags in (("target-count","target_count.c",[]),("family","family.c",["-pthread"])):
        need(p.sha(HERE/src)==REG["files"][src],"unregistered hardware observer or control")
        subprocess.run(["/usr/bin/cc","-O2","-Wall","-Wextra","-Werror",*flags,HERE/src,"-o",ROOT/name],check=True)
    d=BASE/"inherited-calibration";d.mkdir();f=ROOT/"family";st=f.stat();ident=dict(rustc_inode=[st.st_dev,st.st_ino]);role="family"
    for label,n in (("small","10"),("large","2000000")):
        argv=[str(f),"main",n,"--crate-name",role,"--emit=dep-info,metadata"]
        ref=s.whole(d/(label+"-plain"),f,argv);raw=(d/(label+"-plain")/"stdout").read_bytes()
        data={}
        for mode in ("owner","whole","roster"):
            target=d/(label+"-"+mode);obs=image_clock(target,mode,ident,role,argv,True,auth=f,cargo=False)
            need((target/"stdout").read_bytes()==raw and len(obs["owner_tasks"])==3 and obs["tasks"]>=4,"original fork/exec/thread control")
            if mode!="roster":data[mode]=obs["instructions"]
        if label=="large":
            need(ref>50_000_000 and all(abs(v-ref)/min(v,ref)<.01 for v in data.values()),"inherited hardware lost physical child/thread work")
        save(d/(label+".json"),dict(plain=ref,**data))


def live_guard(dest,ident):
    f=ROOT/"mapping-input.rs";f.write_text("pub fn f(input: u64) -> u64 { input.rotate_left(7) }\n")
    cmd=[str(w.SDK/"bin/rustc"),"--crate-name","physical_compiler_guard","--crate-type","lib","--emit=dep-info,metadata","--out-dir",str(ROOT),str(f)]
    whole=s.whole(dest/"mapping-whole",w.SDK/"bin/rustc",cmd);meta=ROOT/"libphysical_compiler_guard.rmeta";first=p.sha(meta)
    row=image_clock(dest/"mapping-owner","owner",ident,"physical_compiler_guard",cmd,True,cargo=False)
    need(first==p.sha(meta) and abs(whole-row["instructions"])/min(whole,row["instructions"])<.02,"real compiler timer calibration")
    save(dest/"mapping.json",dict(metadata=first,whole=whole,owner=row["instructions"]))


def source_times():
    raw=subprocess.check_output(["git","-C",w.SRC,"diff","--name-only","-z",A,B])
    paths=set()
    for item in raw.decode().split("\0")[:-1]:
        file=w.SRC/item;paths.add(file)
        for parent in file.parents:
            if parent==w.SRC:break
            paths.add(parent)
    return {str(f.relative_to(w.SRC)):f.stat().st_mtime_ns for f in paths}


class Checkpoint:
    def __init__(self,name,revision,report):
        self.snapshot=ROOT/("snapshot-"+name);self.rev=revision;self.mtimes=source_times()
        if self.snapshot.exists():discard(self.snapshot)
        self.snapshot.mkdir();self.rows={}
        for key in ("state","cargo","temp","home"):
            origin=ROOT/key;self.rows[key]=w.tree_identity(origin)
            need(w.resources()[1]>(15<<30)+self.rows[key]["bytes"]+(1<<30),"private checkpoint reserve")
            copy(origin,self.snapshot/key)
            need(w.tree_identity(self.snapshot/key)==self.rows[key],"checkpoint bytes, mtimes or hardlink topology")
        save(report,dict(revision=revision,rows=self.rows,source_mtimes=self.mtimes))

    def restore(self):
        p.source(self.rev)
        for rel,mtime in self.mtimes.items():
            f=w.SRC/rel;os.utime(f,ns=(f.stat().st_atime_ns,mtime))
        for key,expected in self.rows.items():
            target=ROOT/key;discard(target);copy(self.snapshot/key,target)
            need(w.tree_identity(target)==expected,"changed physical "+key+" checkpoint")
        w.resources()


def clocked(dest,how,cmd,crate,ident,dirty):
    if how=="plain":
        x=s.whole(dest,ROOT/"proxies/cargo",cmd);return dict(instructions=x)
    return image_clock(dest,how,ident,crate,cmd,dirty)


def safety(dest,ident):
    s.fresh();p.source(B);dest.mkdir()
    d=dest/"fresh";obs=image_clock(d,"roster",ident,"ty_vendored",p.CHECK,True);s.capture(d,"new",obs)
    src=w.SRC/"crates/ty_vendored/src/lib.rs";original=src.read_bytes()
    try:
        src.write_bytes(original+p.INVALID)
        bad=dest/"E0308";w.run([*p.CHECK,"--message-format=json"],env(),bad,expected=101)
        rows=s.check_messages(bad,False);errors=[r["message"] for r in rows if r["reason"]=="compiler-message" and r["message"]["level"]=="error"]
        need(len(errors)==1 and errors[0]["code"]["code"]=="E0308" and any(span["is_primary"] and span["file_name"].endswith("crates/ty_vendored/src/lib.rs") and any("OHM_FROZEN_LITERAL_INVALID" in t["text"]for t in span["text"])for span in errors[0]["spans"]),"different typed error")
    finally:src.write_bytes(original)
    p.source(B);d=dest/"repair";obs=image_clock(d,"roster",ident,"ty_vendored",p.CHECK,True);s.capture(d,"new",obs)


def fixed_inputs(base,source_dir,main,switch):
    # Supplemental genuine rustc, separate from the ordinary Cargo measurements. Reuse the
    # physical P provider metadata, original generator output and exact native compiler argv.
    base.mkdir();trace=source_dir.with_suffix(".epochs");av=main["argv"]
    raw=(trace/f"{main['owner']:05}.env").read_bytes();envs=dict(item.decode().split("=",1)for item in raw.split(b"\0")[:-1])
    removed={k:envs.pop(k)for k in ("CARGO_MAKEFLAGS","MAKEFLAGS","MFLAGS")if k in envs}
    child_bin=ROOT/"cargo/bin"
    need(not child_bin.is_symlink()and (not child_bin.exists()or child_bin.is_dir()and not any(child_bin.iterdir())),"child search prefix contains an installed tool")
    # The actual rustup-launched Cargo adds its private CARGO_HOME/bin to the child PATH.
    child_path=os.pathsep.join((str(child_bin),env()["PATH"]))
    need(envs.get("CARGO_HOME")==str(ROOT/"cargo") and envs.get("CARGO_MANIFEST_DIR")==str(w.SRC/"crates/ty_vendored")and envs.get("OUT_DIR") and envs.get("PATH")==child_path,"different real rustc child context")
    arc=Path(envs["OUT_DIR"])/"zipped_typeshed.zip";before=p.sha(arc)
    save(base/"source.json",dict(argv=av,donor_image=main["owner"],removed_external_jobserver=removed,original_env=p.sha(trace/f"{main['owner']:05}.env"),archive=before,extern=main["extern"]))
    output=Path(av[av.index("--out-dir")+1]);incs=[Path(v.removeprefix("-C").removeprefix("incremental=")) for v in av if v.removeprefix("-C").startswith("incremental=")]
    need(len(incs)==1 and incs[0].is_relative_to(w.STATE) and output.is_relative_to(w.STATE) and output.name=="out" and "/ty_vendored/" in str(output) and not arc.is_relative_to(output),"wrong private compiler products")
    for index,role in enumerate("PCP"):
        ident=s.physical(role,switch.activate);dst=base/(str(index+1)+role);dst.mkdir();save(dst/"identity.json",ident)
        need(incs[0].parent.name=="incremental" and incs[0].is_dir(),"unexpected shared incremental namespace")
        root_caches=[c for c in incs[0].iterdir() if c.name.startswith("ty_vendored-")]
        need(root_caches,"physical target-specific incremental state")
        for cache in root_caches:discard(cache)
        discard(output);output.mkdir()
        logs=dst/"run.epochs";logs.mkdir();w.run([ROOT/"target-count","owner",logs,w.SDK/"bin/rustc","ty_vendored",*av],envs,dst/"run")
        info,_=tree_clock.decode(logs,"owner",ident,"ty_vendored");need(info["argv"]==av and info["status"]==0 and p.sha(arc)==before and tree_clock.externs(av)==main["extern"],"changed fixed inputs")
        save(dst/"run/physical.json",info);s.capture(dst/"run","new",info)
    need(switch.current=="P","failed to restore ordinary source compiler")


def target_history(base,ident,switch,with_fixed):
    p.source(A);s.fresh();cold=base/"cold";s.whole(cold,ROOT/"proxies/cargo",p.CHECK);s.capture(cold,"old")
    after=Checkpoint("target",A,base/"target-checkpoint.json")
    for mode in ("plain","owner","whole"):
        after.restore();d=base/mode;d.mkdir()
        o=clocked(d/"old-idle",mode,p.CHECK,"ty_vendored",ident,False);s.capture(d/"old-idle","old")
        if mode!="plain":need(not o["compilers"] and not o["build_scripts"],"restored OLD scheduled work")
        p.source(B);current=clocked(d/"edit",mode,p.CHECK,"ty_vendored",ident,True);s.capture(d/"edit","new",current if mode!="plain"else None)
        if mode!="plain":
            need(current["compilers"]==[["ty_vendored","--emit=dep-info,metadata"]] and len(current["build_scripts"])==1 and "/ty_vendored/"in current["build_scripts"][0],"different actual edited root or generator")
        idle=clocked(d/"new-idle",mode,p.CHECK,"ty_vendored",ident,False);s.capture(d/"new-idle","new")
        if mode!="plain":need(not idle["compilers"] and not idle["build_scripts"],"edited root stayed dirty")
    # Empty this real package in the genuinely restored OLD history while retaining its
    # authenticated upstream metadata. Full empty-root and native checks also run independently.
    after.restore();p.source(B);d=base/"same-deps-clean";d.mkdir()
    w.run(["cargo","+ohm","clean","-p","ty_vendored"],env(),d/"clean")
    seen=list(w.STATE.rglob("libty_vendored-*.rmeta"))
    need(not seen,"ordinary package clean kept the root metadata: "+repr(seen[:2]))
    obs=image_clock(d/"check","roster",ident,"ty_vendored",p.CHECK,True);s.capture(d/"check","new",obs)
    need(all(n[0]in("ty_vendored","build_script_build")for n in obs["compilers"]),"clean root replaced another dependency")
    if with_fixed:fixed_inputs(base/"fixed-operand",d/"check",obs,switch)
    safety(base/"safety",ident);discard(after.snapshot)


def parser_history(base,ident):
    p.source(B);s.fresh();d=base/"parser";d.mkdir()
    s.whole(d/"cold",ROOT/"proxies/cargo",p.PARSER);s.capture(d/"cold","new",crate="ruff_python_parser")
    w.run(["cargo","+ohm","clean","-p","ruff_python_parser"],env(),d/"clean")
    need(not list(w.STATE.rglob("libruff_python_parser-*.rmeta")),"parser clean kept output")
    before=Checkpoint("parser",B,d/"checkpoint.json")
    for mode in ("plain","owner","whole"):
        before.restore();f=d/mode;obs=clocked(f,mode,p.PARSER,"ruff_python_parser",ident,True)
        s.capture(f,"new",obs if mode!="plain"else None,"ruff_python_parser")
        if mode!="plain":need(obs["compilers"]==[["ruff_python_parser","--emit=dep-info,metadata"]] and not obs["build_scripts"],"parser root was not isolated")
    discard(before.snapshot)


def main():
    p.acquire();save(BASE/"inherited-enrollment.json",REG);s.primary_inputs();s.fresh();controls();switch=Switch();seen=set()
    for i,role in enumerate(p.REG["order"],1):
        base=BASE/f"visit-{i}-{role}";base.mkdir();ident=s.physical(role,switch.activate);save(base/"identity.json",ident);save(base/"sdk-file-stats.json",switch.states[role]);live_guard(base,ident)
        target_history(base,ident,switch,i==1);parser_history(base,ident)
        if role not in seen:s.native(base/"native");seen.add(role)
        print("Finished fixed-input visit",i,role,flush=True)
    p.source(B);save(BASE/"complete.json",dict(order=p.REG["order"],native=["P","C"],source=B,protocol=REG,original_source_clean=True,final_resources=w.resources()))


if __name__=="__main__":
    try:main()
    except BaseException:
        if BASE.is_dir():(BASE/"refused.txt").write_text(traceback.format_exc())
        raise
