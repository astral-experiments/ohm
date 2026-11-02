"""Archive primitives copied verbatim from the original qualified production SDK consumer a08fbd2d."""
import shutil,tarfile
from pathlib import Path,PurePosixPath
from zipfile import ZipFile
import core as c
m=c.m
TARGET="x86_64-unknown-linux-gnu"
REQUIRED={"ohm.tar.gz","SHA256SUMS","source.json","role.json","sdk-inventory.json","component-inventory.json"}
def unpack(source,dest,kind):
    dest.mkdir()
    with ZipFile(source) as z:
        files=[i for i in z.infolist() if not i.is_dir()];names=[i.filename for i in files]
        m.guard(len(names)==len(set(names)) and len(names)<=100 and sum(i.file_size for i in files)<800<<20,"bad total ZIP inventory")
        if kind=="sdk":m.guard(set(names)==REQUIRED,"SDK ZIP members")
        for i in files:
            parts=PurePosixPath(i.filename)
            m.guard(not parts.is_absolute() and ".." not in parts.parts and parts.as_posix()==i.filename and "\\" not in i.filename and
                    (i.external_attr>>16)&0o170000 in (0,0o100000) and not (i.flag_bits&1) and
                    (i.file_size<=700<<20 if i.filename=="ohm.tar.gz" else i.file_size<=100<<20),"unsafe or oversized artifact member")
            p=dest/parts;p.parent.mkdir(parents=True,exist_ok=True)
            with z.open(i) as a,p.open("xb") as b:shutil.copyfileobj(a,b,1<<20)
            m.guard(p.stat().st_size==i.file_size,"truncated member")

def runtime_files(role,installed,inventory,rv):
    runtime={rv[k]["path"]:rv[k]["sha256"] for k in ("launcher","driver","llvm")}
    inventory=m.read(inventory)
    for key in ("launcher","driver","llvm","bundled_cargo"):
        rel=rv[key]["path"];row=inventory[rel];m.guard(rel==PurePosixPath(rel).as_posix() and ".." not in Path(rel).parts and
            row["sha256"]==rv[key]["sha256"] and m.filesha(installed/rel)==row["sha256"],("component binding",role,key))
    m.guard(rv["launcher"]["path"]=="bin/rustc" and rv["bundled_cargo"]["path"]=="bin/cargo" and rv["bolt_note"] is True and
            rv["source_commit"]==m.P["roles"][role]["commit"] and rv["source_tree"]==m.P["roles"][role]["tree"] and
            rv["epoch"]==m.P["roles"][role]["epoch"] and rv["effective_benchmark_cargo_sha256"]==m.P["signed_cargo_sha256"],"compiler role mismatch")
    return runtime

def official_cargo(archive,out):
    name="rust-1.99.0-dev-"+TARGET+"/cargo/bin/cargo";path=out/"signed-cargo"
    with tarfile.open(archive,"r|gz") as t:
        for item in t:
            if item.name!=name:continue
            m.guard(item.isfile() and 0<item.size<100<<20 and item.mode&0o111 and not path.exists(),"expected one regular signed native Cargo")
            with t.extractfile(item) as a,path.open("xb") as b:shutil.copyfileobj(a,b,1<<20)
            m.guard(path.stat().st_size==item.size,"truncated Cargo")
    m.guard(m.filesha(path)==m.P["signed_cargo_sha256"],"signed Cargo checksum");path.chmod(0o755);return path
