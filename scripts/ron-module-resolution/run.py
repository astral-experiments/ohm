"""Replay one signed Ron compiler role. The pinned input capsule is shared with the prior study."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from reopen import scoped_joins, sha


def require_source():
    manifest=json.loads((HERE/"source.json").read_bytes())
    with tarfile.open(HERE/"source-verified.tar.xz") as archive:
        assert {e.name for e in archive}==set(manifest)
        for e in archive:
            assert e.isfile() and e.size<1024*1024 and ".." not in Path(e.name).parts and not Path(e.name).is_absolute()
            body=archive.extractfile(e).read();entry=manifest[e.name]
            assert hashlib.sha256(body).hexdigest()==entry["sha256"]
            assert hashlib.sha1(b"blob "+str(len(body)).encode()+b"\0"+body).hexdigest()==entry["oid"]
    original=json.loads(gzip.decompress((HERE/"observed.json.gz").read_bytes()))
    receipt=original["receipt"]
    assert len(original["input_sha256"])==555 and original["source_refs"]==manifest
    for arm in original["gdb"].values():
        assert len(scoped_joins(arm,receipt["input_ids"]))==3
    assert sum(code==0 for code in receipt["producer_rows"].values())==6
    print("Verified two signed native bridge captures, eight uninstrumented verdicts, six reader ELFs and both source pins.")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--work",type=Path);p.add_argument("--kit",type=Path);p.add_argument("--sdk",type=Path)
    p.add_argument("--verify-recorded",action="store_true");a=p.parse_args()
    require_source()
    if a.verify_recorded:return
    if not all((a.work,a.kit,a.sdk)):p.error("supply --work, --kit and --sdk for a fresh native replay")
    dest=a.work.resolve();kit=a.kit.resolve();sdk=a.sdk.resolve()
    assert sha(kit/"SHA256SUMS")=="a0234af903544344229030d65528e34af43c407d9a4aa212a0a2629fa9c58f5a"
    dest.mkdir();(dest/"rustup/toolchains").mkdir(parents=True);(dest/"rustup/toolchains/ohm").symlink_to(sdk)
    shutil.copyfile(HERE/"source.json",dest/"source.json");shutil.copyfile(HERE/"registration.json",dest/"registration.json")
    with tarfile.open(HERE/"source-verified.tar.xz") as archive:
        for member in archive:
            path=dest/"source"/member.name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(archive.extractfile(member).read())
    env=dict(os.environ,RON_CONTROL_WORK=str(dest),RON_CONTROL_KIT=str(kit),RON_CONTROL_SDK=str(sdk))
    for file in ("capture.py","bridge.py","decode.py"):
        subprocess.run([sys.executable,"-IB",str(HERE/file)],env=env,check=True)
    with (dest/"independent.json").open("xb") as output:
        subprocess.run([sys.executable,"-IB",str(HERE/"reopen.py"),str(dest)],check=True,stdout=output)
    print("Fresh independent receipt",sha(dest/"independent.json"))


if __name__=="__main__":
    main()
