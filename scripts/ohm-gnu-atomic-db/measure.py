"""One preregistered, fresh balanced pair of ordinary cross-target Ruff library commands."""
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent/'ohm-gnu-syscall')]
import sdk
from sdk import census
import consumer
import screen
import paired

CMD = ['cargo','+ohm','build','-p','ruff_db','--lib','--target',census.TARGET,
       '--locked','--offline','-j4','--message-format=json']
REGISTERED = json.loads((HERE/'registered.json').read_text())


def graph(messages):
    assert messages[-1] == {'reason':'build-finished','success':True}
    units = [m for m in messages if m['reason'] == 'compiler-artifact']
    assert len(units) == 174
    roster = sorted(json.dumps([r[k] for k in ('package_id','target','features','profile')],sort_keys=True)
                    for r in units)
    names = sorted(m['target']['name'] for m in units if not m['fresh'])
    root, = [m for m in units if m['target']['name']=='ruff_db' and m['target']['kind']==['lib'] and not m['profile']['test']]
    archive, = (Path(f) for f in root['filenames'] if f.endswith('.rlib'))
    return {'roster':census.digest('\n'.join(roster).encode()), 'units':len(units),'dirty':names}, archive


def change_source(src,env):
    census.command(['git','restore','--source',screen.NEW,'--staged','--worktree','--','.'],src,env)
    assert census.command(['git','write-tree'],src,env)==screen.TREES[screen.NEW]
    assert not census.command(['git','diff','--name-only'],src,env) and census.sha(src/'Cargo.lock')==screen.LOCK


def confirm_output(messages, src, env, out, inputs, old=False):
    archive, details = screen.witness(messages,'build',out,src,env,old=old)
    upstream = json.loads((out/'archive-members.json').read_text())
    assert upstream['raw']==details['sha256'] and len(upstream['objects'])==216
    details['consumer'] = consumer.run(inputs,archive,env,src,out/'downstream',old=old)
    census.save(out/'checked-product.json',details)
    return details, sorted((name,size,sha) for name,_,size,sha in upstream['objects'])


def measured_commands(out,src,env,watch):
    for label in ('edit','repeat'):
        (out/label).mkdir()
    # No reads of the program, private build directories or compiler between edit and repeat.
    for label in ('edit','repeat'):
        d=out/label
        with (d/'stdout.raw').open('xb') as stdout, (d/'stderr.raw').open('xb') as stderr:
            p=subprocess.run([watch,d/'clock.json',*CMD],cwd=src,env=env,stdout=stdout,stderr=stderr,timeout=2400)
        assert p.returncode==0
    result={}
    for label in ('edit','repeat'):
        d=out/label
        for name in ('stdout','stderr'):
            raw=d/(name+'.raw')
            census.blob(d/(name+'.gz'),raw.read_bytes())
            raw.unlink()
        clock=json.loads((d/'clock.json').read_text())
        assert paired.check_clock(clock),clock
        messages=[json.loads(line) for line in gzip.decompress((d/'stdout.gz').read_bytes()).splitlines()]
        roster,path=graph(messages)
        result[label]=(clock,roster,path,messages)
    return result


