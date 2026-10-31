"""Private actual host Cargo consumer; each independent reference starts at the same empty canonical path."""
from pathlib import Path
import contextlib, gzip, hashlib, json, os, re, shutil, signal, subprocess, sys, time

CFG=json.loads(Path(sys.argv[1]).read_text())
D=Path(CFG['private_state']);SDK=D/'rustup/toolchains/ohm';N=D/'native';W=D/'work.active'
SIDE=SDK/'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/libutil.so'
R=Path(CFG['ruff']);PROXY=Path(CFG['proxy']);FLOOR=11*(1<<28);rec=D/sys.argv[2]
sys.path.insert(0,str(Path(__file__).resolve().parent))
import observed
records={k:(Path(v['binary']),v['head'],v['sha256']) for k in CFG['roles'] for v in [CFG['roles'][k]]}
ROLES=records
ORDINARY=[str(PROXY/'cargo'),'+ohm','build','-p','ruff_unicode_names2','--locked','--offline','-j4','--message-format=json']
CARGO=ORDINARY
READSRC='extern crate unicode_names2; fn main() { for n in ["NULL","NUL","NEW LINE","NEWLINE"] {println!("{:?}", unicode_names2::character(n).map(u32::from));} }\n'
ENV={'RUSTUP_AUTO_INSTALL':'0','HOME':CFG['effective_home'],'PATH':str(PROXY)+':/usr/local/bin:/usr/bin:/bin','RUSTUP_HOME':str(D/'rustup'),'CARGO_TARGET_DIR':str(W/'target'),'CARGO_BUILD_BUILD_DIR':str(W/'shared'),'CARGO_HOME':str(D/'cargo-home'),'CARGO_NET_OFFLINE':'true','CARGO_CACHE_AUTO_CLEAN_FREQUENCY':'never','CARGO_TERM_COLOR':'never','LC_ALL':'C'}
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
                if minimum<=FLOOR or time.monotonic()-start>420: raise RuntimeError(('physical guard',minimum,argv))
                time.sleep(.1)
        except BaseException:
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            proc.wait();raise
    result=[proc.returncode,out.read_bytes(),err.read_bytes(),minimum]
    for p,content in ((out,result[1]),(err,result[2])):
        gz(p.with_suffix(p.suffix+'.gz'),content);p.unlink()
    return result
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
    assert digest(SDK/'bin/rustc')=='f7663fb7dec7e5c7ea613a85ff1d6e4c00bf97b8c50534f17e5c95cd599712b9'
    driver,=list((SDK/'lib').glob('librustc_driver-*'));assert digest(driver)=='dae4f8dc64b2b2ac9dc04dfe2cfad633d6af1a87da2dfc532e757ffe758680e3'
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
    rec.mkdir();shutil.copytree(N,rec/'native-fixture');jd(rec/'protocol.json',dict(source='93526150df078af7dd8fc4226cdcc469539d2001',sdk=[digest(SDK/'bin/rustc'),digest(driver),digest(SIDE.with_name('ld.bfd'))],cargo={k:[str(p),c,h] for k,(p,c,h) in ROLES.items()},command=CARGO,env=ENV,min_free=FLOOR,per_install_min=FLOOR+80*(1<<20),scope='Migrate two signed poisoned target/shared directories to strict Cargo at the same binary path and mtime. Independently empty signed and strict references and a real Ruff generator edit. Native work counts only.',native_sources={p.name:digest(p) for p in N.iterdir()},reader=READSRC,script=digest(__file__)))
