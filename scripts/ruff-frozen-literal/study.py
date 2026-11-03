"""Single-boot PC/CP discovery on the complete, locked, unchanged Ruff checkout."""
import ctypes
import hashlib
import mmap
import io
import json
import os
from pathlib import Path
import shutil
import sys
import traceback
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import prep as p
import readout

w, REG, ROOT, BASE, A, B = p.w,p.REG,p.ROOT,p.BASE,p.A,p.B
need,save,env = p.need,p.save,p.env


def fresh():
    w.fresh_state()
    for name in ("home","temp"):
        loc=ROOT/name
        need(loc.is_dir() and not loc.is_symlink() and loc.parent==ROOT,"private scratch")
        shutil.rmtree(loc);loc.mkdir()
    w.resources()


def store(data):
    digest=hashlib.sha256(data).hexdigest();path=BASE/"objects"/digest
    if path.exists():need(path.read_bytes()==data,"inconsistent physical content identity")
    else:
        with path.open("xb") as f:f.write(data)
    return digest


def one_bytes(paths, label):
    selected=sorted(set(x.resolve(strict=True) for x in paths))
    need(0<len(selected)<=16,"missing or excessive "+label)
    choices={}
    for x in selected:
        data=x.read_bytes()
        need(0<len(data)<=150<<20,"oversize "+label)
        choices.setdefault(store(data),[]).append(str(x))
    need(len(choices)==1,"ambiguous original "+label+": "+repr(choices))
    digest,names=next(iter(choices.items()))
    return dict(sha256=digest,paths=names,bytes=(BASE/"objects"/digest).stat().st_size)


def zip_identity(data, state):
    with zipfile.ZipFile(io.BytesIO(data))as f:
        rows={};infos=f.infolist()
        need(len(infos)==REG["expected_member_count"] and len({i.filename for i in infos})==len(infos),"duplicate or absent generated files")
        for i in infos:
            raw=f.read(i)
            rows[i.filename]=dict(bytes=len(raw),method=i.compress_type,crc=i.CRC,sha256=hashlib.sha256(raw).hexdigest())
        need(rows==p.expected(state),"original generated contents changed")
    return len(rows)


def capture(directory,state,selected=None,crate="ty_vendored"):
    # Use the physical owner argv if available. Also require every surviving candidate of this
    # root in this private one-package check history to have the same complete emitted bytes.
    meta=one_bytes(w.STATE.rglob("lib"+crate+"-*.rmeta"),"root metadata")
    deps=sorted(d for d in w.STATE.rglob(crate+"-*.d") if ("/"+crate+"/src/lib.rs").encode() in d.read_bytes())
    need(deps,"missing package dep-info")
    if selected:
        argv=selected["argv"]; suffix=[a.removeprefix("-C").removeprefix("extra-filename=") for a in argv if a.removeprefix("-C").startswith("extra-filename=")]
        need(len(suffix)==1 and argv.count("--out-dir")==1,"root output identity")
        loc=(Path(argv[argv.index("--out-dir")+1])/("lib"+crate+suffix[0]+".rmeta")).resolve(strict=True)
        need(str(loc) in meta["paths"] or any(loc.samefile(k) for k in meta["paths"]),"kernel owner emitted a different rmeta")
    result=dict(crate=crate,metadata=meta,dep_info=[dict(path=str(d),sha256=store(d.read_bytes())) for d in deps])
    if crate=="ty_vendored":
        z=one_bytes(w.STATE.rglob("zipped_typeshed.zip"),"generated ZIP");raw=(BASE/"objects"/z["sha256"]).read_bytes()
        need(any(any(k.encode() in d.read_bytes() for k in z["paths"])for d in deps),"ZIP not among actual rustc dep-info inputs")
        need((BASE/"objects"/meta["sha256"]).read_bytes().count(raw)==1,"missing exact source bytes in native compiler metadata")
        result.update(archive=z,members=zip_identity(raw,state))
    save(directory/"products.json",result)
    return result


