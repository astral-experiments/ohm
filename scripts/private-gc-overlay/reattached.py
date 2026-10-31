"""Stop actual x86_64 public Cargo at a verified directory open and attach one owned bind."""
import ctypes as C
import errno
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import uuid
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'gc-mount-evidence'))
import compare as ctrl

VERSION={'signed':('2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c','4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e'),
         'combined':('3239cc06edcc11db2c3ca134c9af6115eb756b0b','84be921330ca5354552dea4ad1c5ba16556c97fc02e9be9c72093029bde23473')}
lib=C.CDLL(None,use_errno=True);lib.ptrace.argtypes=[C.c_ulong,C.c_int,C.c_void_p,C.c_void_p];lib.ptrace.restype=C.c_long
def ptrace(cmd,pid=0,a=0,b=0):
    C.set_errno(0);ret=lib.ptrace(cmd,pid,a,b)
    if ret<0 and C.get_errno():raise OSError(C.get_errno(),os.strerror(C.get_errno()))
    return ret

def no_openat2():
    # x86_64 only. Force exactly openat2 to ENOSYS, leaving every mount/FD/stat syscall genuine.
    class Ins(C.Structure):
        _fields_=[('op',C.c_ushort),('yes',C.c_ubyte),('no',C.c_ubyte),('k',C.c_uint)]
    class Program(C.Structure):
        _fields_=[('size',C.c_ushort),('filter',C.POINTER(Ins))]
    code=(Ins*4)(Ins(0x20,0,0,0),Ins(0x15,0,1,437),Ins(0x06,0,0,0x50000|errno.ENOSYS),Ins(0x06,0,0,0x7fff0000))
    program=Program(4,code)
    assert os.uname().machine=='x86_64' and lib.prctl(38,1,0,0,0)==0
    assert lib.prctl(22,2,C.byref(program),0,0)==0,C.get_errno()

def state(path):
    try:
        fd=os.open(path,os.O_PATH|os.O_NOFOLLOW)
    except FileNotFoundError:return None
    try:
        st=os.fstat(fd);ident=[int(v.split()[1]) for v in Path('/proc/self/fdinfo',str(fd)).read_text().splitlines() if v.startswith('mnt_id:')]
        return dict(device=st.st_dev,inode=st.st_ino,nlink=st.st_nlink,size=st.st_size,mount=ident[0],
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None)
    finally:os.close(fd)

