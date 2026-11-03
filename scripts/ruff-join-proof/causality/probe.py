from pathlib import Path
import os,sys,hashlib,json,re,tempfile,shutil,tarfile,urllib.request,subprocess,time,signal
src=Path(__file__).resolve().parent;sys.path.insert(0,str(src.parent.parent/'ruff-foreign-span-observer'))
import worker as sdk
plan=json.loads((src/'plan.json').read_bytes());se=sdk.install();root=Path(os.environ['RUNNER_TEMP'])/'join-scheduler';root.mkdir();pub=sdk.proof;w=root/'source';w.mkdir();tgt=root/'target';shared=root/'shared';alias=w/'selected.rmeta';active=root/'active';(active/'bin').mkdir(parents=True);(active/'lib').symlink_to(sdk.sdk/'lib');(active/'bin/rustc').symlink_to(sdk.sdk/'bin/rustc');(active/'bin/rustdoc').symlink_to(sdk.sdk/'bin/rustdoc');binding=active/'bin/cargo';binding.symlink_to(sdk.sdk/'bin/cargo')
archive=root/'cargo.tar.xz'
with urllib.request.urlopen(plan['upstream_package'],timeout=90)as a,archive.open('xb')as b:shutil.copyfileobj(a,b)
assert sdk.hf(archive)==plan['upstream_sha256'];official=root/'official-cargo'
with tarfile.open(archive)as ar:
 m,=[m for m in ar.getmembers()if m.name.endswith('/cargo/bin/cargo')and m.isfile()];assert m.size<=150*2**20
 with ar.extractfile(m)as a,official.open('xb')as b:shutil.copyfileobj(a,b)
official.chmod(0o755);e={**se,'RUSTUP_HOME':str(root/'rustup'),'CARGO_TARGET_DIR':str(tgt),'CARGO_BUILD_BUILD_DIR':str(shared)};subprocess.run(['rustup','toolchain','link','ohm',active],env=e,check=True);sdk.put(pub/'admission.json',{'plan':plan,'source_sha':sdk.hf(Path(__file__)),'selected_ohm':sdk.hf(sdk.sdk/'bin/cargo'),'official_bin':sdk.hf(official),'official_tar':sdk.hf(archive),'same_rustc':sdk.hf(sdk.sdk/'bin/rustc')})
candidate=None
if os.environ.get('OHM_INPUT_RECHECK_QA')=='1':
 sys.path.insert(0,str(src.parent/'fix'));import build as factory
 candidate,build_env,cargo_repo=factory.setup(sdk,se)
def write(rel,body):
 f=w/rel;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(body);return f
write('Cargo.toml','[workspace]\nmembers=["producer","client"]\nresolver="2"\n')
write('producer/Cargo.toml','[package]\nname="selected_producer"\nversion="0.1.0"\nedition="2021"\n')
write('client/Cargo.toml','[package]\nname="selected_client"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nselected_producer={path="../producer"}\n')
producer=write('producer/src/lib.rs','');client=write('client/src/main.rs','fn main(){println!("{}",selected_producer::FIXED);}\n');placeholder=client.read_text()
client_source='''const fn fnv(bytes:&[u8])->u64{let mut v=14695981039346656037u64;let mut i=0;while i<bytes.len(){v=(v^bytes[i] as u64).wrapping_mul(1099511628211);i+=1;}v}
const fn decimal(bytes:&[u8])->u64{let mut v=0;let mut i=0;while i<bytes.len(){v=v*10+(bytes[i]-b'0') as u64;i+=1;}v}
const HASH:u64=fnv(include_bytes!("../../selected.rmeta"))+selected_producer::FIXED;
const _: [();1] = [(); (env!("CHECK_VALUE").as_bytes()[0]==b'0' || HASH==decimal(env!("OLD_VALUE").as_bytes())) as usize];
fn main(){println!("{HASH}");}
'''
def fnv(raw):
 n=14695981039346656037
 for c in raw:n=((n^c)*1099511628211)&0xffffffffffffffff
 return n
def flip_link(src):
 p=active/'bin/next-cargo';p.symlink_to(src);p.replace(binding)
def guard():assert sdk.avail()>=8*2**30 and shutil.disk_usage(root).free>=15*2**30
global_runs=0
def evict():
 global global_runs
 for o in (tgt,shared):
  if o.exists():o.rename(root/(o.name+f'-frozen-{global_runs}'))
 global_runs+=1
