from pathlib import Path
import gzip,hashlib,json,os,re,shutil,signal,stat,subprocess,time,traceback
import argparse
ap=argparse.ArgumentParser(description="Reproduce the first edited check with a literal rmeta input and two authentic rustc SDKs.")
ap.add_argument("--work",type=Path,required=True,help="New, previously absent private working directory, on a volume with 15 GiB free.")
ap.add_argument("--parent-sdk",type=Path,required=True)
ap.add_argument("--candidate-sdk",type=Path,required=True)
ap.add_argument("--cargo",type=Path,help="Optional real corrected Cargo executable; default is the shipped Cargo inside both authenticated SDKs.")
ap.add_argument("--cargo-sha256",help="Required SHA256 of the alternative Cargo.")
ap.add_argument("--b3sum",type=Path,required=True)
ap.add_argument("--expect",choices=["legacy","aware"],required=True)
ap.add_argument("--registry-outputs",action="store_true",help="Place actual target and build directories below this new private cargo-home/registry.")
ap.add_argument("--registration",type=Path,required=True,help="Source- and SDK-bound pre-observation registration for this cell.")
args=ap.parse_args()
ops=Path(__file__).resolve().parent;B=args.work.resolve();B.mkdir(mode=0o700,parents=False,exist_ok=False)
R=json.loads(args.registration.read_bytes())
B3=args.b3sum.resolve(strict=True)
assert bool(args.cargo)==bool(args.cargo_sha256)
if args.cargo:
    args.cargo=args.cargo.resolve(strict=True);assert hashlib.sha256(args.cargo.read_bytes()).hexdigest()==args.cargo_sha256
else:assert args.expect=="legacy"
assert not args.registry_outputs or args.expect=="aware"
real={"P":args.parent_sdk.resolve(strict=True),"C":args.candidate_sdk.resolve(strict=True)}
active_cargo=args.cargo_sha256 or R["cargo"]
R["actual_native_cargo"]=active_cargo;R["expected_contract"]=args.expect;R["registry_outputs"]=args.registry_outputs
assert active_cargo==(R["aware_cargo_sha256"] if args.expect=="aware" else R["cargo"])
output_parent=B/"cargo-home/registry/private-capability" if args.registry_outputs else B
outputs={name:output_parent/name for name in ("target","shared")}
(B/"registration.json").write_text(json.dumps(R,sort_keys=True,indent=1)+chr(10))
COMPILER={}
for role,donor in real.items():
    assert hashlib.sha256((donor/"bin/cargo").read_bytes()).hexdigest()==R["cargo"]
    view=B/"role-sdk"/role;view.mkdir(parents=True)
    (view/"bin").mkdir()
    for x in donor.iterdir():
        if x.name!="bin":(view/x.name).symlink_to(x)
    for x in (donor/"bin").iterdir():
        (view/"bin"/x.name).symlink_to(args.cargo if args.cargo and x.name=="cargo" else x)
    COMPILER[role]=view
obs=B/'out';obs.mkdir()
def save(path,body):path.write_text(json.dumps(body,sort_keys=True,indent=1)+'\n')
def sha(p):
 with p.open('rb')as inp:return hashlib.file_digest(inp,'sha256').hexdigest()
def write(p,s):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(s)
def bytesha(data):return hashlib.sha256(data).hexdigest()
def fnv(b):
 v=14695981039346656037
 for c in b:v=((v^c)*1099511628211)&0xffffffffffffffff
 return v
def available():return int(re.search(r'^MemAvailable:\s+(\d+)',Path('/proc/meminfo').read_text(),re.M)[1])*1024
def admit():
 start=time.monotonic()
 while available()<(8<<30)+(256<<20):
  if time.monotonic()-start>900:raise ValueError('entry floor, no process started')
  time.sleep(4)
 assert shutil.disk_usage(B).free>15<<30