def trace(f,c,target,relocated,leaf,out,mask):
    src='private-after-scan.bin';output=out/'cargo.stdout';err=out/'cargo.stderr';pid=os.fork()
    if pid==0:
        try:
            for n,path in [(1,output),(2,err)]:
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o644);os.dup2(fd,n);os.close(fd)
            os.chdir(c['cwd']);os.setgroups([]);os.setgid(f.gid);os.setuid(f.uid)
            assert lib.prctl(4,1,0,0,0)==0
            if mask:no_openat2()
            ptrace(0);os.kill(os.getpid(),signal.SIGSTOP)
            binary=str(f.w/'shims/cargo');os.execve(binary,[binary,'+ohm','gc','-v','--color','never'],c['env'])
        except BaseException as exc:
            os.write(2,repr(exc).encode());os._exit(125)
    _,st=os.waitpid(pid,0);assert os.WIFSTOPPED(st) and os.WSTOPSIG(st)==signal.SIGSTOP
    ptrace(0x4200,pid,0,0x00000001|0x00100000) # TRACESYSGOOD | EXITKILL
    phase=None;active=None;observed=[];mountinfo=0;to_send=0;binding=None
    while True:
        ptrace(24,pid,0,to_send);_,st=os.waitpid(pid,0);to_send=0
        if os.WIFEXITED(st):code=os.WEXITSTATUS(st);break
        assert not os.WIFSIGNALED(st),st
        sig=os.WSTOPSIG(st)
        if sig!=signal.SIGTRAP|0x80:
            if sig not in (signal.SIGTRAP,signal.SIGSTOP):to_send=sig
            continue
        buf=C.create_string_buffer(128);ptrace(0x420e,pid,128,C.addressof(buf))
        raw=buf.raw;typ=raw[0]
        if typ==2 and active is not None:
            active['return']=struct.unpack_from('q',raw,24)[0];observed.append(active);active=None
        if typ!=1:continue
        assert struct.unpack_from('I',raw,4)[0]==0xc000003e
        num,*args=struct.unpack_from('7Q',raw,24)
        if num not in (257,437,263):continue
        try:
            fd=args[0];dfd=os.readlink('/proc/%d/fd/%d'%(pid,fd)) if fd<2**31 else 'CWD'
            mem=os.open('/proc/%d/mem'%pid,os.O_RDONLY)
            try:
                name=os.pread(mem,512,args[1]).partition(b'\0')[0].decode(errors='backslashreplace')
                flags=args[2] if num!=437 else struct.unpack('Q',os.pread(mem,8,args[2]))[0]
                resolve=0 if num!=437 else struct.unpack('Q',os.pread(mem,8,args[2]+16))[0]
            finally:os.close(mem)
        except (FileNotFoundError,ValueError,OSError):continue
        if name=='/proc/self/mountinfo':
            mountinfo+=1
            observed.append({'mountinfo':mountinfo,'pid':pid})
        if phase and '/proc/self/fdinfo/' in name:
            active={'kind':'mount-id-open','name':name,'pid':pid}
        if num==263 and name==src:
            active={'kind':'unlinkat-payload','dirfd':dfd,'name':name,'flags':flags,'pid':pid}
        if name==target.name and Path(dfd)==target.parent and flags&os.O_DIRECTORY and flags&os.O_NOFOLLOW:
            assert num in (257,437)
            active={'kind':'openat2' if num==437 else 'openat','dirfd':dfd,'name':name,'flags':flags,'resolve':resolve,'pid':pid}
            if phase is None:
                assert mountinfo>=2,mountinfo
                image=Path('/proc/%d/exe'%pid).resolve()
                before=state(target);before_leaf=state(leaf);assert before['mount']==state(target.parent)['mount']
                target.rename(relocated);target.mkdir();os.chown(target,f.uid,f.gid)
                f.mount('--bind',relocated,target)
                after=state(target);ext=state(relocated)
                assert (before['device'],before['inode'])==(after['device'],after['inode'])==(ext['device'],ext['inode'])
                assert after['mount']!=before['mount']==ext['mount'] and state(leaf)['sha256']==before_leaf['sha256']
                binding={'exec':str(image),'sha256':ctrl.o.st(image)['sha256'],'pid':pid,'mountinfo_reads':mountinfo,
                         'before_dir':before,'bound_dir':after,'outside_dir':ext,'before_leaf':before_leaf,'bound_leaf':state(leaf),'outside_leaf':state(relocated/src)}
                phase='bound'
    assert phase=='bound' and binding,observed
    return {'exit':code,'binding':binding,'events':observed,'outside_after':state(relocated/src),'visible_after':state(leaf),'err':err.read_text(),'stdout':output.read_text()}

