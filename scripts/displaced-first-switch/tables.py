"""Read both immutable checkout sessions and measure an uninstalled same-filesystem shadow."""
import collections
import contextlib
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import time
import shutil
import stat
import subprocess
import tempfile
import zlib

UNITS = collections.Counter("""ruff ruff ruff_db ruff_graph ruff_linter ruff_markdown ruff_python_ast
ruff_python_codegen ruff_python_edits ruff_python_formatter ruff_python_importer ruff_python_index
ruff_python_literal ruff_python_parser ruff_python_semantic ruff_ranged_value ruff_server
ruff_workspace ty_module_resolver ty_site_packages""".split())
SESSION = re.compile(r"s-[a-z0-9]+-_([0-9a-f]{16})_[a-z0-9]+-[a-z0-9]+")
KINDS = {"G": "dep-graph", "Q": "query-cache"}
MIN_SIZE, MAX_SIZE = 64 << 10, 512 << 20
STEP = 256 << 10

def need(ok, reason):
    if not ok:
        raise ValueError(str(reason))

def save(path, val):
    with path.open("x") as f:
        json.dump(val, f, sort_keys=True, indent=1)
        f.write("\n")

def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def load(folder):
    with gzip.open(folder / "path-inodes.json.gz", "rt") as f:
        return json.load(f)

def shape(s):
    return [s.st_dev, s.st_ino, s.st_nlink, s.st_mode, s.st_blocks, s.st_size]

def allocated(p):
    return p.lstat().st_blocks * 512

def label(unit):
    return Path(unit).name.rsplit("-", 1)[0]

def sessions(ledger):
    units = collections.defaultdict(list)
    for name, row in ledger.items():
        p = PurePosixPath(name)
        need(not p.is_absolute() and ".." not in p.parts and p.parts[0] in ("target","build") and str(p)==name, name)
        if stat.S_ISDIR(row[3]) and "incremental" in p.parts and SESSION.fullmatch(p.name) and label(str(p.parent)) in UNITS:
            units[str(p.parent)].append(name)
    need(collections.Counter(map(label, units)) == UNITS, "different twenty Ruff crate owners")
    return units

def names(ledger):
    grouped = collections.defaultdict(set)
    for key, row in ledger.items():
        grouped[tuple(row[:2])].add(key)
    return grouped

@contextlib.contextmanager
def regular(root, rel, expected):
    path = root / rel
    need(path.resolve()==path and stat.S_ISREG(expected[3]) and shape(path.lstat())==expected, ("not the actual ordinary file",rel))
    fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NOATIME)
    with os.fdopen(fd, "rb") as f:
        a=os.fstat(fd)
        need(shape(a)==expected, ("physical identity changed",rel))
        yield f
        b=os.fstat(fd)
        need(shape(b)==expected and (a.st_mtime_ns,a.st_ctime_ns)==(b.st_mtime_ns,b.st_ctime_ns) and shape(path.lstat())==expected, ("changed during read",rel))

def table(dir_,kind):
    name=KINDS[kind]+".bin"
    return str(Path(dir_)/name),[str(Path(dir_)/n) for n in (name,"ohm-build-"+name,"ohm-check-"+name)],str(Path(dir_)/("ohm-packed-"+name))

def physical_raw(root, ledger, aliases, directory, kind):
    key, allowed, packed=table(directory,kind);row=ledger[key]
    hits=aliases[tuple(row[:2])]
    need(hits==set(allowed[:2]) and row[2]==2 and packed not in ledger and MIN_SIZE<=row[5]<=MAX_SIZE, ("foreign alias, partial pair or unsupported size",key,hits))
    need(all(ledger[p]==row for p in hits),("inconsistent hardlinks",key))
    with regular(root,key,row) as f:
        need(f.read(4)==b"RSIC",("raw magic",key))
        f.seek(0); digest=hashlib.file_digest(f,"sha256").hexdigest()
    return dict(path=key,aliases=sorted(hits),mask=3,stat=row,sha256=digest,bytes=row[5],allocated=row[4]*512)

