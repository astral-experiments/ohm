"""Try real same-stat native library changes against an unchanged, previously linked test."""
import gzip
import hashlib
import json
import os
import re
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
    if (getenv("OHM_RUFF_NATIVE_WITNESS")) {
        const char message[] = "OHM_RUFF_NATIVE_" ROLE "\n";
        if (write(2, message, sizeof(message) - 1) != sizeof(message) - 1)
            _exit(123);
    }
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

def test_binary(path,env):
    dyn=subprocess.check_output(['readelf','-dW',path])
    needed=[l for l in dyn.splitlines() if b'(NEEDED)' in l and b'libohm-ruff-db-' in l]
    assert len(needed)<=1
    letter=''
    if needed:
        match=re.search(rb'\[libohm-ruff-db-([AB])\.so\]',needed[0])
        assert match,needed
        letter=match[1].decode()
    p=subprocess.run([path,'--list','--format','terse'],cwd=SRC,env=dict(env,OHM_RUFF_NATIVE_WITNESS='1'),capture_output=True,check=True)
    marker=('OHM_RUFF_NATIVE_'+letter+'\n').encode() if letter else b''
    assert p.stderr==marker and sum(l.endswith(b': test') for l in p.stdout.splitlines())==126
    return dict(witness=letter,dynamic=dyn.decode(),stderr=p.stderr.decode(),list_sha256=hashlib.sha256(p.stdout).hexdigest())

def main(role):
    assert git('rev-parse','HEAD')==NEW and not git('status','--porcelain')
    assert role in ('23','253') and json.loads((RECORDS/'accepted.json').read_text())['role']==role
    wild=SDK/'lib/rustlib'/HOST/'bin/wild-ld/ld.bfd'
    assert sha(wild)==WILD
    provider=wild.with_name('libutil.so')
    assert not provider.is_symlink() and not provider.exists()
    env=json.loads((RECORDS/'environment.json').read_text())
    env.update(CARGO_NET_OFFLINE='true',LD_LIBRARY_PATH=str(ROOT/'native-loader'))
    ordinary=json.loads((RECORDS/'visits.json').read_text())['clean']
    libs=compile_libraries(ROOT/'native-loader')
    proof=RECORDS/'provider';proof.mkdir()
    for letter,payload in libs.items():
        (proof/('libohm-ruff-db-'+letter+'.so')).write_bytes(payload)
    (proof/'native-witness.c').write_text(C_SOURCE)
    reference={}; rows={}
    def observe(label, allowed, *, may_fail=False, must_fail=False):
        folder=proof/label;folder.mkdir()
        p=subprocess.run(COMMAND,cwd=SRC,env=env,capture_output=True,timeout=720)
        (folder/'stdout.gz').write_bytes(gzip.compress(p.stdout))
        (folder/'stderr.gz').write_bytes(gzip.compress(p.stderr))
        result=dict(code=p.returncode,provider=identity(provider) if provider.exists() else None)
        if p.returncode:
            diagnostics=p.stdout+b'\n'+p.stderr
            assert (may_fail or must_fail) and p.returncode==101 and str(provider).encode() in diagnostics,diagnostics[-4000:]
            assert any(t in diagnostics.lower() for t in (b'wild',b'unknown input',b'unsupported',b'invalid'))
        else:
            assert not must_fail,label
            exe,roster,dirty=test_artifact([json.loads(l) for l in p.stdout.splitlines()])
            assert roster==ordinary['roster']
            assert native(exe,folder,env)==ordinary['tests']
            outcome=test_binary(exe,env)
            letter=outcome['witness']
            assert letter in allowed,(label,letter,allowed)
            product=sha(exe)
            if not letter:assert product==ordinary['sha256']
            result.update(native=outcome,binary=identity(exe),path=str(exe),dirty=dirty,units=len(roster))
            if letter not in reference:
                target=proof/('test-'+(letter or 'absent')+'.elf.gz')
                with exe.open('rb') as src,gzip.open(target,'xb',compresslevel=2) as dst:
                    shutil.copyfileobj(src,dst)
                reference[letter]=(product,outcome['list_sha256'])
            assert reference[letter]==(product,outcome['list_sha256'])
        rows[label]=result
        save('provider/visits.json',rows)
        return result

    def write_same(payload,times):
        with provider.open('r+b') as f:
            assert os.fstat(f.fileno()).st_size==len(payload)
            f.write(payload);f.flush();os.fsync(f.fileno())
        os.utime(provider,ns=times)
    observe('absent',{''})
    with provider.open('xb') as f:
        f.write(libs['A']);f.flush();os.fsync(f.fileno())
    stat=provider.stat();times=(stat.st_atime_ns,stat.st_mtime_ns)
    identity_a=identity(provider)
    try:
        observe('insert-A',{'','A'})
        STATE.rename(ROOT/'prior-native-A')
        clean_a=observe('clean-A',{'A'})
        write_same(libs['B'],times)
        warm_b=observe('swap-B',{'A','B'})
        write_same(b'\xff' * len(libs['B']),times)
        broken=observe('broken',{'A','B'},may_fail=True)
        if not broken['code']:
            # Set the prior complete output aside to require a genuine new link.
            Path(broken['path']).rename(ROOT/'kept-before-invalid-fresh-link')
            observe('fresh-link-broken',set(),must_fail=True)
        write_same(libs['B'],times)
        observe('repaired',{'B'})
        STATE.rename(ROOT/'prior-native-B')
        observe('clean-B',{'B'})
        assert len({r[0] for r in reference.values()})==3
        assert clean_a['binary']['sha256']==reference['A'][0]
        # The two distinct SONAMEs keep the old executable observable after a change.
        if warm_b['native']['witness']=='A':
            assert warm_b['binary']['sha256']==clean_a['binary']['sha256']
        for label in ('swap-B','broken','repaired','clean-B'):
            assert all(rows[label]['provider'][k]==identity_a[k] for k in ('dev','ino','size','mtime'))
    finally:
        provider.unlink(missing_ok=True)
    observe('removed',{'','B'})
    STATE.rename(ROOT/'prior-native-absent')
    observe('clean-removed',{''})
    assert sha(wild)==WILD
    save('provider/accepted.json',dict(role=role,wild=WILD,source=NEW,head=os.environ['GITHUB_SHA'],
         values={k:v[0] for k,v in reference.items()},insert=rows['insert-A']['native']['witness'],
         swap=rows['swap-B']['native']['witness'],malformed=broken['code'],removed=rows['removed']['native']['witness'],
         files_changed='task-owned native provider only'))

if __name__=='__main__':main(sys.argv[1])
