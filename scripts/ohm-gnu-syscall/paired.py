"""Two original Ruff edits to full CLI builds, enrolled against private clean same-path artifacts."""
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/'ohm-gnu-ty-input-census')]
import census
import cli
from bootstrap import rt, CHILD, PARENT
from restore_prior import DRIVER
def sha(value):return hashlib.sha256(value).hexdigest()
def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as out:out.write(data)
def check_clock(row):
    assert row['code']==0 and row['stop']>row['start'] and row['user_us']+row['system_us']>0
    return row['event_errno']==0 and row['instructions']>0 and row['enabled']>0 and row['running']>=.995*row['enabled']

def calibrate(out,watch,loop):
    out.mkdir()
    cases=[('0','1'),('1','1'),('2','1'),('2','2'),('exec','1'),('thread','1'),('thread','2')]
    observations=[];answers=[]
    n=80000000
    for depth,copies in cases:
        values=[]
        for iters in (0,n,0,n):
            ident=str(len(observations))
            result=out/(ident+'.json')
            subprocess.run([watch,result,loop,depth,str(iters),copies],check=True)
            r=rt.load(result);hardware=check_clock(r)
            values.append(r);observations.append({'depth':depth,'copies':copies,'iters':iters,'receipt':rt.sha(result),'hardware':hardware})
        lo=[x['instructions'] for x in values[::2]];hi=[x['instructions'] for x in values[1::2]]
        wanted=2*n*int(copies)
        delta=statistics.median(hi)-statistics.median(lo)
        cpu=lambda x:x['user_us']+x['system_us']
        delta_cpu=statistics.median(map(cpu,values[1::2]))-statistics.median(map(cpu,values[::2]))
        answers.append({'depth':depth,'copies':copies,'expected':wanted,'delta':delta,'cpu_delta':delta_cpu})
    hardware=all(x['hardware'] for x in observations) and all(abs(x['delta']/x['expected']-1)<.02 for x in answers)
    one=answers[0]['cpu_delta']
    tree_cpu=one>7000 and all(.45*one*int(x['copies'])<=x['cpu_delta']<=2.3*one*int(x['copies']) for x in answers)
    rt.save(out/'summary.json',{'rows':observations,'checks':answers,'whole_tree_hw':hardware,'tree_cpu':tree_cpu})
    return hardware,tree_cpu

def run_logged(cmd,cwd,env,d):
    d.mkdir()
    p=subprocess.run(cmd,cwd=cwd,env=env,capture_output=True,timeout=3900)
    census.blob(d/'stdout.gz',p.stdout);census.blob(d/'stderr.gz',p.stderr)
    assert p.returncode==0,p.stderr[-2000:]
    return p.stdout

def product(data,src,env,old,out):
    messages=[json.loads(x) for x in data.splitlines()]
    assert messages[-1]=={'reason':'build-finished','success':True}
    units=[m for m in messages if m['reason']=='compiler-artifact']
    matches=[x for x in units if x['target']['name']=='ruff' and x['target']['kind']==['bin'] and x.get('executable')]
    assert len(matches)==1
    f=Path(matches[0]['executable']).resolve(strict=True)
    roster=sorted(json.dumps([m[k] for k in ('package_id','target','features','profile')],sort_keys=True,separators=(',',':')) for m in units)
    dirty=sorted(m['target']['name'] for m in units if not m['fresh'])
    return {'roster':sha(json.dumps(roster).encode()),'unit_count':len(units),'dirty':dirty},f

def private_bytes(work):
    unique={};sessions=collections.Counter();raw=[]
    for directory in [work/'target',work/'shared']:
        assert directory.is_dir() and not directory.is_symlink()
        for root,dirs,files in os.walk(directory,followlinks=False):
            rel=Path(root)
            paths=([rel] if rel==directory else [])+[rel/x for x in sorted(dirs+files)]
            for p in paths:
                st=p.lstat();key=(st.st_dev,st.st_ino)
                record=(st.st_size,st.st_blocks,st.st_mode)
                assert unique.setdefault(key,record)==record
                raw.append([p.relative_to(work).as_posix(),*key,*record])
                if p.name.startswith('s-') and p.parent.parent.name=='incremental':sessions[p.parent.relative_to(work).as_posix()]+=1
    return 512*sum(v[1] for v in unique.values()),raw,dict(sessions)

