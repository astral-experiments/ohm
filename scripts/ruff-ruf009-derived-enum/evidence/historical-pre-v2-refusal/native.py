"""Reopen the old unscored pilot's native evidence without treating it as a matched trial."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import zipfile

ORIGINAL = "bbad7bd93996ca2b1485456a23e2ecb19024f99b8e85117c2ac485885bc29248"
NAMES = ["native-buggy","native-edited","native-reverse","native-repair","native-empty-edit"]
CASES = ["attr-attributes","attr-field","both-clean","both-warn"]
EXPECTED = {"buggy":[0,1,0,1],"fixed":[1,0,0,1]}
def file_hash(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def region(f,offset,size):
    f.seek(offset);h=hashlib.sha256()
    for _ in range(0,size,1<<20):
        n=min(size,1<<20);buf=f.read(n);assert len(buf)==n;h.update(buf);size-=n
    return h.hexdigest()
def sections(p):
    with p.open("rb") as f:
        hdr=f.read(64);assert hdr[:7]==b"\x7fELF\x02\x01\x01"
        shoff=struct.unpack_from("<Q",hdr,40)[0];shsize,count,names=struct.unpack_from("<HHH",hdr,58)
        assert shsize==64 and 0<names<count
        f.seek(shoff);tab=struct.iter_unpack("<IIQQQQIIQQ",f.read(shsize*count));tab=list(tab)
        f.seek(tab[names][4]);strings=f.read(tab[names][5])
        out={}
        for row in tab[1:]:
            off,kind,flags,_,pos,n,*_=row
            name=strings[off:strings.index(0,off)].decode();assert name not in out
            out[name]={"type":kind,"flags":flags,"bytes":n,"sha256":None if kind==8 else region(f,pos,n)}
        return out
def guard(p):
    available=int(next(l.split()[1] for l in Path("/proc/meminfo").read_text().splitlines() if l.startswith("MemAvailable:")))*1024
    f=os.statvfs(p);assert available>=8<<30 and f.f_bavail*f.f_frsize>=15<<30
def main():
    ap=argparse.ArgumentParser();ap.add_argument("archive",type=Path);ap.add_argument("work",type=Path);ap.add_argument("result",type=Path);a=ap.parse_args()
    a.work.mkdir(exist_ok=True);guard(a.work);assert file_hash(a.archive)==ORIGINAL
    visited={};media={};records={};sh={}
    with zipfile.ZipFile(a.archive) as z:
        for role in ("P","C"):
            records[role]={}
            for label in NAMES:
                guard(a.work);r=json.loads(z.read(f"{role}/{label}/native.json"));key=r["sha256"];out=a.work/key
                if key not in visited:
                    if not out.exists():
                        with tempfile.NamedTemporaryFile(dir=a.work,delete=False) as tmp:
                            dest=Path(tmp.name)
                            with subprocess.Popen(["zstd","-q","-dc"],stdin=subprocess.PIPE,stdout=tmp) as child:
                                digest=hashlib.sha256()
                                with z.open("members/"+key+".elf.zst") as source:
                                    while chunk:=source.read(1<<20):digest.update(chunk);child.stdin.write(chunk)
                                child.stdin.close();assert child.wait()==0 and digest.hexdigest()==r["compressed"]
                        assert dest.stat().st_size==r["bytes"] and file_hash(dest)==key;dest.chmod(0o555);dest.rename(out)
                    assert file_hash(out)==key and out.stat().st_size==r["bytes"];sh[key]=sections(out)
                    visited[key]=r["state"];media[key]=[]
                    for ci,name in enumerate(CASES):
                        probe=r["probes"][name];assert probe["code"]==EXPECTED[r["state"]][ci] and probe["stderr"]==""
                        with tempfile.TemporaryDirectory(dir=a.work) as cwd:
                            cmd=[out.resolve(),"check","--isolated","--no-cache","--select","RUF009","--output-format=json","--stdin-filename=case.py","-"]
                            rr=subprocess.run(cmd,cwd=cwd,input=probe["input"],text=True,capture_output=True,timeout=30)
                            assert (rr.returncode,rr.stderr)==(probe["code"],probe["stderr"])
                            old=json.loads(probe["stdout"]);new=json.loads(rr.stdout);assert len(old)==len(new)==rr.returncode
                            for x,y in zip(old,new):
                                assert x["filename"]=="/home/runner/work/ohm/ohm/ruff/case.py" and y["filename"]==str(Path(cwd)/"case.py")
                                assert x==dict(y,filename=x["filename"]) and x["code"]=="RUF009"
                            media[key].append({"case":name,"exit":rr.returncode,"input_sha256":hashlib.sha256(probe["input"].encode()).hexdigest(),"original_stdout_sha256":hashlib.sha256(probe["stdout"].encode()).hexdigest()})
                assert visited[key]==r["state"];records[role][label]=key
            rows=records[role];assert rows[NAMES[0]]==rows[NAMES[2]] != rows[NAMES[1]]==rows[NAMES[3]]==rows[NAMES[4]]
    assert len(media)==4
    cross={}
    for label in NAMES[:2]:
        p,c=[records[x][label] for x in ("P","C")];ps,cs=sh[p],sh[c];assert ps.keys()==cs.keys()
        cross[label]={k:[ps[k],cs[k]] for k in sorted(ps) if ps[k]!=cs[k]}
    a.result.write_text(json.dumps({"archive_sha256":ORIGINAL,"roles":records,"independent_local_native_probes":media,"cross_role_different_sections":cross,"within_role_edited_equals_repaired_and_empty":True,"local_filename_substitution":"Only the verified original absolute runner prefix vs current temporary working directory changed in diagnostic JSON. All codes, messages, source ranges and other bytes agreed."},sort_keys=True,indent=1)+"\n")
    print(file_hash(a.result),{k:list(v) for k,v in cross.items()})
if __name__=="__main__":main()
