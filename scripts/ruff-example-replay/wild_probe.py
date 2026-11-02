"""Read GNU section metadata and replay the signed linker on its own frozen real inputs."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import byte_probe
import factory
import study
from factory import need, save, sha


def sections(data):
    need(data[:6]==b"\x7fELF\x02\x01","ELF64 LE input")
    table=struct.unpack_from("<Q",data,40)[0]
    stride,count,idx=struct.unpack_from("<3H",data,58)
    need(stride==64 and 0<count<=65534 and table+count*stride<=len(data),"bounded section headers")
    values=[struct.unpack_from("<IIQQQQIIQQ",data,table+i*stride) for i in range(count)]
    names=values[idx]
    strings=data[names[4]:names[4]+names[5]]
    result=[]
    for i,v in enumerate(values):
        n=v[0]
        name=strings[n:strings.index(b"\0",n)].decode(errors="backslashreplace")
        result.append((name,v,table+i*stride))
    return result


def read_image(path, dest):
    data=path.read_bytes()
    ss=sections(data)
    notes=[(row,index) for name,row,index in ss if name==".note.gnu.build-id"]
    ro=[(row,index) for name,row,index in ss if name==".rodata"]
    need(len(notes)==len(ro)==1,"unique output identity and rodata")
    (note,_),=notes
    (r,index),=ro
    o=note[4]
    need(note[1]==7 and note[5]==48 and data[o:o+16]==struct.pack("<III",4,32,3)+b"GNU\0","actual 32-byte NT_GNU_BUILD_ID")
    physical=subprocess.check_output(["readelf","-W","-S","-n",path])
    study.compressed(dest,physical)
    need(data[o+16:o+48].hex().encode() in physical and
         any(b".rodata " in line for line in physical.splitlines()),"GNU reader corroborates")
    masks=bytearray(data)
    masks[o+16:o+48]=bytes(32)
    id_only=hashlib.sha256(masks).hexdigest()
    masks[index+56:index+64]=bytes(8)
    return {"sha256":hashlib.sha256(data).hexdigest(),"size":len(data),"build_id":data[o+16:o+48].hex(),
            "note_offset":o+16,"rodata_field_offset":index+56,"rodata_entsize":r[9],"rodata_flags":r[2],
            "rodata_range":[r[3],r[3]+r[5]],"rodata_sha256":hashlib.sha256(data[r[4]:r[4]+r[5]]).hexdigest(),
            "digest_except_note":id_only,"digest_except_note_and_rodata_entsize":hashlib.sha256(masks).hexdigest()}


def postcard(data):
    view=memoryview(data)
    at=0
    def var():
        nonlocal at
        val=0
        for shift in range(0,70,7):
            b=view[at];at+=1
            val|=(b&127)<<shift
            if b<128:
                return val
        raise ValueError("oversized unsigned varint")
    def raw():
        nonlocal at
        n=var()
        val=bytes(view[at:at+n]);at+=n
        need(len(val)==n,"full postcard string")
        return val
    def choice():
        n=var()
        need(n in (0,1),"actual bool or Option")
        return n
    result=[]
    for _ in range(var()):
        name=os.fsdecode(raw())
        member=(var(),var(),os.fsdecode(raw())) if choice() else None
        rows=[(var(),var()) if choice() else None for _ in range(var())]
        temp=bool(choice())
        result.append((name,member,rows,temp))
    metrics=var()
    need(at==len(view),"entire released postcard layout decoded")
    return result,metrics


def contributions(layout, bounds, target):
    rows,metrics=postcard(layout.read_bytes())
    first,last=bounds
    out=[]
    for ix,(name,member,placed,temp) in enumerate(rows):
        hits=[(j,b) for j,b in enumerate(placed) if b and first<=b[0]<b[1]<=last]
        if not hits:
            continue
        path=Path(name)
        if not path.is_absolute():
            path=(target/path).resolve(strict=True)
        with path.open("rb") as stream:
            if member:
                stream.seek(member[0]);data=stream.read(member[1]-member[0])
            else:
                data=stream.read()
        ss=sections(data)
        inputs=[]
        for j,(start,end) in hits:
            n,h,_=ss[j]
            inputs.append([j,n,h[9],h[2],start,end])
        out.append({"file_index":ix,"file":str(path),"member":member,"input_sha256":hashlib.sha256(data).hexdigest(),
                    "placed":inputs})
    return {"files":len(rows),"metrics":metrics,"contributors":out}


def manifest(root):
    return {str(p.relative_to(root)):sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def literal_inputs(root, live_output, frozen, inputs):
    live={}
    for relative, recorded in inputs.items():
        if relative=="run-with":
            continue
        path=Path("/")/relative
        if not path.is_file():
            parent=path.parent
            need(path.name=="symbols.o" and parent.name.startswith("rustc") and
                 parent.parent==live_output.parent and parent.parent.resolve(strict=True).is_relative_to(root),
                 ("only restore the signed rustc invocation's private temporary object",str(path)))
            parent.mkdir(mode=0o700,exist_ok=True)
            need(not parent.is_symlink() and sha(frozen/relative)==recorded,"authentic saved physical file")
            with path.open("xb") as dest,(frozen/relative).open("rb") as src:
                shutil.copyfileobj(src,dest)
        live[str(path)]=sha(path)
        if live[str(path)]!=recorded:
            # Wild's save feature relocates embedded absolute paths only in text linker scripts.
            with path.open("rb") as stream:
                start=stream.read(4096)
            need(b"GROUP" in start or b"INPUT" in start,("raw file matches captured bytes",str(path)))
    return live


def main():
    ws=Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    head=os.environ["GITHUB_SHA"]
    need(os.environ["GITHUB_REPOSITORY"]=="astral-experiments/ohm" and os.environ["GITHUB_REF"]==study.BRANCH
         and os.environ["GITHUB_RUN_ATTEMPT"]=="1" and os.environ["REVIEWED_HEAD"]==head,"bounded nonrelease native receipt")
    for d,h in (("enrolled",head),("historical",study.RENDERER)):
        need(subprocess.check_output(["git","-C",ws/d,"rev-parse","HEAD"]).decode().strip()==h,"actual source")
    sys.path.insert(0,str(ws/"historical/scripts/gnu-example-ceiling"))
    import workload as w
    root=Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)/"ruff-example-price"
    root.mkdir();out=root/"evidence";out.mkdir()
    bins=factory.recover_factory(root,ws,out)
    bins["released"]=root/"distribution/bin/cargo"
    wild=root/"distribution"/study.WILD
    need(sha(wild)=="0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5","unchanged physical released Wild")
    cpus=sorted(os.sched_getaffinity(0));need(len(cpus)>=4,"four CPUs");os.sched_setaffinity(0,cpus[:4])
    study.select(root,bins,"released")
    src=w.source(root);w.sources(src,"corrected")
    env=w.env_for(root);seed=w.prepare_registry(root,src,env,out);study.reset(env,seed,w)
    args=["test","-p",study.PACKAGE,"--test","rustc_tests","--no-run"]
    study.execute(root,src,env,out/"prepare",args)
    saved=root/"frozen-wild-inputs"
    actual=study.execute(root,src,dict(env,WILD_SAVE_BASE=str(saved)),out/"actual",args,trace=True)
    target=Path(actual["executables"]["test/rustc_tests/True"][0])
    chosen=[f for f in saved.glob("*/run-with") if f.read_text().splitlines()[-1].startswith("# Original output file:") and
            Path(f.read_text().splitlines()[-1].removeprefix("# Original output file:").strip()).name==target.name]
    need(len(chosen)==1,("one saved signed linker closure",target.name,[str(p)for p in saved.glob("*/run-with")]))
    script,=chosen;inputs=manifest(script.parent);save(out/"frozen-inputs.json",inputs)
    (out/"run-with.txt").write_bytes(script.read_bytes())
    programs=[row["args"]for row in actual["execs"]if row["kind"]=="wild" and "-o" in row["args"] and Path(row["args"][row["args"].index("-o")+1]).name==target.name]
    need(len(programs)==1,"physical original Wild command")
    save(out/"original-argv.json",programs[0])
    images={"ordinary":read_image(target,out/"ordinary-readelf.gz")}
    results={}
    argv=programs[0]
    stable=Path(argv[argv.index("-o")+1])
    need(stable.is_file() and stable.resolve(strict=True).is_relative_to(root) and sha(stable)==sha(target),
         "real private output path and original promoted file")
    need(Path(argv[0]).samefile(wild),"actual signed executable")
    live=literal_inputs(root,stable,script.parent,inputs)
    save(out/"live-inputs.json",live)
    # The upstream replay script rewrites the PT_INTERP string. The original command below
    # reuses the actual GNU interpreter path and the exact original rustc temp input.
    known_before=dict(live)
    cases=[("plain-a",[],None),("plain-b",[],None),("one",["--threads=1"],None),("four",["--threads=4"],None),
           ("single-file",["--threads=1"],"1"),("two-files",["--threads=1"],"2"),("eight-files",["--threads=1"],"8")]
    for label,opts,group in cases:
        sub=dict(env,WILD_WRITE_LAYOUT="1")
        if group:sub["WILD_FILES_PER_GROUP"]=group
        cmd=[*argv,*opts]
        proc=subprocess.run(cmd,cwd=src,env=sub,capture_output=True,timeout=180)
        study.compressed(out/(label+"-stderr.gz"),proc.stderr)
        need(proc.returncode==0,(label,proc.returncode,proc.stderr[-1500:]))
        image=read_image(stable,out/(label+"-readelf.gz"))
        images[label]=image
        outcome=byte_probe.verdicts(src,env,out/(label+"-verdict"),{"rustc_tests":(str(stable),image["sha256"],image["size"])})
        results[label]=outcome["rustc_tests"]
        need(results[label]["exit"]==0 and len(results[label]["cases"])==72 and
             all(v=="ok" for n,v in results[label]["cases"]),"72 real libtest verdicts")
        layout=Path(str(stable)+".layout")
        study.compressed(out/(label+"-layout.gz"),layout.read_bytes())
        save(out/(label+"-contributors.json"),contributions(layout,image["rodata_range"],src))
        save(out/(label+"-image.json"),image)
        save(out/(label+"-case-verdict.json"),results[label])
    need(all(image["digest_except_note_and_rodata_entsize"]==images["ordinary"]["digest_except_note_and_rodata_entsize"]
             for image in images.values()) and
         images["ordinary"]["sha256"] in {image["sha256"] for name,image in images.items() if name!="ordinary"},
         "literal replay preserves every original byte outside the observed fields, and one entire signed control")
    need(images["one"]["rodata_entsize"]==0 and images["single-file"]["rodata_entsize"]==8,
         "one mixed group vs last single-file group")
    groups=json.loads((out/"single-file-contributors.json").read_bytes())["contributors"]
    winner=groups[-1]
    path=Path(winner["file"])
    member=winner["member"]
    placed=winner["placed"]
    need(member and path.name.startswith("libcompiler_builtins-") and len(placed)==1 and
         placed[0][1:3]==[".rodata.cst8",8] and str(path) in argv,"original terminal contributor")
    private=root/"single-input-control"
    private.mkdir()
    copy=private/path.name
    shutil.copyfile(path,copy)
    need(not copy.samefile(path) and sha(copy)==live[str(path)],"private immutable-input copy")
    args=[str(copy) if v==str(path) else v for v in argv]
    control_env=dict(env,WILD_FILES_PER_GROUP="1")
    intervention={}
    for version in ("original-copy","four-byte-entity"):
        if version=="four-byte-entity":
            with copy.open("r+b") as stream:
                stream.seek(member[0]);body=stream.read(member[1]-member[0])
                need(hashlib.sha256(body).hexdigest()==winner["input_sha256"],"specific loaded archive member")
                sec,original,hdr=sections(body)[placed[0][0]]
                need(sec==".rodata.cst8" and original[9]==8 and original[5]%4==0,
                     "precise input section and valid retained entity width")
                stream.seek(member[0]+hdr+56);stream.write(struct.pack("<Q",4))
        proc=subprocess.run([*args,"--threads=1"],cwd=src,env=control_env,capture_output=True,timeout=180)
        study.compressed(out/(version+"-stderr.gz"),proc.stderr)
        need(proc.returncode==0,(version,proc.returncode,proc.stderr[-1500:]))
        measured=read_image(stable,out/(version+"-readelf.gz"))
        verdict=byte_probe.verdicts(src,env,out/(version+"-verdict"),{"rustc_tests":(str(stable),measured["sha256"],measured["size"])})
        intervention[version]={"private_input_sha256":sha(copy),"image":measured,"verdict":verdict["rustc_tests"]}
        save(out/(version+"-input-control.json"),intervention[version])
    need(intervention["original-copy"]["image"]["sha256"]==images["single-file"]["sha256"] and
         intervention["four-byte-entity"]["image"]["rodata_entsize"]==4 and
         all(row["verdict"]["exit"]==0 and len(row["verdict"]["cases"])==72 and
             all(v=="ok" for n,v in row["verdict"]["cases"]) for row in intervention.values()),
         "actual two-width input influence and complete behavior")
    need(all(sha(Path(name))==digest for name,digest in known_before.items()),"literal original inputs stayed unchanged")
    save(out/"input-influence.json",{"winner":winner,"intervention":intervention})
    save(out/"images.json",images)
    save(out/"verdicts.json",results)
    need(manifest(script.parent)==inputs,"unchanged physical input closure across all links")
    save(out/"terminal.json",{"boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
         "run":os.environ["GITHUB_RUN_ID"],"head":head,"released_cargo":sha(bins["released"]),"wild":sha(wild),
         "source_tag":"0.11.0","source_commit":"e856d81f6683cad80b9fe0ebf1a0c3c403c6fe11","cases":cases,
         "physical_inputs":len(inputs),"images":images})


if __name__=="__main__":
    main()