def phase(base,name):
    q=base/name;q.mkdir();tr=W/'trace';tr.mkdir()
    rc,s,e,f=run(['/usr/bin/strace','-ff','-qq','-ttt','-s','16384','-e','trace=execve,execveat,clone,clone3,fork,vfork,openat,openat2,statx,newfstatat,access,faccessat,faccessat2','-o',str(tr/'exec'),*CARGO],q,'cargo')
    raw,exes,probes=observed.trace(tr);gz(q/'exec-and-provider-open.gz',raw)
    exe_groups={k:[] for k in ('rustc','ld','cc','collect2','generator')}
    for pid,prog,line in exes:
        n=Path(prog).name
        if n=='rustc' and '"--crate-name"' in line:
            m=re.search(r'"--crate-name", "([^"]+)"',line)
            if m and m.group(1)!='___':exe_groups['rustc'].append([pid,m.group(1)])
        elif n in ('ld.bfd','ld','ld.lld','ld.gold','ld.mold','rust-lld','wild'):exe_groups['ld'].append([pid,prog])
        elif n in ('cc','gcc','gcc-13'):exe_groups['cc'].append([pid,prog])
        elif n=='collect2':exe_groups['collect2'].append([pid,prog])
        elif n in ('build_script_build','build-script-build') and 'ruff_unicode_names2' in prog:exe_groups['generator'].append([pid,prog])
    msgs=[json.loads(l) for l in s.splitlines() if l.startswith(b'{')]
    units=[m for m in msgs if m['reason']=='compiler-artifact']
    u={'status':rc,'typed':len(units),'dirty':[[m['target']['name'],m['target']['kind']] for m in units if not m['fresh']],'physical':exe_groups,'trace':digest(q/'exec-and-provider-open.gz'),'higher':[(p,o,t) for p,o,t in probes if str(SIDE) in t],'floor_observed':f,'error_tail':e.decode('utf-8','replace')[-1000:]}
    cs=observed.chacha_files(W,q)
    u.update(chacha=cs,command=CARGO,search=observed.search(raw,str(SIDE),str(SIDE.with_name('ld.bfd'))))
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
        assert rr==0 and std.decode().splitlines()[:2]==['Some('+str(int(m,16))+')','Some(0)'],(rr,std,err)
        u.update(reader_sha256=digest(W/'consumer'),reader=std.decode().splitlines())
        for source in [W/'consumer',*gen.glob('*.rs')]:
            archive=rec/'objects'/(digest(source)+'.gz')
            if not archive.exists():
                archive.parent.mkdir(exist_ok=True)
                archive.write_bytes(gzip.compress(source.read_bytes(),compresslevel=2,mtime=0))
    jd(q/'observation.json',u)
    print(base.name,name,rc,u.get('generate_code'),{k:len(v) for k,v in exe_groups.items()},'opened',len(u['higher']),flush=True)
    if rc and not (b'E0425' in s or 'linking' in u['error_tail'] or b'linking' in s or b'linking' in e):raise RuntimeError((rc,e[-3000:],s[-3000:]))
    return u
def main():
    global CARGO
    setup()
    for role,(src,c,h) in ROLES.items():
        temp=SDK/'bin/cargo-private-incoming';assert not temp.exists();temp.symlink_to(src);temp.replace(SDK/'bin/cargo')
        assert digest(SDK/'bin/cargo')==h
        version=subprocess.check_output([PROXY/'cargo','+ohm','-Vv'],env=ENV).decode();assert ('commit-hash: '+c+'\n') in version
        assert 'c79998a5cd143c445a4b2528f20953b176a65c5d' in subprocess.check_output([PROXY/'rustc','+ohm','-vV'],env=ENV).decode()
        CARGO=ORDINARY[:2]+(['-Zohm-defaults=no'] if role=='defaults-off' else [])+ORDINARY[2:]
        base=rec/role;base.mkdir();ledger=[]
        jd(base/'runtime.json',dict(version=version,descriptor=CFG['roles'][role],cargo=digest(SDK/'bin/cargo'),driver=observed.identity(next((SDK/'lib').glob('librustc_driver-*'))),rustc=observed.identity(SDK/'bin/rustc'),wild=observed.identity(SIDE.with_name('ld.bfd')),side=str(SIDE),command=CARGO,sha=CFG['qa']))
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
