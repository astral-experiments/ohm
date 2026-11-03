"""Sample the actual shipped compiler on exactly one ordinary Ruff check, retaining all controls."""
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import inventory
import owner_read
import worker as w

TARGET="ty_python_semantic"
STAGES=("old","old-unchanged","edited","new-unchanged","invalid","repair","clean")

def image_records(where):
    images={}
    for f in sorted(where.glob("*.nul")):
        cells=f.read_bytes().split(b"\0")
        w.need(cells.pop()==b"" and len(cells)>=5,"incomplete physical command")
        pid,dev,ino,exe,*argv=[s.decode() for s in cells]
        images[int(f.stem)]=(int(pid),int(dev),int(ino),exe,argv)
    history=defaultdict(list);counts=Counter();counts_by_task=Counter();monitor=None
    for ln in (where/"epochs.tsv").read_text().splitlines():
        row=ln.split()
        if row[0]=="M":
            w.need(monitor is None,"duplicate observer");monitor=int(row[1])
        elif row[0]=="I":
            n,pid,tid,stamp=map(int,row[1:5]);w.need(images[n][0]==pid and row[5] in ("exec","first"),"incorrect image epoch")
            history[pid].append((stamp,n,row[5]))
        else:
            w.need(row[0]=="C","unknown kernel record");n,pid,tid,count,enabled,running=map(int,row[1:])
            w.need(images[n][0]==pid and enabled==running and (enabled>0 or count==0),"unreadable or multiplexed task counter")
            counts[n]+=count;counts_by_task[(n,tid)]+=count
    w.need(monitor and monitor not in history and all(v==sorted(v) for v in history.values()),"wrong image time order")
    return images,history,counts,counts_by_task

def acquire():
    w.checked_head()
    w.need(not any(os.environ.get(k) for k in ("GH_TOKEN","GITHUB_TOKEN","RUSTC_WRAPPER","LD_PRELOAD")),"ambient control")
    ref=json.loads((w.HERE/"pc-reference.json").read_bytes());top=w.OUT
    kit=json.loads((top/"sdk.json").read_bytes()); mem=kit["members"]
    driver,=(w.SDK/"lib").glob("librustc_driver-*.so")
    cd={n:dict(path=str(f),device=f.stat().st_dev,inode=f.stat().st_ino,sha256=w.sha(f)) for n,f in
        (("rustc",w.SDK/"bin/rustc"),("driver",driver),("cargo",w.SDK/"bin/cargo"),("wild",w.SDK/"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"))}
    w.need(all(v["sha256"]==ref[k]==mem[str(Path(v["path"]).relative_to(w.SDK))][3] for k,v in cd.items()),"wrong signed runtime")
    w.save(top/"pc-sdk.json",cd)
    from matched import COUNT_SHA
    w.need(w.sha(w.HERE/"whole_count.c")==COUNT_SHA,"unverified whole counter for ordinary controls")
    subprocess.run(["/usr/bin/cc","-O2","-Wall","-Wextra","-Werror",w.HERE/"whole_count.c","-o",w.ROOT/"whole-count"],check=True)
    perf,observer=w.setup_perf()
    w.OUT=top/"release23";w.OUT.mkdir()
    w.save(w.OUT/"compiler.json",{"rustc_vV":subprocess.check_output(["rustc","+ohm","-vV"],env=w.environment(),text=True)})
    capture=top/"profile";capture.mkdir();where=capture/"exec";where.mkdir()
    raw=capture/"perf.data"
    def observe(out,env):
        # Restore the complete ordinary Cargo environment immediately after perf has started.
        tool=[*w.perf.record(perf,raw,["/usr/bin/env","-i",*(k+"="+v for k,v in sorted(env.items())),observer,where,*w.CMD],w.perf.PERIOD)]
        w.run(tool,env,out)
        w.need(0<raw.stat().st_size<256<<20,"native profile size")
        with (capture/"perf.data.zst").open("xb")as f:subprocess.run(["zstd","-q","-3","-c",raw],stdout=f,check=True)
        w.save(capture/"raw-identity.json",dict(bytes=raw.stat().st_size,sha256=w.sha(raw),compressed_sha256=w.sha(capture/"perf.data.zst")))
        images,hist,counts,tasks=image_records(where)
        roots=[];by_name={};role=cd["rustc"]
        for pid,epochs in hist.items():
            for stamp,n,why in epochs:
                _,dev,ino,exe,argv=images[n]
                if why!="exec" or (dev,ino,exe)!=(role["device"],role["inode"],role["path"]) or "--crate-name" not in argv or "--out-dir" not in argv:continue
                name=argv[argv.index("--crate-name")+1]
                w.need(name not in by_name and name in ref["normalized_argv"] and owner_read.fingerprint(argv)==ref["normalized_argv"][name],"different shipped native argv: "+name)
                tids=sorted(tid for k,tid in tasks if k==n)
                by_name[name]=dict(pid=pid,epoch=n,start_ns=stamp,threads=tids,instructions=counts[n],argv_sha256=owner_read.digest(json.dumps(argv,separators=(",",":")).encode()))
                roots.append(dict(crate=name,pid=pid,argv=argv))
        w.need(by_name.keys()==ref["normalized_argv"].keys() and by_name[TARGET]["instructions"]>0,"wrong physical edit roster")
        w.save(capture/"owner-epochs.json",by_name);return roots
    def phase(name,state,**kwargs):
        return inventory.phase(name,state,observe=observe if name=="edited" else None,**kwargs)
    inventory.main(phase=phase)
    phases={name:json.loads((w.OUT/name/"phase.json").read_bytes()) for name in STAGES}
    for name,row in phases.items():
        w.need(sum(row["counts"].values())==ref["ordinary"][name]["literal_rustcs"] and row["diagnostics"]==ref["ordinary"][name]["diagnostics"],"different source-matched normal control "+name)
    w.need(phases["edited"]["counts"]==phases["repair"]["counts"]==dict.fromkeys(ref["normalized_argv"],1),"different repaired owner roster")
    metas={n:v["workspace_rmeta"] for n,v in phases.items() if n!="invalid"}
    w.need(metas["old"]==metas["old-unchanged"] and metas["edited"]==metas["new-unchanged"]==metas["repair"] and
           sorted(k for k,v in metas["edited"].items() if metas["clean"][k]==v)==ref["empty_matches"] and all(len(v)==31 for v in metas.values()),"wrong clean/full metadata behavior")
    w.save(top/"native-profile-controls.json",dict(source=ref["source"],cargo=ref["cargo_source"],controls={k:v["counts"] for k,v in phases.items()},clean_equal=ref["empty_matches"]))
    # Preserve raw observations and the entire genuine oracle even if the optional source decoder rejects its coverage.
    n=w.perf.decode(perf,raw,capture)
    buildids=subprocess.run([*w.perf.private_argv(perf),"buildid-list","--with-hits","-i",str(raw)],env=w.perf.clean_subprocess(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    (capture/"buildids.txt").write_bytes(buildids.stdout);(capture/"buildids.stderr").write_bytes(buildids.stderr)
    import semantic_pcs
    semantic_pcs.analyze(raw,capture,cd,minimum=5000)
    w.save(top/"pc-complete.json",dict(samples=n,head=os.environ["REVIEWED_HEAD"],boot=json.loads((top/"worker.json").read_bytes())["boot"],native=True,semantic=w.sha(capture/"semantic.json")))
    raw.unlink()

if __name__=="__main__":acquire()
