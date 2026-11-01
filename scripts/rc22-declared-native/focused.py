"""Observe both binaries and the unmodified C driver using a private native library."""
import hashlib,json,os,platform,shutil,subprocess,sys
from pathlib import Path
lane,kit,mode=Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve(),sys.argv[3]
assert mode in ('debug','private','mixed','shadow','default')
lane.mkdir(); project=lane/'source'; (project/'src/bin').mkdir(parents=True);(project/'engine/src').mkdir(parents=True)
def put(rel,s):
 p=project/rel;p.write_text(s)
put('Cargo.toml','[package]\nname="reader"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nengine={path="engine"}\n')
put('engine/Cargo.toml','[package]\nname="engine"\nversion="0.1.0"\nedition="2021"\n')
put('engine/src/lib.rs','#[inline(never)] pub fn value(n: usize)->usize { unsafe { core::arch::asm!("/* {0} */", in(reg) n, options(nomem,nostack,preserves_flags)); } n }\n')
s='extern "C" { fn answer()->i32; }\n'
if mode=='mixed':
 s+='#[link(name="extra",kind="static")] extern "C" { fn extra()->i32; }\n'
 s+='fn main(){println!("{}:{}",engine::value(unsafe{answer()} as usize),unsafe{extra()});}\n'
else:s+='fn main(){println!("{}",engine::value(unsafe{answer()} as usize));}\n'
for name in ('first','second'):put('src/bin/'+name+'.rs',s)
for d in ('native','earlier','alternate'):(project/d).mkdir()
config=project/'link-mode';config.write_text('0\n')
build='fn main(){let p=std::env::var("CARGO_MANIFEST_DIR").unwrap();\nprintln!("cargo::rerun-if-changed=native/libanswer.a");\n'
if mode=='private':build+='println!("cargo::rerun-if-changed=link-mode");println!("cargo::rerun-if-changed=alternate/libanswer.a");\n'
if mode=='shadow':build+='println!("cargo::rustc-link-search=native={p}/earlier");\n'
build+='println!("cargo::rustc-link-search=native={p}/native");println!("cargo::rustc-link-lib=static=answer");}\n'
put('build.rs',build)
def lib(where,name,value,preserve=False):
 d=project/where; path=d/('lib'+name+'.a'); old=path.stat() if path.exists() else None
 with (d/'member.c').open('w') as f:f.write('int '+name+'(void){return '+str(value)+';}\n')
 subprocess.run(['cc','-c','member.c','-o','member.o'],cwd=d,check=True)
 tmp=d/'replacement.a'
 if tmp.exists():tmp.unlink()
 subprocess.run(['ar','rcs',tmp,'member.o'],cwd=d,check=True)
 path.write_bytes(tmp.read_bytes())
 if preserve:
  assert path.stat().st_size==old.st_size and path.stat().st_ino==old.st_ino
  os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
lib('native','answer',17);lib('alternate','answer',41)
if mode=='mixed':lib('native','extra',3)
driver=project/'configured-cc'
driver.write_text('''#!/usr/bin/env python3
from pathlib import Path
import json,os,sys,subprocess,shutil
r=Path(os.environ['OBSERVE']); p=Path(os.environ['NATIVE_PROJECT'])
a=sys.argv[1:]
if '-o' in a:
    from tempfile import mkdtemp
    d=Path(mkdtemp(dir=r,prefix='call-'))
    (d/'args.json').write_text(json.dumps(a))
    (d/'env.json').write_text(json.dumps({k:v for k,v in os.environ.items() if k in ('PATH','SDKROOT','MACOSX_DEPLOYMENT_TARGET')}))
    with (r/'links').open('a') as f:f.write('link\\n')
    if (p/'link-mode').read_text().strip()=='1':a=['-L'+str(p/'alternate'),*a]
    s=subprocess.run(['cc',*a],capture_output=True)
    (d/'stderr').write_bytes(s.stderr)
    for i,v in enumerate(a):
        if v=='-dependency_info' and Path(a[i+2]).is_file():shutil.copyfile(a[i+2],d/'darwin.dep')
        if v.startswith('--dependency-file=') and Path(v.split('=',1)[1]).is_file():shutil.copyfile(v.split('=',1)[1],d/'gnu.dep')
        if v=='--dependency-file' and Path(a[i+2]).is_file():shutil.copyfile(a[i+2],d/'gnu.dep')
    sys.stdout.buffer.write(s.stdout);sys.stderr.buffer.write(s.stderr);sys.exit(s.returncode)
os.execvp('cc',['cc',*a])
''')
driver.chmod(0o755)
env={k:v for k,v in os.environ.items() if not k.startswith(('CARGO_','RUST','OHM_','LLVM_'))}
for k,c in [('TMPDIR','tmp'),('CARGO_HOME','cargo'),('RUSTUP_HOME','rustup'),('CARGO_TARGET_DIR','target'),('CARGO_BUILD_BUILD_DIR','build')]:
 d=lane/c;d.mkdir();env[k]=str(d)