def arm(role,out,watch):
    out.mkdir()
    work,receipts,src,env=sdk.acquire(role,CMD)
    assert not {'CI','RUSTFLAGS','CARGO_INCREMENTAL','RUSTC_WRAPPER','LD_PRELOAD','GITHUB_TOKEN','GH_TOKEN'}&env.keys()
    enrolled=json.loads((receipts/'enrolled.json').read_text())
    cold,messages,native=census.trace_build('old',work,receipts,src,env,CMD)
    deps=consumer.args_from_training(native,src)
    old,old_objects=confirm_output(messages,src,env,cold,deps,old=True)
    old_graph,_=graph(messages)
    assert len(old_graph['dirty'])==174
    change_source(src,env)
    measured=measured_commands(out,src,env,watch)
    for label,(_,r,_,_) in measured.items():
        expected=['portable_atomic','ruff_db','salsa'] if role=='P' else ['ruff_db'] if label=='edit' else []
        assert r['dirty']==expected and r['roster']==old_graph['roster'],(role,label,r)
    assert measured['edit'][2]==measured['repeat'][2]
    allocated,inodes,sessions=paired.private_bytes(work)
    census.blob(out/'disk-inodes.json.gz',json.dumps(sorted(inodes),separators=(',',':')).encode())
    census.save(out/'disk.json',{'unique_allocated_bytes':allocated,'entries':len(inodes),'sessions':sessions})
    warm,objects=confirm_output(measured['repeat'][3],src,env,out/'repeat',deps)
    assert old['consumer']['elf']!=warm['consumer']['elf'] and old_objects!=objects
    settled,msg,k=census.trace_build('physical-repeat',work,receipts,src,env,CMD)
    assert graph(msg)[0]==measured['repeat'][1]
    assert [(r['crate'],r['link_only'],r['terminal']) for r in k['rustcs']]==([('portable_atomic',False,[0])] if role=='P' else [])
    assert not k['link_tools']
    # A malformed edit and repair exercise the same private target after the scored commands.
    (src/screen.FILE).write_text((src/screen.FILE).read_text()+'\nconst _: usize = '+screen.INVALID+';\n')
    _,errors,_=census.trace_build('invalid',work,receipts,src,env,CMD,101)
    assert any((m.get('message',{}).get('code') or {}).get('code')=='E0425' and
               screen.INVALID in m['message']['rendered'] for m in errors)
    census.command(['git','restore','--worktree','--',screen.FILE],src,env)
    repaired,msg,k=census.trace_build('repair',work,receipts,src,env,CMD)
    assert any(r['crate']=='ruff_db' and not r['link_only'] for r in k['rustcs'])
    repair,revision_objects=confirm_output(msg,src,env,repaired,deps)
    paired.empty_roots(work)
    empty,msg,k=census.trace_build('independent-empty',work,receipts,src,env,CMD)
    assert len(graph(msg)[0]['dirty'])==174
    clean,clean_objects=confirm_output(msg,src,env,empty,consumer.args_from_training(k,src))
    assert warm['consumer']==clean['consumer']==repair['consumer'] and objects==clean_objects==revision_objects
    assert old_graph['roster']==clean['roster'] and not census.command(['git','diff','--name-only'],src,env)
    sampled={label:{'instructions':clock['instructions'],'elapsed_ns':clock['stop']-clock['start'],
                    'tree_cpu_us':clock['user_us']+clock['system_us']} for label,(clock,*_) in measured.items()}
    sampled['edit+repeat']={k:sampled['edit'][k]+sampled['repeat'][k] for k in sampled['edit']}
    sampled['edit+repeat']['elapsed_ns']=measured['repeat'][0]['stop']-measured['edit'][0]['start']
    result={'role':role,'source':enrolled['compiler'],'cargo':enrolled['cargo_sha'],'measurements':sampled,
            'graph':{label:r for label,(_,r,_,_) in measured.items()},'target_and_shared_allocated':allocated,
            'products':{'old':old,'repeat':warm,'repair':repair,'empty':clean}}
    census.save(out/'terminal.json',result)
    assert work==Path(os.environ['CENSUS_ROOT']).resolve() and work.parent==Path(os.environ['RUNNER_TEMP']) and not work.is_symlink()
    shutil.move(receipts,out/'unscored')
    shutil.rmtree(work)
    return result


def main():
    position=int(sys.argv[1])
    order=REGISTERED['twelve_independent_blocks'][position-1]
    assert 1<=position<=12 and [order.count(r) for r in 'PC']==[1,1]
    root=Path(os.environ['RUNNER_TEMP'])
    out=root/'atomic-measurements';out.mkdir()
    bin_dir=out/'observer';bin_dir.mkdir()
    watch=bin_dir/'watch';loop=bin_dir/'calibrate'
    for source,exe in [('watch.c',watch),('calibrate.c',loop)]:
        subprocess.run(['cc','-std=c11','-O2','-pthread','-Wall','-Wextra','-Werror',paired.HERE/source,'-o',exe],check=True)
    hardware,cpu=paired.calibrate(out/'calibration',watch,loop)
    assert hardware,(out/'calibration/summary.json')
    census.save(out/'enrollment.json',{'position':position,'order':order,'argv':CMD,
                'registration_sha256':census.sha(HERE/'registered.json'),'tree_cpu_qualified':cpu,
                'github_run_id':os.environ['GITHUB_RUN_ID'],'workflow_sha':os.environ['GITHUB_SHA']})
    os.environ['CENSUS_ROOT']=str(root/'atomic-paired-ruff')
    results={role:arm(role,out/role,watch) for role in order}
    p,c=results['P'],results['C']
    assert p['graph']['edit']['roster']==c['graph']['edit']['roster'] and p['cargo']==c['cargo']
    assert p['products']['old']['consumer']==c['products']['old']['consumer']
    assert p['products']['empty']['consumer']==c['products']['empty']['consumer']
    endpoints={s:{k:[results[r]['measurements'][s][k] for r in 'PC'] for k in ('instructions','elapsed_ns','tree_cpu_us')}
               for s in ('edit','repeat','edit+repeat')}
    census.save(out/'pair.json',{'position':position,'order':order,'hardware':hardware,'cpu_qualified':cpu,
               'measurements':endpoints,'storage':{r:results[r]['target_and_shared_allocated'] for r in 'PC'}})


if __name__=='__main__':main()
