"""One-boot price of true Wild phase exits plus separate byte and output scans on the original inputs."""
from collections import Counter
from pathlib import Path
import gzip,hashlib,importlib.util,json,os,shutil,struct,subprocess as sp,sys

def run(w,b,H,P,priv,kit,env):
    out=P/'phase-price';out.mkdir();src=Path(os.environ['GITHUB_WORKSPACE'])/'wild-source'
    def write(tag,x):b.write(out/tag,x)
    orig=H/'lookup-diagnostic.patch';patch=H/'phase-diagnostic.patch';sp.run(['git','-C',src,'apply','-R',orig],check=True)
    assert not sp.check_output(['git','-C',src,'status','--porcelain'])
    sp.run(['git','-C',src,'apply','--check',patch],check=True);sp.run(['git','-C',src,'apply',patch],check=True)
    assert sp.check_output(['git','-C',src,'diff','--name-only'],text=True).strip()=='libwild/src/lib.rs'
    buildenv=dict(env,CARGO_HOME=str(kit/'cargo-home'),CARGO_TARGET_DIR=str(kit/'target'),CARGO_BUILD_BUILD_DIR=str(kit/'shared'))
    with(out/'compile-stdout').open('wb')as so,(out/'compile-stderr').open('wb')as se:
        proc=sp.run(['cargo','+ohm','-Zohm-defaults=no','build','--release','--locked','-p','wild-linker','--bin','wild','-j4'],cwd=src,env=buildenv,stdout=so,stderr=se,timeout=1800)
    assert proc.returncode==0,(out/'compile-stderr').read_text()[-1700:]
    exe=kit/'phase';shutil.copy2(kit/'target/release/wild',exe);write('source.json',{'actor':w.hf(exe),'patch':w.hf(patch),'lib_rs':w.hf(src/'libwild/src/lib.rs'),'stock':w.hf(kit/'stock')})
    inv=json.loads(gzip.decompress((P/'current-observed/inventory.json.gz').read_bytes()))['executables']
    def args(folder):return [os.fsdecode(x)for x in (folder/'argv.nul').read_bytes().split(b'\0')[4:-1]]
    own=[priv,*sorted(priv.glob('role-*'))];assert len(own)==50
    def dest(folder):
        av=args(folder);return Path(av[av.index('-o')+1])
    own.sort(key=dest);assert len(set(map(dest,own)))==50
    def stats(path):
        s=path.stat();return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns]
    def phase(folder,mode,tag,price=True,error=False):
        rec=out/tag;rec.mkdir();av=args(folder);o=dest(folder);wire={'command':av,'actor':str(exe),'phase':mode,'private':str(folder)}
        if price:wire['clock']=[str(w.root/'whole_count'),str(rec/'hardware.json')]
        b.write(rec/'plan.json',wire)
        with(rec/'stdout').open('xb')as so,(rec/'stderr').open('xb')as se:
            proc=sp.run(['/usr/bin/python3','-IB',H/'dispatch.py',rec/'plan.json'],stdout=so,stderr=se,cwd=w.work,env=env,timeout=180)
        assert (proc.returncode!=0)==error,(tag,proc.returncode,(rec/'stderr').read_text()[-300:])
        if price:
            hw=json.loads((rec/'hardware.json').read_bytes());assert hw['status']==0 and hw['instructions']>0 and hw['enabled']==hw['running']>0,(tag,hw)
        lines=(rec/'stderr').read_text().splitlines();cut=[line.split('\t')for line in lines if line.startswith('QA_CUT\t')]
        if error or mode=='complete':assert not cut
        else:assert len(cut)==1 and cut[0][1]==mode
        return lines,cut
    stable={};roles=[];all_paths=[];e2e=None
    for ix,folder in enumerate(own):
        o=dest(folder);av=args(folder);sym,=[Path(v)for v in av if v.endswith('/symbols.o')];raw=Path(next(v[2:]for v in av if v.startswith('-L')))
        assert o.is_relative_to(w.root)and sym.parent.parent==o.parent and raw==sym.parent/'raw-dylibs'
        assert not any(v.startswith(('@','--version-script','--dynamic-list','--export-list'))for v in av)
        if folder!=priv:
            assert not sym.parent.exists();sym.parent.mkdir();shutil.copyfile(folder/'symbols.o',sym)
            if (folder/'raw-present').read_text().strip()=='1':raw.mkdir()
        assert w.hf(sym)==w.hf(folder/'symbols.o')
        orig=inv[str(o.relative_to(w.root))]['elf'];assert [o.stat().st_size,w.hf(o)]==[orig['bytes'],orig['sha256']]
        stable[str(o)]=stats(o);roles.append({'folder':str(folder),'output':str(o),'argv_sha':w.hf(folder/'argv.nul'),'output_sha':orig['sha256'],'bytes':orig['bytes'],'symbols':str(sym),'symbols_sha':w.hf(sym)})
        if folder==priv:e2e=ix
    assert e2e is not None;write('roles.json',roles)
    for i,folder in enumerate(own):
        w.guard();o=dest(folder);base=f'role-{i:02}';backup=w.root/'single-original-price-output';assert not backup.exists()
        o.rename(backup)
        try:
            phase(folder,'complete',base+'-complete');roles[i]['full_emitted_sha']=w.hf(o)
        finally:
            if o.exists():o.unlink()
            backup.rename(o)
        audit,summary=phase(folder,'audit',base+'-audit',False)
        entries=[]
        for line in audit:
            if not line.startswith('QA_INPUT\t'):continue
            _,n,h,p=line.split('\t');assert len(h)==64 and p.startswith('/')and p.isascii()and Path(p).stat().st_size==int(n)
            entries.append([p,int(n),h])
        assert len(entries)==int(summary[0][2])and sum(a[1]for a in entries)==int(summary[0][3])and roles[i]['symbols']in {a[0]for a in entries}
        all_paths.extend(x[0]for x in entries);roles[i]['input_entries']=len(entries);roles[i]['input_bytes']=sum(x[1]for x in entries);roles[i]['input_root']=summary[0][4]
        for mode in (('paths','sections','hash')if i%2==0 else ('hash','sections','paths')):
            _,cut=phase(folder,mode,base+'-'+mode)
            if mode=='hash':assert cut[0][2:]==summary[0][2:]
        assert stats(o)==stable[str(o)]and w.hf(o)==roles[i]['output_sha']
    write('roles.json',roles)
    primary=roles[e2e];assert primary['full_emitted_sha']==primary['output_sha']and primary['input_entries']==409
    for mode in ('hash','sections','paths'):phase(priv,mode,'e2e-reverse-'+mode)
    capture=P/'native-capture';sym=Path(primary['symbols']);raw=sym.parent/'raw-dylibs';made=not raw.exists()
    if made:raw.mkdir()
    prov=raw/'libutil.a';assert not prov.exists();shutil.copyfile(capture/'libutil.a',prov)
    _,healthy=phase(priv,'hash','challenge-shadow',False);st=sym.stat();shutil.copyfile(capture/'four-byte-symbols.o',sym);os.utime(sym,ns=(st.st_atime_ns,st.st_mtime_ns))
    _,bad=phase(priv,'hash','challenge-four',False);assert healthy[0][4]!=bad[0][4]and healthy[0][2:4]==bad[0][2:4]
    shutil.copyfile(capture/'symbols.o',sym);os.utime(sym,ns=(st.st_atime_ns,st.st_mtime_ns))
    prov.write_bytes(b'DELIBERATELY MALFORMED NATIVE PROVIDER\n');phase(priv,'paths','challenge-malformed-paths',False,True);phase(priv,'sections','challenge-malformed-sections',False,True)
    prov.unlink()
    if made:raw.rmdir()
    _,repair=phase(priv,'hash','challenge-repair',False);assert repair[0][4]==primary['input_root']
    assert all(stats(Path(p))==v for p,v in stable.items())
    union=sorted(set(all_paths));outputs=list(map(str,map(dest,own)));expected={p:[Path(p).stat().st_size,w.hf(Path(p))]for p in [*union,*outputs]}
    scanproj=H.parent/'native-input-union';scandir=w.root/'native-input-scan';sp.run(['cc','-O2','-Wall','-Wextra','-Werror',scanproj/'scan.c','-lcrypto','-o',scandir],check=True)
    spec=importlib.util.spec_from_file_location('old_scanner',scanproj/'measure.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.proof=out
    primary_inputs=[line.split('\t')[-1]for line in (out/f'role-{e2e:02}-audit/stderr').read_text().splitlines()if line.startswith('QA_INPUT\t')]
    for label,items,mode in [('e2e-positive',primary_inputs,'read'),('e2e-output',[str(dest(priv))],'read'),('all-occurrences',all_paths,'read'),('unique-held',union,'lease'),('all-outputs',outputs,'read'),('all-outputs-reverse',outputs,'read'),('unique-held-reverse',union,'lease'),('e2e-output-reverse',[str(dest(priv))],'read'),('e2e-positive-reverse',primary_inputs,'read')]:
        m.scan(label,items,mode,expected,env)
    source=(scanproj/'scan.c').read_text();needle='    EVP_MD_CTX *hash';assert source.count(needle)==1
    source=source.replace('int main(int argc, char **argv) {',(H/'phase-index.inc').read_text()+'\nint main(int argc, char **argv) {').replace(needle,'    input=compact_inputs(input);\n'+needle)
    cfile=w.root/'compact.c';cfile.write_text(source);compact=w.root/'native-compact-scan';sp.run(['cc','-O2','-Wall','-Wextra','-Werror',cfile,'-lcrypto','-o',compact],check=True)
    index={p:i for i,p in enumerate(union)};idxdigest=hashlib.sha256(b''.join(struct.pack('<I',index[p])for p in all_paths)).hexdigest()
    for ix in range(2):
        where=out/f'compact-held-{ix}';where.mkdir()
        with(where/'observed.txt').open('xb')as so,(where/'stderr').open('xb')as se:
            sp.run([w.root/'whole_count',where/'hardware.json',compact,compact,'lease',out/'all-occurrences/paths.nul'],env=env,stdout=so,stderr=se,check=True,timeout=240)
        hw=json.loads((where/'hardware.json').read_bytes());assert hw['instructions']>0 and hw['running']==hw['enabled']>0
        assert (where/'observed.txt').read_bytes()==(out/'unique-held/observed.txt').read_bytes()
        header=(where/'stderr').read_text().splitlines()[0].split();assert header[:4]==['QA_INDEX',str(len(all_paths)),str(len(union)),str(4*len(all_paths))]and header[5]==idxdigest
    write('gate.json',{'roles':len(roles),'primary':e2e,'exact_complete_outputs':sum(row['full_emitted_sha']==row['output_sha']for row in roles),'source_occurrences':len(all_paths),'unique':len(union),'payload_bytes_unique':sum(expected[p][0]for p in union),'output_bytes':sum(expected[p][0]for p in outputs),'index_sha256':idxdigest})
