"""Physical outputs for the unmodified historical help edit on Linux."""
import hashlib,json,os,re,shutil,subprocess as sp,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=Path(os.environ['RUNNER_TEMP']).resolve(strict=True)/'ohm-clap-cli'
PUB=ROOT/'ordinary';DIAG=ROOT/'diagnostic';SDKBASE=ROOT/'dist';SDK=SDKBASE/'sdk';RUSTUP=SDKBASE/'rustup'
WORK=Path(os.environ['GITHUB_WORKSPACE']).resolve(strict=True)/'ruff'
TARGET,BUILD,HOME=(ROOT/x for x in ('target','build','cargo-home'))
OLD='f3280423f6c535690287e8169c25929f8d6433ce';NEW='d136bd8d002a648de5f344df602e492658306f1e'
LOCK='fea1c04b2bce37f54c14449e8402528e652f4e5b9fcd366c118c360d439924c8'
SRC=WORK/'crates/ruff/src/args.rs'
SRCS={OLD:'755cb07af1ecffa4469f80d955402f6ca9a7c2f00d27040b8df26ce06689167f',NEW:'df7501dec81e30c999ef4a44cd7f9ceb7a1e9633845338c2b3d948f1df7c8f78'}
WILD='lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd'
MODE=os.environ['OHM_STUDY_MODE'];assert MODE in ('build','check')
CMD=['cargo','+ohm',MODE,'-p','ruff','--bin','ruff']
def need(value,msg):
    if not value:raise ValueError(msg)
def hf(path):
    with path.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def put(p,data):p.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
def git(*args):return sp.check_output(['git',*args],cwd=WORK,text=True).strip()
def select(sha):
    git('switch','--detach',sha)
    need(git('rev-parse','HEAD')==sha and hf(SRC)==SRCS[sha] and hf(WORK/'Cargo.lock')==LOCK and not git('status','--porcelain'), 'different Ruff inputs')
def guard():
    avail=int(next(s.split()[1]for s in Path('/proc/meminfo').read_text().splitlines()if s.startswith('MemAvailable:')))*1024
    need(avail>8*2**30 and shutil.disk_usage(ROOT).free>15*2**30,'resource reserve')
def env():
    e={k:os.environ[k] for k in ('HOME','PATH','USER','LANG') if k in os.environ}
    e.update(RUSTUP_HOME=str(RUSTUP),CARGO_HOME=str(HOME),CARGO_TARGET_DIR=str(TARGET),CARGO_BUILD_BUILD_DIR=str(BUILD),
             CARGO_NET_GIT_FETCH_WITH_CLI='true',CARGO_BUILD_JOBS='4',CARGO_NET_OFFLINE='true',CARGO_TERM_COLOR='never')
    return e
def prepare():
    marker=ROOT/'selected-binary-input.json'
    if marker.is_file():marker.unlink()
    need(not any(q.exists() for q in (TARGET,BUILD,HOME)),'previous outputs survived fresh setup')
    e=env();e.pop('CARGO_NET_OFFLINE')
    sp.run(['cargo','+ohm','fetch','--locked','--target','x86_64-unknown-linux-gnu'],cwd=WORK,env=e,check=True)
    need(hf(WORK/'Cargo.lock')==LOCK,'fetch modified lockfile')
def zsave(p,base):
    digest=hf(p);base.mkdir(exist_ok=True);dest=base/(digest+'.zst')
    if not dest.exists():
        with dest.open('xb')as f:sp.run(['zstd','-q','-3','-c',p],stdout=f,check=True)
    return digest
def crate_arg(argv,flag):
    for i,arg in enumerate(argv):
        if arg==flag and i+1<len(argv):return argv[i+1]
        if arg.startswith(flag+'='):return arg[len(flag)+1:]
    return None
