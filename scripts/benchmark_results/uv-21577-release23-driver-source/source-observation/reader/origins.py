"""Authenticate the selected physical archives while the selected compiler's Cargo parent is still waiting."""
import gzip
import hashlib
import os
import shlex
import tomllib
from pathlib import Path
from read import digest,require

def keep(root,kind,raw):
    h=digest(raw);f=root/(kind+"-"+h+".gz")
    if not f.exists():
        with f.open("xb")as out:out.write(gzip.compress(raw,compresslevel=2,mtime=0))
    return {"file":f.name,"sha256":h,"bytes":len(raw)}

def read_native(root,ref):
    path=root/ref["file"]
    require(path.parent==root and path.name.endswith("-"+ref["sha256"]+".gz"),"invalid source member")
    b=gzip.decompress(path.read_bytes());require(len(b)==ref["bytes"] and digest(b)==ref["sha256"],"source media changed")
    return b

def source_manifest(source):
    if source and source.is_file():
        for parent in source.parents:
            manifest=parent/'Cargo.toml'
            if not manifest.is_file():continue
            raw=manifest.read_bytes();body=tomllib.loads(raw.decode())
            if "package" not in body:continue
            if (parent/body.get("lib",{}).get("path","src/lib.rs")).resolve()==source:
                return manifest,raw,body
            return None
    return None

def originals(visit,observed,request):
    cwd=request["cwd"]
    workspace=next((p for p in Path(request["manifest"]).parents if (p/"Cargo.toml").is_file() and
                    "workspace" in tomllib.loads((p/"Cargo.toml").read_text())),None)
    retained=visit/'origins';retained.mkdir()
    entries=[]
    for row in observed['rows']:
        path=Path(row['source'])
        with path.open('rb') as stream:
            st=os.fstat(stream.fileno())
            require((st.st_dev,st.st_ino,st.st_size)==(row['physical']['dev'],row['physical']['ino'],row['physical']['size']),
                    ("selected archive changed before post-compiler custody",path))
            fingerprint=hashlib.file_digest(stream,"sha256").hexdigest()
            end=os.fstat(stream.fileno())
            require((end.st_dev,end.st_ino,end.st_size,end.st_mtime_ns,end.st_ctime_ns)==
                    (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns),("archive changed while hashed",path))
        item={"path":str(path),"key":row["key"],"size":st.st_size,"sha256":fingerprint,"native_sources":[]}
        for alias in sorted({path,path.resolve(strict=True)}):
            dep=alias.with_name(alias.name.removeprefix("lib").removesuffix(".rlib")+".d")
            if not dep.is_file():continue
            raw=dep.read_bytes();require(len(raw)<32<<20,("large dep-info",dep))
            records=[line.partition(b": ")[2]for line in raw.splitlines()if line.startswith(os.fsencode(alias)+b": ")]
            if len(records)!=1:continue
            inputs=shlex.split(os.fsdecode(records[0]))
            if not inputs:continue
            candidates={}
            for base in (Path(cwd),workspace):
                if base is None:continue
                first=(base/inputs[0]).resolve()
                candidate=source_manifest(first)
                if candidate:candidates.setdefault(first,(base,candidate))
            if len(candidates)!=1:continue
            (first,(base,(m,manifest,meta))),=candidates.items()
            item["native_sources"].append({"alias":str(alias),"base":str(base),"dep_info":keep(retained,"dep-info",raw),
                "lib":str(first),"lib_sha256":digest(first.read_bytes()),"manifest":str(m),"manifest_bytes":keep(retained,"manifest",manifest),
                "name":meta["package"]["name"],"version":meta["package"].get("version")})
        entries.append(item)
    return entries

def verify(visit,native,entries,cwd):
    require(len(entries)==len(native["rows"]), "incomplete archive custody")
    for row,entry in zip(native["rows"],entries):
        require((row["source"],row["key"],row["physical"]["size"])==(entry["path"],entry["key"],entry["size"]) and
                len(entry["sha256"])==64, "archive inventory changed/reordered")
        for src in entry["native_sources"]:
            dep=read_native(visit/'origins',src["dep_info"])
            source,=[a.partition(b": ")[2] for a in dep.splitlines() if a.startswith(os.fsencode(src["alias"])+b": ")]
            lib=Path(os.path.normpath(Path(src["base"])/shlex.split(os.fsdecode(source))[0]))
            manifest=tomllib.loads(read_native(visit/'origins',src['manifest_bytes']).decode())
            require(str(lib)==src["lib"] and (Path(src["manifest"]).parent/manifest.get("lib",{}).get("path","src/lib.rs"))==lib and
                    src['name']==manifest['package']['name'] and src['version']==manifest['package'].get('version'),
                    ("source/manifest does not describe original dep-info",src))
