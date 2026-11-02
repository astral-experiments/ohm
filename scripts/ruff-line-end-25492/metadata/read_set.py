"""Collect three host-rustc graphs after matching the seven genuine CLI units."""
import gzip
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent)]
import acquire as a
import worker as w
from audit import run,save,sha
import contact
import native_replay

ARGS=['build','-p','ruff_macros','--lib','--locked','--offline','-j4']

def dep(g,i,name):
    found={d['index'] for d in g['units'][i]['dependencies'] if d['extern_crate_name']==name}
    assert len(found)==1,(i,name,found)
    return found.pop()

def edge_closure(g,root):
    reached=set();stack=[root];edges=[]
    while stack:
        i=stack.pop()
        if i in reached:continue
        reached.add(i);unit=g['units'][i]
        for d in unit['dependencies']:
            target=d['index'];stack.append(target)
            edges.append([a.shape(unit),{k:v for k,v in d.items() if k!='index'},a.shape(g['units'][target])])
    return sorted(json.dumps(e,sort_keys=True) for e in edges)

def host(g):
    macro,=[i for i,u in enumerate(g['units']) if u['target']['name']=='ruff_macros' and u['target']['kind']==['proc-macro'] and u['mode']=='build']
    owner=dep(g,macro,'ruff_python_trivia');src=dep(g,owner,'ruff_source_file')
    assert all(g['units'][u]['features']==[] for u in (owner,src,macro))
    return macro,owner,src

def state(case,root,env,archive,args):
    phase=w.LOG/'host-read-set'/case
    phase.mkdir();root.mkdir(exist_ok=True)
    assert w.git('rev-parse','HEAD')==(w.OLD if case=='old' else w.NEW) and sha(w.SRC/'Cargo.lock')==w.LOCK and not w.git('status','--porcelain','--untracked-files=no')
    private=native_replay.inputs(case,root,phase);trace=private/'trace';trace.mkdir()
    env={**env,'CARGO_TARGET_DIR':str(root/'target'),'CARGO_BUILD_BUILD_DIR':str(root/'build'),'CARGO_NET_OFFLINE':'true'}
    cmd=['strace','-ff','-qq','-v','-s','131072','-e','trace=execve','-o',trace/'exec','--','cargo','+ohm',*args,'--message-format=json']
    status=run(cmd,env,w.SRC,exact=None)
    w.gz(phase/'stdout.gz',status.stdout);w.gz(phase/'stderr.gz',status.stderr)
    assert status.returncode==0,status.stderr[-4200:]
    rows=[json.loads(x) for x in status.stdout.splitlines()]
    assert rows[-1]=={'reason':'build-finished','success':True}
    products=[r for r in rows if r['reason']=='compiler-artifact']
    assert len(products)<=22 and not any(r['target']['name'] in ('ruff','ruff_linter','ruff_python_ast') for r in products)
    ids={}
    dirs=sorted({Path(f).parent for r in products for f in r['filenames'] if f.endswith(('.rlib','.rmeta','.so'))})
    for lib in ('ruff_source_file','ruff_python_trivia','ruff_macros'):
        row,=[r for r in products if r['target']['name']==lib]
        ids[lib]={Path(f).name:sha(Path(f)) for f in row['filenames']}
        if lib=='ruff_macros':continue
        rlib,=[p for p in row['filenames'] if p.endswith('.rlib')]
        src=(HERE/'trivia.rs') if lib=='ruff_python_trivia' else (HERE.parent/'witness.rs')
        binary=phase.parent.parent.parent/(case+'-native-'+lib)
        cmd=['rustc','+ohm','--edition=2024',src,'--extern',lib+'='+rlib]
        for d in dirs:cmd+=['-L','dependency='+str(d)]
        run([*cmd,'-o',binary],env,w.SRC);replay=run([binary],env,w.SRC)
        assert not replay.stderr
        expected=(json.loads((HERE.parent/'ordinary.json').read_bytes())['phases'][case]['typed_by_features']['no-features'] if lib=='ruff_source_file' else '"> é\\r\\n>\\n> β\\r"\n"> A\\n> B"\n""\n')
        assert replay.stdout.decode()==expected,(lib,replay.stdout,expected)
        (phase/(lib+'-typed.txt')).write_bytes(replay.stdout)
    native_equal=native_replay.collect(case,root,phase,private,trace,dirs,env)
    if not (phase/'process.json').is_file():
        save(phase/'unobserved.json',{'phase':case,'dirty':[r['target']['name'] for r in products if not r['fresh']],'products':ids})
        return False
    original=json.loads((phase/'original.json').read_bytes())
    argv=original['argv'];phref=[p['args'] for p in json.loads(archive.read(case+'/processes.json'))['compilers'] if p['crate']=='ruff_python_trivia']
    assert len(phref)==2, len(phref)
    wanted=contact.canonical(argv);matches=[i for i,v in enumerate(phref) if contact.canonical(v)==wanted]
    meta={v.rsplit('.',1)[0]:h for v,h in ids['ruff_source_file'].items() if v.endswith('.rmeta')};assert original['provider_sha256'] in meta.values()
    save(phase/'history.json',{'case':case,'source':w.git('rev-parse','HEAD'),'product_ids':ids,'products':len(products),
                               'dirty':[r['target']['name'] for r in products if not r['fresh']],'full_arguments':phref,
                               'matches':matches,'focused':wanted,'default_macro_env':{k:env.get(k) for k in ('RUSTFLAGS','RUSTC_WORKSPACE_WRAPPER','CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST','CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST')},'canonical_sha256':contact.digest(wanted)})
    assert 'ruff_source_file='+original['provider_path'] in argv
    return len(matches)==1 and native_equal

