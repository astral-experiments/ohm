"""Capture an unwrapped RNG edit, then recreate the whole genuine workflow from OLD in Callgrind."""
from pathlib import Path
import ast,hashlib,json,os,re,shutil,subprocess as sp,sys
base=Path(__file__).resolve().parent;d=base.parent;u=d.parent/'unicode-array-layout-88a50-01';sys.path.insert(0,str(u));import setup
role=sys.argv[1];sdk=Path(sys.argv[2]).resolve();assert role in ('c7','c8','c9')
w=base/'rng-ordinary';w.mkdir(exist_ok=True);p=w/role;p.mkdir();live=w/'live';live.mkdir(exist_ok=True)
targets=[live/'target',live/'shared'];assert all(not f.exists()for f in targets);assert shutil.disk_usage(w).free>15*2**30
rustup=w/'rustup/toolchains/ohm';rustup.parent.mkdir(exist_ok=True,parents=True)
if rustup.is_symlink():rustup.unlink()
rustup.symlink_to((sdk/'toolchains/ohm').resolve(),target_is_directory=True); exe=rustup/'bin/rustc'
def sha(f):
 with f.open('rb')as c:return hashlib.file_digest(c,'sha256').hexdigest()
def record(f,x):f.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
full={'c7':'06fe634feaa39288210a6f17b8994346a5fae1c1','c8':'eda9434eda0b4f8519fc2257867ab7c7dd4b59fd','c9':'573b92c4c0d6c941b20d992465581d21a3494a3e'}[role]
home=w/'cargo-home';seed=u/'rand-holdout/seed/registry';inputs=json.loads((u/'rand-holdout/inputs.json').read_bytes());a='523d83c941cbae9b7c8a10739c839a8eeda3245d';b='bfedc614b7670b8766576b64afd426c292f8c2ce';assert list(inputs['lock'])==[a,b]
if not home.exists():
 reg=home/'registry';reg.mkdir(parents=True);(reg/'cache').symlink_to(seed/'cache',target_is_directory=True);shutil.copytree(seed/'index',reg/'index')
archives={f.name:sha(f)for f in (home/'registry/cache').glob('*/*.crate')};assert all(archives.get(n)==expected for n,expected in inputs['archives'].items())
env=setup.env()|dict(RUSTUP_HOME=str(rustup.parent.parent),CARGO_HOME=str(home),CARGO_TARGET_DIR=str(targets[0]),CARGO_BUILD_BUILD_DIR=str(targets[1]),CARGO_BUILD_JOBS='2',CARGO_NET_OFFLINE='true')
assert not any(k in env for k in ('RUSTC_WRAPPER','RUSTFLAGS','CI','CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST','CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST'))
assert full.encode() in sp.check_output(['rustc','+ohm','-vV'],env=env)
src=setup.ruff.parent/'ruff-ohm-lexer-rng-kernel-20261104';setup.identity(setup.ruff)
assert sp.check_output(['/home/dev-user/.local/bin/gh-auto','api','user','--jq','.login'],cwd=setup.ruff).strip()==b'charliermarsh'
if not src.exists():sp.run(['cargo','+ohm','worktree','add','--offline','-b','charlie/qa-lexer-rng-kernel-20261104','--target-dir',targets[0],src,a],env=dict(env,CARGO_TARGET_DIR=str(w/'initial-target')),cwd=setup.ruff,check=True)
setup.identity(src);assert not setup.git(src,'status','--porcelain')
def checkout(rev):
 if setup.git(src,'rev-parse','HEAD').decode().strip()!=rev:sp.run(['git','switch','--detach',rev],cwd=src,check=True)
 assert not setup.git(src,'status','--porcelain')and sha(src/'Cargo.lock')==inputs['lock'][rev]