def actual_pair(role,out,stable,watch,hw,cpu):
    out.mkdir();donor=Path(os.environ['CENSUS_PARENT'])
    native=rt.ROOT/'candidate-sdk'
    original=rt.load(rt.LOG/'candidate.json')
    assert original['driver'][0]==DRIVER
    driver=stable/original['driver_path'];temp=driver.with_name('new-study-driver')
    source=(donor if role=='P' else native)/original['driver_path']
    if not driver.samefile(source):
        os.link(source,temp);temp.replace(driver)
    assert not temp.exists()
    after=rt.sha(driver)
    assert (after==DRIVER)==(role=='C')
    os.environ['CENSUS_SDK']=str(stable)
    if role=='C':os.environ['CENSUS_CANDIDATE_RECORD']=str(rt.LOG/'candidate.json')
    else:os.environ.pop('CENSUS_CANDIDATE_RECORD',None)
    work,receipts,src,env=census.acquire(cli.OLD,cli.NEW,cli.TREES,cli.LOCK,cli.FILES,cli.CLI)
    assert not {'CI','RUSTFLAGS','CARGO_INCREMENTAL','CARGO_ENCODED_RUSTFLAGS','RUSTC_WRAPPER','LD_PRELOAD'}&env.keys()
    enrol=rt.load(receipts/'enrolled.json');assert enrol['compiler']['source']==(PARENT if role=='P' else CHILD)
    rt.save(out/'enrolment.json',enrol)
    cmd=cli.CLI
    cold=run_logged(cmd,src,env,out/'cold')
    old,exe=product(cold,src,env,True,out/'cold');actual=cli.cli_product(exe,True,out/'cold',src,env)
    assert actual['verdicts']['starred']==[('PLE0643',2)] and old['unit_count']==372
    census.command(['git','restore','--source',cli.NEW,'--staged','--worktree','--','.'],src,env)
    assert census.command(['git','write-tree'],src,env)==cli.TREES[cli.NEW] and not census.command(['git','diff','--name-only'],src,env)
    assert rt.sha(src/'Cargo.lock')==cli.LOCK
    for step in ('edit','repeat'):(out/step).mkdir()
    # No reads or probes of the program, compiler, or private build directories between these commands.
    for step in ('edit','repeat'):
        where=out/step
        with (where/'stdout.raw').open('xb') as stdout,(where/'stderr.raw').open('xb') as stderr:
            p=subprocess.run([watch,where/'clock.json',*cmd],cwd=src,env=env,stdout=stdout,stderr=stderr,timeout=2400)
        assert p.returncode==0
    samples={}; roster={}
    for step in ('edit','repeat'):
        where=out/step
        c=rt.load(where/'clock.json');valid=check_clock(c); assert not hw or valid
        for stream in ('stdout','stderr'):
            raw=where/(stream+'.raw');b=raw.read_bytes();census.blob(where/(stream+'.gz'),b);raw.unlink()
            if stream=='stdout':stdout=b
        row,returned=product(stdout,src,env,False,where);assert returned==exe and row['roster']==old['roster']
        is_dirty={v in row['dirty'] for v in ('rustix','tempfile','terminal_size')}
        assert is_dirty=={role=='P'},(step,role,row['dirty'])
        if step=='edit':assert 'ruff_linter' in row['dirty']
        roster[step]=row;samples[step]=c
    actual_new=cli.cli_product(exe,False,out/'repeat',src,env)
    assert actual_new['verdicts']['starred']==[] and actual['sha256']!=actual_new['sha256']
    allocated,files,sessions=private_bytes(work)
    census.blob(out/'disk-inodes.json.gz',json.dumps(sorted(files),separators=(',',':')).encode())
    rt.save(out/'disk.json',{'allocated':allocated,'count':len(files),'sessions':sessions})
    for n in ('target','shared'):
        path=work/n
        assert path.parent==work and path.is_dir() and not path.is_symlink()
        shutil.rmtree(path)
    clean=run_logged(cmd,src,env,out/'independent-empty')
    same,clean_exe=product(clean,src,env,False,out/'independent-empty')
    clean_new=cli.cli_product(clean_exe,False,out/'independent-empty',src,env)
    assert same['roster']==old['roster'] and clean_new==actual_new,(role,clean_new,actual_new)
    assert after==rt.sha(driver) and census.command(['git','write-tree'],src,env)==cli.TREES[cli.NEW]
    measurements={s:{'elapsed_ns':v['stop']-v['start'],'tree_cpu_us':v['user_us']+v['system_us'] if cpu else None,'user_instructions':v['instructions'] if hw else None} for s,v in samples.items()}
    measurements['edit+repeat']={'elapsed_ns':samples['repeat']['stop']-samples['edit']['start'],
        'tree_cpu_us':sum(v['tree_cpu_us'] for v in measurements.values()) if cpu else None,
        'user_instructions':sum(v['user_instructions'] for v in measurements.values()) if hw else None}
    result={'role':role,'compiler':enrol['compiler'],'cargo':enrol['cargo_sha'],'native':{'old':actual,'new':actual_new,'empty':clean_new},
            'commands':cmd,'measurements':measurements,'hardware_pass':hw,'tree_cpu_pass':cpu,'graph':roster,'disk':allocated}
    rt.save(out/'terminal.json',result)
    assert work==rt.ROOT/'ordinary-ruff' and not work.is_symlink()
    shutil.rmtree(work)
    return result