subprocess.run(['rustup','toolchain','link','ohm-declared-proof',kit],env=env,cwd=lane,check=True)
observe=lane/'calls';observe.mkdir();env.update(OBSERVE=str(observe),NATIVE_PROJECT=str(project),CARGO_INCREMENTAL='1')
host=subprocess.check_output(['rustc','+ohm-declared-proof','-vV'],env=env,text=True).split('host: ')[1].splitlines()[0]
if mode!='default':env['CARGO_TARGET_'+host.upper().replace('-','_')+'_LINKER']=str(driver)
records=[]
def step(name,expected,links=None):
 (observe/'links').write_text('')
 argv=['cargo','+ohm-declared-proof','build','--bins','--offline','-vv']
 trace=lane/(name+'.strace')
 if mode=='default' and platform.system()=='Linux':
  argv=['strace','-ff','-qq','-s','65535','-e','trace=execve','-o',str(trace),*argv]
 with (lane/(name+'.log')).open('wb') as out: r=subprocess.run(argv,cwd=project,env=env,stdout=out,stderr=subprocess.STDOUT)
 assert r.returncode==0,(name,r.returncode)
 vals=[subprocess.check_output([lane/'target/debug'/n],text=True).strip() for n in ('first','second')]
 count=len((observe/'links').read_text().splitlines())
 targets=[]
 if mode=='default' and platform.system()=='Linux':
  traces=sorted(lane.glob(name+'.strace.*'));assert traces,(name,'no per-process exec traces')
  import ast,re
  for line in (line for path in traces for line in path.read_text(errors='replace').splitlines()):
   match=re.search(r'execve\((".*?"), (\[.*?\]), (?:0x|\[|/\*).*?\)\s+= 0$',line)
   if not match:continue
   exe=Path(ast.literal_eval(match[1]));args=ast.literal_eval(match[2])
   if exe.name not in {'ld','ld.bfd','ld.lld','wild-ld','wild','rust-lld','x86_64-linux-gnu-ld','x86_64-linux-gnu-ld.bfd'} or '-o' not in args:continue
   path=Path(args[args.index('-o')+1])
   m=re.fullmatch(r'(first|second)(?:-[0-9a-f]+)?',path.name)
   if m and path.is_relative_to(lane):targets.append((m[1],str(exe)))
  count=len(targets)
  expected_targets=[] if name.startswith('warm') else ['first','second']

 records.append(dict(step=name,values=vals,links=count,physical=targets));(lane/'results.json').write_text(json.dumps(records,indent=2)+'\n')
 print(name,vals,count,flush=True)
 assert vals==[expected,expected],(name,expected,vals)
 if mode=='default' and platform.system()=='Linux':
  assert sorted(t[0] for t in targets)==expected_targets,(name,targets)
  assert all('/wild-ld/' in exe for _,exe in targets),(name,targets)
 if links is not None:assert count==links,(name,count,links)
step('cold','17:3' if mode=='mixed' else '17')
step('warm','17:3' if mode=='mixed' else '17',0 if mode=='private' else None)
if mode=='private':
 old=config.stat();config.write_text('1\n');os.utime(config,ns=(old.st_atime_ns,old.st_mtime_ns))
 step('declared-private-change','41',2);step('warm-after-private','41',0)
elif mode=='mixed':
 lib('native','extra',9,True);step('rust-declared-second-archive','17:9',2)
elif mode=='shadow':
 lib('earlier','answer',29);step('higher-priority-archive','29',2)
elif mode=='default':
 lib('native','answer',29,True);step('native-edit','29');step('warm-again','29')
