"""Read the temporary bootstrap policy and opt-dist's real pre-BOLT backup during the unchanged build."""
import gzip
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
import gate as g
import suppliers
import phase_config

def digest(b): return hashlib.sha256(b).hexdigest()
def wrapper_bytes(path,w,out):
    real=path.resolve(strict=True)
    assert real.is_relative_to(w/"source/rust/build")
    with real.open("rb") as f:
        before=os.fstat(f.fileno());assert stat.S_ISREG(before.st_mode) and 0<before.st_size<8<<20
        data=f.read()
        after=os.fstat(f.fileno())
    assert all(getattr(before,k)==getattr(after,k) for k in ("st_dev","st_ino","st_size","st_mtime_ns","st_ctime_ns")) and len(data)==before.st_size
    key=digest(data);name=f"actual-gnu-wrapper-{key}.gz";dest=out/name
    if not dest.exists():dest.write_bytes(gzip.compress(data,compresslevel=4,mtime=0))
    return {"path":str(path),"resolved":str(real),"bytes":len(data),"sha256":key,"raw":name}
def stash(path, out, key):
    data=path.read_bytes()
    assert len(data)<32<<20 and not path.is_symlink()
    label=f"{key}-{digest(data)}.gz";dest=out/label
    if not dest.exists(): dest.write_bytes(gzip.compress(data,compresslevel=4,mtime=0))
    return {"path":str(path),"bytes":len(data),"sha256":digest(data),"raw":label}

def argv_bytes(raw,out):
    assert raw.endswith(b"\x00") and 0<len(raw)<16<<20
    key=digest(raw);file=out/("driver-argv-"+key+".gz")
    if not file.exists():file.write_bytes(gzip.compress(raw,compresslevel=4,mtime=0))
    return {"bytes":len(raw),"sha256":key,"raw":file.name}

def cargo_message_stream(rustc_pid,scope,out):
    """Identify the actual consuming bootstrap pipe and Cargo which wrote the artifact records."""
    chain=[];cargo=None;pipe=None;pid=rustc_pid;compiler=None
    for _ in range(18):
        proc=Path("/proc")/str(pid);exe=(proc/"exe").resolve(strict=True)
        chain.append({"pid":pid,"exe":str(exe)})
        if pid==rustc_pid:compiler=stash(exe,out,"phase-rustc-launcher")
        if cargo is None and exe.name=="cargo":
            native={os.fsdecode(k):os.fsdecode(v) for item in (proc/"environ").read_bytes().split(b"\0") if b"=" in item for k,v in [item.split(b"=",1)]}
            assert native.get("OHM_RUSTC_DRIVER_LINK_DIR")==str(scope),("Cargo scope",pid,native.get("OHM_RUSTC_DRIVER_LINK_DIR"),str(scope))
            argv=(proc/"cmdline").read_bytes();args=[os.fsdecode(v) for v in argv.split(b"\0") if v]
            assert any(a.startswith(("--message-format=json","json-render-diagnostics")) for a in args),("Cargo JSON mode",args)
            pipe=os.readlink(proc/"fd/1");assert re.fullmatch(r"pipe:\[\d+\]",pipe),("Cargo stdout",pipe)
            cargo={"pid":pid,"exe":str(exe),"exe_sha256":g.sha(exe),"cwd":str((proc/"cwd").resolve(strict=True)),
                   "argv":argv_bytes(argv,out),"stdout":pipe,"env":{k:native.get(k) for k in ("OHM_RUSTC_DRIVER_LINK_DIR","RUSTC_REAL","RUSTC_WRAPPER","RUSTC_STAGE","RUSTC_SYSROOT")}}
        elif cargo is not None:
            for fd in (proc/"fd").iterdir():
                try:
                    if os.readlink(fd)!=pipe:continue
                    info=(proc/"fdinfo"/fd.name).read_text()
                except FileNotFoundError:continue
                flags=int(re.search(r"(?m)^flags:\s+([0-7]+)$",info)[1],8)
                if flags & os.O_ACCMODE == os.O_RDONLY:
                    return {"rustc_pid":rustc_pid,"rustc_launcher":compiler,"chain":chain,"cargo":cargo,"json_reader":{"pid":pid,"exe":str(exe),"exe_sha256":g.sha(exe),"fd":int(fd.name),"pipe":pipe}}
        pid=int(re.search(r"(?m)^PPid:\s+(\d+)$",(proc/"status").read_text())[1])
        if pid<=1:break
    raise AssertionError(("Cargo JSON stdout reader missing",rustc_pid,chain))

