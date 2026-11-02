"""Compare real Cargo arguments across two legitimately distinct compiler cache namespaces."""
from pathlib import Path
import re

TAG=re.compile(r"(?<=/)v2-[0-9a-f]{16}(?=/)")
PLACEHOLDER="v2-<compiler-file-identity>"


def layout(env):
    return {k:env[k] for k in ("CARGO_BUILD_BUILD_DIR","CARGO_TARGET_DIR")}


def map_path(path,dirs,keys,*,registry=None):
    if not TAG.search(path):
        return path
    root=Path(path)
    if not root.is_absolute() or str(root)!=path or ".." in root.parts or PLACEHOLDER in path:
        raise ValueError("unrecognized v2 path")
    for name,tail,shared in (("CARGO_BUILD_BUILD_DIR",r"debug/build/registries/",True),
                             ("CARGO_TARGET_DIR",r"debug/build/workspaces/[0-9a-f]{16}/",False)):
        base=Path(dirs[name])
        if not base.is_absolute() or not root.is_relative_to(base):
            continue
        relative=root.relative_to(base).as_posix()
        match=re.fullmatch(tail+r"(v2-[0-9a-f]{16})/(.+)",relative)
        if not match or len(TAG.findall(path))!=1:
            continue
        keys.add(match[1])
        if shared and registry is not None:
            registry.add(path)
        return TAG.sub(PLACEHOLDER,path,count=1)
    raise ValueError("v2 path outside the actual registry or local workspace trees")


def argv(args,dirs,keys,registry=None):
    out=[]
    for i,v in enumerate(args):
        if not TAG.search(v):
            if PLACEHOLDER in v:
                raise ValueError("prospective comparison token in original argv")
            out.append(v)
            continue
        prev=args[i-1] if i else ""
        if prev=="--out-dir":
            out.append(map_path(v,dirs,keys))
            continue
        if v.startswith("/") and v.endswith(".rlink") and "--crate-name" in args and "--out-dir" in args:
            name=args[args.index("--crate-name")+1]
            dest=Path(args[args.index("--out-dir")+1])
            suffix=[a.partition("=")[2] for j,a in enumerate(args) if j and args[j-1]=="-C" and a.startswith("extra-filename=")]
            if (name=="e2e" and any(j and args[j-1]=="-Z" and a=="link-only" for j,a in enumerate(args)) and
                len(suffix)==1 and re.fullmatch(r"-[0-9a-f]{16}",suffix[0]) and str(dest/(name+suffix[0]+".rlink"))==v):
                out.append(map_path(v,dirs,keys))
                continue
        name,eq,p=v.partition("=")
        if not eq or not (prev=="--extern" and re.fullmatch(r"[A-Za-z0-9_:]+",name) or
                          prev=="-L" and name in ("dependency","native","crate","all","framework") or
                          prev=="-Z" and name=="temps-dir" or prev=="-C" and name=="incremental"):
            raise ValueError(("compiler namespace appeared in an unregistered argument",prev,v))
        out.append(name+eq+map_path(p,dirs,keys,registry=registry if prev=="--extern" else None))
    return out


def project(record,dirs):
    keys=set()
    reg=set()
    owners=[[name,argv(args,dirs,keys,reg)] for name,args in record["root_argv"]]
    roster=record["roster"].copy()
    if "autocfg" in roster:
        expected=[]
        for r in roster["autocfg"]:
            expected.append(r|{"argv":argv(r["argv"],dirs,keys),"owner":map_path(r["owner"],dirs,keys)})
        roster["autocfg"]=sorted(expected,key=lambda r:(r["owner"],r["suffix"],r["stdin_sha256"]))
    if len(keys)>1 or (owners and (len(keys)!=1 or not reg)):
        raise ValueError("missing or ambiguous ordinary shared-registry extern in selected compiler argv")
    receipt={"paths":layout(dirs),"ids":sorted(keys),"shared_owner_extern_paths":sorted(reg)}
    return owners,roster,receipt


def comparable(record,dirs):
    owners,roster,_=project(record,dirs)
    mandatory=("dirty","inventory","verdict","elf","error")
    return {k:record.get(k) for k in mandatory}|{"root_argv":owners,"roster":roster}
