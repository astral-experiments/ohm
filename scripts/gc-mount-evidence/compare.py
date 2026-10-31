"""Compare signed and fixed public Cargo in independent private mount namespaces."""
import fcntl
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent))
import observe as o

SENTINEL=o.PAYLOAD
HEALTHY=b'healthy ordinary unrelated owned GC output '*2
assert len(HEALTHY)!=len(SENTINEL)
ROOT='0123456789abcdef';OTHER='fedcba9876543210'
SHA=lambda b:o.sha(b)
def outer(root,artifact,late=False):
    assert root.is_absolute() and root==root.resolve() and root.parent==Path(os.environ['RUNNER_TEMP']).resolve() and root.name=='gc-mount-qualification'
    manifest=json.loads((Path(__file__).resolve().parent/'candidate-source/spec.json').read_bytes())
    sealed=json.loads((artifact/'build.json').read_bytes())
    build_qa='46d28e8bff1c6b52f3e7b7bc13192019e964a7da' if late else os.environ['GITHUB_SHA']
    assert manifest['head']==sealed['candidate'] and manifest['parent']==sealed['parent'] and sealed['qa']==build_qa
    assert o.st(artifact/'cargo')['sha256']==sealed['delivered']==sealed['compiled']
    signed=root/'sdk-21';dirs={'signed':signed,'fixed':root/'sdk-fixed'}
    assert o.st(signed/'bin/cargo')['sha256']==o.CARGO
    fix=dirs['fixed'];fix.mkdir();(fix/'bin').mkdir()
    for f in signed.iterdir():
        if f.name!='bin':(fix/f.name).symlink_to(f,target_is_directory=f.is_dir())
    for f in (signed/'bin').iterdir():
        if f.name!='cargo':(fix/'bin'/f.name).symlink_to(f,target_is_directory=f.is_dir())
    shutil.copyfile(artifact/'cargo',fix/'bin/cargo');(fix/'bin/cargo').chmod(0o755)
    for filename in ('bin/rustc','lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd'):
        assert (signed/filename).samefile(fix/filename)
    packet=root/'packet';packet.mkdir(mode=0o700)
    o.save(packet/'build.json',sealed);o.save(packet/'spec.json',manifest)
    jobs={}
    for role,runtime in dirs.items():
        case=Path(tempfile.mkdtemp(prefix='qa-'+role+'-',dir=root));output=packet/role;output.mkdir(mode=0o700)
        nonce=str(uuid.uuid4());(case/'.owned').write_text(nonce)
        id_before=o.ns();assert not any(Path(v['path']).is_relative_to(case) for v in o.mounts().values())
        cmd=['sudo','-n','/usr/bin/env','-i','PATH=/usr/sbin:/usr/bin:/sbin:/bin','LANG=C','/usr/bin/unshare','--mount','--propagation','private','--fork','--',
             '/usr/bin/python3','-IB',str(Path(__file__).resolve()),'inside-late' if late else 'inside',role,str(root),str(case),str(runtime),str(output),str(os.getuid()),str(os.getgid()),
             str(id_before),nonce,shutil.which('rustup'),manifest['head'] if role=='fixed' else manifest['parent'],sealed['compiled'] if role=='fixed' else o.CARGO]
        r=subprocess.run(cmd,capture_output=True,env={'PATH':'/usr/bin:/bin','LANG':'C'})
        (output/'inner.stdout').write_bytes(r.stdout);(output/'inner.stderr').write_bytes(r.stderr)
        after=[v for v in o.mounts().values() if Path(v['path']).is_relative_to(case)]
        o.save(output/'outer.json',{'before':id_before,'after':o.ns(),'residual':after,'exit':r.returncode})
        assert not after and id_before==o.ns()
        jobs[role]=r.returncode
    o.save(packet/'terminal.json',{'roles':jobs,'qa':os.environ['GITHUB_SHA'],'uname':os.uname().release})
    assert all(v==0 for v in jobs.values()),jobs