def outer_cc(entry,out):
    chain=[int(entry.name)]
    for _ in range(12):
        table=(Path("/proc")/str(chain[-1])/"status").read_text()
        parent=int(re.search(r"(?m)^PPid:\s+(\d+)$",table)[1])
        if parent<=1:break
        chain.append(parent);p=Path("/proc")/str(parent);exe=(p/"exe").resolve(strict=True)
        if not re.fullmatch(r"(?:[\w.+-]+-)?(?:gcc|g\+\+|clang\+\+|clang|cc)(?:-[0-9.]+)?",exe.name):continue
        raw=(p/"cmdline").read_bytes();cwd=(p/"cwd").resolve(strict=True)
        argv=[os.fsdecode(a) for a in raw.split(b"\0") if a]
        responses=[stash(cwd/a[1:],out,"cc-response") for a in argv if a.startswith("@")]
        ld_responses=[stash(cwd/a[5:],out,"cc-ld-response") for a in argv if a.startswith("-Wl,@")]
        return {"chain_lld_to_cc":chain,"pid":parent,"exe":str(exe),"exe_sha256":g.sha(exe),"cwd":str(cwd),"argv":argv_bytes(raw,out),"responses":responses,"linker_responses":ld_responses}
    return None

def policy(w,out,seen,executor=None,pending=None):
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
                row={"owners":o,"exceptions":rec}
                if executor is not None:
                    row["driver"]=stash(p/"driver",out,"driver-manifest-dir")
                    row["cargo_message_stream"]=cargo_message_stream(int(lst.stem),p,out)
                    # Hold read-only descriptors through hashing, without delaying the linker observer.
                    pending[str(lst)]=executor.submit(suppliers.finish,suppliers.opened(w,p),out)
                seen[str(lst)]=row
        except FileNotFoundError:
            continue

def opened_operands(argv,cwd):
    opened=[]
    try:
        for index,arg in enumerate(argv):
            if not arg.endswith((".o",".rlib")):continue
            path=(cwd/arg).resolve(strict=True);f=path.open("rb");opened.append((index,arg,str(path),f))
        assert opened
        return opened
    except BaseException:
        for *_,f in opened:f.close()
        raise

def hash_operands(opened,out):
    rows=[]
    try:
        for index,arg,path,f in opened:
            st=os.fstat(f.fileno());assert stat.S_ISREG(st.st_mode) and st.st_size>0
            header=f.read(20);f.seek(0);digest=hashlib.file_digest(f,"sha256").hexdigest()
            after=os.fstat(f.fileno())
            assert all(getattr(st,k)==getattr(after,k) for k in ("st_dev","st_ino","st_size","st_mtime_ns"))
            rows.append(dict(index=index,arg=arg,path=path,dev=st.st_dev,ino=st.st_ino,bytes=st.st_size,mtime_ns=st.st_mtime_ns,header=header.hex(),sha256=digest))
    finally:
        for *_,f in opened:f.close()
    return suppliers.keep(json.dumps(rows,sort_keys=True,separators=(",",":")).encode(),"final-native-operands",out)

