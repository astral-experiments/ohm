"""Replay the signed green-metadata failure with earlier outputs present, observing actual files."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import json
import os
import shutil
import gzip
import zipfile
import subprocess as sp
import ron_normal_boundary as n
r=n.r;b=n.b;w=n.w;P=b.PROOF


def main():
    assert os.environ['REVIEWED_HEAD']==os.environ['GITHUB_SHA'] and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert w.git('rev-parse','HEAD')==b.NEW and w.git('rev-parse','HEAD^')==b.OLD and w.hf(w.work/'Cargo.lock')==r.LOCK and w.hf(w.src/'sdk.json')==b.SPEC['sdk_manifest']
    w.guard()
    b.write(P/'registration.json',{'head':os.environ['GITHUB_SHA'],'source':b.NEW,'sdk':b.SPEC['sdk_manifest'],'run':os.environ['GITHUB_RUN_ID'],'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'role':r.SHA,'earlier_refusal':{'run':41627562321,'digest':'5978bc1ac4c0f8afa51db130105f317147bc90a1203732f1f71bcc97ac28cb32'},'normal_output':'Preserve previous products on all successful and failing warm calls. Move the session only for an independently empty cache. All 36 original input files retained.'})
    zf=r.download();w.install()
    with zipfile.ZipFile(zf)as z:owner,rh,old=r.restore(z)
    argv=rh['replay_argv'];inc=w.root/'same-replay-session';inc.mkdir()
    output=Path(argv[argv.index('--out-dir')+1]);output.mkdir(exist_ok=True,parents=True)
    assert output==w.root/'ron-replay/private-out' and argv.count('embed-metadata=no')==1 and not any(x.startswith('incremental=') for x in argv)
    cwd=Path(owner['owner_cwd']);env=owner['owner_env']
    wrapper=w.root/'jobserver';shutil.copyfile(n.HERE/'ron_jobserver.py',wrapper);wrapper.chmod(0o700)
    count=w.root/'whole-count'
    sp.run(['cc','-O2','-Wall','-Wextra','-Werror',n.HERE/'whole_count.c','-o',count],check=True)
    result={}
    def products():
        return {p.name:{'sha256':w.hf(p),'bytes':p.stat().st_size}
                for p in output.iterdir()if p.is_file()and not p.is_symlink()}
    def physical(label,args,expected,*,trace=False,bits=None,code=None):
        dest=P/label;dest.mkdir();before=products();w.guard()
        old_objects={}
        # A successful rustc finalizes a new s-TIME-DISAMBIG directory. Retain only the
        # actual new session in the physical donor calculation; older sessions are separate.
        existing={str(p)for p in inc.glob('*/s-*')if p.is_dir()}
        for directory in existing:
            for obj in Path(directory).glob('*.o'):
                st=obj.stat();old_objects[(st.st_dev,st.st_ino)]=w.hf(obj)
        cmd=[str(wrapper),args[0],*args[1:]]
        sense=dict(env,OHM_LICENSED_RUSTC=args[0],OHM_F_JOBSERVER_PROOF=str(dest/'jobserver.json'))
        tracepath=w.root/(label+'.strace')
        if trace:cmd=['strace','-f','-q','-s','1024','-e','trace=%file','-o',str(tracepath),*cmd]
        else:
            cmd=[str(wrapper),str(count),str(dest/'counter.json'),args[0],*args]
            sense['OHM_LICENSED_RUSTC']=str(count)
        with (dest/'stdout').open('wb')as so,(dest/'stderr').open('wb')as se:
            proc=sp.run(cmd,env=sense,cwd=cwd,stdout=so,stderr=se,timeout=150)
        messages=[json.loads(l)for l in(dest/'stderr').read_bytes().splitlines()if l.startswith(b'{')]
        errs=[(j['message'],(j.get('code')or{}).get('code'),
               [(s['file_name'],s['line_start'],s['column_start'],s['column_end'])for s in j.get('spans',[])if s['is_primary']])for j in messages if j.get('level')=='error']
        artifacts=[(j['emit'],j['artifact'])for j in messages if j.get('artifact')]
        step={'argv':args,'returncode':proc.returncode,'messages':errs,'artifact_events':artifacts,'before':before,'after':products()}
        if trace:
            with tracepath.open('rb')as src,gzip.open(dest/'file-syscalls.gz','wb',compresslevel=5)as out:shutil.copyfileobj(src,out)
            rows=tracepath.read_text().splitlines()
            step['stub_syscalls']=[l for l in rows if '/stub.rmeta"'in l]
            step['full_syscalls']=[l for l in rows if '/full.rmeta"'in l or '/metadata.rmeta"'in l]
        else:
            clk=json.loads((dest/'counter.json').read_bytes());step['counter']=clk
            assert clk['status']==proc.returncode<<8 and clk['enabled']==clk['running']>0 and clk['instructions']>0
        all_files={};census=[]
        for file in inc.rglob('*'):
            if file.is_file():
                st=file.stat();all_files[st.st_dev,st.st_ino]=st.st_blocks*512
        fresh=[p for p in inc.glob('*/s-*')if p.is_dir()and str(p)not in existing and not p.name.endswith('-working')]
        for d in fresh:
            for obj in d.glob('*.o'):
                st=obj.stat();digest=w.hf(obj)
                census.append({'name':obj.name,'dev':st.st_dev,'ino':st.st_ino,'sha':digest,'prior':old_objects.get((st.st_dev,st.st_ino))==digest})
        step.update(bytes=sum(all_files.values()),files=len(all_files),new_session=[str(p)for p in fresh],new_objects=census)
        result[label]=step;b.write(P/'result.json',result)
        assert proc.returncode==expected,(label,proc.returncode,errs)
        if bits is not None:
            # Preserve the original jobserver interface for the unmetered typed consumer too.
            exe=w.root/'buyer';source=w.root/'buyer.rs';source.write_text('fn main(){let e=ron::extensions::Extensions::from_ident("implicit_some").unwrap();println!("{} {}",e.bits(),ron::ser::to_string(&e.bits()).unwrap());}\n')
            lib,=output.glob('*.rlib');args2=[args[0],str(source),'--edition=2021','--extern','ron='+str(lib),'--extern','ron='+str(lib.with_suffix('.rmeta')),'-L','dependency='+str(output),'-o',str(exe)]
            for i,a in enumerate(args):
                if a=='-L':args2+=['-L',args[i+1]]
            if exe.exists():exe.unlink()
            with(dest/'typed-stderr').open('wb')as se:
                sp.run([wrapper,*args2],cwd=cwd,env=dict(sense,OHM_LICENSED_RUSTC=args[0],OHM_F_JOBSERVER_PROOF=str(dest/'consumer-jobserver.json')),stderr=se,check=True)
            witness=sp.check_output([exe],env=env,text=True);(dest/'typed-stdout').write_text(witness)
            assert witness==f'{bits} {bits}\n',witness
            step['typed_executable_sha']=w.hf(exe)
        if code:
            assert any(c==code for _,c,_ in errs)and all(t!='link'for t,_ in artifacts)
        b.write(P/'result.json',result);return step
    def fresh_session(label):
        assert inc.is_dir();inc.rename(w.root/label);inc.mkdir()
    original=physical('original-native',argv,0,bits=2)
    lib,=[v for k,v in original['after'].items()if k.endswith('.rlib')]
    assert lib['sha256']==old['rlib_replayed']
    a=argv+['-C','incremental='+str(inc)]
    t=physical('split-fresh',a,0,trace=True,bits=2)
    assert any('open'in l and 'O_CREAT'in l and 'ENOENT'not in l for l in t['stub_syscalls'])
    fail=physical('split-warm-prior-products-present',a,1,trace=True)
    assert fail['before']==t['after']and any(x.startswith('failed to create encoded metadata from file: No such file or directory')for x,_,_ in fail['messages'])
    assert any('open'in l and 'O_RDONLY'in l and 'ENOENT'in l for l in fail['stub_syscalls'])and not any('O_CREAT'in l for l in fail['stub_syscalls'])
    assert all(t!='link' for t,_ in fail['artifact_events'])
    fresh_session('split-history');physical('split-independent-cold-repair',a,0,trace=True,bits=2)
    # The only flag changed in this separate diagnostic is embedding the full metadata.
    # Stock Ohm deliberately enables the split form only for non-path deps by default.
    fresh_session('split-fresh-reference')
    full=[x if x!='embed-metadata=no'else 'embed-metadata=yes'for x in a]
    assert sum(x!=y for x,y in zip(full,a))==1
    train=physical('embedded-training',full,0,bits=2)
    for name in ('embedded-warm-1','embedded-warm-2'):physical(name,full,0,bits=2)
    dso,=[Path(v.split('=',1)[1])for i,v in enumerate(argv)if i and argv[i-1]=='--extern'and v.startswith('serde_derive=')]
    good=dso.read_bytes();bad,auth=n.corrupt(good)
    assert auth['normal']==r.DSO and auth['malformed']=='d10101784698b81eec63d9994e59590a3c4596f0861a46f8ee7ccf41718b5d14'
    n.replace(dso,bad,good)
    try:
        fail=physical('embedded-malformed-native',full,1,code='E0782')
        assert any(c=='E0782'and any(f.endswith('bitflags-2.13.2/src/public.rs')and(l,p,e)==(17,37,98)for f,l,p,e in spans)for _,c,spans in fail['messages'])
    finally:n.replace(dso,good,bad)
    physical('embedded-repaired-native',full,0,bits=2)
    source=cwd/'src/extensions.rs';good=source.read_bytes();line=b'return Some(extension);'
    assert good.count(line)==1;new=good.replace(line,b'return Some(Extensions::UNWRAP_NEWTYPES);')
    n.replace(source,new,good)
    try:
        physical('embedded-source-edit',full,0,bits=1)
        invalid=new+b'\nconst _: u8 = "checked source";\n';n.replace(source,invalid,new)
        try:physical('embedded-invalid-rust',full,1,code='E0308')
        finally:n.replace(source,new,invalid)
        physical('embedded-source-repair',full,0,bits=1)
        fresh_session('embedded-history');physical('embedded-independent-clean-edit',full,0,bits=1)
    finally:n.replace(source,good,new)
    physical('embedded-original-repair',full,0,bits=2)
    assert not w.git('status','--porcelain')and sum(p.stat().st_size for p in P.rglob('*')if p.is_file())<35*2**20


if __name__=='__main__':main()
