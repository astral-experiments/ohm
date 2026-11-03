from pathlib import Path
import json,subprocess,os,sys,hashlib,time,signal,re
q=Path(__file__).resolve().parent; w=q/'fixture';f=q.parent;l=f.parent;a=l.parent.parent
producer=w/'producer/src/lib.rs';client=w/'client/src/main.rs';original=producer.read_bytes();placeholder=client.read_bytes();stamp=producer.stat().st_mtime_ns
env={k:os.environ[k] for k in ('HOME','USER','LANG','PATH','RUSTUP_HOME','CARGO_HOME')if k in os.environ};assert Path(env['RUSTUP_HOME'],'toolchains','ohm','bin','rustc').is_file()
def sha(data):return hashlib.sha256(data).hexdigest()
def available():return int(re.search(r'^MemAvailable:\s+(\d+) kB$',Path('/proc/meminfo').read_text(),re.M)[1])*1024
def run(args,d,env):
 while available()<9.6*2**30:time.sleep(.75)
 assert os.statvfs(q).f_frsize*os.statvfs(q).f_bavail>15*2**30
 d.mkdir(parents=True);start=time.monotonic();minimum=available()
 with (d/'stdout').open('wb')as out,(d/'stderr').open('wb')as err:
  p=subprocess.Popen(args,cwd=w,env=env,stdout=out,stderr=err,start_new_session=True)
  while p.poll()is None:
   cur=available();minimum=min(minimum,cur)
   if cur<8*2**30 or time.monotonic()-start>90:
    os.killpg(p.pid,signal.SIGKILL);p.wait();raise RuntimeError('sacrificed for resource or duration guard')
   time.sleep(.04)
 (d/'exit.json').write_text(json.dumps({'argv':args,'code':p.returncode,'min_available':minimum}));return p.returncode
def fnv(raw):
 value=14695981039346656037
 for b in raw:value=((value^b)*1099511628211)&0xffffffffffffffff
 return value
def edit(n):
 z=original.replace(b'10 }',str(n).encode()+b' }');assert len(original)==len(z);producer.write_bytes(z);os.utime(producer,ns=(stamp,stamp))
def pathdep(target,shared):
 x=[p for r in(target,shared)if r.exists()for p in r.rglob('libselected_producer*.rmeta')if p.is_file()and not p.is_symlink()];assert len(x)==1,x;return x[0]
def compile(mode,label,tgt,shared):
 d=q/'runs'/mode/label;e={**env,'CARGO_TARGET_DIR':str(tgt),'CARGO_BUILD_BUILD_DIR':str(shared)}
 argv=['cargo','+ohm',mode,'-p','selected_client','--offline','--locked','-j2','--message-format=json']
 code=run(argv,d,e);rows=[json.loads(x)for x in(d/'stdout').read_text().splitlines()if x.startswith('{')]
 meta=pathdep(tgt,shared);raw=meta.read_bytes();(d/'actual.rmeta').write_bytes(raw)
 h=subprocess.check_output(['rustc','+ohm',meta,'-Zls=public_hash'],env=e,text=True).strip()
 b={'exit':code,'nonfresh':[p['target']['name']for p in rows if p['reason']=='compiler-artifact'and not p['fresh']],'errors':[p['message']['code']['code']for p in rows if p['reason']=='compiler-message'and p['message']['level']=='error'and p['message']['code']],'actual_rmeta':str(meta),'sha':sha(raw),'size':len(raw),'public':h,'expected':fnv(raw)}
 if mode=='build' and code==0:
  exe=tgt/'debug/selected_client';b['verdict']=int(subprocess.check_output([exe]));b['elf']=sha(exe.read_bytes());ea=q/'bodies'/b['elf'];ea.parent.mkdir(exist_ok=True);ea.write_bytes(exe.read_bytes())
 if label in ('old','old-unchanged','edit','next-unchanged','independent-clean'):
  dep=[p for root in(tgt,shared)if root.exists()for p in root.rglob('selected_client*.d')if p.is_file()and not p.is_symlink()]
  checks=[(p,ln)for p in dep for ln in p.read_text().splitlines()if ln.startswith('# checksum:')and ln.split(' ',3)[-1]==str(meta)]
  if not checks and code==0:print('RAW_CANDIDATES',[(str(x),x.read_text()[-1000:])for x in dep],flush=True)
  if code==0:assert len({r for _,r in checks})==1,(label,dep,checks)
  b['declared_rmeta_checksums']=[r for _,r in checks]
 (d/'proof.json').write_text(json.dumps(b,indent=2)+'\n');print(mode,label,b['exit'],b['nonfresh'],b['errors'],b.get('verdict'),b['expected'],flush=True);return b
def main():
 assert b'10 }'in original and 'include_bytes' not in placeholder.decode()
 run(['cargo','+ohm','generate-lockfile','--offline'],q/'runs/lock',env)
 results={}
 for mode in ('build','check'):
  edit(10);client.write_bytes(placeholder);tgt=q/(mode+'-target');sd=q/(mode+'-shared');rs=results[mode]={}
  rs['discover']=compile(mode,'discover',tgt,sd);source_path=rs['discover']['actual_rmeta'];expected=rs['discover']['expected']
  code='''const fn f(bytes:&[u8])->u64{let mut h=14695981039346656037u64;let mut i=0;while i<bytes.len(){h=(h^bytes[i] as u64).wrapping_mul(1099511628211);i+=1;}h}\nconst HASH:u64=f(include_bytes!(r#"%s"#))+selected_producer::FIXED;\n'''%source_path
  if mode=='check':code+='const _: [();1] = [();(HASH == %d) as usize];\n'%expected
  client.write_text(code+'fn main(){println!("{HASH}");}\n')
  for label,n in [('old',10),('old-unchanged',10),('edit',20),('next-unchanged',20),('independent-clean',20)]:
   if label=='independent-clean':
    tgt.rename(q/(tgt.name+'-retained-warm'))
    if sd.exists():sd.rename(q/(sd.name+'-retained-warm'))
   edit(n);rs[label]=compile(mode,label,tgt,sd)
  for label in ('old-unchanged','edit','next-unchanged','independent-clean'):assert rs[label]['public']==rs['old']['public']
  assert rs['edit']['sha']!=rs['old']['sha']and rs['edit']['sha']==rs['independent-clean']['sha']
  if mode=='build':assert rs['old']['verdict']==rs['old']['expected']and rs['independent-clean']['verdict']==rs['edit']['expected']
  else:assert rs['old']['exit']==0 and rs['independent-clean']['errors']==['E0308']
 (q/'completed.json').write_text(json.dumps(results,sort_keys=True,indent=2)+'\n')
try:main()
finally:producer.write_bytes(original);os.utime(producer,ns=(stamp,stamp));client.write_bytes(placeholder)