w=B/'workspace';w.mkdir()
write(w/'Cargo.toml','[workspace]\nmembers = ["dep", "app"]\nresolver = "3"\n')
write(w/'dep/Cargo.toml','[package]\nname="dep"\nversion="0.0.0"\nedition="2024"\n')
write(w/'app/Cargo.toml','[package]\nname="app"\nversion="0.0.0"\nedition="2024"\n[dependencies]\ndep={path="../dep"}\n')
write(w/'Cargo.lock','version = 4\n\n[[package]]\nname = "app"\nversion = "0.0.0"\ndependencies = ["dep"]\n\n[[package]]\nname = "dep"\nversion = "0.0.0"\n')
hidden='pub(super) fn classify(value: u8) -> bool { value == 0 }\n#[derive(Clone, Copy, Debug, PartialEq, Eq)]\npub(super) enum Hidden { Value(u8) }\n'
moved=hidden.replace('value == 0 }\n','value == 1 }\n\n')
interface='#![allow(dead_code)]\nmod hidden;\npub fn visible() -> impl std::fmt::Debug { 7u8 }\n#[macro_export]\nmacro_rules! observed { () => { $crate::visible() }; }\n'
base='fn needs_send<T: Send>(_: T) {}\nfn main() { needs_send(dep::observed!()); }\n'
template='''const fn byte_hash(bytes: &[u8]) -> u64 {
    let mut hash = 14695981039346656037u64;
    let mut i = 0;
    while i < bytes.len() { hash = (hash ^ bytes[i] as u64).wrapping_mul(1099511628211); i += 1; }
    hash
}
const ACTUAL_INPUT: &[u8] = include_bytes!(r#"@RUST_METADATA@"#);
const _: [(); 1] = [(); (byte_hash(ACTUAL_INPUT) == @OLD_FNV@u64) as usize];
'''
write(w/'dep/src/lib.rs',interface)
# The source snippets must be the exact Rust factory control, rather than recreating an analogue.
factory=ops/"fixture/source.json"
frozen=json.loads(factory.read_bytes())["files"]
for n,body in (("dep-lib.rs",interface),("dep-hidden-old.rs",hidden),("dep-hidden-edited.rs",moved),("app-main.rs",base),("literal-template.rs",template)):
    assert (ops/"fixture"/n).read_bytes()==body.encode() and bytesha(body.encode())==frozen[n]
ru=B/'rustup';(ru/'toolchains').mkdir(parents=True);write(ru/'settings.toml','version="12"\nprofile="minimal"\n')
alias=ru/'toolchains/ohm';proxy=Path(shutil.which('rustup')).resolve()
proxies=B/'proxies';proxies.mkdir()
for cmd in ('cargo','rustc','rustdoc','rustup'):(proxies/cmd).symlink_to(proxy)
save(obs/'enrollment.json',dict(plan=sha(B/'registration.json'),runner=sha(Path(__file__)),factory_guard=sha(factory),b3sum=sha(B3),rustup=sha(proxy),provider=bytesha(interface.encode()),old=bytesha(hidden.encode()),edited=bytesha(moved.encode()),consumer=bytesha(template.encode()),path= str(w)))
def stamp(f):
 st=f.stat();return dict(path=str(f),dev=st.st_dev,ino=st.st_ino,mtime_ns=st.st_mtime_ns,ctime_ns=st.st_ctime_ns,nlink=st.st_nlink,bytes=st.st_size,sha256=sha(f))
def b3(f):return subprocess.check_output([B3,'--no-names',f],text=True).strip()
def capture_files(dest,meta):
 found={};blob=obs/'blobs';blob.mkdir(exist_ok=True)
 for name,p in outputs.items():
  if not p.is_dir():continue
  for f in p.rglob('*'):
   if not f.is_file() or not (f.suffix in ('.d','.rmeta')or f.name.startswith(('dep-bin-app','dep-lib-dep','bin-app','lib-dep'))):continue
   if f.stat().st_size>262144:continue
   row=stamp(f);raw=f.read_bytes();ident=bytesha(raw);assert ident==row['sha256'];dst=blob/ident
   if not dst.exists():dst.write_bytes(raw)
   tag=(Path(name)/f.relative_to(p)).as_posix();found[tag]=row|{'literal_path':os.fsencode(meta) in raw}
 save(dest/'files.json',found);return found