class Fixture:
    def __init__(self,role,root,w,runtime,output,uid,gid,outer_ns,nonce,shim,commit,cargo_sha):
        assert os.geteuid()==0 and w.parent==root and w==w.resolve() and re.fullmatch('qa-'+role+'-[a-zA-Z0-9_-]+',w.name)
        assert (w/'.owned').read_text()==nonce and w.stat().st_uid==uid and uid>0 and gid>0 and o.ns()!=outer_ns
        assert role in ('signed','fixed') and runtime==root/('sdk-21' if role=='signed' else 'sdk-fixed')
        assert o.st(runtime/'bin/cargo')['sha256']==cargo_sha and output==root/'packet'/role
        assert not any(t.startswith(('shared:','master:')) for v in o.mounts().values() if w.is_relative_to(Path(v['path'])) for t in v['propagation'])
        self.w=w;self.uid=uid;self.gid=gid;self.o=output;self.role=role;self.runtime=runtime
        self.mkdir(w/'shims');self.mkdir(w/'rustup/toolchains');(w/'rustup/toolchains/ohm').symlink_to(runtime,target_is_directory=True)
        for n in ('cargo','rustc'):(w/'shims'/n).symlink_to(shim)
        case=self.makecase('version')
        p=self.cmd(case,'version',['-Vv'])
        assert p.returncode==0 and ('commit-hash: '+commit).encode() in p.stdout
        o.save(output/'identity.json',{'expected':commit,'cargo':o.st(runtime/'bin/cargo'),'rustc':o.st((runtime/'bin/rustc').resolve(strict=True)),'driver':o.st(next((runtime/'lib').glob('librustc_driver*.so')).resolve(strict=True)),
                'wild':o.st((runtime/'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd').resolve(strict=True)),
                'uid':uid,'base':str(w),'namespace':o.ns(),'parent_namespace':outer_ns,'version':p.stdout.decode()})
    def mkdir(self,p):
        assert p.is_relative_to(self.w) and p.resolve()==p
        if not p.exists():self.mkdir(p.parent);p.mkdir();os.chown(p,self.uid,self.gid)
        return p
    def write(self,p,b):
        self.mkdir(p.parent)
        with p.open('xb') as f:f.write(b)
        os.chown(p,self.uid,self.gid)
    def makecase(self,label):
        base=self.mkdir(self.w/label);j={n:self.mkdir(base/n) for n in ('home','cargo','cwd','target','shared','xdg','tmp','outside')}
        j['env']={'PATH':str(self.w/'shims')+':/usr/bin:/bin','CARGO_HOME':str(j['cargo']),'HOME':str(j['home']),'XDG_CACHE_HOME':str(j['xdg']),
                  'CARGO_TARGET_DIR':str(j['target']),'CARGO_BUILD_BUILD_DIR':str(j['shared']),'CARGO_NET_OFFLINE':'true','LANG':'C','TERM':'dumb',
                  'RUSTUP_HOME':str(self.w/'rustup'),'RUSTUP_AUTO_INSTALL':'0','TMPDIR':str(j['tmp'])}
        j['label']=label;return j
    def cmd(self,c,name,args):
        loc=self.o/(c['label']+'-'+name);loc.mkdir();os.chown(loc,self.uid,self.gid);trace=loc/'native.trace'
        cmd=[str(self.w/'shims/cargo'),'+ohm',*map(str,args)]
        call=['/usr/bin/strace','-f','-qq','-ttt','-yy','-s','2048','-e','trace=execve,openat,openat2,statx,fstatfs,rename,renameat,renameat2,unlink,unlinkat,rmdir','-o',str(trace),'--',*cmd]
        p=subprocess.run(call,env=c['env'],cwd=c['cwd'],user=self.uid,group=self.gid,extra_groups=[],timeout=120,capture_output=True)
        for key,b in [('stdout',p.stdout),('stderr',p.stderr),('native.trace',trace.read_bytes())]:
            with gzip.open(loc/(key+'.gz'),'xb') as f:f.write(b)
        trace.unlink();o.save(loc/'command.json',{'argv':cmd,'uid':self.uid,'exit':p.returncode,'stdout':SHA(p.stdout),'stderr':SHA(p.stderr)})
        return p
    def gc(self,c,name,dry,shared):
        return self.cmd(c,name,['gc','--color','never','-v']+(['--dry-run'] if dry else [])+(['--build-dir',shared] if shared is not None else []))
    def mount(self,*args):subprocess.run(['/usr/bin/mount',*map(str,args)],capture_output=True,check=True)
    def bind(self,path,dest):
        assert path.is_relative_to(self.w) and dest.is_relative_to(self.w) and path==path.resolve() and dest==dest.resolve()
        assert not list(dest.iterdir());old=o.st(dest);self.mount('--bind',path,dest);src,view=o.st(path),o.st(dest)
        assert src['dev']==view['dev'] and src['ino']==view['ino'] and view['mount_id'] not in (old['mount_id'],src['mount_id']);return view['mount_id']
    def unmount(self,mid):
        p=Path(o.mounts()[mid]['path']);assert p.is_relative_to(self.w) and p!=self.w and p.exists()
        subprocess.run(['/usr/bin/umount','--',str(p)],capture_output=True,check=True);assert mid not in o.mounts()
    def tmpfs(self,path):
        self.mkdir(path);self.mount('-t','tmpfs','-o','size=12m,nodev,nosuid,noexec,mode=0755','qa-only-tmpfs',path);os.chown(path,self.uid,self.gid);return o.st(path)['mount_id']
    def context(self,shared,staged,name):
        if not (shared/o.MARKER).exists():self.write(shared/o.MARKER,b'')
        if not (shared/'debug/.cargo-build-lock').exists():self.write(shared/'debug/.cargo-build-lock',b'')
        if not staged:return self.mkdir(shared/'debug/build/registries'/name)
        stage=self.mkdir(shared/'debug/.ohm-gc-trash-v1'/('entry-'+name));self.write(stage/'owner',b'ohm-build-gc-v1\n');return self.mkdir(stage/'payload')

