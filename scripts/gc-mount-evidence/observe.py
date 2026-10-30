"""Native public cargo gc, with unprivileged commands and private test-only mounts."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback
import uuid

SCRIPT=Path(__file__).resolve()
ARCHIVE='6f550de85f95440a61b5bd1a9d2ab0528d4fcaf674fdc008f5e986d2138be6c4'
CARGO='4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e'
CONTEXT='0123456789abcdef'
MARKER='.ohm-shared-registry-cache-v1'
NAME='QA_SENTINEL'
PAYLOAD=(b'Ohm owned disposable mount control. '*8)[:137]
assert len(PAYLOAD)==137

def sha(b):return hashlib.sha256(b).hexdigest()
def save(path,value):
    with path.open('x') as f:json.dump(value,f,sort_keys=True,indent=2);f.write('\n')
def run(*a):return subprocess.check_output([str(v) for v in a],text=True).strip()
def ns():return os.stat('/proc/self/ns/mnt').st_ino
def decoded(field):return re.sub(r'\\([0-7]{3})',lambda m:chr(int(m[1],8)),field)
def mounts():
    result={}
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        a,tail=line.split(' - ',1);fields=a.split()
        result[int(fields[0])]={'path':decoded(fields[4]),'root':decoded(fields[3]),'dev':fields[2],'type':tail.split()[0],'propagation':fields[6:]}
    return result
def st(path):
    if not path.exists():return None
    fd=os.open(path,os.O_PATH|os.O_NOFOLLOW)
    try:
        s=os.fstat(fd);entry={'dev':s.st_dev,'ino':s.st_ino,'size':s.st_size,'nlink':s.st_nlink,'mode':stat.S_IMODE(s.st_mode)}
        mid=int(re.search(r'^mnt_id:\s*(\d+)$',Path(f'/proc/self/fdinfo/{fd}').read_text(),re.M)[1])
        entry.update(mount_id=mid,filesystem=mounts()[mid]['type'])
        if stat.S_ISREG(s.st_mode):entry['sha256']=sha(path.read_bytes())
        return entry
    finally:os.close(fd)

def outer(root):
    assert os.getuid()!=0 and root.is_absolute() and root.resolve()==root and root.parent==Path(os.environ['RUNNER_TEMP']).resolve() and root.name=='gc-signed21'
    assert json.loads((root/'receipts/21/custody.json').read_bytes())['archive_sha256']==ARCHIVE
    assert sha((root/'sdk-21/bin/cargo').read_bytes())==CARGO
    fixture=Path(tempfile.mkdtemp(prefix='ephemeral-',dir=root))
    packet=root/'packet';packet.mkdir(mode=0o700)
    nonce=str(uuid.uuid4());(fixture/'.owned').write_text(nonce)
    shim=shutil.which('rustup');assert shim and os.path.isabs(shim)
    oldns=ns();old={i:v for i,v in mounts().items() if Path(v['path']).is_relative_to(fixture)}
    assert old=={}
    env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C'}
    cmd=['sudo','-n','/usr/bin/env','-i','PATH='+env['PATH'],'LANG=C','/usr/bin/unshare','--mount','--propagation','private','--fork','--',
         '/usr/bin/python3','-IB',str(SCRIPT),'inside',str(root),str(fixture),str(os.getuid()),str(os.getgid()),str(oldns),nonce,str(shim)]
    result=subprocess.run(cmd,capture_output=True,env=env)
    (packet/'inner.stdout').write_bytes(result.stdout);(packet/'inner.stderr').write_bytes(result.stderr)
    now={i:v for i,v in mounts().items() if Path(v['path']).is_relative_to(fixture)}
    save(packet/'outer.json',{'ns_before':oldns,'ns_after':ns(),'mounts_before':old,'mounts_after':now,'exit':result.returncode,'qa':os.environ['GITHUB_SHA'],
                            'runner':os.environ.get('RUNNER_NAME'),'uname':os.uname().release,'uid':os.getuid(),'artifact_sha':ARCHIVE,'cargo_sha':CARGO})
    if result.returncode:print(result.stderr.decode(errors='replace')[-2500:],file=sys.stderr)
    assert now=={} and ns()==oldns and result.returncode==0

def inner(root,w,uid,gid,oldns,nonce,shim):
    assert os.getuid()==0 and ns()!=oldns and (w/'.owned').read_text()==nonce
    assert w.parent==root and re.fullmatch('ephemeral-[a-zA-Z0-9_-]+',w.name) and w==w.resolve() and w.stat().st_uid==uid and uid>0 and gid>0
    assert root.parent.is_absolute() and root.name=='gc-signed21' and st(root/'sdk-21/bin/cargo')['sha256']==CARGO
    tab=mounts();assert not any(t.startswith(('shared:','master:')) for r in tab.values() if w.is_relative_to(Path(r['path'])) for t in r['propagation'])
    out=root/'packet'
    def mkdir(p):
        assert p.is_relative_to(w) and p.resolve()==p
        if not p.exists():mkdir(p.parent);p.mkdir();os.chown(p,uid,gid)
        return p
    def write(p,b):
        mkdir(p.parent)
        with p.open('xb') as f:f.write(b)
        os.chown(p,uid,gid)
    def tool_mount(*args):
        subprocess.run(['/usr/bin/mount',*map(str,args)],check=True,capture_output=True)
    def unmount(mid):
        table=mounts();assert mid in table
        path=Path(table[mid]['path'])
        assert path.is_relative_to(w) and path!=w and path.exists()
        subprocess.run(['/usr/bin/umount','--',str(path)],check=True,capture_output=True)
        assert mid not in mounts()
    def bind(source,dest):
        assert source.is_relative_to(w) and dest.is_relative_to(w) and not (source.is_symlink() or dest.is_symlink())
        assert source.is_dir() and dest.is_dir() and not list(dest.iterdir())
        before=st(dest);tool_mount('--bind',source,dest);a,b=st(source),st(dest)
        assert a['dev']==b['dev'] and a['ino']==b['ino'] and b['mount_id'] not in (a['mount_id'],before['mount_id'])
        return b['mount_id']
    def tmpfs(path):
        mkdir(path);tool_mount('-t','tmpfs','-o','size=12m,nodev,nosuid,noexec,mode=0755','qa-gc-tmpfs',path);os.chown(path,uid,gid);return st(path)['mount_id']
    def paths(place):
        d={k:mkdir(w/place/k) for k in ('home','cargo','target','shared','cwd','tmp','xdg')}
        return d,{'PATH':str(w/'shims')+':/usr/bin:/bin','HOME':str(d['home']),'CARGO_HOME':str(d['cargo']),'XDG_CACHE_HOME':str(d['xdg']),
                 'RUSTUP_HOME':str(w/'rustup'),'RUSTUP_AUTO_INSTALL':'0','CARGO_TARGET_DIR':str(d['target']),'CARGO_BUILD_BUILD_DIR':str(d['shared']),
                 'CARGO_NET_OFFLINE':'true','TERM':'dumb','LANG':'C','TMPDIR':str(d['tmp'])}
    def cmd(label,args,dirs,env):
        loc=out/label;loc.mkdir();os.chown(loc,uid,gid)
        trace=loc/'native.trace';binary=str(w/'shims/cargo')
        allargs=['/usr/bin/strace','-f','-qq','-ttt','-yy','-s','2048','-e','trace=execve,rename,renameat,renameat2,unlink,unlinkat,rmdir',
                 '-o',str(trace),'--',binary,'+ohm',*map(str,args)]
        p=subprocess.run(allargs,cwd=dirs['cwd'],env=env,user=uid,group=gid,extra_groups=[],capture_output=True,timeout=75)
        for n,b in [('stdout',p.stdout),('stderr',p.stderr),('native.trace',trace.read_bytes())]:
            with gzip.open(loc/(n+'.gz'),'xb') as f:f.write(b)
        trace.unlink()
        save(loc/'command.json',{'argv':[binary,'+ohm',*map(str,args)],'uid':uid,'gid':gid,'exit':p.returncode,'stdout':sha(p.stdout),'stderr':sha(p.stderr)})
        return p
    def gc(label,dirs,env,shared,dry):
        args=['gc','--color','never','-v']+(['--dry-run'] if dry else [])+(['--build-dir',shared] if shared is not None else [])
        return cmd(label,args,dirs,env)
    def summary(p):
        lines=p.stderr.decode().splitlines()
        return [v for v in lines if 'Summary' in v or 'Removed' in v or 'Skipping' in v or 'error' in v.lower()]
    def counted(p,count):
        return p.returncode==0 and re.search(r'Summary\s+'+str(count)+r' files?, '+str(count*len(PAYLOAD))+r'B total',p.stderr.decode()) is not None
    def shared_root(sh):
        ctx=sh/'debug/build/registries'/CONTEXT;mkdir(ctx)
        if not (sh/MARKER).exists():write(sh/MARKER,b'')
        if not (sh/'debug/.cargo-build-lock').exists():write(sh/'debug/.cargo-build-lock',b'')
        return ctx

    mkdir(w/'shims')
    for name in ('cargo','rustc'):(w/'shims'/name).symlink_to(shim)
    mkdir(w/'rustup/toolchains');(w/'rustup/toolchains/ohm').symlink_to(root/'sdk-21',target_is_directory=True)
    common,env=paths('shared-subject');sh=common['shared'];external=mkdir(w/'outside/shared-mount-source');sentinel=external/NAME
    write(sentinel,PAYLOAD);guard=w/'outside/QA_UNRELATED';write(guard,b'unrelated task control')
    v=cmd('signed-cargo-version',['-Vv'],common,env);assert v.returncode==0 and b'commit-hash: 2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c' in v.stdout
    save(out/'isolation.json',{'parent_ns':oldns,'inner_ns':ns(),'fixture':str(w),'shared':str(sh),'outside':str(external),'guard':st(guard),
                             'root':st(sh),'signed_runtime':st(root/'sdk-21/bin/cargo'),'user_for_every_cargo':uid})
    results={};issues={}

    def regular():
        ctx=shared_root(sh);f=ctx/'ordinary';write(f,PAYLOAD)
        before=st(f);d=gc('regular-ext4-dry',common,env,sh,True)
        assert counted(d,1) and st(f)==before and before['filesystem']=='ext4',(d.stderr,before)
        a=gc('regular-ext4-real',common,env,sh,False);assert a.returncode==0 and not f.exists(),a.stderr
        return {'before':before,'after':st(f),'preview':summary(d),'actual':summary(a)}
    def foreign():
        ctx=shared_root(sh);foreign=w/'unrelated-tmpfs';fmid=tmpfs(foreign)
        dest=mkdir(ctx/'mounted');write(foreign/NAME,PAYLOAD)
        mid=bind(foreign,dest)
        try:
            ext=st(foreign/NAME);seen=st(dest/NAME);parent=st(ctx)
            assert ext['dev']==seen['dev']!=parent['dev']
            d=gc('foreign-dry',common,env,sh,True)
            assert d.returncode==0 and b'on a different filesystem; left untouched' in d.stderr and st(foreign/NAME)==ext,d.stderr
            return {'external':ext,'seen':seen,'parent':parent,'kept':True,'preview':summary(d),'real_executed':False}
        finally:unmount(mid);unmount(fmid)
    def same():
        ctx=shared_root(sh);dest=mkdir(ctx/'mounted');mid=bind(external,dest)
        fd=os.open(sentinel,os.O_RDONLY)
        try:
            orig=st(sentinel);seen=st(dest/NAME);parent=st(ctx)
            assert orig['dev']==seen['dev']==parent['dev'] and orig['ino']==seen['ino'] and seen['mount_id']!=orig['mount_id']
            d=gc('same-device-dry',common,env,sh,True)
            admitted=counted(d,1) and b'Skipping' not in d.stderr
            assert st(sentinel)==orig and st(dest/NAME)==seen
            fact={'before':orig,'view_before':seen,'parent':parent,'external_path':str(sentinel),'before_mount_id':mid,'preview':summary(d),'admitted':admitted}
            if admitted:
                assert w.is_relative_to(root) and external.is_relative_to(w) and sh.is_relative_to(w) and not external.is_relative_to(sh)
                assert st(root/'sdk-21/bin/cargo')['sha256']==CARGO and orig['sha256']==sha(PAYLOAD) and ns()!=oldns
                a=gc('same-device-real',common,env,sh,False)
                snap=os.fstat(fd);os.lseek(fd,0,os.SEEK_SET)
                fact.update(actual=summary(a),actual_exit=a.returncode,external_after=st(sentinel),held_after={'dev':snap.st_dev,'ino':snap.st_ino,
                    'nlink':snap.st_nlink,'bytes_sha256':sha(os.read(fd,4096))},view_after=str(Path(mounts()[mid]['path'])/NAME))
                assert st(guard)['sha256']==sha(b'unrelated task control')
            save(out/'same-device-immediate.json',fact)
            print('Native same-device bind:',json.dumps(fact,sort_keys=True),flush=True)
            return fact
        finally:os.close(fd);unmount(mid)
    def private():
        dirs,e=paths('private-control');proj=dirs['cwd'];target=proj/'target';e['CARGO_TARGET_DIR']=str(target)
        write(proj/'Cargo.toml',b'[package]\nname="owned_gc_fixture"\nversion="0.1.0"\nedition="2024"\n')
        write(proj/'src/lib.rs',b'pub const VALUE: u32 = 1;\n')
        b=cmd('private-enroll',['check','--offline'],dirs,e);assert b.returncode==0,b.stderr
        marker=target/'.ohm-target-last-use-v1';assert marker.is_file()
        elapsed=time.time()-3*60*60;os.utime(marker,(elapsed,elapsed))
        private_source=mkdir(w/'outside/private-mount-source');write(private_source/NAME,PAYLOAD)
        view=mkdir(target/'debug/incremental/fixture-bound');mid=bind(private_source,view)
        try:
            src=st(private_source/NAME);via=st(view/NAME);d=gc('private-same-device-dry',dirs,e,None,True)
            assert d.returncode==0 and b'would cross mount at ' in d.stderr and str(view) in d.stderr.decode() and st(private_source/NAME)==src,d.stderr
            return {'source':src,'view':via,'kept':True,'preview':summary(d),'real_executed':False}
        finally:unmount(mid)
    def overlay():
        base=mkdir(w/'overlay-control');lower=mkdir(base/'lower');other=tmpfs(lower);overlay_id=None
        try:
            raw=shared_root(lower/'cache');write(raw/'ordinary',PAYLOAD)
            upper=mkdir(base/'upper');work=mkdir(base/'work');merged=mkdir(base/'merged')
            tool_mount('-t','overlay','-o',f'lowerdir={lower},upperdir={upper},workdir={work},xino=off','overlay',merged)
            overlay_id=st(merged)['mount_id'];root2=merged/'cache';f=root2/'debug/build/registries'/CONTEXT/'ordinary'
            first=st(f);par=st(f.parent);assert first['filesystem']==par['filesystem']=='overlay' and first['mount_id']==par['mount_id']
            d=gc('single-overlay-dry',common,env,root2,True);assert d.returncode==0 and st(f)==first,d.stderr
            return {'file':first,'parent':par,'preview':summary(d),'same_mount_id':True,'different_dev':first['dev']!=par['dev'],'real_executed':False}
        finally:
            if overlay_id is not None:unmount(overlay_id)
            unmount(other)
    for label,call in [('regular',regular),('foreign',foreign),('same-device',same),('private',private),('overlay',overlay)]:
        try:results[label]=call()
        except Exception:
            issues[label]=traceback.format_exc()
            print(issues[label],file=sys.stderr,flush=True)
    residual={i:r for i,r in mounts().items() if Path(r['path']).is_relative_to(w)}
    save(out/'result.json',{'results':results,'issues':issues,'mounts_remaining':residual,'guard_after':st(guard)})
    assert not residual and not issues,(residual,list(issues))

if __name__=='__main__':
    if sys.argv[1]=='inside':inner(Path(sys.argv[2]),Path(sys.argv[3]),int(sys.argv[4]),int(sys.argv[5]),int(sys.argv[6]),sys.argv[7],sys.argv[8])
    else:outer(Path(sys.argv[1]))