def invoke(d,environment,driver,meta,traced):
 admit();d.mkdir(parents=True);cmd=R['argv'];argv=cmd
 if traced:argv=['/usr/bin/strace','-ff','-qq','-yy','-s','260000','-e','trace=execve,mmap','-o',str(d/'trace'),*cmd]
 save(d/'input.json',dict(argv=argv,source_hidden=sha(w/'dep/src/hidden.rs'),app=sha(w/'app/src/main.rs'),literal=None if meta is None else str(meta),available=available()))
 with (d/'stdout').open('wb')as so,(d/'stderr').open('wb')as se:
  p=subprocess.Popen(argv,cwd=w,env=environment,stdout=so,stderr=se,start_new_session=True);start=time.monotonic();low=available()
  while p.poll()is None:
   low=min(low,available())
   if low<8<<30 or time.monotonic()-start>90:
    os.killpg(p.pid,signal.SIGKILL);p.wait();raise ValueError((d.name,'reserve or timeout',low))
   time.sleep(.025)
 rows=[json.loads(l)for l in (d/'stdout').read_bytes().splitlines()];rc=p.returncode
 assert rows[-1]=={'reason':'build-finished','success':rc==0} and rc in (0,101),(d,rc,(d/'stderr').read_bytes()[-400:])
 arts=[r for r in rows if r.get('reason')=='compiler-artifact'];provider,=[x for x in arts if x['target']['name']=='dep']
 f,=[Path(z)for z in provider['filenames'] if z.endswith('.rmeta')];assert f.is_file() and (meta is None or f==meta and f.samefile(meta))
 raw=f.read_bytes();hashes=subprocess.check_output(['rustc','+ohm',f,'-Zls=root'],env=environment).decode();(d/'root-output.txt').write_text(hashes)
 pub=re.search(r'public_hash (\w{32})',hashes)[1];hpriv=re.search(r'private hash (\w{32}) stable_crate_id',hashes)[1]
 errors=[r['message']for r in rows if r.get('reason')=='compiler-message' and r['message']['level']=='error']
 if rc:assert [e['code']['code']for e in errors]==['E0308'] and ['app/src/main.rs']==[s['file_name']for s in errors[0]['spans']if s['is_primary']],(d,errors)
 if not rc:assert not errors
 kernels=[];decoder=json.JSONDecoder();frontend=driver.parent.parent/'bin/rustc'
 for t in sorted(d.glob('trace.*')):
  lines=t.read_text().splitlines()
  for l in lines:
   if not l.startswith('execve(') or not l.endswith(' = 0') or '"--crate-name"' not in l or '"--emit=dep-info,metadata"' not in l:continue
   ex,i=decoder.raw_decode(l[7:]);arr,_=decoder.raw_decode(l[7+i:].lstrip(', '))
   if not Path(ex).samefile(frontend):assert Path(ex).samefile(proxy);continue
   crate=arr[arr.index('--crate-name')+1];assert crate in ('app','dep')
   mappings=[l for l in lines if l.startswith('mmap(') and 'PROT_EXEC' in l and '<'+str(driver)+'>' in l and re.search(r' = 0x[0-9a-f]+$',l)]
   assert mappings,(d,crate,driver)
   assert ('-Zohm-checked-private-derives' in arr)==(args.expect=='aware' and role=='C' and crate=='dep'),(d,role,crate,arr)
   kernels.append(dict(pid=int(t.suffix[1:]),crate=crate,argv=arr,mappings=mappings,exe=stamp(frontend),driver=sha(driver)))
  with gzip.open(str(t)+'.gz','wb',compresslevel=1)as out:out.write(t.read_bytes())
  t.unlink()
 files=capture_files(d,f);out=dict(exit=rc,cargo_nonfresh=sorted(x['target']['name']for x in arts if not x['fresh']),kernel=sorted(x['crate']for x in kernels) if traced else None,
  errors=[e['code']['code']for e in errors],public=pub,private=hpriv,meta=stamp(f),blake3=b3(f),fnv=fnv(raw),literal_depinfo=[k for k,v in files.items()if k.endswith('.d')and '/app/' in k and v['literal_path']],minimum_available=low)
 save(d/'kernel.json',kernels);save(d/'result.json',out);return out,f
def evict(dest):
 dest.mkdir()
 for key in (('cargo-home','home','temp') if args.registry_outputs else ('target','shared','cargo-home','home','temp')):
  p=B/key
  if p.exists():p.rename(dest/key)
  p.mkdir()
 for p in outputs.values():p.mkdir(parents=True,exist_ok=True)
