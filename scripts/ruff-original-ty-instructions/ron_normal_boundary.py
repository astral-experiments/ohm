"""Price a genuine producer boundary and the stock incremental compiler on its authenticated native role."""
from pathlib import Path
import collections
import json
import os
import re
import shutil
import struct
import subprocess as sp
import sys
import zipfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import ron_full_input as r
import workspace29697 as b
from ron_native_guard import corrupt
from ron_causality import replace
w=b.w; P=b.PROOF
SITES={
    'analysis_complete':[0x7c5d080,0x6e96b80],
    'backend_entry':[0x7c5e352,0x7327d00,0x6e99a84],
    'derive':[0x78ae986,0x6525f80],
}
ENTRIES={'analysis_complete':0x6e96b80,'backend_entry':0x6e99a84,'derive':0x6525f80}
NAMES={'analysis_complete':'<rustc_interface::queries::Linker>::codegen_and_build_linker','backend_entry':'<rustc_codegen_llvm::LlvmCodegenBackend as rustc_codegen_ssa::traits::backend::CodegenBackend>::codegen_crate','derive':'rustc_expand::proc_macro::expand_derive_macro'}


def enroll(image):
    parsed=collections.defaultdict(set)
    nm=sp.Popen(['nm','-anS','-C',image],stdout=sp.PIPE,text=True)
    for line in nm.stdout:
        f=line.rstrip().split(maxsplit=3)
        if len(f)==4 and f[2]in ('t','T'):
            name=re.sub(r'\[[0-9a-f]{16}\]','',f[3])
            for key,n in NAMES.items():
                if name==n:parsed[key].add(int(f[0],16))
    assert nm.wait()==0 and all(set(v)==parsed[k]for k,v in SITES.items()),str(parsed)
    with image.open('rb')as so:
        h=so.read(64);off=struct.unpack_from('<Q',h,32)[0];ent,n=struct.unpack_from('<HH',h,54)
        segments=[]
        for i in range(n):
            so.seek(off+i*ent);kind,flags,at,va,_,size,_,_=struct.unpack('<IIQQQQQQ',so.read(56))
            if kind==1 and flags&1:segments.append((at,va,size))
        pre={}
        for s in sum(SITES.values(),[]):
            at,=[p+s-v for p,v,z in segments if v<=s and s+12<=v+z];so.seek(at);pre[str(s)]=so.read(12).hex()
    assert all(a in SITES[k] and pre[str(a)].startswith('55415741564155415453')for k,a in ENTRIES.items())
    return pre


def clean_output(argv):
    out=Path(argv[argv.index('--out-dir')+1]);assert out==w.root/'ron-replay/private-out'
    out.mkdir(exist_ok=True,parents=True)
    for p in out.iterdir():
        assert p.is_file()and not p.is_symlink();p.unlink()
    return out


def native(rundir,argv,env,bits):
    out=Path(argv[argv.index('--out-dir')+1]);rs=w.root/'consumer.rs';exe=w.root/'consumer'
    rs.write_text('fn main() { let v=ron::extensions::Extensions::from_ident("implicit_some").unwrap(); println!("bits={} rendered={}",v.bits(),ron::ser::to_string(&v.bits()).unwrap()); }\n')
    lib,=out.glob('libron-*.rlib')
    cmd=[argv[0],str(rs),'--edition=2021','--crate-name','actual_ron_user','--extern','ron='+str(lib),'--extern','ron='+str(lib.with_suffix('.rmeta')),'-L','dependency='+str(out),'-o',str(exe)]
    for i,a in enumerate(argv):
        if a=='-L':cmd+=['-L',argv[i+1]]
    if exe.exists():exe.unlink()
    with (rundir/'consumer-stderr').open('wb')as se:cp=sp.run(cmd,cwd=w.root,env=env,stdout=se,stderr=se,timeout=60)
    assert cp.returncode==0,(rundir/'consumer-stderr').read_text()[-1000:]
    value=sp.check_output([exe],env=env,text=True)
    assert value==f'bits={bits} rendered={bits}\n',value
    return value.strip()


def work_product_graph(session):
    # Count physical regular files once, including non-object state carried by the mechanism.
    seen={};objects={}
    for f in session.rglob('*'):
        if f.is_file():
            s=f.stat();i=(s.st_dev,s.st_ino)
            if i not in seen:seen[i]=s.st_blocks*512
            if f.suffix=='.o':objects[f.name]=[s.st_dev,s.st_ino,w.hf(f)]
    return {'bytes':sum(seen.values()),'physical_files':len(seen),'objects':objects}


