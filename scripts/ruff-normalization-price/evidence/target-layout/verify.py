"""Verify the original compiler guard data. Pass --run-native to also execute the saved Linux programs."""
import argparse
import hashlib
import json
import lzma
from pathlib import Path
import re
import struct
import subprocess
import tempfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run-native",action="store_true")
args=parser.parse_args()
root=Path(__file__).resolve().parent
import zipfile
packet=zipfile.ZipFile(root/"originals.zip")
members=packet.namelist();assert len(members)==len(set(members))
manifest=json.loads(packet.read("manifest.json"))
def load(name):
    entry=manifest[name]
    raw=lzma.decompress(packet.read("objects/"+entry["sha256"]+".xz"))
    assert len(raw)==entry["bytes"] and hashlib.sha256(raw).hexdigest()==entry["sha256"]
    return raw
def obj(name):return json.loads(load(name))
seen=set()
for name,entry in manifest.items():
    digest=entry["sha256"]
    assert re.fullmatch("[0-9a-f]{64}",digest)
    if digest not in seen:load(name);seen.add(digest)
assert set(members)=={"manifest.json",*("objects/"+h+".xz"for h in seen)}
executed={}
def native(name,expected):
    raw=load(name);sha=hashlib.sha256(raw).hexdigest()
    assert raw[:7]==b"\x7fELF\x02\x01\x01" and struct.unpack_from("<H",raw,18)==(62,)
    if args.run_native and sha not in executed:
        with tempfile.TemporaryDirectory()as here:
            p=Path(here)/"observer";p.write_bytes(raw);p.chmod(0o700)
            executed[sha]=subprocess.check_output([p],timeout=40).decode().strip()
    if args.run_native:assert executed[sha]==expected
    return sha
def symbols(raw):
    assert raw[:5]==b"\x7fELF\x02";fmt={1:"<",2:">"}[raw[5]]
    unpack=lambda shape,at:struct.unpack_from(fmt+shape,raw,at)
    assert unpack("H",16)==(1,)
    off,=unpack("Q",40);width,count,_=unpack("HHH",58);assert width==64
    sections=[unpack("IIQQQQIIQQ",off+i*width)for i in range(count)]
    result={}
    for s in sections:
        if s[1]!=2:continue
        names=sections[s[6]];strings=raw[names[4]:names[4]+names[5]];assert s[9]==24
        for pos in range(s[4],s[4]+s[5],24):
            name,info,_,ix,value,size=unpack("IBBHQQ",pos)
            if info&15!=1 or not ix:continue
            sym=strings[name:strings.index(0,name)].decode()
            if not sym.startswith("OHM_"):continue
            sh=sections[ix];start=value-sh[3];assert 0<=start<=sh[5]-size
            result[sym[4:]]=raw[sh[4]+start:sh[4]+start+size],sh[8]
    return unpack("H",18)[0],fmt,result
