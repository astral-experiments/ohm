"""Run public Cargo against actual private profiles and record native file identities."""
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO = 'astral-experiments/ohm'
SOURCES = {'signed': '2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c',
           'shared-fix': 'c7f394c8c9aaef1272c621ff11d77dcf569ed94b'}
CARGOS = {'signed': '4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e',
          'shared-fix': '2e78b6774f1a04e6ce60ed82d3287808a09e157f433287c72f7cec1b40e598d5'}

def sha(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def save(path, obj):
    with path.open('x') as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write('\n')

def which_mount(path):
    return subprocess.check_output(['findmnt', '-T', str(path), '-n', '-o', 'FSTYPE']).decode().strip()

def props(st):
    return [st.st_dev,st.st_ino,st.st_nlink,st.st_size,st.st_mode]

def identity(path):
    try:
        ls = path.lstat()
    except FileNotFoundError:
        return None
    fd = os.open(path, os.O_PATH | os.O_NOFOLLOW)
    try:
        with os.scandir(path.parent) as entries:
            de, = [e.inode() for e in entries if e.name == path.name]
        parent = os.open(path.parent, os.O_PATH | os.O_DIRECTORY)
        try:
            at = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        finally:
            os.close(parent)
        ident = dict(d_ino=de,lstat=props(ls), fstat=props(os.fstat(fd)), fstatat=props(at),
                     mount_id=int(next(v.split()[1] for v in Path('/proc/self/fdinfo',str(fd)).read_text().splitlines() if v.startswith('mnt_id:'))))
        assert ident['fstat'] == ident['lstat'] == ident['fstatat']
        if path.is_file() and not path.is_symlink():
            ident['sha256'] = sha(path)
        return ident
    finally:
        os.close(fd)

def cargo(sdk,case,out,label,cmd):
    out.mkdir(exist_ok=True)
    cargo=case/'shims/cargo'
    env = {'PATH':str(cargo.parent)+':/usr/bin:/bin','HOME':str(case/'home'),'CARGO_HOME':str(case/'cargo-home'),
           'RUSTUP_HOME':str(case/'rustup'), 'RUSTUP_AUTO_INSTALL':'0','CARGO_TARGET_DIR':str(case/'ws/target'),
           'CARGO_BUILD_BUILD_DIR':str(case/'shared'),'XDG_CACHE_HOME':str(case/'xdg'),'TMPDIR':str(case/'tmp'),
           'CARGO_NET_OFFLINE':'true','LANG':'C','TERM':'dumb'}
    trace=out/(label+'.strace')
    args=[str(cargo),'+ohm',*cmd]
    p=subprocess.run(['strace','-f','-qq','-yy','-s','700','-e','trace=execve,flock,fcntl,openat,openat2,newfstatat,statx,getdents64,unlink,unlinkat,rmdir','-o',str(trace),'--',*args],env=env,cwd=case/'ws',capture_output=True,timeout=90)
    raw=trace.read_bytes()
    for name,b in [('trace',raw),('stdout',p.stdout),('stderr',p.stderr)]:
        (out/(label+'.'+name+'.gz')).write_bytes(gzip.compress(b,mtime=0))
    trace.unlink()
    launched=case/'rustup/toolchains/ohm/bin/cargo'
    assert launched.samefile(sdk/'bin/cargo') and ('execve("'+str(launched)+'"').encode() in raw, (args,raw[:3000])
    assert p.returncode==0,(label,p.stderr)
    return dict(argv=args,exit=p.returncode,stdout=p.stdout.decode(),stderr=p.stderr.decode(),trace_sha256=hashlib.sha256(raw).hexdigest())

def main(root,other,role,base,expect_fs):
    sdk=(root/'sdk-21').resolve()
    assert sha(sdk/'bin/cargo') == CARGOS['signed']
    out=root/'packet'/role;out.mkdir(parents=True)
    if role!='signed':
        doc=json.loads((other/'build.json').read_bytes())
        if role=='shared-fix':
            assert doc['qa']=='5032f93b1a2e08f3bc2f6ed6425df3f6e28bead9'
        assert doc['candidate']==SOURCES[role] and sha(other/'cargo')==doc['compiled']==doc['delivered']==CARGOS[role]
        save(out/'build.json',doc)
        dst=root/('sdk-'+role);dst.mkdir();(dst/'bin').mkdir()
        for f in sdk.iterdir():
            if f.name!='bin':(dst/f.name).symlink_to(f, target_is_directory=f.is_dir())
        for f in (sdk/'bin').iterdir():
            if f.name!='cargo':(dst/'bin'/f.name).symlink_to(f)
        shutil.copyfile(other/'cargo',dst/'bin/cargo');(dst/'bin/cargo').chmod(0o755)
        assert (dst/'bin/rustc').samefile(sdk/'bin/rustc');sdk=dst
    case=base/role;case.mkdir(parents=True)
    assert which_mount(case)==expect_fs,(case,which_mount(case),expect_fs)
    for sub in ['home','cargo-home','shared','xdg','tmp','shims','rustup/toolchains','ws/src']:
        (case/sub).mkdir(parents=True,exist_ok=True)
    (case/'rustup/toolchains/ohm').symlink_to(sdk)
    proxy=Path(shutil.which('rustup')).resolve()
    for n in ['cargo','rustc']:(case/'shims'/n).symlink_to(proxy)
    proj=case/'ws';(proj/'Cargo.toml').write_text('[package]\nname="private_gc_probe"\nversion="0.1.0"\nedition="2024"\n')
    (proj/'src/lib.rs').write_text('pub const ORIGINAL: u32 = 17;\n')
    cmds={};run=lambda phase,args:cmds.setdefault(phase,cargo(sdk,case,out,phase,args))
    assert 'commit-hash: '+SOURCES[role] in run('version',['-Vv'])['stdout']
    ev=run('enroll',['check','--offline','--message-format=json'])
    events=[json.loads(v) for v in ev['stdout'].splitlines()]
    assert any(e['reason']=='compiler-artifact' and e['target']['name']=='private_gc_probe' and not e['fresh'] for e in events)
    records=list((case/'cargo-home/.ohm-worktree-targets-v1').rglob('*.json'))
    assert records, list((case/'cargo-home').iterdir())
    bindings=[json.loads(r.read_bytes()) for r in records]
    t=proj/'target';d=t/'debug'; paths={'target':t,'profile':d,'old_lock':d/'.cargo-lock','held_lock':d/'.cargo-artifact-lock',
                                         'inside':d/'deps/private-visible-output','root_output':t/'root-private-output',
                                         'sibling':t/'doc/independent-visible-output','outside':case/'outside-sentinel'}
    for name in ['old_lock','held_lock']:
        if not paths[name].exists():paths[name].touch(exist_ok=False)
    for name in ['inside','sibling','root_output','outside']:
        p=paths[name];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(('owned '+name+'\n').encode()*11)
    marker=t/'.ohm-target-last-use-v1';assert marker.is_file();stamp=time.time_ns()-4*3600*10**9;os.utime(marker,ns=(stamp,stamp))
    snap=lambda:{name:identity(p) for name,p in paths.items()}
    states={'initial':snap()};fstat={}
    lock=paths['held_lock'];gc=['gc','-v','--color','never']
    with lock.open('rb') as holder, paths['inside'].open('rb') as payload:
        fcntl.flock(holder,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert subprocess.run(['flock','-n',str(lock),'true']).returncode==1
        for tag in ['held','released']:
            if tag=='released':
                fcntl.flock(holder,fcntl.LOCK_UN)
                assert subprocess.run(['flock','-n',str(lock),'true']).returncode==0
            for variant in ['dry','real']:
                phase=tag+'-'+variant;row=run(phase,gc+(['--dry-run'] if variant=='dry' else []))
                assert str(t) in row['stderr'],row['stderr']
                states[phase]=snap();fstat[phase]=dict(lock=props(os.fstat(holder.fileno())),payload=props(os.fstat(payload.fileno())))
    report={'role':role,'source':SOURCES[role],'cargo_sha256':sha(sdk/'bin/cargo'),'filesystem':expect_fs,
            'job':os.environ['GITHUB_JOB'],'runner':os.uname().release,'qa':os.environ['GITHUB_SHA'],'paths':{k:str(v) for k,v in paths.items()},
            'records':bindings,'commands':cmds,'states':states,'held_descriptors':fstat}
    save(out/'observation.json',report)
    before=states['initial']
    assert states['held-dry']==before and states['released-dry']==states['held-real']
    assert all(s['outside']==before['outside'] for s in states.values())
    assert all(states['held-real'][name]==before[name] for name in ['inside','root_output','sibling','old_lock','held_lock'])
    assert fstat['held-real']['payload'][2]==1
    print(role,expect_fs,{phase:(v['inside'] is not None,v['root_output'] is not None,v['sibling'] is not None) for phase,v in states.items()},flush=True)

if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],Path(sys.argv[4]),sys.argv[5])
