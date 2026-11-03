"""Retain the source-native dist before eligibility checks; even a later refusal preserves the bytes."""
import gzip
import os
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import gate as g
sys.path.append(str(g.PREVIOUS))
import sdk

def stage(w,output):
    archive=w/"source/rust/build/dist"/(sdk.TARBASE+".tar.gz")
    if not archive.is_file():return None
    assert not archive.is_symlink() and archive.stat().st_size>0
    dest=w/"driver-source-dist";dest.mkdir()
    physical=dest/"ohm.tar.gz";os.link(archive,physical);assert physical.samefile(archive)
    source=w/"trait-evidence/source.json";shutil.copyfile(source,dest/"source.json")
    q={"role":os.environ["BENCH_ARM"],"coordinator":os.environ["GITHUB_SHA"],"run":int(os.environ["GITHUB_RUN_ID"]),"source":g.sha(source),"archive_bytes":physical.stat().st_size,"archive_sha256":g.sha(physical),"eligible":False}
    g.save(dest/"dist-custody.json",q)
    with output.open("a") as out:out.write("available=true\n")
    before=w/"driver-audit-private/pre-bolt.so"
    if before.is_file():
        capture=g.read(w/"trait-evidence/driver-witness/capture.json")
        assert not before.is_symlink() and g.sha(before)==capture["pre_bolt"]["sha256"]
        with before.open("rb") as inp,(dest/"pre-bolt.so.gz").open("xb") as data:
            with gzip.GzipFile(filename="",mode="wb",fileobj=data,compresslevel=3,mtime=0) as compressed:shutil.copyfileobj(inp,compressed,1<<20)
        shutil.copyfile(w/"trait-evidence/driver-witness/capture.json",dest/"capture.json")
    return q
if __name__=="__main__":
    w=g.checkout("build");assert os.environ["BENCH_ARM"]=="T"
    stage(w,Path(os.environ["GITHUB_OUTPUT"]))
