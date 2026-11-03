"""After the ordinary packet has been uploaded, price each actual selected compiler lifetime."""
import json
import os
from pathlib import Path
import subprocess as sp

import actor
from actor import CASES, COMMAND, CRATES, HERE, LIB, base, need, old, w
from member_names import native_identity

def lifetimes(directory,physical):
    labels={};group={};records=[];whole=None
    for line in (directory/"epochs.tsv").read_text().splitlines():
        f=line.split()
        if f[0]=="I":
            i,g=int(f[1]),int(f[2]);parts=(directory/f"{i:05}.nul").read_bytes().split(b"\0")
            need(parts.pop()==b"" and int(parts[0])==g,"original lifetime descriptor")
            labels[i]=(tuple(map(int,parts[1:3])),[os.fsdecode(v) for v in parts[4:]],f[5]);group[i]=g
        elif f[0]=="R":
            i,pid,n,e,r,code=map(int,f[1:]);identity,argv,origin=labels[i]
            need(origin=="exec" and identity==physical and group[i]==pid and n>0 and e==r>0 and code==0,"incomplete selected lifetime")
            records.append({"pid":pid,"image":i,"argv":argv,"instructions":n,"enabled":e,"running":r})
        elif f[0]=="W":
            whole,enabled,running,code=map(int,f[1:]);need(whole>0 and enabled==running>0 and code==0,"invalid observer total")
    need(whole is not None,"incomplete journal")
    return records,whole

def identity(path):
    s=path.stat();return s.st_dev,s.st_ino
def measure(trace,exe,args,directory,env,cwd):
    directory.mkdir();tasks=directory/"tasks";tasks.mkdir()
    with (directory/"stdout.jsonl").open("xb")as out,(directory/"stderr").open("xb")as err:
        sp.run([trace,"--lifetime",exe,tasks,*args],cwd=cwd,env=env,stdout=out,stderr=err,check=True)
    return lifetimes(tasks,identity(exe))

def calibrate(td,trace,env):
    exe=w.root/"thread-meter";sp.run(["cc","-O2","-pthread","-Wall","-Wextra","-Werror",HERE/"thread_meter.c","-o",exe],check=True)
    result={}
    for n,mode in ((1000000,"alone"),(4000000,"alone"),(1000000,"spawn")):
        rows,total=measure(trace,exe,[exe,str(n),mode],td/(str(n)+"-"+mode),env,w.root)
        by={a["argv"][-1]:a["instructions"]for a in rows}
        need(len(by)==len(rows) and set(by)==({mode,"child"} if mode=="spawn"else {mode}),"unexpected calibration image")
        need(abs(sum(by.values())/total-1)<.02,"process lifetime units or coverage")
        result[(n,mode)]=by
    first=result[1000000,"alone"]["alone"]
    need(3.8<result[4000000,"alone"]["alone"]/first<4.2 and abs(result[1000000,"spawn"]["spawn"]/first-1)<.03
         and result[1000000,"spawn"]["child"]>7*first,"thread inheritance or child-process exclusion")
    w.put(td/"calibration.json",{str(k):v for k,v in result.items()})

def main():
    case=os.environ["OHM_OWNER_CASE"];old.old,old.new,old.lock,order=CASES[case]
    need(os.environ["GITHUB_RUN_ATTEMPT"]=="1" and os.environ["REVIEWED_HEAD"]==os.environ["GITHUB_SHA"],"different physical worker")
    source=w.proof;ordinary=json.loads((source/"result.json").read_bytes());reg=json.loads((source/"registration.json").read_bytes())
    need(ordinary["case"]==case and reg["order"]==order and reg["boot"]==Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"different ordinary input")
    ctx=json.loads((w.root/"continuation.json").read_bytes());env=ctx["environment"];roots={r:Path(v)for r,v in ctx["roots"].items()}
    dest=w.root/"diagnostic";dest.mkdir();trace=w.root/"exec_count"
    calibrate(dest,trace,env);reports={}
    for role in order:
        w.guard();out=dest/role;out.mkdir();root=roots[role]
        need(root.is_relative_to(w.root) and root.is_dir() and not w.sdk.exists(),"unregistered diagnostic SDK layout")
        root.rename(w.sdk)
        for directory in (w.target,w.shared):
            if directory.name not in ctx["parked"][role]:continue
            (w.root/("park-"+role+"-"+directory.name)).rename(directory)
        try:
            driver,=(w.sdk/"lib").glob("librustc_driver-*.so");need(w.hf(driver)==reg["binding"]["driver"][role],"different physical compiler")
            selected=w.sdk/"bin/rustc"
            observed={}
            for phase,state in (("observed-old",old.old),("observed-edit",old.new),("observed-unchanged",old.new)):
                old.state(state);td=out/phase
                readings,whole=measure(trace,selected,COMMAND,td,env,w.work)
                records,_=old.result_rows(td,True);dirty=sorted(r["target"]["name"]for r in records if not r["fresh"])
                census=old.census(td,env);received={}
                for row in readings:
                    argv=row["argv"]
                    if "--crate-name"not in argv:continue
                    name=argv[argv.index("--crate-name")+1];need(name not in received,"duplicate native rustc")
                    received[name]=row["instructions"]
                need(set(received)==set(dirty) and sorted(census["real_execs"])==sorted("rustc:"+v for v in received),"different program or physical compile roster")
                if phase=="observed-edit":
                    need(dirty==ordinary["roles"][role]["actual_dirty"] and received["ty_project"]>0,"different ordinary edit")
                    libs=base.products(records);expected=json.loads((source/role/"edit/native.json").read_bytes())
                    matches={}
                    for crate in CRATES:
                        actual=base.read_names(libs[crate]["rlib"],crate)
                        need(native_identity(actual)==native_identity(expected[crate]["mapping"]),("diagnostic changed physical target",crate))
                        matches[crate]=old.record_file(libs[crate]["rlib"])
                    w.put(td/"native-outputs.json",matches)
                if phase=="observed-unchanged":need(not dirty and not received,"real no-op compiler")
                observed[phase]={"observed":census,"whole":whole,"lifetimes":received,"raw":readings,"dirty":dirty}
                w.put(td/"result.json",observed[phase])
            reports[role]=observed["observed-edit"]
        finally:
            w.sdk.rename(root);old.remove_outputs()
    w.put(dest/"result.json",{"case":case,"run":os.environ["GITHUB_RUN_ID"],"roles":reports,"affected_rustc_reduction":1-reports["C"]["lifetimes"]["ty_project"]/reports["P"]["lifetimes"]["ty_project"]})
if __name__=="__main__":
    main()