def phase(label,rev,mode):
 checkout(rev);at=p/label;at.mkdir();argv=['cargo','+ohm','check','-p','ruff_unicode_names2','--lib','--locked','--offline','--message-format=json']
 if mode=='trace':argv=['strace','-ff','-qq','-s','262144','-v','-e','trace=execve,execveat,chdir,fchdir','-o',str(at/'trace'),*argv]
 if mode=='guest':argv=['valgrind','--tool=callgrind','--trace-children=yes','--instr-atstart=yes','--collect-atstart=yes','--compress-strings=yes','--collect-jumps=no','--log-file='+str(at/'vg.%p'),'--callgrind-out-file='+str(at/'callgrind.%p'),'--',*argv]
 with(at/'out').open('wb')as f,(at/'err').open('wb')as e:result=sp.run(argv,env=env,cwd=src,stdout=f,stderr=e)
 assert result.returncode==0,(label,result.returncode,(at/'err').read_text()[-700:])
 rows=[json.loads(l)for l in(at/'out').read_bytes().splitlines()];assert rows[-1]==dict(reason='build-finished',success=True)
 xs=[x for x in rows if x['reason']=='compiler-artifact'];owner,=[x for x in xs if x['target']['name']=='unicode_names2'];native,=[Path(f)for f in owner['filenames']if f.endswith('.rmeta')]
 out=next(Path(x['out_dir'])for x in rows if x['reason']=='build-script-executed'and 'ruff_unicode_names2' in x['package_id'] and (Path(x['out_dir'])/'generated.rs').is_file())
 actual={'dirty':sorted(x['target']['name']for x in xs if not x['fresh']),'units':len(xs),'rmeta':sha(native),'generated':{f.name:sha(f)for f in out.glob('generated*.rs')},'rev':rev,'lock':sha(src/'Cargo.lock'),'argv':argv};record(at/'result.json',actual);shutil.copy2(native,at/'owner.rmeta');print(role,label,len(actual['dirty']),actual['rmeta'][:12],flush=True);return actual
old=phase('old',a,'native');warm=phase('old-settled',a,'native');assert len(old['dirty'])==20 and warm['dirty']==[]
for t in targets:sp.run(['cp','-a','--reflink=auto',t,p/('seeded-'+t.name)],check=True)
normal=phase('edit',b,'trace');repeat=phase('settled',b,'native');assert len(normal['dirty'])==11 and repeat['dirty']==[] and repeat['rmeta']==normal['rmeta'] and repeat['generated']==normal['generated']!=old['generated']
owner=[]
for f in(p/'edit').glob('trace.*'):
 cwd=src
 for line in f.read_text().splitlines():
  if line.startswith('chdir(')and line.endswith(') = 0'):cwd=(cwd/ast.literal_eval(line[6:-5])).resolve()
  if not line.startswith('execve(')or not line.endswith(') = 0'):continue
  prog,args,ev=ast.literal_eval('('+line[7:-5]+')')
  if '--crate-name'not in args or args[args.index('--crate-name')+1]!='unicode_names2'or not Path(prog).is_file()or not os.path.samefile(prog,exe):continue
  owner.append({'pid':int(f.name.split('.')[-1]),'file':str(f),'exe':prog,'argv':args,'cwd':str(cwd),'env_sha256':hashlib.sha256(json.dumps(sorted(ev)).encode()).hexdigest()})
assert len(owner)==1,owner;record(p/'kernel.json',owner[0])
for t in targets:t.rename(p/('native-'+t.name));(p/('seeded-'+t.name)).rename(t)
guest=phase('guest-edit',b,'guest');assert guest['dirty']==normal['dirty'] and guest['rmeta']==normal['rmeta']and guest['generated']==normal['generated']
matches=[];expected=' '.join([owner[0]['exe'],*owner[0]['argv'][1:]])
for f in(p/'guest-edit').glob('callgrind.*'):
 data=f.read_bytes();cm=re.search(rb'^cmd:\s*(.+)$',data,re.M);cm=cm[1].decode()if cm else ''
 if cm==expected:
  value,=re.findall(rb'^summary: (\d+)$',data,re.M);matches.append({'file':f.name,'ir':int(value),'sha256':sha(f)})
assert len(matches)==1,(expected,[(f.name,next((l[:160]for l in f.read_text().splitlines()if l.startswith('cmd:')and '--crate-name unicode_names2 'in l),''))for f in(p/'guest-edit').glob('callgrind.*')if '--crate-name unicode_names2 'in f.read_text()[:15000]])
for t in targets:t.rename(p/('guest-'+t.name))
fresh=phase('empty',b,'native');assert len(fresh['dirty'])==17 and fresh['generated']==normal['generated']and fresh['rmeta']==normal['rmeta']; 
for t in targets:t.rename(p/('empty-'+t.name))
result={'source':full,'role':role,'owner':matches[0],'driver':sha(next((rustup/'lib').glob('librustc_driver-*.so'))),'kernel':sha(p/'kernel.json'),'old':old,'edit':normal,'settled':repeat,'guest':guest,'empty':fresh};record(p/'verified.json',result);print('verified',role,result['owner'],flush=True)