def count(p,n,size):
    return p.returncode==0 and re.search(r'Summary\s+'+str(n)+r' files?, '+str(size)+r'B total',p.stderr.decode()) is not None

def boundary(f,label,staged,foreign=False):
    c=f.makecase(label);sh=c['shared'];ctx=f.context(sh,staged,ROOT);plain=f.context(sh,staged,OTHER)/'healthy';f.write(plain,HEALTHY)
    src=c['outside']/'source';other=f.tmpfs(src) if foreign else None;f.mkdir(src)
    sent=src/o.NAME;f.write(sent,SENTINEL);view=f.mkdir(ctx/'mounted');mid=f.bind(src,view);fd=os.open(sent,os.O_RDONLY)
    try:
        base=o.st(sent);seen=o.st(view/o.NAME);parent=o.st(ctx)
        assert base['ino']==seen['ino'] and base['dev']==seen['dev'] and (seen['dev']!=parent['dev'])==foreign and base['mount_id']!=seen['mount_id']
        dry=f.gc(c,'dry',True,sh);assert o.st(sent)==base and o.st(view/o.NAME)==seen and plain.exists()
        admitted=count(dry,2,len(SENTINEL)+len(HEALTHY));protected=count(dry,1,len(HEALTHY))
        record={'base':base,'view':seen,'parent':parent,'view_name':str(view),'external_name':str(sent),'healthy':str(plain),'old_mount':o.mounts()[mid],
                'preview':dry.stderr.decode(),'admitted':admitted,'protected_plus_healthy':protected,'real_ran':False}
        if admitted or protected:
            # Neither the positive nor the protected control can leave the private
            # namespace. Only these two task-owned files are eligible in the preview.
            assert src.is_relative_to(f.w) and not src.is_relative_to(sh) and base['sha256']==SHA(SENTINEL) and SHA(plain.read_bytes())==SHA(HEALTHY)
            real=f.gc(c,'real',False,sh);s=os.fstat(fd);os.lseek(fd,0,os.SEEK_SET)
            record.update(real_ran=True,actual_exit=real.returncode,actual=real.stderr.decode(),external_after=o.st(sent),
                         healthy_after=o.st(plain),new_mount=o.mounts()[mid],held={'ino':s.st_ino,'dev':s.st_dev,'nlink':s.st_nlink,'hash':SHA(os.read(fd,4096))})
        return record
    finally:
        os.close(fd);f.unmount(mid)
        if other is not None:f.unmount(other)