def whole(directory,agent,argv):
    w.run([ROOT/"whole-count",directory/"hardware.json",agent,*argv],env(),directory)
    info=json.loads((directory/"hardware.json").read_bytes())
    need(info["status"]==0 and info["pid"]>0 and 0<info["instructions"] and info["enabled"]==info["running"]>0,"incomplete whole-tree counter")
    return info["instructions"]


def calibration():
    base=BASE/"calibration";base.mkdir()
    data={}
    for variant in ("thread","child"):
        for level in (0,1):
            loop="sum(range(6000000))" if level else "None"
            code=("import threading;t=threading.Thread(target=lambda:"+loop+");t.start();t.join()" if variant=="thread" else "import sys,subprocess;subprocess.run([sys.executable,'-IB','-c',"+repr(loop)+"],check=True)")
            argv=["python3","-IB","-c",code]; label=variant+str(level)
            x=whole(base/(label+"-whole"),"/usr/bin/python3",argv)
            logs=base/(label+".epochs");logs.mkdir()
            w.run([ROOT/"exec-count",logs,"/usr/bin/python3",*argv[1:]],env(),base/(label+"-exec"))
            ims,counts,threads=readout.counted(logs);py=[i for i,k in ims.items() if k["trigger"]=="exec" and Path(k["exe"]).samefile("/usr/bin/python3")]
            need(len(py)==(2 if variant=="child" else 1) and (variant=="child" or any(len(threads[i])>=2 for i in py)),"lost calibrated fork/thread")
            y=sum(v[0]for i,v in counts.items()if i!=1)
            data[label]=[x,y]
        for arm in (0,1):need(data[variant+"1"][arm]>data[variant+"0"][arm]+10_000_000,"missing affirmative calibration")
    save(base/"closed.json",data)


def physical(role):
    actual=p.activate(role); d,=(w.SDK/"lib").glob("librustc_driver-*.so")
    def inode(path):
        st=path.stat();return [st.st_dev,st.st_ino]
    # Overlayfs can report the overlay device for stat(2) and the backing device for
    # /proc/TID/maps. Map this exact authenticated descriptor in this namespace once.
    with d.open("rb") as f:
        st=os.fstat(f.fileno())
        need(hashlib.file_digest(f,"sha256").hexdigest()==actual["driver"],"different opened compiler library")
        with mmap.mmap(f.fileno(),1,access=mmap.ACCESS_COPY) as mm:
            addr=ctypes.addressof(ctypes.c_char.from_buffer(mm))
            rows=[r for r in Path("/proc/self/maps").read_text().splitlines() if int(r.split("-")[0],16)<=addr<int(r.split()[0].split("-")[1],16)]
            need(len(rows)==1,"ambiguous authenticated mapping")
            row=rows[0].split(None,5);major,minor=map(lambda x:int(x,16),row[3].split(":"))
            need(len(row)==6 and row[5]==str(d) and int(row[4])>0 and int(row[2],16)==0,"different compiler file actually mapped")
            mapped=[os.makedev(major,minor),int(row[4])]
    return dict(role=role,driver=actual["driver"],driver_path=str(d),driver_inode=[st.st_dev,st.st_ino],mapped_driver_inode=mapped,mapped_driver_row=rows[0],rustc=actual["rustc"],rustc_inode=inode(w.SDK/"bin/rustc"),cargo=actual["cargo"],cargo_inode=inode(w.SDK/"bin/cargo"),source=actual["config"]["source"],active=actual["active"],versions=[actual["rustc_version"],actual["cargo_version"]])