def collect(argv,path,env):
 guard();path.mkdir(parents=True);trace=path/'exec';low=sdk.avail();assert low>=9*2**30
 with(path/'stdout').open('wb')as so,(path/'stderr').open('wb')as se:
  p=subprocess.Popen(['strace','-ff','-qq','-s','65535','-e','trace=execve,execveat','-o',trace,*argv],cwd=w,env=env,stdout=so,stderr=se,start_new_session=True);start=time.monotonic()
  while p.poll()is None:
   low=min(low,sdk.avail())
   if low<8*2**30 or time.monotonic()-start>55:
    os.killpg(p.pid,signal.SIGKILL);p.wait();raise ValueError('resources')
   time.sleep(.04)
 raw={x.name:x.read_text(errors='strict')for x in path.glob('exec.*')};hits={}
 for k,s in raw.items():
  for n in ('selected_client','selected_producer'):
   if f'"--crate-name", "{n}"' in s:hits.setdefault(n,[]).append(k)
 rows=[json.loads(ln)for ln in(path/'stdout').read_text().splitlines()if ln.startswith('{')]
 sdk.put(path/'exec-index.json',{'argv':argv,'exit':p.returncode,'rustcs':hits,'minimum_available':low});return p.returncode,rows,hits
def observe(mode,label,path,flags,env,package='selected_client',historical_input=None):
 argv=['cargo','+ohm',*flags,mode,'-p',package,'--locked','--offline','-j2','--message-format=json'];rc,rows,hits=collect(argv,path,env)
 filenames=[Path(f)for r in rows if r['reason']=='compiler-artifact'and r['target']['name']=='selected_producer'for f in r['filenames']]
 choices=[p for p in filenames if p.suffix=='.rmeta'and p.is_file()]
 if not choices:choices=[p.with_suffix('.rmeta')for p in filenames if p.suffix=='.rlib'and p.with_suffix('.rmeta').is_file()]
 if not choices:choices=[p for d in (tgt,shared)if d.exists()for p in d.rglob('libselected_producer*.rmeta')if p.is_file()and not p.is_symlink()]
 assert choices and len({p.resolve()for p in choices})==1,(filenames,choices)
 meta=choices[0];raw=meta.read_bytes();(path/'actual.rmeta').write_bytes(raw);hdr=subprocess.check_output(['rustc','+ohm',meta,'-Zls=root'],env=env,text=True);(path/'root.txt').write_text(hdr);h1=re.search(r'private hash (\w{32}) stable_crate_id',hdr)[1];h2=re.search(r'public_hash (\w{32})',hdr)[1]
 if label=='discover':
  if alias.is_symlink():alias.unlink()
  alias.symlink_to(meta)
 if historical_input is None:assert alias.samefile(meta),(alias,meta)
 else:assert (str(alias.readlink()),sdk.hf(alias))==historical_input
 explicit=alias.read_bytes();(path/'literal-input.rmeta').write_bytes(explicit)
 ds=[]
 for d in (tgt,shared):
  if d.exists():
   for dep in d.rglob('selected_client*.d'):
    if dep.is_file()and not dep.is_symlink():
     content=dep.read_bytes();i=len(ds);(path/f'raw-{i}.d').write_bytes(content);ds.append(str(dep))
 out={'exit':rc,'rustc_execs':hits,'metadata_path':str(meta),'metadata_mtime_ns':meta.stat().st_mtime_ns,'lexical_include':str(alias),'explicit_target':str(alias.readlink()),'explicit_sha':sdk.hf(alias),'explicit_fnv':fnv(explicit),'private':h1,'public':h2,'rmeta':sdk.hf(meta),'bytes':len(raw),'fnv':fnv(raw),'nonfresh':[r['target']['name']for r in rows if r['reason']=='compiler-artifact'and not r['fresh']],'errors':[r['message']['code']['code']for r in rows if r['reason']=='compiler-message'and r['message']['level']=='error'and r['message'].get('code')],'depfiles':ds,'source_sha':sdk.hf(producer),'source_mtime_ns':producer.stat().st_mtime_ns,'client_source_sha':sdk.hf(client)}
 if label.startswith('old')or label=='discover':assert rc==0,(label,out)
 if mode=='build'and rc==0:
  exe=tgt/'debug/selected_client';sig=sdk.hf(exe);b=pub/'bodies'/sig;b.parent.mkdir(exist_ok=True)
  if not b.exists():shutil.copyfile(exe,b)
  out.update(elf=sig,native=int(subprocess.check_output([exe],env={'PATH':'/usr/bin:/bin'})))
 sdk.put(path/'proof.json',out);return out
def cases(case):
 if case.startswith('private'):
  old='#![allow(dead_code)]\nfn hidden() -> u8 { 10 }\npub const FIXED: u64 = 0;\n';return old,old.replace('10 }','20 }')
 short='// pad\n';long='// pad with 37 more visible source bytes........\n';body='#[macro_export]\nmacro_rules! left { ($m:ident)=>{ ::shape_observer::inspect!($m 17 29) } }\npub const FIXED: u64=0;\n';return short+body+long,long+body+short
