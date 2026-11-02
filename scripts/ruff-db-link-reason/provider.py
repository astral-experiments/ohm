"""Try real same-stat native library changes against an unchanged, previously linked test."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from diagnose import COMMAND, NEW, RECORDS, ROOT, SDK, SRC, STATE, git, native, sha, test_artifact
from install import HOST, WILD, save

C_SOURCE = r'''
#define _GNU_SOURCE
#include <stdlib.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

pid_t getpid(void) { return (pid_t)syscall(SYS_getpid); }
gid_t getgid(void) { return (gid_t)syscall(SYS_getgid); }
uid_t getuid(void) { return (uid_t)syscall(SYS_getuid); }
uid_t geteuid(void) { return (uid_t)syscall(SYS_geteuid); }

__attribute__((constructor)) static void identify_provider(void) {
    if (getenv("OHM_RUFF_NATIVE_WITNESS"))
        (void)write(2, "OHM_RUFF_NATIVE_" ROLE "\n", sizeof("OHM_RUFF_NATIVE_" ROLE "\n") - 1);
}
'''

def identity(p):
    st=p.stat()
    return dict(dev=st.st_dev,ino=st.st_ino,size=st.st_size,mtime=st.st_mtime_ns,ctime=st.st_ctime_ns,sha256=sha(p))

def compile_libraries(loader):
    loader.mkdir()
    source=ROOT/'native-witness.c'; source.write_text(C_SOURCE)
    result={}
    for letter in 'AB':
        path=loader/('libohm-ruff-db-'+letter+'.so')
        subprocess.run(['cc','-O2','-fPIC','-shared','-Wl,--build-id=none','-Wl,-soname,'+path.name,
                        '-DROLE="'+letter+'"',source,'-o',path],check=True)
        assert path.name.encode() in subprocess.check_output(['readelf','-dW',path])
        result[letter]=path.read_bytes()
    assert len(result['A'])==len(result['B']) and result['A']!=result['B']
    return result

def test_binary(path,env,letter):
    dyn=subprocess.check_output(['readelf','-dW',path])
    needed=[l for l in dyn.splitlines() if b'(NEEDED)' in l and b'libohm-ruff-db-' in l]
    expected=('libohm-ruff-db-'+letter+'.so').encode() if letter else None
    if letter:
        assert len(needed)==1 and expected in needed[0],(letter,needed)
    else:
        assert not needed
    p=subprocess.run([path,'--list','--format','terse'],cwd=SRC,env=dict(env,OHM_RUFF_NATIVE_WITNESS='1'),capture_output=True,check=True)
    marker=('OHM_RUFF_NATIVE_'+letter+'\n').encode() if letter else b''
    assert p.stderr==marker and sum(l.endswith(b': test') for l in p.stdout.splitlines())==126
    return dict(dynamic=dyn.decode(),stderr=p.stderr.decode(),list_sha256=hashlib.sha256(p.stdout).hexdigest())

def main():
    assert git('rev-parse','HEAD')==NEW and not git('status','--porcelain')
    assert json.loads((RECORDS/'accepted.json').read_text())['role']=='23'
    wild=SDK/'lib/rustlib'/HOST/'bin/wild-ld/ld.bfd'
    assert sha(wild)==WILD
    provider=wild.with_name('libutil.so')
    assert not provider.is_symlink() and not provider.exists()
    env=json.loads((RECORDS/'environment.json').read_text())
    env.update(CARGO_NET_OFFLINE='true',LD_LIBRARY_PATH=str(ROOT/'native-loader'))
    ordinary=json.loads((RECORDS/'visits.json').read_text())['clean']
    libs=compile_libraries(ROOT/'native-loader')
    proof=RECORDS/'provider';proof.mkdir()
    reference={}; rows={}
    def observe(label, letter, want_valid=True):
        folder=proof/label;folder.mkdir()
        with (folder/'stdout.gz').open('xb') as out,(folder/'stderr.gz').open('xb') as err:
            p=subprocess.run(COMMAND,cwd=SRC,env=env,capture_output=True,timeout=720)
            out.write(gzip.compress(p.stdout));err.write(gzip.compress(p.stderr))
        result=dict(code=p.returncode,provider=identity(provider) if provider.exists() else None)
        if not want_valid:
            diagnostics=p.stdout+b'\n'+p.stderr
            assert p.returncode==101 and str(provider).encode() in diagnostics,diagnostics[-4000:]
            assert any(t in diagnostics.lower() for t in (b'wild',b'unknown input',b'unsupported',b'invalid'))
        else:
            if p.returncode:raise RuntimeError((label,p.returncode,p.stderr[-3000:]))
            exe,roster,dirty=test_artifact([json.loads(l) for l in p.stdout.splitlines()])
            assert roster==ordinary['roster']
            assert native(exe,folder,env)==ordinary['tests']
            if not letter:
                assert sha(exe)==ordinary['sha256']
            result.update(native=test_binary(exe,env,letter),binary=identity(exe),dirty=dirty,units=len(roster))
            if letter not in reference:
                target=proof/('test-'+(letter or 'absent')+'.elf.gz')
                with exe.open('rb') as src, gzip.open(target,'xb',compresslevel=2) as dst:shutil.copyfileobj(src,dst)
                reference[letter]=(result['binary']['sha256'],result['native']['list_sha256'])
            assert reference[letter]==(result['binary']['sha256'],result['native']['list_sha256'])
        rows[label]=result;save('provider/visits.json',rows)
    def write_same(payload,times):
        with provider.open('r+b') as f:
            assert os.fstat(f.fileno()).st_size==len(payload)
            f.write(payload);f.flush();os.fsync(f.fileno())
        os.utime(provider,ns=times)
    observe('absent','')
    with provider.open('xb') as f:f.write(libs['A']);f.flush();os.fsync(f.fileno())
    stat=provider.stat();times=(stat.st_atime_ns,stat.st_mtime_ns)
    identity_a=identity(provider)
    try:
        observe('A','A')
        write_same(libs['B'],times);observe('B','B')
        assert len({r[0] for r in reference.values()})==3
        # A retained prior binary continues to require A even when the selected native input now requires B.
        old=ROOT/'old-native-test'
        with gzip.open(proof/'test-A.elf.gz','rb') as inf,old.open('xb') as outf:shutil.copyfileobj(inf,outf)
        old.chmod(0o700);assert test_binary(old,env,'A')['stderr']!=rows['B']['native']['stderr']
        write_same(b'\xff' * len(libs['B']),times);observe('broken','',False)
        write_same(libs['B'],times);observe('repaired','B')
        # Rebuild every Cargo artifact with the real provider at the very same paths.
        STATE.rename(ROOT/'prior-native-B');observe('clean-B','B')
        write_same(libs['A'],times);STATE.rename(ROOT/'prior-native-A');observe('clean-A','A')
        identity_last=identity(provider)
        assert all(identity_a[k]==identity_last[k] for k in ('dev','ino','size','mtime','sha256'))
    finally:
        provider.unlink(missing_ok=True)
    observe('removed','')
    assert sha(wild)==WILD
    save('provider/accepted.json',dict(role='23',wild=WILD,source=NEW,head=os.environ['GITHUB_SHA'],
         valueA=reference['A'][0],valueB=reference['B'][0],absent=reference[''][0],
         malformed=rows['broken']['code'],files_changed='task-owned native provider only'))
if __name__=='__main__':main()
