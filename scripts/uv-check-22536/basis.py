"""Original-input gates and transparent Linux process inventory for the held uv session."""
from pathlib import Path
from collections import Counter
import gzip,hashlib,json,os,re,runpy,shutil,subprocess,tarfile,tomllib
HERE=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_bytes())
def digest(data):return hashlib.sha256(data).hexdigest()
def filehash(p):
    with Path(p).open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def canon(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def write(p,z):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb')as f:f.write(canon(z)+b'\n')
def writez(p,z):
    with Path(p).open('xb')as f:f.write(gzip.compress(canon(z),compresslevel=2,mtime=0))
def readz(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
PLAN=read(HERE/'protocol.json');CASE=read(HERE/'case.json');KIT=read(HERE/'instruments.json');LOCK=readz(HERE/'production-inputs.json.gz')
assert filehash(HERE/'protocol.json')==CASE['protocol']=='8ce5b388b9e5ca2a3543abbdf572aff97bf4a7958aa0be69813978d330eaf803'
assert filehash(HERE/'production-inputs.json.gz')==CASE['role_authority']and all(filehash(HERE/'kit'/n)==z['sha256']for n,z in KIT.items())
SIX=PLAN['six'];WORKSPACE={r['crate']:r['source']for r in CASE['expected']['A']['workspace']};assert len(WORKSPACE)==38 and len(SIX)==6
WUNITS=set(WORKSPACE)|set(read(HERE/'full-surfaces.json')['additional_linked_workspace_metadata']);assert len(WUNITS)==39
def collector():
    path=HERE/'kit/exec_events.py';src=path.read_text();assert src.count('len(rows)<20000')==1
    gl={'__file__':str(path),'__name__':'records_for_large_unmodified_cold_command'};exec(compile(src.replace('len(rows)<20000','len(rows)<200000'),str(path),'exec'),gl);return gl
EVENTS=collector()
def sdk_inventory(role,sdk,exact=True):
    sdk=Path(sdk).resolve(strict=True);expect=LOCK['roles'][role]['runtime'];assert len(expect)==142
    for n,r in expect.items():
        x=sdk/n;assert not x.is_symlink() and x.is_file() and x.stat().st_size==r['bytes']and bool(x.stat().st_mode&0o111)==bool(r['mode']&0o111) and filehash(x)==r['sha256'],(role,n)
    if exact:assert {str(f.relative_to(sdk))for f in sdk.rglob('*')if f.is_file()or f.is_symlink()}==expect.keys()
    else:assert role=='R','only the original, fully installed signed distribution may contain additional official components during local unscored qualification'
    return {'source':LOCK['roles'][role]['source'],'runtime_sha256':LOCK['roles'][role]['hash'],'signed_cargo':expect['bin/cargo']['sha256'],'members':len(expect),'core_only':exact,'rustc_kernel_identity':EVENTS['file_id'](sdk/'bin/rustc'),'cargo_kernel_identity':EVENTS['file_id'](sdk/'bin/cargo')}
def registry(home,src):
    pk=[z for z in tomllib.loads((src/'Cargo.lock').read_text())['package']if z.get('source')];assert len(pk)==654 and all(z['source']=='registry+https://github.com/rust-lang/crates.io-index'for z in pk)
    cache,=[f for f in (home/'registry/cache').iterdir()if all((f/(z['name']+'-'+z['version']+'.crate')).is_file()for z in pk)]
    for z in pk:assert filehash(cache/(z['name']+'-'+z['version']+'.crate'))==z['checksum'],z['name']
    return {'locked':len(pk),'index_dir':cache.name,'package_name_version_archive_sha256':digest(canon(sorted((z['name'],z['version'],z['checksum'])for z in pk)))}
class Env:
    def __init__(self,cfg):
        self.inp=cfg;self.root=Path(cfg['root']).resolve();self.target=self.root/'target';self.src=self.root/'uv';self.cargo=self.root/'cargo';self.sdk=self.root/'sdk';self.bin=self.sdk/'bin/rustc';self.results=Path(cfg['results']).resolve();self.bank=self.root/'banks';self.cas=self.root/'products';self.bin_dir=self.root/'tools'
        self.env={'HOME':str(self.root/'home'),'CARGO_HOME':str(self.cargo),'CARGO_TARGET_DIR':str(self.target),'TMPDIR':str(self.root/'tmp'),'PATH':str(self.sdk/'bin')+':/usr/bin:/bin','RUSTC':str(self.bin),'RUSTDOC':str(self.sdk/'bin/rustdoc'),'LC_ALL':'C.UTF-8','GIT_ALLOW_PROTOCOL':'file','GIT_NO_LAZY_FETCH':'1','GIT_TERMINAL_PROMPT':'0','GIT_CONFIG_GLOBAL':'/dev/null','SSL_CERT_DIR':'/usr/lib/ssl/certs','SSL_CERT_FILE':'/usr/lib/ssl/cert.pem'}
        self.argv=[str(self.sdk/'bin/cargo'),*PLAN['command'][1:]]
    def git(self,*v):return subprocess.check_output(['git','-C',self.src,*v],env=self.env).decode().strip()
    def source(self,state):
        ref=CASE['states'][state];assert not self.git('status','--porcelain','--untracked-files=all')
        if self.git('rev-parse','HEAD')!=ref['source']:self.git('checkout','-q','--detach',ref['source'])
        assert self.git('rev-parse','HEAD')==ref['source']and self.git('rev-parse','HEAD^{tree}')==ref['tree']and not self.git('status','--porcelain','--untracked-files=all') and filehash(self.src/'Cargo.lock')==CASE['lock']
        return ref['source']
    def choose(self,role):
        src=Path(self.inp['sdks'][role]).resolve(strict=True);tmp=self.root/'new-sdk-view';assert not tmp.exists()and not tmp.is_symlink() and (not self.sdk.exists()or self.sdk.is_symlink())
        tmp.symlink_to(src,target_is_directory=True);tmp.replace(self.sdk);assert self.sdk.resolve()==src and filehash(self.sdk/'bin/cargo')==PLAN['control']['signed_22_cargo']
    def reset(self):
        assert self.target.parent==self.root and self.target.name=='target'and not self.target.is_symlink()
        if self.target.exists():shutil.rmtree(self.target)
        self.target.mkdir()
    def close(self):assert not self.git('status','--porcelain','--untracked-files=all')
def setup(e):
    assert e.root.is_dir()and not any(e.root.iterdir())and e.results.is_dir()and not any(e.results.iterdir()) and e.inp['control_candidate_source_inputs']==CASE['role_authority']
    for p in (e.target,e.src,e.bank,e.cas,e.bin_dir,e.root/'home',e.root/'tmp'):p.mkdir()
    subprocess.run(['git','init','-q',e.src],check=True);d=Path(e.inp['source_donor']).resolve();obj=Path(subprocess.check_output(['git','-C',d,'rev-parse','--path-format=absolute','--git-path','objects'],text=True).strip())
    assert obj.is_dir();(e.src/'.git/objects/info/alternates').write_text(str(obj)+'\n');e.git('remote','add','origin','https://github.com/astral-sh/uv.git');e.git('checkout','-q','--detach',CASE['states']['A']['source'])
    for n in 'ABCD':e.source(n)
    if e.inp.get('require_source_tag'):
        tag='7456b60bc6bc348e13e06e3691bf08e78d3aef54';assert subprocess.check_output(['git','-C',d,'rev-parse','refs/tags/0.13.4^{}'],text=True).strip()==tag
        e.git('update-ref','refs/tags/0.13.4',tag);assert e.git('describe','--tags','--match','0.13.4','--long',CASE['states']['A']['source']).startswith('0.13.4-21-g')
    e.source('A');upstream=Path(e.inp['cargo_home']).resolve();assert not e.cargo.exists();e.cargo.mkdir();(e.cargo/'registry').mkdir()
    for n in ('index','cache'):shutil.copytree(upstream/'registry'/n,e.cargo/'registry'/n)
    data=registry(e.cargo,e.src);write(e.results/'source-registry.json',dict(states=CASE['states'],registry=data,lock=CASE['lock']));assert not (e.cargo/'registry/src').exists()
    actual={r:sdk_inventory(r,sdk,exact=not(e.inp.get('local_full_signed')and r=='R'))for r,sdk in e.inp['sdks'].items()}
    assert set(actual)=={'R','S','F'};write(e.results/'actual-inputs.json',actual)
def option(a,k):
    v=[a[i+1]for i,t in enumerate(a[:-1])if t==k]+[t[len(k)+1:]for t in a if t.startswith(k+'=')];assert len(v)<=1;return v[0]if v else None
def shape(a):
    # Only Cargo's 16-hex unit/file hashes are incidental to the compiler choice.
    return [re.sub(r'(?<=[=/-])[0-9a-f]{16}(?=$|/|\.(?:so|rlib|rmeta|d)$)','<cargo-ID>',arg)for arg in a]
def receive(e,t,ob,policy):
    cf=EVENTS['file_id'](e.sdk/'bin/cargo');rf=EVENTS['file_id'](e.bin);im=t['images'];r=t['root'];raw={}
    assert im[0]['file']==cf and im[0]['argv']==e.argv and t['exits'][r]==0
    by={z['pid']:z for z in im};units=[];nonunits=[];sources={}
    for z in im[1:]:
        a=z.get('argv',[]);pid=z['pid']
        if z['file']!=rf:
            assert Path(z['exe']).name!='rustc' and not(a and Path(a[0]).name=='rustc');continue
        assert Path(z['exe']).samefile(e.bin)and Path(a[0]).samefile(e.bin)and pid in ob
        par=t['births'][pid]
        while par not in by:par=t['births'][par]
        n=option(a,'--crate-name');od=option(a,'--out-dir');emit=option(a,'--emit');stop=t['exits'][pid]
        if par==r:
            assert stop==0
            if not emit:
                assert a[1:]==['-vV']or any(x=='--print'or x.startswith('--print=')for x in a);nonunits.append([pid,'Cargo identification',stop]);continue
            assert n and od and Path(od).is_relative_to(e.target);units.append([n,pid,par]);raw.setdefault(n,[]).append(a)
            files=[v for v in a if v.endswith('.rs') and v.startswith('crates/')]
            if files and option(a,'--crate-type')=='lib'and n in WORKSPACE:
                assert len(files)==1 and files[0]==WORKSPACE[n];suffix,=[x.split('=',1)[1]for x in a if x.startswith('extra-filename=')];lib=Path(od)/('lib'+n+suffix+'.rmeta');assert lib.is_file()
                key=n+'@rlib' if 'link' in emit.split(',') else n;assert key not in sources and ((key==n) or lib.with_suffix('.rlib').exists());sources[key]=str(lib.relative_to(e.target))
        else:
            parent=Path(by[par]['exe']);assert parent.name=='build_script_build'and parent.is_relative_to(e.target/'debug/build')
            if emit:assert emit in ('metadata','dep-info,metadata','llvm-ir')and stop in(0,1)and (od or option(a,'-o'));nonunits.append([pid,'Cargo build-script feature compilation',stop])
            else:assert '--version'in a or '-vV'in a or any(x.startswith('--print')for x in a);nonunits.append([pid,'Cargo build-script identification',stop])
    if policy=='cold':assert len(units)==497 and len(nonunits)==45 and set(sources)==WUNITS and dict(Counter(x[1]for x in nonunits))==CASE['expected']['A']['other'],(len(units),len(nonunits),sorted(sources))
    elif policy=='edited':assert sorted(raw)==SIX and set(sources)==set(SIX)and len(units)==6 and not nonunits and all(len(v)==1 for v in raw.values())
    elif policy=='unchanged':assert not units and not nonunits
    else:raise ValueError(policy)
    return {'root':r,'all_units':units,'all_other_rustcs':nonunits,'forms':raw,'workspace_rmeta_from_argv':sources}
def kernel(e,out,policy):
    out.mkdir();cwd={};fid=EVENTS['file_id'](e.bin)
    def child(pid,last,s):
        if s['file']==fid:cwd[pid]=os.readlink('/proc/'+str(pid)+'/cwd')
    EVENTS['capture'](out,e.argv,e.env,str(e.src),fid,child);data=read(out/'kernel-events.json');rec=receive(e,EVENTS['decode'](data),cwd,policy)
    assert b'Finished 'in(out/'stderr').read_bytes()and not(out/'stdout').stat().st_size
    writez(out/'kernel.json.gz',data);(out/'kernel-events.json').unlink();writez(out/'argv.json.gz',rec);writez(out/'cwd.json.gz',cwd);return rec