def main():
    assert os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD']and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert w.hf(w.src/'sdk.json')==b.SPEC['sdk_manifest']and w.git('rev-parse','HEAD')==b.NEW and w.git('rev-parse','HEAD^')==b.OLD and w.hf(w.work/'Cargo.lock')==r.LOCK
    w.guard()
    b.write(P/'registration.json',{'previous':r.PRIOR,'previous_sha':r.SHA,'source':b.NEW,'sdk':b.SPEC['sdk_manifest'],'driver':r.DRIVER,'head':os.environ['GITHUB_SHA'],'run':os.environ['GITHUB_RUN_ID'],'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'order':['full','analysis_complete','backend_entry','backend_entry','analysis_complete','full'],'sites':SITES,'source_symbols':NAMES,'scope':'A deliberately terminated normal compiler at each native frontier has no success verdict. Two-thread 4:1 calibration, signed complete replicas, and real derived diagnostics/caller. The stock -Cincremental mechanism executes all derives but creates additional retained disk state and can choose different default CGUs. No Cargo savings claim.'})
    f=r.download();baseenv=w.install()
    with zipfile.ZipFile(f)as z:owner,rh,old=r.restore(z)
    argv=rh['replay_argv'];image,=(w.sdk/'lib').glob('librustc_driver*.so')
    assert w.hf(image)==r.DRIVER and not any(x.startswith('incremental=')for x in argv)
    pre=enroll(image);b.write(P/'symbols.json',dict(names=NAMES,addresses=SITES,preimages=pre))
    wrapper=w.root/'jobserver';shutil.copyfile(HERE/'ron_jobserver.py',wrapper);wrapper.chmod(0o700)
    shared=w.root/'counter.so';cal=w.root/'two-workers';whole=w.root/'whole_count'
    for source,cmd in [('ron_counter.c',['-shared','-fPIC','-o',shared]),('ron_counter_calibration.c',['-pthread','-o',cal]),('whole_count.c',['-o',whole])]:
        sp.run(['cc','-O2','-Wall','-Wextra','-Werror',HERE/source,*cmd],check=True)
    common=dict(owner['owner_env']);cwd=Path(owner['owner_cwd'])
    data={}
    def gdb_round(label,program,frontier=None,do_cal=False):
        dest=P/label;dest.mkdir();env=dict(baseenv)if do_cal else dict(common)
        policy={'argv':program,'frontier':frontier,'driver':None if do_cal else str(image),'preimages':pre,'addresses':{k:[v]for k,v in ENTRIES.items()},'counter':str(shared)}
        b.write(dest/'plan.json',policy)
        env['OHM_ROUND']=str(dest)
        prefix=''
        if not do_cal:
            env.update(OHM_LICENSED_RUSTC=program[0],OHM_F_JOBSERVER_PROOF=str(dest/'jobserver.json'));prefix='set exec-wrapper '+str(wrapper)+'\n'
        script=dest/'run.gdb';probe=HERE/'ron_phase_probe.py'
        script.write_text('set confirm off\nset python print-stack full\nset pagination off\nset disable-randomization off\nset startup-with-shell on\n'+prefix+'set debuginfod enabled off\nset auto-load off\nset auto-solib-add off\nset print thread-events off\nhandle SIGUSR1 nostop noprint pass\nstart\npython\nexec(compile(open('+repr(str(probe))+').read(),'+repr(str(probe))+',"exec"))\nend\ncontinue\npython finish()\n')
        if not do_cal:o=clean_output(program)
        w.guard()
        with (dest/'stdout').open('wb')as so,(dest/'stderr').open('wb')as se:
            cp=sp.run(['gdb','-q','-nx','-nh','-batch','-x',script,'--args',*program],cwd=cwd,env=env,stdout=so,stderr=se,timeout=180)
        assert cp.returncode==0,(dest/'stderr').read_text()[-1000:]
        q=json.loads((dest/'counter.json').read_bytes())
        if do_cal:
            n=int(program[-1]);assert f'two actual workers {8*n}'in (dest/'stdout').read_text()
            assert 8*n <= q['retired_user']<8*n+350000,q
        else:
            q['products']={p.name:w.hf(p)for p in o.iterdir()if p.is_file()}
            assert (b'ohm-foreign-span-bytes' in next(o.glob('*.d')).read_bytes()) and any(k=='derive'for k,_,_ in q['events'])
            if not frontier:
                lib,=o.glob('*.rlib');assert w.hf(lib)==old['rlib_replayed']
                q['native']=native(dest,program,common,2)
            else:assert not list(o.glob('*.rlib'))
        data[label]=q;b.write(P/'results.json',data);return q['retired_user']
    v=[gdb_round('cal-'+str(i),[str(cal),str(i)],do_cal=True)for i in(1000000,4000000)]
    assert 3.90<v[1]/v[0]<4.02,v
    order=[None,'analysis_complete','backend_entry','backend_entry','analysis_complete',None]
    for i,frontier in enumerate(order):gdb_round('normal-'+str(i),argv,frontier)
    session=w.root/'one-session';session.mkdir()
    pins=w.root/'pinned-donors';pins.mkdir()
    def regular(label,args,code,check_bits=None):
        dest=P/label;dest.mkdir();o=clean_output(args);w.guard()
        cmd=[str(wrapper),str(whole),str(dest/'counter.json'),args[0],*args]
        env=dict(common,OHM_LICENSED_RUSTC=str(whole),OHM_F_JOBSERVER_PROOF=str(dest/'jobserver.json'))
        with (dest/'stdout').open('wb')as so,(dest/'stderr').open('wb')as se:
            cp=sp.run(cmd,cwd=cwd,env=env,stdout=so,stderr=se,timeout=180)
        cov=json.loads((dest/'counter.json').read_bytes())
        assert cp.returncode==code and cov['status']==code<<8 and cov['instructions']>0 and cov['enabled']==cov['running']>0
        q={'count':cov,'products':{p.name:w.hf(p)for p in o.iterdir()if p.is_file()},'disk':work_product_graph(session),'errors':[]}
        for l in(dest/'stderr').read_bytes().splitlines():
            if l.startswith(b'{'):
                m=json.loads(l)
                if m.get('level')=='error'and m.get('code'):q['errors'].extend([[m['code']['code'],s['file_name'],s['column_start'],s['column_end']]for s in m['spans']if s['is_primary']])
        if check_bits is not None:q['native']=native(dest,args,common,check_bits)
        if code:assert not list(o.glob('*.rlib'))and q['errors']
        data[label]=q;b.write(P/'results.json',data);return q
    normal=regular('raw-normal',argv,0,2)
    for i in (0,5):
        a=normal['count']['instructions'];c=data['normal-'+str(i)]['retired_user']
        assert abs(a-c)<min(a,c)*.02,(a,c)
    av=[*argv,'-C','incremental='+str(session)]
    train=regular('inc-training',av,0,2)
    assert train['disk']['objects']
    for f in session.rglob('*.o'):
        target=pins/(str(f.stat().st_dev)+'-'+str(f.stat().st_ino))
        if not target.exists():os.link(f,target)
    for nm in ('inc-first','inc-second'):
        q=regular(nm,av,0,2)
        prior={(v[0],v[1],v[2])for v in train['disk']['objects'].values()}
        q['old_physical_native_donors']=sum(tuple(v)in prior for v in q['disk']['objects'].values())
        b.write(P/'results.json',data)
    dso,=[Path(v.split('=',1)[1])for i,v in enumerate(av)if i and av[i-1]=='--extern'and v.startswith('serde_derive=')]
    good=dso.read_bytes();bad,auth=corrupt(good)
    assert auth['normal']==r.DSO and auth['malformed']=='d10101784698b81eec63d9994e59590a3c4596f0861a46f8ee7ccf41718b5d14'
    replace(dso,bad,good)
    try:
        fail=regular('inc-malformed-native',av,1)
        assert any(code=='E0782'and fn.endswith('bitflags-2.13.2/src/public.rs')and(c,e)==(37,98) for code,fn,c,e in fail['errors'])
    finally:replace(dso,good,bad)
    source=cwd/'src/extensions.rs';pristine=source.read_bytes();s=source.stat()
    line=b'return Some(extension);';assert pristine.count(line)==1
    native_edit=pristine.replace(line,b'return Some(Extensions::UNWRAP_NEWTYPES);')
    replace(source,native_edit,pristine)
    try:
        regular('inc-native-source-edit',av,0,1)
        invalid=native_edit+b'\nconst _: u8 = "ron-boundary-type-error";\n'
        replace(source,invalid,native_edit)
        fail=regular('inc-invalid-rust',av,1);assert any(z[0]=='E0308'for z in fail['errors'])
        replace(source,native_edit,invalid);regular('inc-source-repair',av,0,1)
        moved=w.root/'completed-session';session.rename(moved);session.mkdir()
        regular('empty-edited-reference',av,0,1)
    finally:
        source.write_bytes(pristine);os.utime(source,ns=(s.st_atime_ns,s.st_mtime_ns))
    regular('inc-pristine-repair',av,0,2)
    assert not w.git('status','--porcelain')and sum(p.stat().st_size for p in P.rglob('*')if p.is_file())<35*2**20

if __name__=='__main__':main()