def history(role,kind,env,driver):
 out=obs/role/kind;out.mkdir(parents=True);evict(out/'previous-private-state')
 ex=kind=='kernel';s=w/'dep/src/hidden.rs';client=w/'app/src/main.rs'
 write(s,hidden);write(client,base);res={};discover,meta=invoke(out/'discover',env,driver,None,ex)
 assert discover['exit']==0
 app=template.replace('@RUST_METADATA@',str(meta)).replace('@OLD_FNV@',str(discover['fnv']))+base;write(client,app);(out/'registered-app.rs').write_text(app);expected=sha(client)
 res['discover']=discover
 for label in R['phases'][1:]:
  if label=='first-edited':time.sleep(1.04);write(s,moved)
  if label in ('repair','independent-repair'):time.sleep(1.04);write(s,hidden)
  if label=='independent-empty-edited':evict(out/'original-unmodified-target-bytes');write(s,moved)
  assert sha(client)==expected
  result,actual=invoke(out/label,env,driver,meta,ex);res[label]=result
  assert actual==meta
  if label in ('old-literal','old-unchanged','repair','repaired-unchanged','independent-repair','independent-repaired-unchanged'):assert result['exit']==0,(label,result)
  if label in ('old-literal','old-unchanged'):assert result['literal_depinfo'],(label,'no path in consuming Rust depfile',meta)
  if label=='independent-empty-edited':assert result['exit']==101 and result['errors']==['E0308'],(role,kind,label,result)
 a,b,c=res['old-literal'],res['first-edited'],res['independent-empty-edited']
 assert a['meta']['sha256']!=b['meta']['sha256']==c['meta']['sha256'] and a['fnv']!=b['fnv']==c['fnv'] and a['blake3']!=b['blake3']==c['blake3']
 assert (a['public']==b['public'])==(role=='C' and args.expect=='aware') and a['public']==res['repair']['public'] and a['meta']['sha256']==res['repair']['meta']['sha256']==res['independent-repair']['meta']['sha256']
 assert res['old-unchanged']['kernel']in (None,[]) and res['repaired-unchanged']['kernel']in (None,[])
 summary={k:{n:v[n]for n in ('exit','errors','cargo_nonfresh','kernel','public','private','blake3','fnv')}for k,v in res.items()}
 save(out/'summary.json',summary);print(role,kind,'first',b['exit'],b['kernel'],'next',res['next-unchanged']['exit'],'clean',c['exit'],'repair',res['repair']['exit'],flush=True)
 return summary
try:
 all={}
 for role in R['roles']:
  if alias.exists():alias.unlink()
  sdk=COMPILER[role].resolve(strict=True);alias.symlink_to(sdk)
  driver,=(sdk/'lib').glob('librustc_driver-*.so');driver=driver.resolve(strict=True);assert sha(driver)==R['driver'][role]and sha(sdk/'bin/cargo')==active_cargo
  e={'HOME':str(B/'home'),'PATH':str(proxies)+':/usr/bin:/bin','RUSTUP_HOME':str(ru),'RUSTUP_AUTO_INSTALL':'0','CARGO_HOME':str(B/'cargo-home'),'CARGO_TARGET_DIR':str(outputs['target']),'CARGO_BUILD_BUILD_DIR':str(outputs['shared']),'CARGO_BUILD_JOBS':'1','CARGO_NET_OFFLINE':'true','CARGO_CACHE_AUTO_CLEAN_FREQUENCY':'never','TMPDIR':str(B/'temp'),'LC_ALL':'C','CARGO_TERM_COLOR':'never','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'}
  all[role]={}
  for kind in R['histories']:
   got=history(role,kind,e,driver);all[role][kind]=got
  assert all[role]['ordinary'].keys()==all[role]['kernel'].keys()
  for k,one in all[role]['ordinary'].items():
   other=all[role]['kernel'][k];assert {n:v for n,v in one.items()if n!='kernel'}=={n:v for n,v in other.items()if n!='kernel'},(role,k)
 for role in R['roles']:
  expected=101
  assert all[role]['ordinary']['first-edited']['exit']==expected
  assert all[role]['kernel']['first-edited']['kernel']==['app','dep']
 save(obs/'terminal.json',{'actual_native_cargo':active_cargo,'expected_contract':args.expect,'rosters':all,'new_wrong_first_check':all['P']['ordinary']['first-edited']['exit']==101 and all['C']['ordinary']['first-edited']['exit']==0})
except BaseException as exc:
 save(obs/'failure.json',{'error':repr(exc),'trace':traceback.format_exc()});raise