def symlinks(f):
    c=f.makecase('symlink');root=c['shared'];sub=f.context(root,False,ROOT);other=f.context(root,False,OTHER)/'healthy';f.write(other,HEALTHY)
    home=c['outside']/'directory';f.mkdir(home);sent=home/o.NAME;f.write(sent,SENTINEL)
    links=[(sub/'file-symlink',sent),(sub/'directory-symlink',home)]
    for p,src in links:p.symlink_to(src,target_is_directory=src.is_dir())
    before=o.st(sent);size=len(HEALTHY)+sum(p.lstat().st_size for p,_ in links)
    dry=f.gc(c,'dry',True,root);assert count(dry,3,size) and o.st(sent)==before,dry.stderr
    a=f.gc(c,'real',False,root)
    return {'exit':a.returncode,'before':before,'after':o.st(sent),'healthy':other.exists(),'links_exist':[os.path.lexists(p) for p,_ in links],'preview':dry.stderr.decode()}

def private(f):
    c=f.makecase('private');proj=c['cwd'];t=proj/'target';c['env']['CARGO_TARGET_DIR']=str(t)
    f.write(proj/'Cargo.toml',b'[package]\nname="owned_gc_boundary"\nversion="0.1.0"\nedition="2024"\n')
    f.write(proj/'src/lib.rs',b'pub const VALUE:u32=1;\n')
    p=f.cmd(c,'enroll',['check','--offline']);assert p.returncode==0,p.stderr
    marker=t/'.ohm-target-last-use-v1';assert marker.is_file();past=time.time()-4*3600;os.utime(marker,(past,past))
    g=t/'debug/incremental/healthy-independent/plain';f.write(g,HEALTHY)
    ext=f.mkdir(c['outside']/'private-external');sent=ext/o.NAME;f.write(sent,SENTINEL)
    dest=f.mkdir(t/'debug/incremental/mounted');mid=f.bind(ext,dest)
    try:
        before=o.st(sent);via=o.st(dest/o.NAME)
        d=f.gc(c,'dry',True,None);assert d.returncode==0 and b'would cross mount at ' in d.stderr and str(dest).encode() in d.stderr
        assert o.st(sent)==before and g.exists()
        r=f.gc(c,'real',False,None)
        return {'before':before,'view':via,'after':o.st(sent),'healthy':g.exists(),'exit':r.returncode,'original_mount':str(dest),'remaining_mount':o.mounts()[mid],
                'preview':d.stderr.decode(),'actual':r.stderr.decode()}
    finally:f.unmount(mid)

def overlay(f):
    c=f.makecase('overlay');base=f.mkdir(c['cwd']/'overlay');low=f.mkdir(base/'lower');other=f.tmpfs(low);mid=None
    try:
        root=low/'cache';sub=f.context(root,True,ROOT);leaf=sub/'regular'
        f.write(leaf,SENTINEL);up=f.mkdir(base/'upper');work=f.mkdir(base/'work');merged=f.mkdir(base/'merged')
        f.mount('-t','overlay','-o',f'lowerdir={low},upperdir={up},workdir={work},xino=off','overlay',merged)
        mid=o.st(merged)['mount_id'];root2=merged/'cache';visible=merged/leaf.relative_to(low)
        before=o.st(visible);par=o.st(visible.parent)
        assert before['mount_id']==par['mount_id']==mid and before['dev']!=par['dev'] and before['filesystem']==par['filesystem']=='overlay'
        d=f.gc(c,'dry',True,root2)
        old=d.returncode==0 and b'Summary 0 files' in d.stderr and b'on a different filesystem' in d.stderr
        new=count(d,1,len(SENTINEL));assert (old or new) and o.st(visible)==before
        a=f.gc(c,'real',False,root2)
        return {'exit':a.returncode,'old_rejection':old,'productive_preview':new,'before':before,'parent':par,'after':o.st(visible),
                'original_lower_after':o.st(leaf),'preview':d.stderr.decode(),'actual':a.stderr.decode()}
    finally:
        if mid is not None:f.unmount(mid)
        f.unmount(other)

def locked(f):
    c=f.makecase('held-profile-lock');sh=c['shared'];ctx=f.context(sh,False,ROOT);leaf=ctx/'owned';f.write(leaf,SENTINEL)
    before=o.st(leaf)
    with (sh/'debug/.cargo-build-lock').open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        d=f.gc(c,'dry-while-held',True,sh);assert d.returncode==0 and b'Summary 0 files' in d.stderr,d.stderr
        a=f.gc(c,'real-while-held',False,sh);kept=o.st(leaf)
    after_release=f.gc(c,'dry-after-release',True,sh);assert count(after_release,1,len(SENTINEL))
    done=f.gc(c,'real-after-release',False,sh)
    return {'while_held':[d.returncode,a.returncode],'after_release':[after_release.returncode,done.returncode],
            'before':before,'while_held_file':kept,'after_release_file':o.st(leaf)}

