"""Physical outputs for the unmodified historical help edit on Linux."""
import hashlib,json,os,shutil,subprocess as sp,sys
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
    need(not any(q.exists() for q in (TARGET,BUILD,HOME)),'previous outputs survived fresh setup')
    e=env();e.pop('CARGO_NET_OFFLINE')
    sp.run(['cargo','+ohm','fetch','--locked','--target','x86_64-unknown-linux-gnu'],cwd=WORK,env=e,check=True)
    need(hf(WORK/'Cargo.lock')==LOCK,'fetch modified lockfile')
def zsave(p,base):
    digest=hf(p);base.mkdir(exist_ok=True);dest=base/(digest+'.zst')
    if not dest.exists():
        with dest.open('xb')as f:sp.run(['zstd','-q','-3','-c',p],stdout=f,check=True)
    return digest
def artifact_paths():
    # The dedicated unit test of the library is never requested. Reject a second real candidate.
    by={}
    for base in (TARGET,BUILD):
        for pattern,kind in [('libruff-*.rmeta','rmeta'),('libruff-*.rlib','rlib')]:
            for p in base.glob('**/deps/'+pattern):
                if p.is_file() and p.stat().st_size:by.setdefault(kind,[]).append(p)
    for kind,paths in by.items():
        need(len({(p.stat().st_dev,p.stat().st_ino)for p in paths})==1,(kind,'ambiguously selected Ruff product',list(map(str,paths))))
    need('rmeta' in by,'unseen Ruff library metadata')
    return {kind:paths[0] for kind,paths in by.items()}
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
    p=artifact_paths();base=PUB/'bodies'
    data={name:{'name':v.name,'size':v.stat().st_size,'sha256':zsave(v,base)if name=='rmeta' else hf(v)}for name,v in p.items()}
    if MODE=='build':
        exe=TARGET/'debug/ruff';need(exe.is_file(),'missing native CLI')
        data['elf']={'size':exe.stat().st_size,'sha256':zsave(exe,base)}
        data['verdict']=verdict(exe,directory,state)
    return data
def command(directory,actual,expected=0):
    directory.mkdir()
    with (directory/'stdout').open('xb')as out,(directory/'stderr').open('xb')as err:p=sp.run(actual,env=env(),cwd=WORK,stdout=out,stderr=err)
    need(p.returncode==expected,(directory.name,p.returncode,(directory/'stderr').read_text(errors='replace')[-800:]))