for t,machine,fmt in (("s390x-unknown-linux-gnu",22,">"),("x86_64-unknown-linux-gnu",62,"<")):
    prior=None
    for arm,marked in (("c5",0),("c7",5)):
        stem=f"layout/{arm}/{t}/"
        assert load(stem+"thir").count(b"LiteralArray(")==marked
        actual,endian,found=symbols(load(stem+"cases.o"))
        assert (actual,endian)==(machine,fmt) and len(found)==11
        for label,(raw,align)in found.items():
            want=bytearray();n=1023 if label=="SHORT" else 1025
            for i in range(n):
                a=(0x1042+i*67)%65536;b=(0xa1b2c3d4+i*15437)%2**32;c=(0x3707+i*37)%65536;ch=(65,955,129408,0x10fffe)[i%4]
                if label=="SCALAR":row=struct.pack(fmt+"H",a)
                elif label=="CHAR":row=struct.pack(fmt+"I",ch)
                elif label=="PADDED":row=struct.pack(fmt+"IB3x",b,a%256)
                elif label in ("NESTED","REORDER","RANGE"):
                    row=struct.pack(fmt+"IHH",b,a,0 if label=="RANGE"and i==n//2 else c)
                else:
                    assert label in ("PAIR","ATTR","SUFFIX","CAST","SHORT")
                    row=struct.pack(fmt+"II",b,ch)
                want.extend(row)
            assert raw==want and align>=min(4,len(row))
        if prior:assert found==prior
        prior=found
for arm,marked in (("c5",0),("c7",4)):
    rec=obj(f"guard/{arm}/verdict.json")
    assert rec["marker_count"]==marked and rec["old"]!=rec["repair"]==rec["empty"]
    assert len(rec["invalid"])==2 and rec["invalid"][0]==rec["invalid"][1]
    for name in ("old","repair","empty"):
        assert native(f"guard/{arm}/program-"+name,rec[name]["output"])==rec[name]["elf"]
    rows=obj(f"pointer/{arm}/result.json")["records"]
    assert [r["label"]for r in rows]==["shared","distinct","offset","aligned","mutable","separate-promotions","invalid","repaired"]
    for row in rows:
        if row["label"]=="invalid":
            assert row["attempts"]==[{"status":101,"codes":["E0308"]}]*2;continue
        rr=row["edit"]
        for kind in ("empty","settled"):
            assert (rr["elf"],rr["output"])==(row[kind]["elf"],row[kind]["output"])
        assert native(f"pointer/{arm}/native/"+rr["elf"],rr["output"])==rr["elf"]
    assert len({r["edit"]["public_hash"]for r in rows[:5]})==5
    assert rows[0]["edit"]["elf"]==rows[-1]["edit"]["elf"]
assert b"left: 0" in load("runmake/parent/stderr") and b"right: 8" in load("runmake/parent/stderr")
runs=load("runmake/candidate/stderr").splitlines()
assert len(runs)==3 and all(v.startswith(b"running: ") and v.endswith(b'/candidate/table"') for v in runs)
rr=obj("transitions/results.json");assert len(rr)==21
for row in rr:
    receipts=[json.loads(s)for s in load("transitions/"+row["label"]+"/stdout").splitlines()]
    assert receipts[-1]=={"reason":"build-finished","success":row["returncode"]==0}
    assert row["dirty"]==[m["target"]["name"]for m in receipts if m["reason"]=="compiler-artifact"and not m["fresh"]]
    if "elf"in row:assert native("transitions/native/"+row["elf"],row["output"])==row["elf"]
    if "error"in row:
        code,file,start,end,message=row["error"]
        matching=[m["message"]for m in receipts if m["reason"]=="compiler-message"and(m["message"].get("code")or{}).get("code")==code]
        diag,=matching;span,=[s for s in diag["spans"]if s["is_primary"]]
        assert (diag["message"],span["file_name"],span["byte_start"],span["byte_end"])==(message,file,start,end)
by={r["label"]:r for r in rr}
assert [r["error"][0]for r in rr if "error"in r]==["E0308","E0308","overflowing_literals","overflowing_literals"]
for left,right in (("c7-edit-build","c7-empty-build"),("c7-edit-build","repaired-build"),("downgrade-build","downgrade-empty-build"),("second-upgrade-edit-build","second-upgrade-empty-build")):
    assert by[left]["elf"]==by[right]["elf"]
assert len({by[n]["elf"]for n in ("old-build","c7-edit-build","downgrade-build","second-upgrade-edit-build")})==4
for arm in ("c5","c7"):
    for mode in ("check","build"):
        for ext in (("rmeta",)if mode=="check"else("rmeta","rlib")):
            assert load(f"registry/{arm}/{mode}/edit/lib.{ext}")==load(f"registry/{arm}/{mode}/empty/lib.{ext}")
    assert load(f"inspection/{arm}/edit/unicode_normalization")==load(f"inspection/{arm}/empty/unicode_normalization")
for arm in ("f5","c5","c7"):
    a,b=[load(f"inspection/{arm}/{s}/ruff_python_parser").splitlines()for s in ("edit","empty")]
    assert len(a)==len(b)==293 and [i for i,(x,y)in enumerate(zip(a,b))if x!=y]==[2,3,31,32,33,34,49,52,59,291]
assert [len(load(f"registry/{arm}/build/edit/lib.rmeta"))for arm in ("c5","c7")]==[1720649,733953]
counts=[]
for arm in ("f5","c5","c7"):
    raw=load(f"holdout/{arm}/callgrind")
    summary,=re.findall(rb"^summary: ([0-9]+)$",raw,re.M);assert re.findall(rb"^totals: ([0-9]+)$",raw,re.M)==[summary]
    counts.append(int(summary))
    res=obj(f"holdout/{arm}/result.json");assert len(res["dirty"])==11 and res["generated"]["generated_phf.rs"]=="4812faa3a82d2a02ac004df2fbde343185927dd71dce1d6cf23b22e94385b855"
assert counts==[9489390493,5830046582,4744397650]
print(f"Verified {len(manifest)} original entries, 22 target-by-target comparisons, 21 compiler-transition calls and all three software counts. Executed {len(executed)} distinct original Linux programs.")