def cold(root, ledger):
    units=sessions(ledger); grouped=names(ledger);result={}
    for unit, dirs in sorted(units.items()):
        need(len(dirs)==1,("not genuinely cold",unit))
        d=dirs[0]
        result[unit]=dict(session=d,tables={k:physical_raw(root,ledger,grouped,d,k) for k in KINDS})
    need(sum(len(v["tables"]) for v in result.values())==40,"cold inventory")
    return result

def header(kind,prefix):
    return bytes((1,ord(kind),3)),prefix.encode()+b"\0"

def decode(f,kind,prefix,dest=None,expected=None):
    # Two independently bounded streams: this decoder and K's production native B outputs.
    start,producer=header(kind,prefix)
    max_head=11+len(producer)
    seen=bytearray(); total=0; digest=hashlib.sha256(); codec=zlib.decompressobj(); magic=b""; size=None
    def consume(buf):
        nonlocal total,size,magic
        if len(seen)<max_head:
            take=min(max_head-len(seen),len(buf));seen.extend(buf[:take]);buf=buf[take:]
            if len(seen)==max_head:
                size=int.from_bytes(seen[3:11],'little')
                need(seen[:3]==start and seen[11:]==producer and MIN_SIZE<=size<=MAX_SIZE, "wrong kind, mask, length or producer")
        if buf:
            need(size is not None and total+len(buf)<=size,"oversize decoded body")
            if len(magic)<4:magic+=buf[:4-len(magic)]
            total+=len(buf);digest.update(buf)
            if dest is not None:need(dest.write(buf)==len(buf),"short independent raw write")
    while block:=f.read(STEP):
        need(not codec.eof,"trailing compressed bytes")
        while block:
            output=codec.decompress(block,STEP)
            consume(output)
            need(not codec.unused_data,"trailing stream or bytes")
            block=codec.unconsumed_tail
    consume(codec.flush())
    need(codec.eof and not codec.unused_data and not codec.unconsumed_tail and size==total and magic==b"RSIC","incomplete stream")
    val=[total,digest.hexdigest()]
    need(expected is None or val==expected,("wrong decoded input", val,expected))
    return val

def encode(exe,fp,kind,prefix,out):
    fd=fp.fileno(); fp.seek(0)
    before=resource.getrusage(resource.RUSAGE_CHILDREN); start=time.monotonic_ns()
    p=subprocess.run([exe,str(fd),kind,"3",prefix,out],pass_fds=[fd],capture_output=True)
    after=resource.getrusage(resource.RUSAGE_CHILDREN); elapsed=time.monotonic_ns()-start
    need(p.returncode==0 and out.is_file(),("source encoder refused",p.returncode,p.stderr.decode(errors="replace")))
    return dict(bytes=out.stat().st_size,allocated=allocated(out),sha256=sha(out),stat=shape(out.lstat()),standalone_diagnostic=dict(elapsed_ns=elapsed,user_us=round((after.ru_utime-before.ru_utime)*1e6),system_us=round((after.ru_stime-before.ru_stime)*1e6)))

def syncdir(p):
    fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)

def allocated_tree(root):
    by_inode={}
    for p in (root,*root.rglob("*")):
        s=p.lstat();key=(s.st_dev,s.st_ino);n=s.st_blocks*512
        need(by_inode.setdefault(key,n)==n and not p.is_symlink(),("unexpected shadow object",p))
    return sum(by_inode.values())

