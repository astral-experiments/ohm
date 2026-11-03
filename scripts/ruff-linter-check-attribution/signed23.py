"""Authenticate and materialize the documented Linux release from its actual package bytes."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile


BINDING = json.loads((Path(__file__).resolve().parent/"signed23-source.json").read_bytes())
RUST = BINDING["provenance"]["sources"]["rust"]["revision"]
CARGO = BINDING["provenance"]["sources"]["cargo"]["revision"]

def digest(data):
    return hashlib.sha256(data).hexdigest()

def role(name):
    # Rust's compiler/standard-library member suffix is derived from the build, so read the actual release member name.
    return re.sub(r"-[0-9a-f]{16}(?=\.(?:rlib|rmeta|so|o)$)", "-<crate>", name)

def install(w, template):
    b=BINDING;a=b["assets"]["archive"]
    meta=json.loads(subprocess.check_output(w.gh("releases/tags/"+b["release"])))
    w.need((meta["tag_name"],meta["target_commitish"],meta["published_at"])==(b["release"],b["packaging"],b["published_at"]),
           "different published release")
    for which,fixed in b["assets"].items():
        found,=[v for v in meta["assets"] if v["id"]==fixed["id"]]
        w.need(all(found[k]==v for k,v in fixed.items()),"different published "+which)
        if which!="archive":
            body=subprocess.check_output(w.gh("releases/assets/"+str(fixed["id"]),"-H","Accept: application/octet-stream"))
            w.need(len(body)==fixed["size"] and digest(body)==fixed["digest"][7:],"incorrect release attachment")
            if which=="checksum":
                w.need(body.decode().split()==[a["digest"][7:],a["name"]],"published checksum")
            else:
                w.need(json.loads(body)==b["provenance"],"published platform provenance")
    archive=w.ROOT/a["name"]
    with archive.open("xb") as out:
        subprocess.run(w.gh("releases/assets/"+str(a["id"]),"-H","Accept: application/octet-stream"),stdout=out,check=True,timeout=600)
    w.need(archive.stat().st_size==a["size"] and w.sha(archive)==a["digest"][7:],"wrong release archive")
    expected={role(tarpath):(role(logical),mode) for logical,(tarpath,mode,_,_) in template.items()}
    w.need(len(expected)==len(template)==79,"unexpected template collision")
    w.SDK.mkdir()
    by_name={};by_role=set()
    with tarfile.open(archive,"r|gz") as tar:
        for m in tar:
            key=role(m.name)
            if key not in expected:continue
            name=m.name.split("/",2)[2];expected_name,mode=expected[key]
            w.need(m.isreg() and role(name)==expected_name and m.mode==mode and
                   key not in by_role and name not in by_name and ".." not in Path(name).parts and not Path(name).is_absolute(),"ambiguous native SDK member")
            path=w.SDK/name;path.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(m) as src,path.open("xb") as dst:shutil.copyfileobj(src,dst,1<<20)
            path.chmod(mode)
            w.need(path.stat().st_size==m.size,"incomplete extracted member")
            by_name[name]=[m.name,mode,m.size,w.sha(path)];by_role.add(key)
    w.need(by_role==set(expected) and len(by_name)==79,"incomplete physical toolchain")
    for name,(_,mode,size,body) in by_name.items():
        path=w.SDK/name
        w.need(path.stat().st_size==size and path.stat().st_mode&0o777==mode and w.sha(path)==body,"physical SDK readback")
    w.save(w.OUT/"sdk.json",{"asset":a,"provenance":b["provenance"],"members":by_name})
    archive.unlink()