def driver_guard(dest,ident):
    input_file=ROOT/"physical-compiler-guard.rs"
    input_file.write_text("pub fn native_guard(x: u64) -> u64 { x.rotate_left(15) }\n")
    trace=dest/"mapping.epochs";trace.mkdir()
    out=ROOT/"physical-compiler-guard.rmeta"
    cmd=[w.SDK/"bin/rustc","--crate-name","physical_compiler_guard","--crate-type=lib","--emit=metadata",input_file,"-o",out]
    w.run([ROOT/"exec-count",trace,*cmd],env(),dest/"mapping")
    ims,counters,_=readout.counted(trace)
    selected=[n for n,im in ims.items() if im["trigger"]=="exec" and [im["dev"],im["ino"]]==ident["rustc_inode"] and im["argv"]==list(map(str,cmd))]
    need(len(selected)==1 and counters[selected[0]][0]>0 and out.stat().st_size>0,"real compiler mapping calibration")
    rows=readout.mapping(trace/f"{selected[0]:05}.maps",ident)
    save(dest/"mapping/verified.json",dict(output=p.sha(out),image=selected[0],rows=rows))


def measure(method, dest, argv, crate, identity, required):
    if method=="whole":
        whole(dest,ROOT/"proxies/cargo",argv);return None
    logs=dest.with_suffix(".epochs");logs.mkdir()
    w.run([ROOT/"exec-count",logs,*argv],env(),dest)
    observed=readout.owner(logs,identity,crate,w.SRC)
    images,_,_=readout.counted(logs)
    cargo=[i for i in images.values() if i["trigger"]=="exec" and [i["dev"],i["ino"]]==identity["cargo_inode"]]
    # rustup handles the +ohm switch and execs the actual immutable Cargo.
    need(len(cargo)==1 and cargo[0]["argv"][1:]==argv[2:],"different actual Cargo command")
    need(len(observed["owner"])==(1 if required else 0),"owner did not perform the registered work at "+dest.name)
    if not required:need(not observed["compilers"],"unexpected compiler at unchanged state")
    save(dest/"physical.json",observed)
    return observed["owner"][0] if required else None


def check_history(dest,method,identity):
    fresh();dest.mkdir()
    for name,state,rev,dirty in (("cold","old",A,True),("old-idle","old",A,False),("edit","new",B,True),("new-idle","new",B,False)):
        p.source(rev);d=dest/name; own=measure(method,d,p.CHECK,"ty_vendored",identity,dirty);capture(d,state,own)


def check_messages(dest,ok):
    rows=[json.loads(line)for line in (dest/"stdout").read_bytes().splitlines()if line]
    need([r["success"]for r in rows if r["reason"]=="build-finished"]==[ok],"missing ordinary Cargo outcome")
    return rows


def safeguards(dest):
    fresh();p.source(B);dest.mkdir()
    new=dest/"fresh";w.run(p.CHECK,env(),new);capture(new,"new")
    file=w.SRC/"crates/ty_vendored/src/lib.rs";original=file.read_bytes()
    try:
        file.write_bytes(original+p.INVALID)
        bad=dest/"E0308";w.run([*p.CHECK,"--message-format=json"],env(),bad,expected=101)
        rows=check_messages(bad,False); errors=[r["message"]for r in rows if r["reason"]=="compiler-message" and r["message"]["level"]=="error"]
        need([x["code"]["code"] for x in errors]==["E0308"] and any(s["is_primary"] and s["file_name"].endswith("crates/ty_vendored/src/lib.rs") and any("OHM_FROZEN_LITERAL_INVALID" in t["text"] for t in s["text"])for s in errors[0]["spans"]),"wrong typed failure")
    finally:file.write_bytes(original)
    p.source(B);d=dest/"repair";w.run(p.CHECK,env(),d);capture(d,"new")