def lld(w,out,seen,executor=None,pending=None):
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
            if exe.name!="rust-lld":continue
            cc=outer_cc(entry,out)
            if cc is None:continue
            scripts=[stash(cwd/s.partition("=")[2],out,"linker-script") for s in options if "="in s]
            cmd=argv_bytes(raw,out)
            wrapper=wrapper_bytes(exe.parent/"gcc-ld/ld.lld",w,out)
            rlibs=[]
            for a in args:
                if not a.endswith(".rlib"):continue
                p=(cwd/a).resolve(strict=True);st=p.stat();assert stat.S_ISREG(st.st_mode)
                rlibs.append({"path":str(p),"dev":st.st_dev,"ino":st.st_ino,"bytes":st.st_size,"mtime_ns":st.st_mtime_ns})
            record={"pid":int(entry.name),"exe":str(exe),"exe_sha256":g.sha(exe),"output":str(output),"options":options,"argv_sha256":digest(raw),"scripts":scripts,
                "argv":cmd,"outer_cc":cc,"gnu_wrapper":wrapper,"actual_rlibs":rlibs}
            if "-Bsymbolic-non-weak-functions" in options:
                opened=opened_operands(args,cwd)
                if executor is None:record["native_operands"]=hash_operands(opened,out)
                else:pending[entry.name]=executor.submit(hash_operands,opened,out)
            seen[entry.name]=record
        except (FileNotFoundError,ProcessLookupError,PermissionError):
            continue

def monitor_links(w,out,links,executor,operands,errors,stop):
    # Do not compete with source-archive hashing for the short live exec window.
    # Only the already selected final compiler needs the faster polling interval.
    while not stop.is_set():
        try:lld(w,out,links,executor,operands)
        except (OSError,AssertionError,ValueError) as err:errors.setdefault("linker capture",repr(err))
        active=any((out/"pre-lto").glob("visit-*/request.json"))
        stop.wait(.004 if active else .18)

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
    seen={};links={};original=None;pending={};operands={};errors={}
    observer_dir=out/"pre-lto";config=phase_config.enter(w,observer_dir)
    executor=concurrent.futures.ThreadPoolExecutor(max_workers=1)
    proc=subprocess.Popen(["/bin/bash","--noprofile","--norc","-e","-o","pipefail",sys.argv[1]])
    stop=threading.Event()
    thread=threading.Thread(target=monitor_links,args=(w,out,links,executor,operands,errors,stop),daemon=True);thread.start()
    try:
        while True:
            try:policy(w,out,seen,executor,pending)
            except (OSError,AssertionError,ValueError) as err:errors.setdefault("supplier capture",repr(err))
            if not original:
                if log.exists():
                    with log.open("rb") as f:
                        f.seek(offset);chunk=f.read();offset=f.tell()
                    parts=(tail+chunk).split(b"\n");tail=parts.pop()
                    lines.extend(x.decode(errors="replace") for x in parts)
                    if len(lines)>64:lines=lines[-64:]
                    if "pre-BOLT" not in errors:
                        try:original=backup(lines,w,private)
                        except (OSError,AssertionError,ValueError) as err:errors["pre-BOLT"]=repr(err)
                    if original:stop.set()
            if proc.poll() is not None:break
            time.sleep(.18 if not original else .5)
    finally:
        if proc.poll() is None:proc.terminate();proc.wait()
        stop.set();thread.join()
        for key,future in pending.items():
            try:
                content=json.dumps(future.result(),sort_keys=True,separators=(",",":")).encode()
                seen[key]["supplier_evidence"]=suppliers.keep(content,"in-tree-cargo-artifacts",out)
            except (OSError,AssertionError,ValueError) as err:errors.setdefault("supplier identification",repr(err))
        for pid,future in operands.items():
            try:links[pid]["native_operands"]=future.result()
            except (OSError,AssertionError,ValueError) as err:errors.setdefault("native operand identification",repr(err))
        executor.shutdown()
        phase_config.leave(config,observer_dir)
        g.save(out/"capture.json",{"arm":arm,"exit":proc.returncode,"pre_bolt":original,"policies":seen,"links":links,"observer_errors":errors})
    if proc.returncode:sys.exit(proc.returncode)
    # The native admission reopens every observation independently after the
    # finished distribution and its installed checks have been preserved.
if __name__=="__main__":main()
