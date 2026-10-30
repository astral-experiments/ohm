"""Private actual host Cargo consumer; each independent reference starts at the same empty canonical path."""
from pathlib import Path
import contextlib, gzip, hashlib, json, os, re, shutil, signal, subprocess, sys, time

CFG=json.loads(Path(sys.argv[1]).read_text())
D=Path(CFG['private_state']);SDK=D/'rustup/toolchains/ohm';N=D/'native';W=D/'work.active'
SIDE=SDK/'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/libutil.so'
R=Path(CFG['ruff']);PROXY=Path(CFG['proxy']);FLOOR=11*(1<<28);rec=D/sys.argv[2]
records={
    'signed':(Path(CFG['signed_sdk'])/'bin/cargo','2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c','abf43741c6c75f7fd4a3bcbf1db0cfc29824a07727bde4a3974b3ea44b379c1a'),
    'classic':(Path(CFG['classic']),'735e1528ed741015c57676dccf05dbdc0ff7bed1','869a24e83ff84cca6e9d6cb35eb62f149aa48555cf8bb7ee9b94d44ad90d2914'),
    'aware':(Path(CFG['aware']),'c18e91b514b2c4e4966c9ab03232c804af3e1b57','9fb29f6abecad05acb6015990615c5fbb435a5907543f0bd33cf88cada4f5826'),
    'fd55':(Path(CFG['fd55']),'fd55a13d0220748794ba3c7c9556ef8ceed8591f','a5345089c120942d881ebf4f67f86e6f01a6d4e19d30df047ef6ac9baa6cf429'),
}
ROLES={k:records[k] for k in CFG['roles']}
CARGO=[str(PROXY/'cargo'),'+ohm','build','-p','ruff_unicode_names2','--locked','--offline','-j4','--message-format=json']
READSRC='extern crate unicode_names2; fn main() { for n in ["NULL","NUL"] {println!("{:?}", unicode_names2::character(n).map(u32::from));} }\n'
ENV={'HOME':CFG['effective_home'],'PATH':str(PROXY)+':/usr/local/bin:/usr/bin:/bin','RUSTUP_HOME':str(D/'rustup'),'CARGO_TARGET_DIR':str(W/'target'),'CARGO_BUILD_BUILD_DIR':str(W/'shared'),'CARGO_HOME':str(D/'cargo-home'),'CARGO_NET_OFFLINE':'true','CARGO_CACHE_AUTO_CLEAN_FREQUENCY':'never','CARGO_TERM_COLOR':'never','LC_ALL':'C'}
# Preserve PIDs/operands from every successful exec, escaped bytes, and all probe/open results.
def digest(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def jd(p,x):p.write_text(json.dumps(x,sort_keys=True,indent=2)+'\n')
def gz(p,x):p.write_bytes(gzip.compress(x,mtime=0))
def capacity():return shutil.disk_usage(D).free
def run(argv, where, tag, cwd=R, env=ENV):
    before=capacity(); assert before>FLOOR,before
    out,err=where/(tag+'.stdout'),where/(tag+'.stderr')
    with out.open('wb') as o,err.open('wb') as e:
        proc=subprocess.Popen(argv,cwd=cwd,env=env,stdout=o,stderr=e,start_new_session=True)
        try:
            minimum=before; start=time.monotonic()
            while proc.poll() is None:
                value=capacity();minimum=min(minimum,value)
                if minimum<=FLOOR or time.monotonic()-start>240: raise RuntimeError(('physical guard',minimum,argv))
                time.sleep(.1)
        except BaseException:
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            proc.wait();raise
    result=[proc.returncode,out.read_bytes(),err.read_bytes(),minimum]
    for p,content in ((out,result[1]),(err,result[2])):
        gz(p.with_suffix(p.suffix+'.gz'),content);p.unlink()
    return result
def trace(out):
    rows=[]; marker=b'libutil.so'; exes=[]; probes=[]
    for f in sorted(out.iterdir()):
        pid=int(f.name.split('.')[-1]);owner=None
        for line in f.read_bytes().splitlines():
            if line.startswith((b'execve(',b'execveat(')):
                rows.append(str(pid).encode()+b' '+line)
                if line.endswith(b'= 0'):
                    m=re.search(rb'execve\("([^"]+)",',line)
                    if m is not None:
                        owner=os.fsdecode(m[1]);exes.append((pid,owner,line.decode('utf-8','replace')))
            elif marker in line:
                rows.append(str(pid).encode()+b' '+line);probes.append((pid,owner,line.decode('utf-8','replace')))
        f.unlink()
    out.rmdir()
    return b'\n'.join(rows)+b'\n',exes,probes
def side(mode,keep=False):
    if mode=='absent':
        SIDE.unlink(missing_ok=True);return None
    data=(N/('observe-'+mode+'.so')).read_bytes() if mode!='bad' else b'not a valid GNU linker input for host-unicode\n'.ljust((N/'observe-83.so').stat().st_size,b' ')
    if keep:
        a=SIDE.stat();assert a.st_size==len(data)
        with SIDE.open('r+b') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.utime(SIDE,ns=(a.st_atime_ns,a.st_mtime_ns))
        b=SIDE.stat();assert (a.st_dev,a.st_ino,a.st_mtime_ns,a.st_size)==(b.st_dev,b.st_ino,b.st_mtime_ns,b.st_size)
    else:
        SIDE.unlink(missing_ok=True);SIDE.write_bytes(data)
    b=SIDE.stat()
    return dict(dev=b.st_dev,ino=b.st_ino,mtime=b.st_mtime_ns,ctime=b.st_ctime_ns,size=b.st_size,sha256=digest(SIDE))
@contextlib.contextmanager
def installation():
    assert not W.exists() and capacity()>FLOOR+80*(1<<20),capacity()
    W.mkdir()
    try:yield
    finally:
        assert W.parent==D and W.name=='work.active' and not W.is_symlink()
        shutil.rmtree(W)
def setup():
    assert not W.exists() and not SIDE.exists() and not SIDE.is_symlink()
    assert subprocess.check_output(['git','-C',R,'rev-parse','HEAD','HEAD:crates/ruff_unicode_names2']).decode().splitlines()==['93526150df078af7dd8fc4226cdcc469539d2001','6204e19cfc0fc74f827f8bd5d2f7d807d7045272']
    assert not subprocess.check_output(['git','-C',R,'status','--porcelain','--untracked-files=no','--','crates/ruff_unicode_names2','crates/ruff_unicode_names2_generator'])
    assert digest(SDK/'bin/rustc')=='86d60426c7f3ebba0da187ca4f24339006aafbfb83a54eca94eadf507caea644'
    driver,=list((SDK/'lib').glob('librustc_driver-*'));assert digest(driver)=='70b47f76ba9996e087fea3a91c23d4f12e4ea6d487815e5e0f1f6e75fdc5f547'
    assert digest(SIDE.with_name('ld.bfd'))=='0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'
    assert subprocess.check_output([PROXY/'rustc','+ohm','--print','sysroot'],env=ENV).decode().strip()==str(SDK)
    for p,_,h in ROLES.values():assert digest(p)==h
    cg=Path(ENV['CARGO_HOME']);cg.mkdir(exist_ok=True);rg=cg/'registry';rg.mkdir(exist_ok=True)
    for k in ['cache','src','index']:
        # Entries in this warm, offline private registry resolve to existing provider stores.
        conf=rg/k;conf.mkdir(exist_ok=True)
        for src in (Path(CFG['registry_home'])/'registry'/k).iterdir():
            dst=conf/src.name
            if not dst.exists():dst.symlink_to(src,target_is_directory=True)
            assert dst.samefile(src)
    rec.mkdir();jd(rec/'protocol.json',dict(source='93526150df078af7dd8fc4226cdcc469539d2001',sdk=[digest(SDK/'bin/rustc'),digest(driver),digest(SIDE.with_name('ld.bfd'))],cargo={k:[str(p),c,h] for k,(p,c,h) in ROLES.items()},command=CARGO,env=ENV,min_free=FLOOR,per_install_min=FLOOR+80*(1<<20),scope='No-time physical consumer test. Cold→settled→new higher 83→same inode/times 47→malformed same inode→removed. Independent empty per mode. Weak vs strict behavior differences reported, never imputed.',native_sources={p.name:digest(p) for p in N.iterdir()},reader=READSRC,script=digest(__file__)))
def phase(base,name):
    q=base/name;q.mkdir();tr=W/'trace';tr.mkdir()
    rc,s,e,f=run(['/usr/bin/strace','-ff','-qq','-s','12288','-e','trace=execve,execveat,openat,openat2','-o',str(tr/'exec'),*CARGO],q,'cargo')
    raw,exes,probes=trace(tr);gz(q/'exec-and-provider-open.gz',raw)
    exe_groups={k:[] for k in ('rustc','ld','cc','collect2','generator')}
    for pid,prog,line in exes:
        n=Path(prog).name
        if n=='rustc' and '"--crate-name"' in line:
            m=re.search(r'"--crate-name", "([^"]+)"',line)
            if m and m.group(1)!='___':exe_groups['rustc'].append([pid,m.group(1)])
        elif n in ('ld.bfd','ld','rust-lld','wild'):exe_groups['ld'].append([pid,prog])
        elif n in ('cc','gcc','gcc-13'):exe_groups['cc'].append([pid,prog])
        elif n=='collect2':exe_groups['collect2'].append([pid,prog])
        elif n in ('build_script_build','build-script-build') and 'ruff_unicode_names2' in prog:exe_groups['generator'].append([pid,prog])
    msgs=[json.loads(l) for l in s.splitlines() if l.startswith(b'{')]
    units=[m for m in msgs if m['reason']=='compiler-artifact']
    u={'status':rc,'typed':len(units),'dirty':[[m['target']['name'],m['target']['kind']] for m in units if not m['fresh']],'physical':exe_groups,'trace':digest(q/'exec-and-provider-open.gz'),'higher':[(p,o,t) for p,o,t in probes if str(SIDE) in t],'floor_observed':f,'error_tail':e.decode('utf-8','replace')[-1000:]}
    if rc==0:
        leaf,=[m for m in units if m['target']['name']=='unicode_names2' and m['target']['kind']==['lib']]
        gen,=[Path(m['out_dir']) for m in msgs if m['reason']=='build-script-executed' and m['package_id']==leaf['package_id']]
        lib,=[Path(a) for a in leaf['filenames'] if a.endswith('.rlib')]
        files={p.name:digest(p) for p in gen.glob('*.rs')};assert sorted(files)==['generated.rs','generated_alias.rs','generated_phf.rs']
        m,=re.findall(rb'\(b"NULL", .*?\\u\{(\w{4})\}',(gen/'generated_alias.rs').read_bytes());u.update(generated=files,generate_code=m.decode(),rlib=digest(lib))
        (W/'consumer.rs').write_text(READSRC)
        dirs=sorted({p.parent for t in [W/'target',W/'shared'] for gl in ('*.rlib','*.rmeta') for p in t.rglob(gl)})
        rr,_,err,_=run([PROXY/'rustc','+ohm','--edition=2024',W/'consumer.rs','--extern','unicode_names2='+str(lib),*['-Ldependency='+str(p) for p in dirs],'-o',W/'consumer'],q,'reader-compile')
        assert rr==0,(rr,err[-1500:])
        rr,std,err,_=run([W/'consumer'],q,'reader-exec')
        assert rr==0 and std.decode().splitlines()==['Some('+str(int(m,16))+')','Some(0)'],(rr,std,err)
        u.update(reader_sha256=digest(W/'consumer'),reader=std.decode().splitlines())
    jd(q/'observation.json',u)
    print(base.name,name,rc,u.get('generate_code'),{k:len(v) for k,v in exe_groups.items()},'opened',len(u['higher']),flush=True)
    if rc and not ('linking' in u['error_tail'] or b'linking' in s or b'linking' in e):raise RuntimeError((rc,e[-3000:],s[-3000:]))
    return u
def main():
    setup()
    for role,(src,c,h) in ROLES.items():
        temp=SDK/'bin/cargo-private-incoming';assert not temp.exists();temp.symlink_to(src);temp.replace(SDK/'bin/cargo')
        assert digest(SDK/'bin/cargo')==h and c in subprocess.check_output([PROXY/'cargo','+ohm','-Vv'],env=ENV).decode()
        base=rec/role;base.mkdir();ledger=[]
        with installation():
            for name,state,keep in [('warm-absent','absent',False),('settled-absent','absent',False),('insert-83','83',False),('same-inode-47','47',True),('same-inode-bad','bad',True),('removed','absent',False)]:
                inode=side(state,keep);u=phase(base,name);ledger.append(dict(phase=name,state=state,provider=inode,result=u))
        for state in ['absent','83','47','bad']:
            with installation():
                inode=side(state);name='empty-'+state;u=phase(base,name);ledger.append(dict(phase=name,state=state,provider=inode,result=u))
        side('absent');jd(base/'complete.json',ledger)
    jd(rec/'complete.json',{r:digest(rec/r/'complete.json') for r in ROLES})
if __name__=='__main__':
    try:main()
    finally:
        if SIDE.exists() and SIDE.is_file() and not SIDE.is_symlink():SIDE.unlink()
