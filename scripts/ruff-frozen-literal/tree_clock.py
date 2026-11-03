"""Read the inherited PMU and join it to kernel-observed complete executable images."""
import hashlib
import os
from pathlib import Path

from readout import need,mapping


def decode(trace,mode,identity,crate):
    images={};birth={};finished={};selection=[];outcome=None;monitor=None
    for line in (trace/"epochs.tsv").read_text().splitlines():
        f=line.split();tag=f.pop(0)
        if tag=="M":
            need(not images and monitor is None and len(f)==2,"monitor record");monitor=int(f[0])
        elif tag=="I":
            n,g,t,when=map(int,f[:4]);need(len(f)==5 and n==len(images)+1 and g>0 and t>0 and when>0 and f[4]in("first","exec"),"image record")
            data=(trace/f"{n:05}.nul").read_bytes().split(b"\0");need(data[-1]==b"" and len(data)>=6 and int(data[0])==g,"physical image and argv")
            images[n]=dict(tgid=g,ino=[int(data[1]),int(data[2])],exe=os.fsdecode(data[3]),argv=[os.fsdecode(v)for v in data[4:-1]],trigger=f[4])
        elif tag=="T":
            t,g,n=map(int,f);need(t not in birth and n in images and images[n]["tgid"]==g,"task birth");birth[t]=(g,n)
        elif tag=="A":
            n,t=map(int,f);need(n in images and images[n]["tgid"]==t,"selected exec");selection.append(n)
        elif tag=="X":
            t,g,n,status=map(int,f);need(n in images and images[n]["tgid"]==g and t in birth and birth[t][0]==g and t not in finished,"complete task exit");finished[t]=(g,status)
        else:
            need(tag=="F" and len(f)==6 and outcome is None,"terminal counter row");outcome=list(map(int,f))
    need(monitor and len(images)>=2 and images[1]["trigger"]=="first" and Path(images[1]["exe"]).name=="target-count" and set(birth)==set(finished) and len(list(trace.glob("*.nul")))==len(images) and outcome is not None,"complete kernel roster")
    status,select,measured,value,enabled,running=outcome
    candidates=[];compilers=[];generators=[]
    for n,im in images.items():
        if im["trigger"]!="exec":continue
        args=im["argv"]
        if "build-script-build" in Path(im["exe"]).name.replace("_","-"):generators.append(im["exe"])
        if im["ino"]!=identity["rustc_inode"] or "--crate-name" not in args:continue
        name=args[args.index("--crate-name")+1];emit=[a for a in args if a.startswith("--emit=")]
        if emit:compilers.append([name,emit[0]])
        if name==crate and "--emit=dep-info,metadata"in args:candidates.append(n)
    need(candidates==selection and (candidates==[select] if select else not candidates) and len(selection)<=1,"complete authentic owner selection")
    first_exec=next(n for n,im in images.items()if im["trigger"]=="exec" and im["tgid"]==images[1]["tgid"])
    expect={"whole":first_exec,"owner":select,"roster":0}[mode]
    need(measured==expect and ((value>0 and enabled==running>0) if expect else value==enabled==running==0),"unscaled inherited PMU and image")
    result=dict(status=status,mode=mode,instructions=value,enabled=enabled,running=running,image=measured,owner=select,compilers=sorted(compilers),build_scripts=sorted(generators),tasks=len(birth),images=len(images))
    if select:
        im=images[select];result.update(argv=im["argv"],tgid=im["tgid"],owner_tasks=sorted(t for t,(g,_)in birth.items()if g==im["tgid"]))
        if identity.get("driver"):
            result["mapping"]=mapping(trace/f"{select:05}.maps",identity)
    return result,images


def externs(argv):
    out={}
    for i,arg in enumerate(argv):
        if arg=="--extern":
            key,value=argv[i+1].split("=",1);path=Path(value);need(key not in out and path.is_absolute()and path.is_file(),"physical --extern input")
            with path.open("rb")as f:h=hashlib.file_digest(f,"sha256").hexdigest()
            out[key]=dict(path=str(path),sha256=h,bytes=path.stat().st_size)
    return out