def main(role,root,inside):
    if role.startswith('final'):
        assert role in ('final','final-enosys')
        spec=json.loads((HERE/'sources/final/candidate-source/spec.json').read_bytes())
        doc=json.loads((root/'product/build.json').read_bytes())
        expect=spec['head'];digest=doc['compiled']
        assert expect=='f1f1cde375c2562e4a39d12f8835092a106a4fb8' and doc['candidate']==expect and doc['tree']['tree']==spec['tree'] and doc['tree']['mode_path_sha256_inventory']==spec['inventory'] and doc['delivered']==digest
    elif role in ('stack','stack-enosys'):
        reg=json.loads((root/'stack-receipt.json').read_bytes());doc=json.loads((root/'product/build.json').read_bytes())
        expect,digest=reg['source'],reg['cargo_sha256']
        assert doc['candidate']==doc['tree']['commit']==expect and doc['tree']['tree']==reg['tree'] and doc['tree']['mode_path_sha256_inventory']==reg['inventory'] and doc['qa']==reg['workflow_sha']
        assert doc['delivered']==doc['compiled']==digest and ctrl.o.st(root/'product/build.json')['sha256']==reg['build_sha256']
    else:
        expect,digest=VERSION[role]
    out=root/'packet'/'fixed';sdk=root/'sdk-fixed'
    if not inside:
        out.mkdir(parents=True)
        if role=='signed':
            sdk.symlink_to(root/'sdk-21',target_is_directory=True)
        else:
            cert=json.loads((root/'product/build.json').read_bytes())
            assert cert['candidate']==expect and cert['compiled']==cert['delivered']==digest
            sdk.mkdir();(sdk/'bin').mkdir()
            orig=root/'sdk-21'
            for p in orig.iterdir():
                if p.name!='bin':(sdk/p.name).symlink_to(p,target_is_directory=p.is_dir())
            for p in (orig/'bin').iterdir():
                if p.name!='cargo':(sdk/'bin'/p.name).symlink_to(p)
            shutil.copyfile(root/'product/cargo',sdk/'bin/cargo');(sdk/'bin/cargo').chmod(0o755)
        assert ctrl.o.st(sdk/'bin/cargo')['sha256']==digest
        w=Path(tempfile.mkdtemp(prefix='qa-fixed-',dir=root));nonce=str(uuid.uuid4());(w/'.owned').write_text(nonce)
        outer=ctrl.o.ns();args=['sudo','-n','/usr/bin/env','-i','PATH=/usr/sbin:/usr/bin:/sbin:/bin','LANG=C','/usr/bin/unshare','--mount','--propagation','private','--fork','--','/usr/bin/python3','-IB',str(Path(__file__).resolve()),role,str(root),'inside',str(w),str(outer),str(os.getuid()),str(os.getgid()),nonce,shutil.which('rustup')]
        r=subprocess.run(args,capture_output=True,timeout=160)
        (out/'worker.stdout').write_bytes(r.stdout);(out/'worker.stderr').write_bytes(r.stderr)
        assert r.returncode==0,(r.stdout,r.stderr)
        assert outer==ctrl.o.ns() and not any(Path(v['path']).is_relative_to(w) for v in ctrl.o.mounts().values())
        return
    w=Path(sys.argv[4]);ns,uid,gid=map(int,sys.argv[5:8]);nonce,proxy=sys.argv[8:10]
    f=ctrl.Fixture('fixed',root,w,sdk,out,uid,gid,ns,nonce,proxy,expect,digest)
    c=f.makecase('private-graft');ws=c['cwd'];t=ws/'target';c['env']['CARGO_TARGET_DIR']=str(t)
    f.write(ws/'Cargo.toml',b'[package]\nname="target_graft"\nversion="0.1.0"\nedition="2024"\n');f.write(ws/'src/lib.rs',b'pub const N:u8=17;\n')
    assert f.cmd(c,'enroll',['check','--offline']).returncode==0
    stamp=time.time_ns()-4*3600*10**9;os.utime(t/'.ohm-target-last-use-v1',ns=(stamp,stamp))
    target=t/'debug/deps';old=c['outside']/'relocated-deps';leaf=target/'private-after-scan.bin';f.write(leaf,b'actual owned frozen output after discovery\n')
    original=state(leaf);assert original['nlink']==1 and original['sha256']
    with leaf.open('rb') as held:
        record=trace(f,c,target,old,leaf,out,role.endswith('-enosys'));record['physical_held_after']={'nlink':os.fstat(held.fileno()).st_nlink,'sha256':hashlib.sha256(held.read()).hexdigest()}
    assert record['binding']['sha256']==digest and original==record['binding']['before_leaf'] and record['physical_held_after']['sha256']==original['sha256']
    # Record either real native outcome before interpreting. The outside copy stays private to this job.
    ctrl.o.save(out/'reattached-result.json',record)
    if role.startswith('final') or role.startswith('stack'):
        assert record['exit']==0 and record['outside_after']==record['binding']['outside_leaf'] and record['physical_held_after']['nlink']==1,record
        assert not any(ev.get('kind')=='unlinkat-payload' for ev in record['events'])
        opens=[ev for ev in record['events'] if ev.get('kind')=='openat2']
        assert any(ev['resolve']&1 and ev['return']==(-errno.ENOSYS if role.endswith('-enosys') else -errno.EXDEV) for ev in opens),record
        if role.endswith('-enosys'):assert any(ev.get('kind')=='mount-id-open' and ev.get('return',-1)>=0 for ev in record['events'])
    mid=state(target)['mount'];assert mid==record['binding']['bound_dir']['mount']
    f.unmount(mid)
    assert record['exit'] in (0,101) and record['physical_held_after']['nlink']==int(record['outside_after'] is not None)

if __name__=='__main__':main(sys.argv[1],Path(sys.argv[2]).resolve(),len(sys.argv)>3 and sys.argv[3]=='inside')
