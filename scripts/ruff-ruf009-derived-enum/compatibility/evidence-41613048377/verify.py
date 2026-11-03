"""Reopen both registered acquisitions, including the real kernel and file-reader evidence."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

HERE=Path(__file__).resolve().parent
CASE=HERE.parent
read=lambda p:json.loads(p.read_bytes())
def sha(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()

def extract(z,d,expected):
    assert sha(z)==expected
    with zipfile.ZipFile(z) as src:
        assert set(src.namelist())=={"originals.tar.zst","manifest.json"}
        manifest=json.loads(src.read("manifest.json"))
        payload=src.read("originals.tar.zst")
    assert len(payload)==manifest["archive_bytes"] and hashlib.sha256(payload).hexdigest()==manifest["sha256"]
    original=d/"source.tar.zst";original.write_bytes(payload)
    raw=subprocess.check_output(["zstd","-qdc",original]);names=set()
    with tarfile.open(fileobj=io.BytesIO(raw)) as source:
        for m in source:
            p=Path(m.name)
            assert m.name==str(p) and ".." not in p.parts and not p.is_absolute()
            if m.isdir():continue
            assert m.name not in names and m.name in manifest["files"]
            q=d/p;q.parent.mkdir(parents=True,exist_ok=True)
            if m.islnk():
                assert m.linkname in names;os.link(d/m.linkname,q)
            else:
                assert m.isfile() and m.size<=48<<20
                with q.open("xb")as f:shutil.copyfileobj(source.extractfile(m),f)
            names.add(m.name)
    assert names==set(manifest["files"]) and sum((d/n).stat().st_size for n in names)==manifest["raw_bytes"]
    return manifest

def fingerprint(raw):
    data=io.BytesIO(raw)
    def take(n):
        r=data.read(n);assert len(r)==n;return r
    def integer(n):return int.from_bytes(take(n),"little")
    def string():return take(integer(4)).decode()
    assert take(5)==bytes.fromhex("01000000ff") and integer(1)==5
    rows=[]
    for _ in range(integer(4)):
        tp=integer(1);path=string();flag=integer(1);assert tp<2 and flag<2
        rows.append([tp,path,[integer(8),string()]if flag else None])
    assert integer(4)==0 and not data.read()
    return [5,rows]

def aliases(d,plan,b3):
    complete=read(d/"complete.json");role=complete["role"]
    assert complete["driver"]==plan["roles"][role]["driver"] and complete["cargo"]==plan["clients"]["current"]["binary"]
    assert complete["input_hashes"]==[subprocess.check_output([b3],input=bytes.fromhex(x)).split()[0].decode() for x in ("11ff865d","1dff865d")]
    specs={"fixed-c2":{"during-save":(0,1),"first-unchanged":(101,1),"independent-empty":(101,1),"repair":(0,1),"repair-settled":(0,0),"native-repair":(0,1),"native-empty":(0,1)},"positive-c2":{"ordinary":(0,1),"ordinary-unchanged":(0,0)}}
    totals={};native=[]
    for kind,phases in specs.items():
        loc=d/kind/"evidence"
        for phase,(rc,expected) in phases.items():
            row=read(loc/(phase+".json"));assert row["phase"]==phase and row["cargo"]==complete["cargo"] and row["min_avail"]>=8<<30
            for ext in ("exec","stdout","stderr"):assert sha(loc/(phase+"."+ext))==row[ext]
            out=[json.loads(l)for l in (loc/(phase+".stdout")).read_bytes().splitlines()]
            errors=[r["message"]["code"]["code"]for r in out if r["reason"]=="compiler-message"and r["message"].get("code")]
            assert out[-1]=={"reason":"build-finished","success":not rc} and errors==row["errors"]==(["E0308"]if rc else[]) and row["rc"]==rc
            trace=(loc/(phase+".exec")).read_text()
            true=sum('"--crate-name", "consumed_input"' in l and '/bin/rustc",' in l and ' = 0' in l for l in trace.splitlines())
            assert true==row["physical_rustc"]==expected
            assert row["fresh"]==[r["fresh"]for r in out if r["reason"]=="compiler-artifact"and r["target"]["name"]=="consumed-input"]
            totals[kind+"/"+phase]=[rc,true]
            if phase.startswith("native-"):
                assert row["verdict"]=="29 29"and len(row["elf_sha"])==64;native.append(row["elf_sha"])
        if kind=="fixed-c2":
            m=read(loc/"after-save.json")
            assert sha(loc/m["fp"])==m["fp"] and sha(loc/m["raw"])==m["raw"]
            table=fingerprint((loc/m["fp"]).read_bytes());assert table==m["encoded"]
            assert [r[2]for r in table[1]if r[1]=="src/payload.bin"]==[None]
            assert not m["raw_rows"] and not any(l.startswith(b"# checksum:")and l.endswith(b"payload.bin")for l in (loc/m["raw"]).read_bytes().splitlines())
    assert len(native)==2 and native[0]==native[1]
    return {"role":role,"phases":totals,"equal_observed_native_elf":native[0]}

def main():
    p=argparse.ArgumentParser();p.add_argument("current",type=Path);p.add_argument("prior",type=Path);p.add_argument("--b3sum",required=True);p.add_argument("--out",type=Path,required=True);a=p.parse_args()
    plan=read(CASE/"matrix/registration.json");answer={"acquisitions":{},"literal":{},"switches":{},"alias":{}}
    with tempfile.TemporaryDirectory()as temp:
        root=Path(temp);new=root/"current";old=root/"prior";new.mkdir();old.mkdir()
        for name,out,z,digest in [("current",new,a.current,"0fa482d3626b2999467671573bfcfa27b97f3f031360f6ad0565086580de3fc8"),("prior",old,a.prior,"2afe9a562a76bfd0c6a7be4810047faa26b44dea0c395d64f1dd8c3933cd6759")]:
            m=extract(z,out,digest);answer["acquisitions"][name]=[digest,m["sha256"],len(m["files"]),m["raw_bytes"],m["completed"]]
        raw=new/"matrix";terminal=read(raw/"complete.json");assert terminal["registration"]==sha(CASE/"matrix/registration.json") and terminal["enrollment"]==sha(raw/"dispatch/enrollment.json")
        proofs={x["label"]:x for x in terminal["completed"]}
        bound=set()
        for label in ("current","early"):
            inv=read(new/"source-receipts"/("scope-kit-"+label+".json"))
            for arm in inv["manifest"]["arms"].values():bound.update(arm["files"].values())
        for label,s in plan["clients"].items():
            inv=read(new/"source-receipts"/(label+"-cargo.json"));assert s["binary"]in json.dumps(inv);bound.add(s["binary"])
        assert {r["driver"]for r in plan["roles"].values()}|{plan["signed_cargo"],plan["wild"]}<=bound
        bounds=root/"members.json";bounds.write_text(json.dumps(sorted(bound)))
        for label in plan["literal"]:
            name="literal-"+label;d=(new if label=="aware-registry"else old)/"matrix"/name;out=root/(label+".json")
            dispatch=read(d.parent/"dispatch"/(name+".json"))
            argv=dispatch["command"];recorded=Path(argv[argv.index("--work")+1]);assert recorded.is_absolute() and recorded.name==d.name and dispatch["exit"]==0
            subprocess.run([sys.executable,"-IB",CASE/"reopen.py","--root",d,"--recorded-root",recorded,"--b3sum",a.b3sum,"--output",out,"--expect","legacy"if label=="legacy"else"aware"],check=True,stdout=subprocess.DEVNULL)
            result=read(out);assert result["commands"]==40 and result["kernel_typed_rustcs"]==24 and sha(out)==proofs[name]["independent"]
            answer["literal"][label]={k:result[k]for k in("commands","kernel_typed_rustcs","terminal_sha256","binary_fingerprint_epoch")}
        for label,*_ in plan["switches"]:
            name="parked-"+label;d=raw/name;out=d/"independent.json"
            subprocess.run([sys.executable,"-IB",CASE/"independent.py",d,bounds],check=True,stdout=subprocess.DEVNULL)
            assert sha(out)==proofs[name]["independent"];r=read(out);visits=r["visits"]
            answer["switches"][name]={"commands":len(visits),"physically_compiled":sum(len(x["typed"])for x in visits),"probes":sum(x["probe_count"]for x in visits),"links":sum(x["linkers"]for x in visits),"native":r["native"],"receipt":sha(out)}
        for role in plan["alias_roles"]:
            d=raw/("literal-alias-"+role);assert proofs[d.name]["complete"]==sha(d/"complete.json");answer["alias"][role]=aliases(d,plan,a.b3sum)
        assert (len(proofs),len(answer["switches"]),len(answer["alias"]))==(9,4,2)
        answer["unique_cargo_commands"]=3*40+4*44+2*9;answer["terminal"]=sha(raw/"complete.json")
    a.out.write_text(json.dumps(answer,indent=1,sort_keys=True)+"\n")
    print(answer["unique_cargo_commands"],sha(a.out))
if __name__=="__main__":main()
