"""Save the small raw command records. Native originals remain authenticated by their full ZIP hash."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

def selected(name):
    if name in {"registration.json","result.json","public-states.json"}:
        return True
    fields=name.split("/")
    if fields[0] not in {"P","C"}:
        return name.startswith("calibration-") and name.endswith("hardware.json")
    if len(fields)==2:
        return fields[-1] in {"admitted.json","tools.json","cold-footprint.json","edit-footprint.json",
                            "edit-retention.json","stale-old-on-edited.stdout"}
    return (len(fields)==3 and fields[-1] in {"hardware.json","result.json","native.json","stdout.jsonl"}) or (
        len(fields)==4 and fields[-2]=="oracle" and fields[-1] in {"stdout","stderr","argv.json","linked-symbols.json"})

def main():
    p=argparse.ArgumentParser()
    p.add_argument("input",type=Path);p.add_argument("--sha256",required=True);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    with a.input.open("rb") as f:
        if hashlib.file_digest(f,"sha256").hexdigest()!=a.sha256:
            raise ValueError("different original archive")
    with zipfile.ZipFile(a.input)as z,zipfile.ZipFile(a.output,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=9)as target:
        rows={};size=0
        for name in sorted(z.namelist()):
            if not selected(name):
                continue
            info=z.getinfo(name);size+=info.file_size
            if info.file_size>24*2**20 or size>200*2**20:
                raise ValueError("unexpectedly large control file")
            data=z.read(name);rows[name]=[len(data),hashlib.sha256(data).hexdigest()]
            entry=zipfile.ZipInfo(name);entry.compress_type=zipfile.ZIP_DEFLATED
            target.writestr(entry,data,compresslevel=9)
        if not {"P/edit/hardware.json","C/edit/hardware.json","result.json"}<=set(rows):
            raise ValueError("incomplete ordinary pair")
        target.writestr(zipfile.ZipInfo("manifest.json"),
                        json.dumps({"ordinary_archive":a.sha256,"members":rows},sort_keys=True,separators=(",",":")))
if __name__=="__main__":
    main()