def main():
    order=sys.argv[1]; assert order in ('PC','CP')
    rt.room();out=rt.LOG/'paired';out.mkdir()
    stable=rt.ROOT/'paired-sdk';shutil.copytree(Path(os.environ['CENSUS_PARENT']),stable,copy_function=os.link)
    tools=rt.ROOT/'observer';tools.mkdir();watch=tools/'watch';loop=tools/'calibrate'
    for src,bin in [(HERE/'watch.c',watch),(HERE/'calibrate.c',loop)]:
        subprocess.run(['cc','-std=c11','-O2','-pthread','-Wall','-Wextra','-Werror',str(src),'-o',str(bin)],check=True)
    hw,cpu=calibrate(out/'calibration',watch,loop)
    rt.save(out/'registration.json',{'order':order,'source':[PARENT,CHILD],'driver':DRIVER,'argv':cli.CLI,
            'primary':'first unchanged cargo build after Ruff 193984681e','hardware':'only after direct, fork, grandchild, duplicate argv, same-pid exec and one/two simultaneous worker-thread calibrations',
            'clock':'measured alongside native process-tree CPU; all scheduled work included','binary':'edited product, isolated rule verdicts and independent same-path, empty two-root build'})
    os.environ['CENSUS_ROOT']=str(rt.ROOT/'ordinary-ruff')
    arms={r:actual_pair(r,out/r,stable,watch,hw,cpu) for r in order}
    assert arms['P']['graph']['edit']['roster']==arms['C']['graph']['edit']['roster'] and arms['P']['cargo']==arms['C']['cargo']
    answer={name:{metric:[arms[role]['measurements'][name][metric] for role in 'PC'] for metric in ('elapsed_ns','tree_cpu_us','user_instructions')} for name in ('edit','repeat','edit+repeat')}
    rt.save(out/'pair.json',{'order':order,'endpoints':answer,'sdk':{'parent':PARENT,'candidate':CHILD,'cargo':arms['P']['cargo']},'return_hashes':{r:arms[r]['native']['new']['sha256'] for r in 'PC'},'storage':{r:arms[r]['disk'] for r in 'PC'}})
    print('Matched complete Ruff CLI pair',out/'pair.json',flush=True)
if __name__=='__main__':main()
