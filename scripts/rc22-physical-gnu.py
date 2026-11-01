"""Count actual native linker processes on the new Linux package with its default driver."""
import ast,hashlib,json,os,re,shutil,subprocess,tarfile,tempfile
from pathlib import Path
root=Path(os.environ['RUNNER_TEMP'])/'rc22-physical-gnu';root.mkdir()
reports=root/'reports';reports.mkdir();assets=Path('release').resolve()
distribution=next(assets.glob('*.tar.gz')); expect=(assets/(distribution.name+'.sha256')).read_text().split()[0]
actual=hashlib.file_digest(distribution.open('rb'),'sha256').hexdigest(); assert actual==expect
for d in ('extract','home','rustup','cargo','tmp'):(root/d).mkdir()
with tarfile.open(distribution) as tf:tf.extractall(root/'extract',filter='data')
inner=root/'extract/rust-1.99.0-dev-x86_64-unknown-linux-gnu/install.sh'
assert inner.is_file() and not inner.is_symlink()
sdk=root/'sdk'
env=dict(HOME=str(root/'home'),PATH=os.environ['PATH'],RUSTUP_HOME=str(root/'rustup'),CARGO_HOME=str(root/'cargo'),TMPDIR=str(root/'tmp'),LC_ALL='C',CARGO_INCREMENTAL='1')
with (reports/'inner-install.log').open('wb') as f:subprocess.run(['sh',str(inner),'--prefix='+str(sdk),'--disable-ldconfig'],env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
alias='ohm-rc22-physical';subprocess.run(['rustup','toolchain','link',alias,str(sdk)],env=env,check=True)
versions={k:subprocess.check_output([k,'+'+alias,'-vV'],env=env,text=True) for k in ('rustc','cargo')}
assert '1bc7b35699479d5899a2935d79392b7bdaf7497d' in versions['rustc'] and '4591cf45cc10abb19d2456c40b99606e08167f29' in versions['cargo']
smoke=Path('scripts/smoke-test-relink.sh').resolve()
assert hashlib.sha256(smoke.read_bytes()).hexdigest()=='e57b87041abe1f91c78c29bb26e276e7ccd41e8f33a360aec616fb260d7ec175'
with (reports/'strict-smoke.log').open('wb') as f:
    strict=subprocess.run(['bash',str(smoke),alias,str(root/'strict')],env=env,stdout=f,stderr=subprocess.STDOUT).returncode
negative=(reports/'strict-smoke.log').read_text()
if strict:assert re.search(r'Expected 0 linker calls for two executables returning 17, observed\s+2',negative),negative[-1800:]
project=root/'default';project.mkdir()
orig=root/'strict/declared'
for f in ('Cargo.toml','engine/Cargo.toml','engine/src/lib.rs','src/bin/first.rs','src/bin/second.rs'):
    dest=project/f;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(orig/f,dest)
assert 'asm!' in (project/'engine/src/lib.rs').read_text()
text=(orig/'build.rs').read_text().splitlines()
assert len([x for x in text if 'cargo::rerun-if-changed=' in x])==1
(project/'build.rs').write_text('\n'.join('    println!("cargo::rerun-if-changed=native/libanswer.a");' if 'cargo::rerun-if-changed=' in x else x for x in text)+'\n')
(project/'native').mkdir();env.update(CARGO_TARGET_DIR=str(root/'target'),CARGO_BUILD_BUILD_DIR=str(root/'build'))
def archive(value):
    m=root/('member-'+str(value));m.mkdir()
    subprocess.run(['cc','-x','c','-c','-o','answer.o','-'],env=env,cwd=m,input=f'int answer(void) {{ return {value}; }}\n'.encode(),check=True)
    subprocess.run(['ar','rcs','libanswer.a','answer.o'],env=env,cwd=m,check=True)
    shutil.copyfile(m/'libanswer.a',project/'native/libanswer.a')
records=[]
ldnames={'ld','ld.bfd','ld.lld','rust-lld','wild','wild-ld','x86_64-linux-gnu-ld','x86_64-linux-gnu-ld.bfd','x86_64-linux-gnu-ld.lld'}
def stage(name,value):
    d=reports/name;d.mkdir()
    with (d/'cargo.log').open('wb') as f:
        subprocess.run(['strace','-ff','-v','-s','65535','-e','trace=execve,execveat','-o',str(d/'exec'),'cargo','+'+alias,'build','--bins','--offline','-vv'],env=env,cwd=project,stdout=f,stderr=subprocess.STDOUT,check=True)
    values=[subprocess.check_output([root/'target/debug'/b],env=env,text=True).strip() for b in ('first','second')];assert values==[str(value)]*2,(name,values)
    events=[];targets=set()
    for f in d.glob('exec.*'):
        for line in f.read_text(errors='replace').splitlines():
            if not (line.startswith('execve(') and re.search(r'\)\s+= 0$',line)):continue
            exe,sep,rest=line[7:].partition(', [')
            if not sep:continue
            exe=ast.literal_eval(exe);argv,sep,_=rest.partition('], [')
            if not sep:continue
            if Path(exe).name not in ldnames:continue
            args=ast.literal_eval('['+argv+']')
            if '-o' not in args:continue
            out=args[args.index('-o')+1];b=re.fullmatch(r'(first|second)(?:-[0-9a-f]+)?',Path(out).name) if Path(out).is_relative_to(root/'target') else None
            if b:events.append(dict(pid=f.suffix[1:],exe=exe,output=out));targets.add(b[1])
    if name in ('initial','changed'):assert targets=={'first','second'},(name,events)
    records.append(dict(stage=name,values=values,links=events,outputs=sorted(targets)))
    (reports/'results.json').write_text(json.dumps(dict(distribution=actual,versions=versions,strict_exit=strict,stages=records),indent=2)+'\n')
archive(17);stage('initial',17);stage('unchanged',17);archive(29);stage('changed',29);stage('unchanged-again',29)
print([(r['stage'],r['outputs'],r['values']) for r in records])
