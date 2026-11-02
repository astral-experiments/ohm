"""Exercise the selected real upstream crate only, retaining its physical metadata."""
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent)]
import worker as w
from audit import checked_exec, exec_environment, run, save, sha
import contact
from project import main as project

REPORT=w.LOG/'meta-25492'
ARGS=['build','-p','ruff_source_file','--lib','--features','get-size,serde','--locked','--offline','-j4']
WANT={'get-size','serde'}
CAP=80
PHASES=('old','edit','clean')


def shape(u):return {k:v for k,v in u.items() if k!='dependencies'}


def graph(env,cmd):
    p=run(['cargo','+ohm',*cmd,'--unit-graph','-Z','unstable-options'],env,w.SRC)
    result=json.loads(p.stdout);assert result['version']==1
    return result


def closure(g,index):
    units=g['units'];stack=[index];used=set()
    while stack:
        i=stack.pop()
        if i in used:continue
        used.add(i);stack.extend(v['index'] for v in units[i]['dependencies'])
    return sorted(json.dumps(shape(units[i]),sort_keys=True) for i in used)


def provider(g):
    matches=[i for i,u in enumerate(g['units']) if u['target']['name']=='ruff_source_file'
             and u['mode']=='build' and set(u['features'])==WANT and u['target']['kind']==['lib']]
    assert len(matches)==1,matches
    return matches[0]


def visit(phase,state,env):
    assert w.git('rev-parse','HEAD')==(w.OLD if phase=='old' else w.NEW)
    assert w.git('status','--porcelain','--untracked-files=no')=='' and sha(w.SRC/'Cargo.lock')==w.LOCK
    state.mkdir(exist_ok=True)
    env={**env,'CARGO_TARGET_DIR':str(state/'target'),'CARGO_BUILD_BUILD_DIR':str(state/'build'),'CARGO_NET_OFFLINE':'true'}
    record=w.ROOT/('metadata-only-'+phase);record.mkdir()
    full=['strace','-ff','-qq','-v','-s','131072','-e','trace=execve','-o',record/'exec','--',
          'cargo','+ohm',*ARGS,'--message-format=json']
    p=run(full,env,w.SRC,exact=None)
    w.gz(REPORT/(phase+'-stderr.gz'),p.stderr);w.gz(REPORT/(phase+'-stdout.gz'),p.stdout)
    assert p.returncode==0,p.stderr[-3000:]
    rows=[json.loads(l) for l in p.stdout.splitlines()]
    assert rows[-1]=={'reason':'build-finished','success':True}
    arts=[r for r in rows if r['reason']=='compiler-artifact']
    assert len(arts)<=CAP and not any(r['target']['name'] in ('ruff_python_ast','ruff','ruff_linter','ruff_python_trivia','ruff_macros') for r in arts)
    target,=[r for r in arts if r['target']['name']=='ruff_source_file']
    assert not target['fresh'] and set(target['features'])==WANT
    meta,=[Path(i) for i in target['filenames'] if i.endswith('.rmeta')]
    lib,=[Path(i) for i in target['filenames'] if i.endswith('.rlib')]
    out=REPORT/(phase+'.rmeta');shutil.copyfile(meta,out);assert sha(meta)==sha(out)
    ls=run(['rustc','+ohm','-Zls=root',str(out)],env,w.SRC)
    (REPORT/(phase+'-ls.txt')).write_bytes(ls.stdout)
    dirs=sorted({Path(f).parent for s in arts for f in s['filenames'] if f.endswith(('.rlib','.rmeta','.so'))})
    native=sorted({path for s in rows if s['reason']=='build-script-executed' for path in s.get('linked_paths',[])})
    cmd=['rustc','+ohm','--edition=2024',HERE.parent/'witness.rs','--extern','ruff_source_file='+str(lib)]
    for d in dirs:cmd+=['-L','dependency='+str(d)]
    for d in native:cmd+=['-L',d]
    binary=w.ROOT/('typed-'+phase);cmd+=['-o',binary];run(cmd,env,w.SRC)
    verdict=run([binary],env,w.SRC)
    ordinary=json.loads((HERE.parent/'ordinary.json').read_text())['phases'][phase]
    assert verdict.stdout.decode()==ordinary['typed_by_features']['get-size+serde'] and not verdict.stderr
    actual=[]
    for trace in record.glob('exec.*'):
        for line in trace.read_text(errors='replace').splitlines():
            ev=checked_exec(line)
            if not ev:continue
            exe,argv=ev
            if exe.endswith('/bin/rustc') and '--crate-name' in argv and argv[argv.index('--crate-name')+1]=='ruff_source_file':
                actual.append({'argv':argv,'env':exec_environment(line)})
    assert len(actual)==1 and {x for x in actual[0]['argv'] if x.startswith('feature=')}=={'feature="get-size"','feature="serde"'}
    with zipfile.ZipFile(contact.REF) as z:
        native=[p['args'] for p in json.loads(z.read(phase+'/processes.json'))['compilers'] if p['crate']=='ruff_source_file' and 'feature="get-size"' in p['args']]
        assert len(native)==1
        ref=contact.canonical(native[0]);obs=contact.canonical(actual[0]['argv'])
    digest=contact.digest
    report={'phase':phase,'cap':CAP,'products':len(arts),'dirty':[r['target']['name'] for r in arts if not r['fresh']],'typed':verdict.stdout.decode(),
            'source':w.git('rev-parse','HEAD'),'rmeta':str(meta),'rmeta_sha256':sha(meta),'rlib_sha256':sha(lib),
            'actual':actual,'ordinary_arguments':native[0],'same_canonical_argv':ref==obs,
            'argv_sha256':[digest(ref),digest(obs)]}
    save(REPORT/(phase+'-raw.json'),report)
    return report


def main():
    # Shared enrollment authenticates release-proposal #253 and its 488 locked
    # archives. Its preflight clocks are irrelevant to this field diagnostic.
    private,env=w.env_and_calibrate()
    w.fetch(private,env);REPORT.mkdir()
    history=private/'history';empty=private/'empty-new'
    common={**env,'CARGO_TARGET_DIR':str(history/'target'),'CARGO_BUILD_BUILD_DIR':str(history/'build'),'CARGO_NET_OFFLINE':'true'}
    big=graph(common,w.CMD[2:-1]);small=graph(common,ARGS)
    assert len(small['units'])<=CAP and len(big['units'])>300
    bc=closure(big,provider(big));sc=closure(small,provider(small))
    save(REPORT/'graph.json',{'ordinary':big,'narrow':small,'matching_subtree_descriptions':bc==sc,
                             'only_full':sorted(set(bc)-set(sc)),'only_focused':sorted(set(sc)-set(bc))})
    visit('old',history,env);w.git('checkout','--detach',w.NEW);visit('edit',history,env);visit('clean',empty,env)
    project(REPORT)
    print('All three typed native consumers passed. No Ruff CLI/AST/trivia/macros were built.',flush=True)


if __name__=='__main__':main()
