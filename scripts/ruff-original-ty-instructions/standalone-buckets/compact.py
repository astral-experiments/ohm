"""Keep the original counter, Cargo, process, ELF-membership and public-row receipts."""
import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

TOP = {"factory-consumed.json","registration.json","sequence.json","public-transitions.json","terminal.json","sdk-proof.json"}
ROLE = {"unit-graph.json","tools.json","qualified.json","retention.json","observed-retention.json","footprint.json","old-client-on-new.stdout"}
PHASE = {"old","edit","unchanged","invalid","repair","observed-old","observed-edit","observed-unchanged","independent-clean"}
RECEIPTS = {"hardware.json","result.json","native.json","stdout.jsonl","stderr","tasks/epochs.tsv","oracle/argv.json",
            "oracle/stdout","oracle/stderr","oracle/compile.stderr","oracle/linked-symbols.json","oracle/old-interface.stderr"}


def selected(name):
    if name in TOP or re.fullmatch(r"calibration-(1000000|4000000)/hardware.json",name):
        return True
    parts=name.split("/",2)
    if parts[0] not in ("P","C"):
        return False
    if len(parts)==2:
        return parts[1] in ROLE
    return (len(parts)==3 and parts[1] in PHASE and
            (parts[2] in RECEIPTS or re.fullmatch(r"tasks/[0-9]{5,6}\.nul",parts[2]) is not None))


def hash_bytes(b):
    return hashlib.sha256(b).hexdigest()


def put(t,name,b):
    h=tarfile.TarInfo(name)
    h.mode=0o644;h.size=len(b);t.addfile(h,io.BytesIO(b))


def pack(directory,manifest,output):
    assets=json.loads(manifest.read_bytes())
    entries={}
    index={}
    for slot in range(6):
        row,=[x for x in assets["assets"] if x["name"].endswith(f"-{slot}")]
        archive=directory/f"{slot}.zip"
        with archive.open("rb") as f:
            if hashlib.file_digest(f,"sha256").hexdigest()!=row["digest"].removeprefix("sha256:") or archive.stat().st_size!=row["size_in_bytes"]:
                raise ValueError("source archive mismatch")
        files={}
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                n=info.filename
                if selected(n):
                    if n in files or info.file_size>16*2**20:
                        raise ValueError("duplicate or oversized control witness")
                    data=z.read(info);h=hash_bytes(data);entries.setdefault(h,data);files[n]=h
        if not TOP.issubset(files):
            raise ValueError("missing top-level controls")
        index[str(slot)]={"original_sha256":row["digest"],"files":files}
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        tar=Path(tmp)/"controls.tar"
        with tarfile.open(tar,"w",format=tarfile.USTAR_FORMAT) as t:
            put(t,"index.json",json.dumps(index,sort_keys=True,separators=(",",":")).encode())
            for h,b in sorted(entries.items()):
                put(t,"b/"+h,b)
        if tar.stat().st_size>128*2**20:
            raise ValueError("unexpected raw control size")
        subprocess.run(["zstd","-q","-15","-T1","-f",tar,"-o",output],check=True)
    return len(entries),output.stat().st_size


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("directory",type=Path);p.add_argument("--assets",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();print(pack(a.directory,a.assets,a.output))