def main():
    private,env=w.env_and_calibrate();w.fetch(private,env)
    out=w.LOG/'host-read-set';out.mkdir()
    h=private/'history';e=private/'empty-new'
    common={**env,'CARGO_TARGET_DIR':str(h/'target'),'CARGO_BUILD_BUILD_DIR':str(h/'build'),'CARGO_NET_OFFLINE':'true'}
    big=a.graph(common,w.CMD[2:-1]);m,u,s=host(big);full=a.closure(big,u)
    assert len(a.closure(big,m))==20 and len(full)==7
    focus_packages=('memchr','itertools','either','ruff_python_trivia','unicode-ident')
    five=[x for name in focus_packages for x in ('--config',f'profile.dev.package.{name}.debug="line-tables-only"')]
    build_override=['--config','profile.dev.build-override.debug="line-tables-only"']
    two=[x for name in ('ruff_source_file','ruff_text_size') for x in ('--config',f'profile.dev.package.{name}.debug=0')]
    options=[('five-host-units',five),('build-override-with-two-exceptions',build_override+two)]
    cases=[]
    for name,config in options:
        args=[*ARGS,*config];small=a.graph(common,args);m2,u2,s2=host(small);focused=a.closure(small,u2)
        exact=(len(small['units'])<=22 and focused==full and edge_closure(big,u)==edge_closure(small,u2))
        cases.append({'name':name,'config':config,'focused':small,'role':[m2,u2,s2],'nodes':len(focused),'same_edges':edge_closure(big,u)==edge_closure(small,u2),
                      'only_full':sorted(set(full)-set(focused)),'only_focused':sorted(set(focused)-set(full)),'matched':exact})
        if exact:break
    save(out/'graph.json',{'full':big,'role':[m,u,s],'full_nodes':len(full),'plans':cases})
    assert exact,('no exact matching seven-unit graph',[(r['name'],len(r['only_full']),len(r['only_focused'])) for r in cases])
    with zipfile.ZipFile(contact.REF) as archive:
        accepted=[state('old',h,env,archive,args)];w.git('checkout','--detach',w.NEW)
        accepted.append(state('edit',h,env,archive,args));accepted.append(state('clean',e,env,archive,args))
    assert all(accepted),('host history physically did not match all three original full commands',accepted)
    print('All three real host readers and typed native controls completed.',flush=True)
if __name__=='__main__':main()