def see_rustcs(seen,records,identity):
    for entry in os.scandir('/proc'):
        if not entry.name.isdigit() or entry.name in seen:continue
        q=Path(entry.path)
        try:
            st=(q/'exe').stat()
            if (st.st_dev,st.st_ino)!=identity:continue
            args=[os.fsdecode(v)for v in (q/'cmdline').read_bytes().split(b'\0')if v]
            seen.add(entry.name)
            if crate_arg(args,'--crate-name')!='ruff':continue
            cwd=Path(os.readlink(q/'cwd'));selected=[]
            for i,arg in enumerate(args):
                b=args[i+1] if arg=='--extern'and i+1<len(args)else arg.removeprefix('--extern=')if arg.startswith('--extern=')else ''
                name,eq,path=b.partition('=')
                if eq and name.split(':')[-1]=='ruff':selected.append(str((cwd/path).absolute()))
            records.append({'pid':int(entry.name),'identity':list(identity),'cwd':str(cwd),'argv':args,
                            'kind':crate_arg(args,'--crate-type'),'out':crate_arg(args,'--out-dir'),'consumer_inputs':selected})
        except (FileNotFoundError,ProcessLookupError,PermissionError):continue
def source_files(directory):
    observations=json.loads((directory/'real-ruff-rustcs.json').read_bytes())
    selected={Path(s)for row in observations if row['kind']=='bin'for s in row['consumer_inputs']}
    marker=ROOT/'selected-binary-input.json'
    if not selected and marker.is_file():
        selected={Path(s)for s in json.loads(marker.read_bytes())}
    if not selected:
        # A very fast binary rustc can finish between reads. Restrict enumeration to a
        # real complete producer's actual --out-dir, checking the actual crate identity.
        possible=set()
        for row in observations:
            if row['kind'] in ('lib','rlib') and row['out']:
                o=(Path(row['cwd'])/row['out']).resolve(strict=True)
                for p in o.iterdir():
                    if re.fullmatch(r'libruff(?:-[a-zA-Z0-9_]+)?\.'+('rlib'if MODE=='build'else 'rmeta'),p.name):
                        possible.add(p)
        selected=possible
    if not selected:
        files=[]
        for root in (TARGET,BUILD,HOME,WORK/'target'):
            if root.exists():
                for directory_name,dirs,names in os.walk(root):
                    for name in names:
                        if re.match(r'(?:lib)?ruff(?:[-.]|$)',name)and name.endswith(('.rmeta','.rlib')):files.append(str(Path(directory_name)/name))
        put(directory/'unresolved-native-layout.json',{'path_candidates':files,'actual_rustcs':observations})
    types={p.suffix for p in selected}
    need(selected and len(types)==len(selected) and types<={'.rlib','.rmeta'}
         and (MODE!='check'or '.rmeta'in types),('ambiguous actual ruff inputs',list(map(str,selected))))
    bindings={}
    for chosen in sorted(selected):
        need(chosen.is_file()and chosen.stat().st_size>0,('missing true input',str(chosen)))
        real=chosen.resolve(strict=True)
        need(any(real.is_relative_to(root.resolve())for root in (TARGET,BUILD,HOME)),('dependency outside enrolled independent roots',str(chosen),str(real)))
        bindings[str(chosen)]=str(real)
    put(marker,sorted(bindings));put(directory/'selected-artifact.json',bindings)
    return sorted(selected)
