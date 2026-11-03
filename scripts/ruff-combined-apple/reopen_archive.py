"""Audit the 75 original Cargo commands and their repaired, clean and signed Mach-O files."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess as sp
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import macho

RUST="d46c44b58d91b9d7b4b0d2fc4850c31ad5cbc8f2"
CARGO="4a6de7858c60e579fc30e01f5b60ddcaa84c2e30"
SOURCE_ARCHIVE="38bc2c1f6827efb9f7b09e6f398025e688d3f82d1831bc6e8308b290847d2e19"


def audit(archive, execute):
    with archive.open("rb") as f:
        assert archive.stat().st_size==4662433 and hashlib.file_digest(f,"sha256").hexdigest()==SOURCE_ARCHIVE
    z=zipfile.ZipFile(archive)
    assert z.testzip() is None
    read=lambda key:json.loads(z.read(key))
    for name in ("candidate.json","sources.json"):
        source=read(name)
        assert (source["rust"],source["cargo"])==(RUST,CARGO)
    assert read("signed.json")["release"]=="371e7cb6ca778e44b599ee4fbb83c7ca85f6306353825bce1d40f7d692f03a53"
    all_commands=[]
    def records(work,label,suffix,status):
        name=f"{work}-{label}.{suffix}"
        rows=list(map(json.loads,z.read(name).splitlines()))
        assert rows[-1]=={"reason":"build-finished","success":status==0}
        codes=[r["message"]["code"]["code"] for r in rows if r.get("reason")=="compiler-message" and r["message"].get("code")]
        assert ("E0308" in codes)==(status==101)
        all_commands.append([name,status])
        return rows
    def fresh(rows,target):
        return [r["fresh"] for r in rows if r.get("reason")=="compiler-artifact" and r["target"]["name"]==target]
    groups={}
    smoke=read("smoke.json")
    assert len(smoke["ordinary_cargo_histories"])==45
    for r in "PC":
        for mode in ("mixed-alias","check","build","test"):
            work=r+"-"+mode
            assert fresh(records(work,"during-save","stdout",0),"consumed-input")==[False]
            warm=records(work,"unchanged","stdout",0 if r=="P" else 101)
            if r=="P":assert fresh(warm,"consumed-input")==[True]
            records(work,"independent-clean","stdout",101)
            if mode=="mixed-alias":continue
            if r=="P":records(work,"upgrade","stdout",101)
            for label in ("repair","repair-clean","repair-unchanged"):
                rows=records(work,label,"stdout",0)
                if label=="repair-clean":assert fresh(rows,"consumed-input")==[False]
                elif label=="repair-unchanged":assert fresh(rows,"consumed-input")==[True]
    for mode in ("build","test"):
        # The fixture records new-toolchain and real upgrade cases, in that order.
        start=2 if mode=="build" else 4
        for i,work in enumerate(("fixed","upgraded")):
            group=smoke["repairs"][start+i]
            assert group[0]==group[2]
            groups[work+"-"+mode]=group[:2]
    assert len(smoke["controls"])==4
    for c in smoke["controls"]:
        work=c["role"]+"-valid-control-"+c["mode"]
        group=c["rows"]
        assert len(group)==4 and group[0]["elf"]==group[1]["elf"]==group[3]["elf"]
        for row in group:
            assert row["status"]==0
            rows=records(work,row["label"],"stdout",0)
            assert fresh(rows,"consumed-input")==row["fresh"]
        groups[work]=[group[1]["elf"],group[2]["elf"]]
    for role in ("signed","fixed"):
        work="prerequisite-"+role
        for label in ("seed","prime","changed","clean-refusal","repair","clean-repair","repaired-unchanged"):
            status=101 if label=="clean-refusal" or (role=="fixed" and label=="changed") else 0
            rows=records(work,label,"jsonl",status)
            if label=="repaired-unchanged":assert fresh(rows,"observer")==[True]
    assert len(all_commands)==len({n for n,_ in all_commands})==75
    native={}
    with tempfile.TemporaryDirectory()as tmp:
        for tag,keys in groups.items():
            data=[]
            for key in keys:
                body=gzip.decompress(z.read(key+".macho.gz"))
                assert hashlib.sha256(body).hexdigest()==key
                if execute:
                    path=Path(tmp)/key;path.write_bytes(body);path.chmod(0o755)
                    sp.run(["/usr/bin/codesign","--verify","--strict",path],check=True,capture_output=True)
                    if tag.endswith("-test"):
                        listing=sp.check_output([path,"--list"])
                        assert b"returns_seventeen: test" in listing and b"1 test," in listing
                        assert b"1 passed;" in sp.check_output([path,"--exact","returns_seventeen"])
                    else:assert sp.check_output([path])==b"17\n"
                data.append(body)
            verdict=macho.compare(*data)
            # Freshly re-sign a changed loadable byte. The independent byte gate must still refuse it.
            bad=bytearray(data[1]);bad[16392]^=1;macho.sign(bad,False)
            try:macho.compare(data[0],bad)
            except AssertionError:pass
            else:raise AssertionError("accepted altered native program")
            native[tag]={"sha256":keys,**verdict}
    return dict(rust=RUST,cargo=CARGO,source_archive=SOURCE_ARCHIVE,cargo_commands=all_commands,
                native=native,real_signatures_and_runtime=execute)

if __name__=="__main__":
    execute=len(sys.argv)==4 and sys.argv[3]=="--execute"
    if execute:assert platform.system()=="Darwin" and platform.machine()=="arm64"
    result=audit(Path(sys.argv[1]),execute);Path(sys.argv[2]).write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("75 original Cargo commands and all eight complete Mach-O reconstructions passed",flush=True)
