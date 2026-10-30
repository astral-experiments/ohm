"""Source-fresh, counter-free three-compiler Ruff admissions on the Linux #293 binary."""
from pathlib import Path
from hashlib import sha256 as H
import json,runpy,sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import frontend
HOLD=runpy.run_path(str(HERE.parent/'ohm-aarch64-confirm/study.py'))
from ruff import residual,q,rt
from study import save,load,sha,need
HIN=runpy.run_path(str(HERE/'acquire.py'))
def key(v):return H(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def admission(root,role):
    record,known,markers=q.visit,{},{}
    def read(base,phase,state,env,searches):
        path=base/phase
        assert not any(k in env for k in ('CI','CARGO_INCREMENTAL','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','RUSTC_WRAPPER'))
        if phase=='edit':
            v,actual=frontend.with_live_environment(lambda:record(base,phase,state,env,searches),path/'native.json',rt.SDK)
            save(path/'real-cargo-and-AST-environment.json',actual)
        else:v=record(base,phase,state,env,searches)
        if state=='invalid':return v
        live=load(path/'native.json')
        known.update({a['crate']:a for a in live['rustcs'] if a['crate'] in residual.NAMES})
        assert set(known)==set(residual.NAMES)
        facts=residual.unit_files(known,path)
        markers[phase]={k:[v['hard'],v['recheck']] for k,v in facts.items()}
        assert len(v['typed'])==39 and len(v['archive']['objects'])==95
        save(path/'exact-typed-inventory.json',v['typed'])
        return v
    q.visit=read
    try:result=q.trial(root.name,role)
    finally:q.visit=record
    save(root/'native-markers.json',markers)
    assert result['measured'] is None and not (root/'counter').exists() and not (root/'counter-unavailable.json').exists()
    stages=result['stages'];profiles={}
    for phase in ('edit','unchanged-1','unchanged-2'):
        native=load(root/phase/'native.json')
        actual=[r['crate'] for r in native['rustcs']]
        want=HOLD['WANT'][role]|({'ruff_python_ast'} if phase=='edit' else set())
        assert len(actual)==len(set(actual)) and set(actual)==want and not native['link_tools'] and not native['compiler_probes'],(role,phase,actual)
        facts=load(root/phase/'unit-evidence.json')['units']
        assert all([facts[k]['hard'],facts[k]['recheck']]==[k in HOLD['WANT'][role],k not in HOLD['WANT'][role]] for k in facts)
        profiles[phase]={'rustc':sorted(actual),'marker':{k:[s['hard'],s['recheck']] for k,s in facts.items()}}
    argv=load(root/'edit/native.json')['rustcs'];args,=[x['argv'] for x in argv if x['crate']=='ruff_python_ast']
    envproof=load(root/'edit/real-cargo-and-AST-environment.json')
    info={'sources':HOLD['SOURCE'][role],'old':result['old']['reader'],'new':result['cold']['reader'],'old_value':result['old']['value'],'new_value':result['cold']['value'],
          'old_objects':key(result['old']['native']),'new_objects':key(result['cold']['native']),'units':key(load(root/'edit/exact-typed-inventory.json')),
          'actual_argv':args,'actual_flags':frontend.flags(args),'actual_env':envproof,'native':profiles,'native_terminal':save(root/'complete.json',result)}
    return info

def main(ancestor,inputs,product):
 p=load(product/'product.json');assert p['cargo_sha256']==HIN['PRODUCT'] and sha(product/'cargo')==HIN['PRODUCT']
 select,log=HOLD['setup'](ancestor,inputs,(product/'cargo',p));rt.select=select;select('A')
 q.prepare_graph()
 transitions=runpy.run_path(str(HERE.parent/'ohm-aarch64-confirm/transitions.py'))
 native=transitions['check'](rt,q,select,sha,log);save(rt.LOG/'all-nine-actual-transitions.json',native)
 q.counter=lambda folder,env,ordinary:None
 sets={}
 for role in 'ANM':sets[role]=admission(rt.LOG/('ruff-native-'+role),role)
 ref=sets['A']
 for k in ('old','new','old_value','new_value','old_objects','new_objects','units'):assert all(row[k]==ref[k] for row in sets.values()),k
 assert ref['old_value']=='3.14 3.14 3.10' and ref['new_value']=='3.15 3.15 3.11' and ref['new']!=ref['old'] and ref['old_objects']!=ref['new_objects']
 # Freeze literal token counts and admissible namespace positions before obtaining a single guest count.
 import re
 normalized=[]
 for role,row in sets.items():
    tag=native['namespaces'][role];args=row['actual_argv'];positions=[]
    for i,arg in enumerate(args):
        if tag in arg:
            assert i and args[i-1] in ('--extern','--out-dir','-L') and arg.count('/'+tag+'/')==1
            positions.append(i)
    assert positions and all(re.search(r'/v2-[0-9a-f]{16}/',arg) is None or tag in arg for arg in args)
    norm=[v.replace('/'+tag+'/','/<compiler-namespace>/') if i in positions else v for i,v in enumerate(args)]
    normalized.append((positions,norm));row['namespace']=tag
 assert normalized[0]==normalized[1]==normalized[2]
 report={'cargo':HIN['PRODUCT'],'sources':HOLD['SOURCE'],'drivers':HOLD['DRIVER'],'roles':sets,'namespace_positions':normalized[0][0],'argv_count':len(normalized[0][1]),
         'raw_normalized_argv':normalized[0][1],'all_nine':sha(rt.LOG/'all-nine-actual-transitions.json'),'phase':'native-only, no guest counters','sdk_selection_snapshots':log}
 save(rt.LOG/'ruff-native-eligibility.json',report)
if __name__=='__main__':main(*map(Path,sys.argv[1:]))
