"""Retain original native input bodies and kernel observations with deterministic ZIP framing."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile


KEEP={"unit-graph.json","owner-inputs.json","ownership-complete.json","registry.json","sdk.json","actual-sdk.json"}
PREFIX=("release23/","calibration/","events-edited/","events-new-unchanged/","observer-source/")

def pack(source, output, manifest, original, artifact):
    with source.open("rb") as f:
        if hashlib.file_digest(f,"sha256").hexdigest()!=original:
            raise ValueError("unauthenticated GitHub archive")
    digests={}
    with zipfile.ZipFile(source) as z, zipfile.ZipFile(output,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as new:
        for name in sorted(z.namelist()):
            if name not in KEEP and not name.startswith(PREFIX):
                continue
            path=Path(name)
            if path.is_absolute() or ".." in path.parts or z.getinfo(name).is_dir() or name in digests:
                raise ValueError(name)
            body=z.read(name)
            if any(t in body for t in (b"ghp_",b"github_pat_",b"X-Amz-Signature=",b"GH_TOKEN=",b"GITHUB_TOKEN=",b"SSH_AUTH_SOCK=")):
                raise ValueError("unexpected private field in "+name)
            digests[name]=hashlib.sha256(body).hexdigest()
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.external_attr=0o100644 << 16
            new.writestr(info,body,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    with zipfile.ZipFile(output) as z:
        if digests!={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()}:raise ValueError("body changed during escrow")
    with output.open("rb") as f: outsha=hashlib.file_digest(f,"sha256").hexdigest()
    manifest.write_text(json.dumps({"original_artifact_id":artifact,"original_sha256":original,"original_bytes":source.stat().st_size,
        "packet_sha256":outsha,"packet_bytes":output.stat().st_size,"members":digests},indent=2,sort_keys=True)+"\n")

if __name__=="__main__":pack(*map(Path,sys.argv[1:4]),sys.argv[4],int(sys.argv[5]))