def verdict(exe,directory,state):
    e=env()|{'NO_COLOR':'1','COLUMNS':'240','LC_ALL':'C','TERM':'dumb','RUFF_NO_CACHE':'true'}
    expected=b'lint.line-length = 100' if state==OLD else b'line-length = 100'
    cases={'help':['--help'],'check-help':['check','--help'],'format-help':['format','--help'],
           'valid-config':['check','--isolated','--config','line-length = 100','--select','F401','-'],
           'invalid-config':['check','--isolated','--config','lint.line-length = 100','-']}
    matches=[];result={}
    for label,tail in cases.items():
        v=sp.run([exe,*tail],input=b'import os\n' if label=='valid-config' else b'x=1\n',cwd=WORK,env=e,capture_output=True,timeout=30)
        (directory/(label+'.stdout')).write_bytes(v.stdout);(directory/(label+'.stderr')).write_bytes(v.stderr)
        if label.endswith('help'):
            need(v.returncode==0 and not v.stderr,(label,v.returncode,v.stderr[-200:]))
            msg=b' '.join(v.stdout.split())
            if b'--config "'+expected+b'"' in msg:matches.append(label)
            if state==NEW:need(b'lint.line-length = 100'not in msg,'old help in edited source')
        elif label=='valid-config':
            need(v.returncode==1 and b'F401'in v.stdout and b'os'in v.stdout and not v.stderr,(label,v.returncode,v.stdout[-300:],v.stderr[-300:]))
        else:need(v.returncode==2 and b'--config'in v.stderr and b'line-length'in v.stderr,(label,v.returncode,v.stdout[-200:],v.stderr[-200:]))
        result[label]={'exit':v.returncode,'out':hashlib.sha256(v.stdout).hexdigest(),'err':hashlib.sha256(v.stderr).hexdigest()}
    need(bool(matches),('no true global config help',state))
    return {'cases':result,'show_example':matches}
def observe_products(directory,state):
    inputs=source_files(directory);base=PUB/'bodies';data={}
    for selected in inputs:
        if selected.suffix=='.rmeta':
            data['rmeta']={'name':selected.name,'size':selected.stat().st_size,'sha256':zsave(selected,base)}
        else:
            import member_names
            data['rlib']={'name':selected.name,'size':selected.stat().st_size,'sha256':hf(selected)}
            try:
                ledger=member_names.read_names(selected,'ruff')
            except (ValueError,KeyError)as error:
                # Preserve the full original if this SDK has an unsupported envelope.
                # The complete CLI ELF, actual external paths and raw library stay mandatory.
                put(directory/'unrecognized-library-envelope.json',{'error':str(error),'raw_body':zsave(selected,base)})
            else:
                put(directory/'selected-ruff-members.json',ledger)
                # native_identity includes the complete lib.rmeta-link ELF with only the
                # invocation nonce in each proven native filename replaced.
                actual_meta=[item for item in ledger['metadata']if item[0]=='lib.rmeta']
                need(len(actual_meta)==1,'missing native Rust metadata')
                proof=[member_names.native_identity(ledger),actual_meta]
                data['canonical_archive']=hashlib.sha256(json.dumps(proof,separators=(',',':')).encode()).hexdigest()
            meta=directory/'embedded-rust-metadata'
            with meta.open('xb')as f:sp.run(['ar','p',selected,'lib.rmeta'],stdout=f,check=True)
            need(meta.stat().st_size>0,'missing selected native metadata')
            data['embedded_rmeta']={'size':meta.stat().st_size,'sha256':zsave(meta,base)}
            meta.unlink()
    if MODE=='build':
        exe=TARGET/'debug/ruff';need(exe.is_file(),'missing native CLI')
        data['elf']={'size':exe.stat().st_size,'sha256':zsave(exe,base)}
        data['verdict']=verdict(exe,directory,state)
    return data
def same_artifacts(a,b):
    if a==b:return True
    if not all(v.get('canonical_archive')and v.get('rlib')for v in (a,b)):return False
    # All ELF member bytes, stable names, ranlib symbol mapping, physical metadata,
    # original user-visible outputs and the entire CLI executable still compare exactly.
    return {k:v for k,v in a.items()if k!='rlib'}=={k:v for k,v in b.items()if k!='rlib'}
def command(directory,actual,expected=0):
    directory.mkdir()
    physical=(SDK/'bin/rustc').stat();identity=(physical.st_dev,physical.st_ino)
    seen=set();records=[]
    with (directory/'stdout').open('xb')as out,(directory/'stderr').open('xb')as err:
        p=sp.Popen(actual,env=env(),cwd=WORK,stdout=out,stderr=err)
        while p.poll()is None:
            see_rustcs(seen,records,identity)
            time.sleep(.012)
    put(directory/'real-ruff-rustcs.json',records)
    need(p.returncode==expected,(directory.name,p.returncode,(directory/'stderr').read_text(errors='replace')[-800:]))
