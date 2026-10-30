"""Keep the authenticated Cargo and kernel streams from each real Ruff command for offline replay."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_links import command, file_hash

PLANS = {
    "signed-focus": ("41054731602","12976193634","086a5224bf973b7fbfa3f2e5567ff048a1ca8867287eb4a75b6e3a4907e34567"),
    "signed-workspace": ("41054731602","12976474099","aa1b3dd9af55c2b9d5ef94bba0b8581c669a10ac9332701f9ed208a377eceb2c"),
    "paired-focus": ("41056076188","12978505922","795507e5d0bf58e49b4cbb4050fa65e1c62097ec69502b8e7655f9686b427121"),
}


def put(tar, name, content):
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mtime = 0
    tar.addfile(info, io.BytesIO(content))


def write(source, kind, outfile):
    run, artifact, expected = PLANS[kind]
    assert not outfile.exists() and file_hash(source)==expected
    with zipfile.ZipFile(source) as raw, tarfile.open(outfile,"x:xz",preset=3) as tar:
        assert len(raw.namelist())==len(set(raw.namelist())) and raw.testzip() is None
        prefixes = []
        for key in sorted(raw.namelist()):
            if key.endswith("/verified.json"):
                result = json.loads(raw.read(key))
                if result.get("scope") in ("focus","workspace"):
                    prefix = key.removesuffix("verified.json")
                    command(raw, prefix, result)
                    prefixes.append(prefix)
        assert prefixes
        selected = []
        for key in sorted(raw.namelist()):
            prefix,_,base = key.rpartition("/")
            if not base:
                continue
            if prefix+"/" in prefixes or base in ("clean-equivalence-old.json","clean-equivalence-new.json","paired-physical.json","focused-physical.json"):
                content = raw.read(key)
                if key.endswith(".gz"):
                    content = gzip.decompress(content)
                put(tar,key,content)
                selected.append((key,hashlib.sha256(content).hexdigest()))
        manifest = dict(run=run,artifact=artifact,original_zip_sha256=expected,kind=kind,command_dirs=prefixes,files=selected)
        put(tar,"MANIFEST.json",json.dumps(manifest,sort_keys=True,separators=(",",":")).encode())


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("kind",choices=PLANS)
    p.add_argument("source",type=Path)
    p.add_argument("output",type=Path)
    args=p.parse_args()
    write(args.source,args.kind,args.output)