def observe(root, initial, first, old, shadow, scratch, codec, progress=None):
    need(shadow.parent.resolve()==root and not shadow.exists() and scratch.parent.resolve()==root and not scratch.exists(),"shadow layout")
    shadow.mkdir();scratch.mkdir()
    dev=shadow.stat().st_dev
    need(dev==(root/"target").stat().st_dev==(root/"build").stat().st_dev==scratch.stat().st_dev,"different allocation devices")
    aliases=names(first); two=sessions(first); need(set(two)==set(old),"changed unit census")
    fixed={}; result={}; rates={}
    for unit,dirs in sorted(two.items()):
        a=old[unit]["session"];need(len(dirs)==2 and a in dirs,("lost original producer",unit))
        b,=set(dirs)-{a}
        need(SESSION.fullmatch(Path(a).name)[1]!=SESSION.fullmatch(Path(b).name)[1],"same checkout label")
        fixed[unit]=(a,b)
        for kind in KINDS:
            rem=physical_raw(root,first,aliases,a,kind)
            need(rem==old[unit]["tables"][kind],("cold-A changed by B",unit,kind))
            need(initial[rem["path"]]==first[rem["path"]],("initial table ownership discontinuity",unit))
    # Establish the codec on every real first-B *before* encoding or inspecting a single old A.
    for unit,(_,b) in fixed.items():
        prefix=Path(b).name.rsplit("-",1)[0]
        for kind in KINDS:
            _,raw_aliases,rel=table(b,kind);need(rel in first and not any(x in first for x in raw_aliases),"hybrid current table")
            row=first[rel];need(0<row[5]<=MAX_SIZE and row[2]==1 and aliases[tuple(row[:2])]=={rel},"unexpected B packed alias")
            with regular(root,rel,row) as f, tempfile.TemporaryDirectory(dir=scratch) as tmp:
                raw=Path(tmp)/"independent.raw";compressed=Path(tmp)/"rerun.zlib"
                with raw.open("xb") as target: decoded=decode(f,kind,prefix,target);target.flush();os.fsync(target.fileno())
                with raw.open("rb") as input_: reencoded=encode(codec,input_,kind,prefix,compressed)
                f.seek(0);original_sha=hashlib.file_digest(f,"sha256").hexdigest()
                f.seek(0)
                with compressed.open("rb") as copy:
                    while block:=f.read(STEP):need(copy.read(len(block))==block,"native B re-encode differs")
                    need(not copy.read(1),"trailing re-encoded bytes")
                need(reencoded['sha256']==original_sha and reencoded['bytes']==row[5],"B codec mismatch")
                rates[unit,kind]=dict(path=rel,decoded=decoded,actual_sha256=original_sha,bytes=row[5],allocated=row[4]*512,reencoded=reencoded)
    need(not any(scratch.iterdir()),"B re-encode work bytes would pollute coexistence")
    for ix,(unit,(a,b)) in enumerate(fixed.items(),1):
        prefix=Path(a).name.rsplit("-",1)[0];d=shadow/Path(unit).name;d.mkdir()
        records={}
        for kind in KINDS:
            prior=old[unit]['tables'][kind];out=d/("ohm-packed-"+KINDS[kind]+".bin")
            with regular(root,prior['path'],prior['stat']) as f:
                pack=encode(codec,f,kind,prefix,out)
                with out.open("rb") as encoded: decode(encoded,kind,prefix,expected=[prior['bytes'],prior['sha256']])
                # Independent content digest plus byte-by-byte comparison against the source of this slot.
                class Compare:
                    def write(self,v):
                        need(f.read(len(v))==v,"A raw byte comparison failed");return len(v)
                f.seek(0)
                with out.open("rb") as encoded: decode(encoded,kind,prefix,Compare(),[prior['bytes'],prior['sha256']])
                need(not f.read(1),"trailing A raw bytes")
            records[kind]=dict(raw=prior,packed=pack,shadow=str(out.relative_to(shadow)),native_B=rates[unit,kind])
        syncdir(d);syncdir(shadow)
        result[unit]=dict(A=a,B=b,streams=records,observed_staged_bytes=allocated_tree(shadow))
        if progress:progress(ix,unit,result[unit])
    return result