def history(arm,case,mode,flags,env):
 evict();folder=pub/arm/case/mode;old,new=cases(case);client.write_text(placeholder);producer.write_text(old);ts=producer.stat().st_mtime_ns;rs={};rs['discover']=observe(mode,'discover',folder/'discover',flags,env);client.write_text(client_source);env={**env,'OLD_VALUE':str(rs['discover']['fnv']),'CHECK_VALUE':str(int(mode=='check'))}
 for label in ('old','old-unchanged','edit','next-unchanged','independent-clean','repair','repaired-unchanged'):
  if label=='edit':
   time.sleep(1.08);producer.write_text(new)
   if case=='private-same-mtime':os.utime(producer,ns=(ts,ts))
   else:assert producer.stat().st_mtime_ns>ts
  if label=='independent-clean':evict()
  if label=='repair':time.sleep(1.08);producer.write_text(old)
  rs[label]=observe(mode,label,folder/label,flags,env)
 assert rs['old']['rmeta']==rs['old-unchanged']['rmeta']and rs['edit']['rmeta']!=rs['old']['rmeta']and rs['edit']['rmeta']==rs['independent-clean']['rmeta'];assert rs['repair']['rmeta']==rs['old']['rmeta']and rs['repair']['exit']==rs['repaired-unchanged']['exit']==0
 if mode=='check':assert rs['independent-clean']['errors']==['E0308'] and rs['independent-clean']['exit']!=0
 else:assert rs['old']['native']==rs['old']['fnv'] and rs['independent-clean']['native']==rs['edit']['fnv']
 return rs
subprocess.run(['cargo','+ohm','generate-lockfile','--offline'],env=e,cwd=w,check=True);out={};fail={}
roles=[('shipped',[],sdk.sdk/'bin/cargo'),('shipped-defaults-off',['-Zohm-defaults=no'],sdk.sdk/'bin/cargo'),('upstream',[],official)] if candidate is None else [('shipped',[],sdk.sdk/'bin/cargo'),('fixed',[],candidate)]
for arm,flags,target in roles:
 flip_link(target);version=subprocess.check_output(['cargo','+ohm','-Vv'],env=e,text=True);assert (factory.spec['candidate']if arm=='fixed'else plan['upstream_cargo'if arm=='upstream'else'cargo_shipped'])in version;assert plan['rustc']in subprocess.check_output(['rustc','+ohm','-vV'],env=e,text=True);sdk.put(pub/(arm+'-cargo.json'),{'version':version,'executable':sdk.hf(binding)});out[arm]={}
 for c in ('private','macro_bytes',*(('private-same-mtime',)if arm in ('shipped','fixed')else())):
  out[arm][c]={}
  for mode in ('check','build'):
   try:out[arm][c][mode]=history(arm,c,mode,flags,{**e,**({'CARGO_INCREMENTAL':'0'}if c=='macro_bytes'else{})})
   except Exception as exc:
    import traceback
    fail['/'.join((arm,c,mode))]=traceback.format_exc();print(fail['/'.join((arm,c,mode))],flush=True)
   sdk.put(pub/'completed.json',out);sdk.put(pub/'failures.json',fail)
for p in ('Cargo.toml','producer/Cargo.toml','client/Cargo.toml'):shutil.copyfile(w/p,pub/(p.replace('/','.')))
sdk.put(pub/'fixture-shapes.json',{'client':client_source,'private':cases('private'),'macro_bytes':cases('macro_bytes')});assert not fail,fail

if candidate:
 for case in ('private','macro_bytes','private-same-mtime'):
  for arm in ('shipped','fixed'):
   rs=out[arm][case]['check'];edit=rs['edit']
   assert ('selected_client' in edit['rustc_execs'])==(arm=='fixed') and edit['errors']==(['E0308'] if arm=='fixed' else []) and edit['exit']==(101 if arm=='fixed' else 0)
   assert rs['next-unchanged']['errors']==rs['independent-clean']['errors']==['E0308']
   nb=out[arm][case]['build']
   assert nb['edit']['native']==nb['edit']['fnv']==nb['independent-clean']['native']
 for arm in ('shipped','fixed'):
  for owner,phase in [('selected_producer','discover'),('selected_client','old')]:
   x=pub/arm/'private/check'/phase
   trace=''.join((x/h).read_text() for h in json.loads((x/'proof.json').read_bytes())['rustc_execs'][owner])
   assert '"-Zthreads=8"' in trace and '"checksum-hash-algorithm=blake3"'in trace and '"-Zpublic-api-hash"'in trace,(arm,owner,trace[:1800])
  assert any('# checksum:blake3=' in p.read_text()and 'selected.rmeta' in p.read_text()for p in x.glob('raw-*.d'))
 import adverse
 failed=adverse.run(globals())
 factory.suite(sdk,build_env,cargo_repo)
 assert not failed,failed
