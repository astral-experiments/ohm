"""Replay the native work product failure on the eleven published crates in Ruff's Ron closure."""
from pathlib import Path
import hashlib,json,os,re,shlex,shutil,subprocess as sp,sys,tomllib
base=Path(sys.argv[1]).resolve()
role,alias,tag=sys.argv[2:]
assert role in ('stock','signed','fixed')
root=base/(role+'-'+tag);root.mkdir()
project=root/'project';shutil.copytree(base/'project',project)
target=root/'target';shared=root/'shared'
env={k:os.environ[k] for k in ('PATH','HOME','LANG') if k in os.environ}
env.update(RUSTUP_HOME=alias,RUSTUP_TOOLCHAIN='ohm',CARGO_HOME=str(root/'cargo-home'),CARGO_TARGET_DIR=str(target),CARGO_BUILD_BUILD_DIR=str(shared),CARGO_NET_OFFLINE='true')
if role=='stock':env['RUSTC_BOOTSTRAP']='1'
def digest(data):return hashlib.sha256(data).hexdigest()
locked=tomllib.loads((project/'Cargo.lock').read_text())['package']
orig=json.loads((base/'source.json').read_bytes())['registry_checksums']
real={p['name']+'-'+p['version']:p.get('checksum') for p in locked if p['name']!='green_stub_ron_replay'}
assert real.keys()==orig.keys() and all(c==orig[k]for k,c in real.items()if k!='ron-0.12.0')
for f in (project/'ron').rglob('*.rs'):
 assert f.read_bytes()==(base/'vendor/ron-0.12.0'/f.relative_to(project/'ron')).read_bytes()
tools={k:sp.check_output([k,'+ohm','-vV'],env=env,text=True)for k in ('rustc','cargo')}
steps={}
def compile(name):
 q=sp.run(['cargo','+ohm','-Zembed-metadata=no','build','--locked','--offline','-vv','--message-format=json'],env=env,cwd=project,capture_output=True,timeout=300)
 (root/(name+'.stderr')).write_bytes(q.stderr);(root/(name+'.stdout')).write_bytes(q.stdout)
 messages=[json.loads(l)for l in q.stdout.splitlines()if l.startswith(b'{')]
 cmds=[l for l in q.stderr.decode().splitlines()if 'Running 'in l and '--crate-name ron 'in l]
 if cmds:
  assert len(cmds)==1 and 'incremental='in cmds[0]and 'embed-metadata=no'in cmds[0]
  tokens=shlex.split(cmds[0].split('Running `',1)[1].rsplit('`',1)[0])
  feats=sorted(tokens[i+1]for i,x in enumerate(tokens)if x=='--cfg'and tokens[i+1].startswith('feature='))
  assert feats==['feature="default"','feature="std"'],feats
 errors=[(m['message'].get('code')or {}).get('code') or m['message']['message']for m in messages if m['reason']=='compiler-message'and m['message']['level']=='error']
 rows=[m for m in messages if m['reason']=='compiler-artifact'and m['target']['name']=='ron']
 products=[p for m in rows for p in m['filenames']]
 steps[name]={'rc':q.returncode,'ron_drivers':len(cmds),'errors':errors,'paths':products,'fresh':[m['fresh']for m in rows]}
 assert not cmds or any(' --extern 'in x for x in cmds)
 print(role,name,q.returncode,len(cmds),errors[:1],flush=True)
 return q.returncode,errors,products
def execute(name,want,exe=None):
 e=exe if exe else target/'debug/green_stub_ron_replay'
 q=sp.run([e],env=env,cwd=project,capture_output=True,timeout=15)
 assert q.returncode==0 and q.stdout==want
 steps[name]={'stdout':q.stdout.decode(),'sha256':digest(e.read_bytes())}
def image(name,paths):
 rlib,=[Path(x)for x in paths if x.endswith('.rlib')];rmeta,=[Path(x)for x in paths if x.endswith('.rmeta')]
 archives=root/'archives';archives.mkdir(exist_ok=True)
 shutil.copyfile(rlib,archives/(name+'.rlib'));shutil.copyfile(rmeta,archives/(name+'.rmeta'))
 rlib,rmeta=archives/(name+'.rlib'),archives/(name+'.rmeta')
 members=sp.check_output(['ar','t',rlib],text=True).splitlines();native={}
 for n in members:
  if not n.endswith('.rcgu.o'):continue
  s=re.fullmatch(r'(.+)\.[a-z0-9]{7}\.rcgu\.o',n);assert s and s[1]not in native,n
  native[s[1]]=digest(sp.check_output(['ar','p',rlib,n]))
 assert native
 return {'native':native,'rmeta':digest(rmeta.read_bytes()),'rlib':digest(rlib.read_bytes())}
rc,errors,paths=compile('cold');assert rc==0 and not errors and steps['cold']['ron_drivers']==1
cold=image('cold',paths);execute('original-runtime',b'[17, 29]\n')
old_binary=root/'original-executable';shutil.copy2(target/'debug/green_stub_ron_replay',old_binary)
rc,errs,_=compile('warm')
assert rc==0 or role=='signed'and rc==101 and any('failed to create encoded metadata from file'in e for e in errs)
# A failed Cargo build may remove the archive. Seed an independent complete history before testing missing output.
target.rename(root/'unchanged-case-target');shared.rename(root/'unchanged-case-shared')
rc,errs,paths=compile('cold-before-missing');assert rc==0 and not errs and steps['cold-before-missing']['ron_drivers']==1
before_missing=image('before-missing',paths)
held=root/'held';held.mkdir();leaves=sorted(p for t in (target,shared)for p in t.rglob('libron*.rlib')if p.is_file())
assert leaves
for i,f in enumerate(leaves):f.rename(held/(str(i)+'-'+f.name))
rc,errs,paths=compile('missing-product');assert steps['missing-product']['ron_drivers']==1
if role=='signed':
 assert rc==101 and any('failed to create encoded metadata from file'in e for e in errs),errs
 repaired=None
else:
 assert rc==0 and not errs
 repaired=image('repaired',paths);assert repaired['native']==before_missing['native']
 execute('repaired-runtime',b'[17, 29]\n')
main=project/'src/main.rs'
old=main.read_text();main.write_text('fn main() { let _: u8 = "wrong"; }\n')
if role!='signed':
 rc,errs,_=compile('invalid-client');assert rc==101 and 'E0308'in errs
main.write_text(old.replace('29','31'))
execute('stale-runtime',b'[17, 29]\n',old_binary)
if role!='signed':
 rc,errs,_=compile('edited-client');assert rc==0 and not errs
 execute('edited-runtime',b'[17, 31]\n')
target.rename(root/'previous-target');shared.rename(root/'previous-shared')
rc,errs,paths=compile('independent-empty');assert rc==0 and not errs and steps['independent-empty']['ron_drivers']==1
clean=image('clean',paths);execute('clean-runtime',b'[17, 31]\n')
result={'role':role,'tools':tools,'ruff':json.loads((base/'source.json').read_bytes()),'moved':[str(p)for p in leaves],'steps':steps,'cold':cold,'missing_donor':before_missing,'repaired':repaired,'empty':clean}
(root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print('verified',role,len(cold['native']),sum(cold['native'].get(k)==h for k,h in clean['native'].items()),'native payloads matching clean')