def native(dest):
    dest.mkdir();fresh()
    for name,rev,state in (("old",A,"old"),("edit",B,"new"),("fresh",B,"new")):
        if name=="fresh":fresh()
        p.source(rev);d=dest/name;d.mkdir();w.run(p.NATIVE,env(),d/"cargo")
        rows=check_messages(d/"cargo",True);units=[r for r in rows if r["reason"]=="compiler-artifact"]
        extern={}
        for crate in ("ty_vendored","ruff_db"):
            roots=[Path(f)for r in units if r["target"]["name"]==crate and r["target"]["kind"]==["lib"] and str(w.SRC) in r["package_id"] for f in r["filenames"]if f.endswith(".rlib")]
            # Cargo may URL-encode a path, but these authenticated workspace roots contain ASCII only.
            need(len(roots)==1 and roots[0].is_file(),"actual native "+crate);extern[crate]=roots[0]
        deps=sorted({str(Path(f).parent)for r in units for f in r["filenames"]})
        libs=sorted({x for r in rows if r["reason"]=="build-script-executed"for x in r["linked_paths"]})
        binary=ROOT/"oracle";flags=[a for k,v in extern.items()for a in ("--extern",k+"="+str(v))]
        args=[w.SDK/"bin/rustc","--edition=2024","--crate-name","frozen_oracle","-Cdebuginfo=0",HERE/"oracle.rs",*flags,*[a for v in deps for a in ("-L","dependency="+v)],*[a for v in libs for a in ("-L",v)],"-o",binary]
        w.run(args,env(),d/"link");w.run([binary],env(),d/"run")
        text=(d/"run/stdout").read_text().split()
        need(text==list(map(str,REG["source"]["required_source_commit_and_doc_count"][state])),"stale emitted native contents")
        body=binary.read_bytes();archive=one_bytes(w.STATE.rglob("zipped_typeshed.zip"),"native ZIP")
        raw=(BASE/"objects"/archive["sha256"]).read_bytes();need(body.startswith(b"\x7fELF") and body.count(raw)>=1,"missing native ZIP")
        rec=dict(elf=store(body),bytes=len(body),archive=archive,members=zip_identity(raw,state),text=text,extern={k:dict(path=str(v),sha256=p.sha(v))for k,v in extern.items()})
        save(d/"products.json",rec)


def primary_inputs():
    table={}
    import subprocess
    names=subprocess.check_output(["git","-C",w.SRC,"diff","--name-only","-z",A,B]).decode().split("\0")[:-1]
    for rev in (A,B):
        p.source(rev);files={}
        for name in sorted(set(names)|{"Cargo.lock","Cargo.toml","crates/ty_vendored/Cargo.toml","crates/ty_vendored/src/lib.rs","crates/ty_vendored/build.rs","crates/ruff_python_parser/Cargo.toml","crates/ruff_python_parser/src/lib.rs"}):
            data=(w.SRC/name).read_bytes();oid=hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
            need(oid==w.git(w.SRC,"rev-parse",rev+":"+name),"source blob changed")
            files[name]=dict(git=oid,sha256=store(data))
        need(files["crates/ty_vendored/build.rs"]["sha256"]==REG["source"]["generator_source"],"different generator implementation")
        table[rev]=dict(tree=w.git(w.SRC,"rev-parse",rev+"^{tree}"),files=files)
    save(BASE/"source-inputs.json",table)


def main():
    p.acquire();primary_inputs();fresh();calibration()
    seen=set()
    for i,role in enumerate(REG["order"]):
        dest=BASE/("visit-"+str(i+1)+"-"+role);dest.mkdir();identity=physical(role);save(dest/"identity.json",identity);driver_guard(dest,identity)
        for method in ("whole","exec"):check_history(dest/method,method,identity)
        safeguards(dest/"safety")
        for method in ("whole","exec"):
            p.source(B);fresh();directory=dest/("parser-"+method)
            chosen=measure(method,directory,p.PARSER,"ruff_python_parser",identity,True)
            capture(directory,"new",chosen,"ruff_python_parser")
        if role not in seen:native(dest/"native");seen.add(role)
        print("Completed physical ordinary Ruff",i+1,role,flush=True)
    p.source(B);save(BASE/"complete.json",dict(order=REG["order"],source=B,original_source_clean=True,final_resources=w.resources()))


if __name__=="__main__":
    try:main()
    except BaseException:
        if BASE.is_dir():(BASE/"refused.txt").write_text(traceback.format_exc())
        raise
