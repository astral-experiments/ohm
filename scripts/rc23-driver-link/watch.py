"""Read the temporary bootstrap policy and opt-dist's real pre-BOLT backup during the unchanged build."""
import gzip
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
import gate as g

def digest(b): return hashlib.sha256(b).hexdigest()
def stash(path, out, key):
    data=path.read_bytes()
    assert len(data)<32<<20 and not path.is_symlink()
    label=f"{key}-{digest(data)}.gz";dest=out/label
    if not dest.exists(): dest.write_bytes(gzip.compress(data,compresslevel=4,mtime=0))
    return {"path":str(path),"bytes":len(data),"sha256":digest(data),"raw":label}

def policy(w,out,seen):
    tmp=w/"source/rust/build/tmp"
    for owners in tmp.glob("rustc-driver-link-*/owners"):
        try:
            p=owners.parent
            for lst in p.glob("*.exports"):
                if str(lst) in seen or not lst.stem.isdecimal(): continue
                data=lst.read_bytes()
                if not data.startswith(b"{\n") or not data.endswith(b"};\n"): continue
                o=stash(owners,out,"owners");rec=stash(lst,out,"exceptions")
                if rec["sha256"]!=digest(data): continue
                seen[str(lst)]={"owners":o,"exceptions":rec}
        except FileNotFoundError:
            continue

def lld(w,out,seen):
    # A genuine linker response file may carry the command. This is supplemental
    # provenance; the closed linker scripts and applied ELF are mandatory.
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal() or entry.name in seen: continue
        try:
            if (entry/"comm").read_text().strip() not in {"ld.lld","lld","rust-lld","ld"}: continue
            raw=(entry/"cmdline").read_bytes();args=[os.fsdecode(x) for x in raw.split(b"\0") if x]
            cwd=(entry/"cwd").resolve(strict=True)
            if "-o" not in args or args.index("-o")+1>=len(args):continue
            output=(cwd/args[args.index("-o")+1]).resolve()
            if not output.is_relative_to(w/"source/rust/build") or not re.fullmatch(r"librustc_driver(-[a-f0-9]+)?\.so",output.name): continue
            options=[s for s in args if s.startswith(("--version-script=","--export-dynamic-symbol-list=","-Bsymbolic"))]
            if not any(s.startswith("--version-script=") for s in options):continue
            exe=(entry/"exe").resolve(strict=True)
            scripts=[stash(cwd/s.partition("=")[2],out,"linker-script") for s in options if "="in s]
            seen[entry.name]={"pid":int(entry.name),"exe":str(exe),"exe_sha256":g.sha(exe),"output":str(output),"options":options,"argv_sha256":digest(raw),"scripts":scripts}
        except (FileNotFoundError,ProcessLookupError,PermissionError):
            continue

def backup(lines,w,private):
    """The true opt-dist log prints backup creation followed by the real -instrument exec."""
    prefix=str(w/"source/rust/build/x86_64-unknown-linux-gnu/stage2/lib")+"/"
    event=re.compile(r"Copying file ("+re.escape(prefix)+r"librustc_driver-[a-f0-9]+\.so) to (/tmp/\.tmp[0-9A-Za-z]+)$")
    for i,line in enumerate(lines[:-1]):
        m=event.search(line)
        if not m: continue
        live,src=map(Path,m.groups())
        next_line=lines[i+1]
        if not ("llvm-bolt -instrument "+str(live)+" ") in next_line: continue
        dest=private/"pre-bolt.so"
        with src.open("rb") as a,dest.open("xb") as b:
            st=os.fstat(a.fileno())
            assert stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid() and 50<<20<st.st_size<700<<20
            shutil.copyfileobj(a,b,1<<20)
            after=os.fstat(a.fileno())
            assert all(getattr(after,k)==getattr(st,k) for k in ("st_dev","st_ino","st_size","st_mtime_ns","st_ctime_ns")) and dest.stat().st_size==st.st_size
        return {"copy_line":line,"instrument_line":next_line,"source":str(src),"live":str(live),"backup_inode":st.st_ino,"bytes":st.st_size,"sha256":g.sha(dest)}
    return None

def main():
    w=Path(os.environ["GITHUB_WORKSPACE"]).resolve();arm=os.environ["BENCH_ARM"]
    out=w/"trait-evidence/driver-witness";out.mkdir()
    private=w/"driver-audit-private";private.mkdir()
    log=w/"trait-evidence/build.log";lines=[];offset=0;tail=b""
    seen={};links={};original=None
    proc=subprocess.Popen(["/bin/bash","--noprofile","--norc","-e","-o","pipefail",sys.argv[1]])
    try:
        while True:
            policy(w,out,seen)
            if not original:
                lld(w,out,links)
                if log.exists():
                    with log.open("rb") as f:
                        f.seek(offset);chunk=f.read();offset=f.tell()
                    parts=(tail+chunk).split(b"\n");tail=parts.pop()
                    lines.extend(x.decode(errors="replace") for x in parts)
                    if len(lines)>64:lines=lines[-64:]
                    original=backup(lines,w,private)
            if proc.poll() is not None:break
            time.sleep(.18 if not original else .5)
    finally:
        if proc.poll() is None:proc.terminate();proc.wait()
        g.save(out/"capture.json",{"arm":arm,"exit":proc.returncode,"pre_bolt":original,"policies":seen,"links":links})
    if proc.returncode:sys.exit(proc.returncode)
    assert original and (bool(seen)==(arm=="T")),(arm,original,len(seen))
if __name__=="__main__":main()