def inner(f):
    methods={'eligible-mounted':lambda:boundary(f,'eligible-mounted',False),
             'marked-trash-mounted':lambda:boundary(f,'marked-trash-mounted',True),
             'separate-device':lambda:boundary(f,'separate-device',False,True),'symlink':lambda:symlinks(f),
             'private':lambda:private(f),'overlay':lambda:overlay(f),'held-profile-lock':lambda:locked(f)}
    errors={};observed={}
    for name,method in methods.items():
        try:
            v=method();o.save(f.o/(name+'.json'),v);observed[name]=v
        except Exception:
            errors[name]=traceback.format_exc();print(name,errors[name],file=sys.stderr)
    issues=[]
    def gate(q,label):
        if not q:issues.append(label)
    for k in ('eligible-mounted','marked-trash-mounted','separate-device'):
        if k not in observed:continue
        v=observed[k];foreign=k=='separate-device';fixed=f.role=='fixed';safe=fixed or foreign
        gate(v['real_ran'] and v['admitted']!=safe and v['protected_plus_healthy']==safe,k+' dry-run')
        if not v['real_ran']:continue
        # The signed EBUSY can prevent an independently staged sibling from
        # running, depending on readdir order. Record its complete state.
        if f.role=='signed' and k=='marked-trash-mounted':
            gate(v['healthy_after'] is None or v['healthy_after']['sha256']==SHA(HEALTHY),k+' signed independent sibling integrity')
        else:gate(v['healthy_after'] is None,k+' unrelated eligible sibling')
        if safe:
            gate(v['external_after']==v['base'] and v['held']['nlink']==1,k+' external preserved')
            gate(v['held']['hash']==v['base']['sha256'] and v['actual_exit']==0,k+' successful safe cleanup')
            if fixed:gate(v['new_mount']['path']==v['old_mount']['path']==v['view_name'],k+' original mount position')
        else:
            gate(v['external_after'] is None and v['actual_exit']==101 and v['held']['nlink']==0,k+' signed native removal control')
    if (v:=observed.get('symlink')):gate(v['exit']==0 and v['before']==v['after'] and not any(v['links_exist']) and not v['healthy'],'symlink contents')
    if (v:=observed.get('private')):gate(v['exit']==0 and v['before']==v['after'] and not v['healthy'] and v['remaining_mount']['path']==v['original_mount'],'private mount protection')
    if (v:=observed.get('held-profile-lock')):gate(v['while_held']==v['after_release']==[0,0] and v['before']==v['while_held_file'] and v['after_release_file'] is None,'held and released lock')
    if (v:=observed.get('overlay')):
        gate(v['exit']==0 and v['productive_preview']==(f.role=='fixed') and v['original_lower_after']['sha256']==SHA(SENTINEL),'overlay admission and immutable lower')
        gate((v['after'] is None)==(f.role=='fixed'),'overlay logical output')
    residual=[v for v in o.mounts().values() if Path(v['path']).is_relative_to(f.w)]
    o.save(f.o/'result.json',{'errors':errors,'issues':issues,'role':f.role,'cases':list(observed),'residual_mounts':residual})
    assert not errors and not issues and not residual,(errors,issues,residual)

if __name__=='__main__':
    if sys.argv[1] in ('inside','inside-late'):
        role,root,w,runtime,output,uid,gid,outer_ns,nonce,shim,commit,digest=sys.argv[2:]
        fixture=Fixture(role,Path(root),Path(w),Path(runtime),Path(output),int(uid),int(gid),int(outer_ns),nonce,shim,commit,digest)
        if sys.argv[1]=='inside-late':
            import late_bind
            late_bind.run(fixture)
        else:inner(fixture)
    elif sys.argv[1]=='late':outer(Path(sys.argv[2]),Path(sys.argv[3]),True)
    else:outer(Path(sys.argv[1]),Path(sys.argv[2]))
