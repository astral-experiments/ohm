"""Stage the original kit once on a native filesystem for real, same-inode receiver mutations."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))

def save(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n')

def witness(src,dst,expected=None):
    os.link(src,dst)
    try:
        def identity(p):
            s=p.stat();return [s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns]
        a,b=identity(src),identity(dst);assert a==b and dst.samefile(src)
        with dst.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        if expected is not None:assert digest==expected
        return {'donor':a,'alias':b,'sha256':digest}
    finally:dst.unlink()

def probe(v,out):
    fs=subprocess.check_output(['findmnt','-T',v,'--noheadings','-o','FSTYPE'],text=True).strip()
    assert fs in ('ext4','tmpfs'),fs
    free=shutil.disk_usage(v).free;assert free>3*1024**3,free
    with tempfile.TemporaryDirectory(dir=v) as t:
        d=Path(t);f=d/'program';shutil.copy2('/bin/true',f);subprocess.run([f],check=True)
        assert f.stat().st_dev==d.stat().st_dev
        row=witness(f,d/'alias')
    tools={}
    for name in ('cc','ld','ar','musl-gcc','strace','b3sum'):
        tool=Path(shutil.which(name)).resolve(strict=True)
        with tool.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        tools[name]=[str(tool),digest,subprocess.check_output([tool,'--version'],stderr=subprocess.STDOUT,text=True).splitlines()[0]]
    packages=subprocess.check_output(['dpkg-query','-W','binutils','gcc','musl','musl-dev','musl-tools','strace','b3sum'],text=True)
    save(out,{'filesystem':fs,'free':free,'exec':True,'same_regular_hardlink':True,'sample':row,'tools':tools,'packages':packages,
              'mount':subprocess.check_output(['findmnt','-T',v,'--noheadings','-o','TARGET,SOURCE,FSTYPE,OPTIONS'],text=True).strip()})

def stage(evidence):
    import composite,restore
    source=composite.PIN
    t=source['records']['source-transfer']
    guard=restore.restore('P',source['run'],source['head'],t['artifact'],t['sha256'],source['identity'],for_provider=True)
    d=Path(os.environ['RUNNER_TEMP']);root=d/'native-guard';root.mkdir()
    actors=guard['drivers']|guard['cargos'];sdk=Path(guard['sdk'])
    for name in ('rustc','rustdoc'):
        actors[name]={'path':sdk/'bin'/name,'sha256':restore.q.PREVIOUS['files']['bin/'+name][0]}
    assert set(actors)=={'P','C','signed','strict','aware','rustc','rustdoc'}
    aliases={}
    with tempfile.TemporaryDirectory(dir=root) as t0:
        d0=Path(t0)
        for name,s in actors.items():
            f=Path(s['path']);assert f.stat().st_dev==d0.stat().st_dev
            aliases[name]=witness(f,d0/name,s['sha256'])
    save(evidence/'regular-aliases.json',aliases)
    save(evidence/'source-proof.json',{'SOURCE_RUN':str(source['run']),'SOURCE_HEAD':source['head'],'TRANSFER_ID':str(t['artifact']),'TRANSFER_DIGEST':t['sha256'],'TRANSFER_SEAL':source['identity']})
    shutil.copy2(restore.s.LOG/'sdk.json',evidence/'source-sdk.json')
    shutil.copy2(restore.s.LOG/'guard-subjects.json',evidence/'guard-subjects.json')

if __name__=='__main__':
    if sys.argv[1]=='probe':probe(*map(Path,sys.argv[2:]))
    elif sys.argv[1]=='stage':stage(Path(sys.argv[2]))
    else:raise ValueError(sys.argv)
