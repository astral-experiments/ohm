"""Retain actual GNU linker/loader probes with their fork ancestry (including Wild worker threads)."""
from decimal import Decimal
from pathlib import Path
import gzip, hashlib, os, re

def identity(p):
    s=p.stat()
    with p.open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
    return dict(path=str(p),real=str(p.resolve()),dev=s.st_dev,ino=s.st_ino,ctime_ns=s.st_ctime_ns,size=s.st_size,sha256=h)
def trace(directory):
    records=[]
    for f in sorted(directory.iterdir()):
        pid=int(f.name.split('.')[-1])
        for n,line in enumerate(f.read_bytes().splitlines()):
            parts=line.split(b' ',1)
            if len(parts)!=2:continue
            stamp,body=parts
            if body.startswith((b'execve(',b'execveat(',b'clone(',b'clone3(',b'fork(',b'vfork(')) or b'libutil.so' in body or b'libutil.a' in body:
                records.append((Decimal(stamp.decode()),pid,n,body))
        f.unlink()
    directory.rmdir()
    lines=[];exes=[];probes=[]
    for stamp,pid,_,body in sorted(records):
        lines.append(('%s %d '%(stamp,pid)).encode()+body)
        m=re.match(rb'execve\("([^"]+)",',body)
        if m and body.endswith(b'= 0'):exes.append((pid,os.fsdecode(m[1]),body.decode(errors='replace')))
        elif b'libutil.so' in body or b'libutil.a' in body:probes.append((pid,None,body.decode(errors='replace')))
    return b'\n'.join(lines)+b'\n',exes,probes
def search(raw,side,wild):
    parents={};executions={};all_probes=[];argv={}
    for row in raw.decode(errors='strict').splitlines():
        stamp,pid_s,body=row.split(' ',2);stamp=Decimal(stamp);pid=int(pid_s)
        m=re.match(r'(?:clone3?|v?fork)\(.*\)\s+=\s+([1-9][0-9]*)(?:\s.*)?$',body)
        if m:
            child=int(m[1]);assert child not in parents;parents[child]=pid
        m=re.match(r'execve\("([^"]+)",',body)
        if m and body.endswith('= 0'):
            executions.setdefault(pid,[]).append((stamp,m[1]));argv.setdefault(pid,[]).append((m[1],body))
        elif re.match(r'(?:openat2?|statx|newfstatat|access|faccessat2?)\(',body) and (side in body or 'libutil.a"' in body):
            all_probes.append((stamp,pid,body))
    def resolve(pid,stamp):
        seen=set()
        while pid not in seen:
            seen.add(pid);earlier=[p for t,p in executions.get(pid,[]) if t<=stamp]
            if earlier:return earlier[-1]
            if pid not in parents:return None
            pid=parents[pid]
        raise AssertionError('cyclic native process ancestry')
    probes=[];dir=str(Path(wild).parent)
    for t,p,s in all_probes:
        owner=resolve(p,t)
        if side in s: which='higher'
        elif '/libutil.a"' in s:which='fallback'
        else:continue
        ret=re.search(r'\)\s+=\s+(-?\d+)',s)
        if not ret:continue
        probes.append(dict(pid=p,exe=owner,kind=which,call=s.split('(',1)[0],result=int(ret[1]),enoent='ENOENT' in s))
    driver=[];real_ld=[]
    for p,steps in argv.items():
        for exe,s in steps:
            name=Path(exe).name
            if name=='collect2' or name in ('cc','gcc','clang') or exe==wild or name in ('ld.bfd','rust-lld','ld.lld','ld.gold','ld.mold','ld','wild'):
                if 'build_script_build' in s or 'build-script-build' in s:
                    driver.append(dict(pid=p,exe=exe,wild_B='-B'+dir in s,wild_L='-L'+dir in s or ('"-L", "'+dir+'"') in s,wild_path=dir in s))
                if name in ('ld.bfd','rust-lld','ld.lld','ld.gold','ld.mold','ld','wild'):real_ld.append(exe)
    return dict(probes=probes,build_script_drivers=driver,physical_ld=real_ld,private_expected_wild=wild)
def chacha_files(root,receipt):
    found=[]
    for tree in (root/'target',root/'shared'):
        for p in tree.rglob('*.d') if tree.is_dir() else ():
            if 'chacha20' not in str(p.relative_to(tree)):continue
            b=p.read_bytes()
            if b'/chacha20-' not in b:continue
            h=hashlib.sha256(b).hexdigest();out=receipt/(h+'.d.gz')
            if not out.exists():out.write_bytes(gzip.compress(b,mtime=0))
            found.append({'path':str(p),'sha256':h,'v1':b'/dev/null/ohm-recheck-dependent-links' in b,'v2':b'/dev/null/ohm-recheck-dependent-links-v2' in b})
    return found
