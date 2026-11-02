"""Fast tests of the real observer/reader boundaries without downloading a compiler or running a trial."""
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import receiver, storage, tracking, placement_peak
import readback
sys.path.insert(0,str(HERE))
import check_handoff, decision, durable, worker
for name in ("receiver","storage","tracking","placement_peak","readback","check_handoff","decision","durable","worker"):
    assert Path(sys.modules[name].__file__).resolve()==HERE/(name+".py"),(name,sys.modules[name].__file__)
from common import need, source_binding


def rejects(fn):
    try:fn()
    except (ValueError,RuntimeError,AssertionError,IndexError):return
    raise ValueError("accepted adversarial input")


def main():
    reg=source_binding();need(reg["roles"]["C"]["revision"]=="4e546b27c311f29d99f9528e64420887f57c7538","unexpected source revision")
    wire=b"OSP\1"+b"k"*32+b"CGU-GLOBAL-LINES\1"+b"payload";row=wire+b"s"*32
    slot=struct.pack("<II",2,len(row))+row
    prefix=b"RSIC"+"normal-workproducts".encode();full=prefix+storage.MAGIC+slot+storage.END
    parsed=storage.parse_footer(full)
    need(parsed["offset"]==len(prefix) and parsed["entries"]==[[2,len(row),(b"k"*32).hex(),(b"s"*32).hex()]],"different framed receipt")
    need(storage.parse_footer(prefix+storage.END) is None and storage.parse_footer(prefix+b"OHMSPL01"+slot+storage.END) is None,"old indexes changed")
    for wrong in (full[:-1],prefix+storage.MAGIC+slot[:-1]+storage.END,prefix+storage.MAGIC+slot+slot+storage.END,
                  prefix+storage.MAGIC+struct.pack("<II",2,0xffffffff)+row+storage.END): rejects(lambda:storage.parse_footer(wrong))
    uid="0"*25;nm="ruff_workspace-0123456789abcdef."+uid+".abcdefg.rcgu.o"
    src="/w/ohm-placement-yB3LD/object";dst="/w/"+nm
    need(tracking.classify(f'rename("{src}", "{dst}") = 0')==(Path(src),Path(dst)) and
         tracking.classify(f'rename("{src}", "{dst}") = -1 EEXIST (File exists)') is None,"wrong file publication")
    rejects(lambda:tracking.classify(f'rename("{src}", "/else/name.o") = 0'))
    actual={10:{"name":"ruff_workspace"}};need(tracking.identity(12,{12:11,11:10},actual,set())==actual[10] and
         tracking.identity(12,{12:11,11:10},actual,{11}) is None,"unverified rustc thread attribution")
    rejects(lambda:tracking.identity(12,{12:11,11:12},{},set()))
    with tempfile.TemporaryDirectory() as d:
        p=Path(d);(p/"lib.rmeta").write_bytes(b"rmeta");(p/nm).write_bytes(b"\x7fELF\x02\x01"+bytes(83))
        subprocess.run(["/usr/bin/ar","rcsD","owner.rlib","lib.rmeta",nm],cwd=p,check=True)
        arc=(p/"owner.rlib").read_bytes();need(durable.member_map(arc)["objects"]=={uid:hashlib.sha256((p/nm).read_bytes()).hexdigest()},"compressed/literal archive member")
        rejects(lambda:durable.member_map(arc[:-1]))
        for n in ("target","build","evidence","indices"): (p/n).mkdir()
        f=p/"target/work-products.bin";f.write_bytes(full);os.link(f,p/"build/same-hardlink");(p/"build/only-symlink").symlink_to(f)
        a=storage.census(p,p/"evidence",p/"indices");need(a["union_unique"]==4 and a["optional_entries"]==1 and a["optional_tail_bytes"]==len(storage.MAGIC)+len(slot),"hardlinks across target/build counted twice")
        (p/"evidence/storage.json").write_text(json.dumps(a));zip_path=p/"files.zip"
        with zipfile.ZipFile(zip_path,"w") as z:
            for f in (p/"evidence").iterdir():z.write(f,"subject/"+f.name)
            for f in (p/"indices").iterdir():z.write(f,"physical/workproduct-indices/"+f.name)
        with zipfile.ZipFile(zip_path) as z:need(readback.storage_read(z,"subject",{})["allocated"]==a["allocated"],"original block counts do not reopen")
        fake=json.loads(json.dumps(a));fake["allocated"]["allocated"]+=512
        with zipfile.ZipFile(p/"bad.zip","w") as out,zipfile.ZipFile(zip_path) as srcz:
            for name in srcz.namelist():out.writestr(name,json.dumps(fake) if name.endswith("storage.json") else srcz.read(name))
        with zipfile.ZipFile(p/"bad.zip") as z:rejects(lambda:readback.storage_read(z,"subject",{}))
        rss=p/"rss";subprocess.run(["/usr/bin/cc","-O2","-Wall","-Wextra","-Werror",HERE/"rss.c","-o",rss],check=True);placement_peak.calibrate(rss,p/"calibration")
    print("source, publication ancestry, GNU archive, v2 optional frames, current storage, hardlink, symlink, wrong allocation, syscall and RSS controls passed")


if __name__=="__main__":main()
