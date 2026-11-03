"""Reopen the individual kernel PMU epochs, actual image argv and mapped rustc_driver."""
import os
from pathlib import Path


def need(test, reason):
    if not test:
        raise ValueError(reason)


def counted(directory):
    images,counts,groups={}, {}, {}
    monitor=None
    for line in (directory/"epochs.tsv").read_text().splitlines():
        r=line.split()
        if r[0]=="M":
            need(monitor is None and not images and len(r)==3,"initial monitor")
            monitor=int(r[1])
        elif r[0]=="I":
            n,g,t,stamp=map(int,r[1:5]);need(len(r)==6 and n==len(images)+1 and r[5] in ("first","exec") and 0<min(g,t,stamp),"image journal")
            data=(directory/f"{n:05}.nul").read_bytes().split(b"\0")
            need(data[-1]==b"" and len(data)>=6 and int(data[0])==g,"image argument body")
            images[n]=dict(group=g,tid=t,dev=int(data[1]),ino=int(data[2]),exe=os.fsdecode(data[3]),argv=[os.fsdecode(x)for x in data[4:-1]],trigger=r[5])
            counts[n]=[0,0,0];groups[n]=set()
        else:
            need(r[0]=="C" and len(r)==7,"counter journal")
            n,g,t,value,enabled,running=map(int,r[1:])
            need(n in images and images[n]["group"]==g and g>0 and t>0 and value>=0 and enabled==running>=0 and (value==0 or enabled>0),"partial kernel count")
            groups[n].add(t)
            for i,k in enumerate((value,enabled,running)):counts[n][i]+=k
    need(monitor and images and len(list(directory.glob("*.nul")))==len(images) and all(groups.values()),"incomplete images")
    # The first image is the controlled launcher between its initial stop and the first exec.
    first=images[1]
    need(first["trigger"]=="first" and first["group"]==first["tid"] and Path(first["exe"]).name=="exec-count","unexpected initial executable")
    return images,counts,groups


def mapping(file, identity):
    matches=[]
    for row in file.read_text().splitlines():
        cols=row.split(None,5)
        need(len(cols)==6 and int(cols[4])>0,"malformed maps row")
        if "x" not in cols[1] or "librustc_driver-" not in cols[5]:continue
        maj,minor=(int(x,16)for x in cols[3].split(":"))
        matches.append([os.makedev(maj,minor),int(cols[4]),cols[5]])
    need(matches and all(x[:2]==identity["driver_inode"] and x[2]==identity["driver_path"] for x in matches),"another or missing live rustc_driver")
    return matches


def owner(directory, identity, crate, revision_root):
    images,counts,groups=counted(directory);picked=[]
    all_compilers=[];build_tools=[]
    for n,im in images.items():
        args=im["argv"]
        if im["trigger"]=="exec" and "build-script-build" in Path(im["exe"]).name.replace("_","-"):
            build_tools.append(dict(exe=im["exe"],argv=args,instructions=counts[n][0],dev=im["dev"],ino=im["ino"]))
        if im["trigger"]!="exec" or [im["dev"],im["ino"]]!=identity["rustc_inode"] or "--crate-name" not in args:continue
        j=args.index("--crate-name");name=args[j+1]
        if name=="___" or "--emit=dep-info,metadata" not in args and not any(a.startswith("--emit=")for a in args):continue
        all_compilers.append(name)
        if name!=crate:continue
        need(args.count("--crate-name")==1 and "--emit=dep-info,metadata" in args and "--crate-type" in args and args[args.index("--crate-type")+1]in("lib","rlib"),"not the registered check emitter")
        selected=[str((revision_root/arg).resolve()) for arg in args if arg.endswith("/src/lib.rs") and (revision_root/arg).resolve()==(revision_root/"crates"/crate/"src/lib.rs").resolve()]
        need(len(selected)==1 and counts[n][0]>0 and im["group"] in groups[n] and len(groups[n])>1,"missing actual root source or host worker instructions")
        mappings=mapping(directory/f"{n:05}.maps",identity)
        picked.append(dict(image=n,tgid=im["group"],argv=args,instructions=counts[n][0],enabled=counts[n][1],running=counts[n][2],threads=sorted(groups[n]),driver=identity["driver"],mappings=mappings))
    total=sum(v[0] for n,v in counts.items() if n!=1)
    need(total>0 and len(picked)<=1,"ambiguous real owner")
    return dict(total=total,owner=picked,compilers=sorted(all_compilers),build_scripts=build_tools,images=len(images))
