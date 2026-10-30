"""Fresh ordinary developer A/Bs on two local Ruff AST verbs on native Apple silicon."""
import argparse
import collections
from hashlib import sha256
import itertools
import json
from pathlib import Path
import sys
import traceback

sys.path.insert(0,str(Path(__file__).resolve().parent))
from cohort import ENDPOINTS, fingerprint_sources, summarize
from execs import ExecTrace
from local_incremental import environment_receipt
from measure import installation, select
from objects import bag
from prepare import prepare_ruff
from receipt_cargo import CANDIDATE
from study import ARGS, CHILD, EDIT, EXPECTED, PARENT, RUFF, check_host, env_for, load, need, save, sha, source_values
from test_build_study import NEGATIVE, STEPS, compare_clean
import verbs

VERBS=('build','test')
SUBJECTS={'build':[RUFF,EDIT], 'test':[verbs.A,verbs.B]}
MODES=('structural','screen','confirm')


def orders(verb,mode):
    if mode!='confirm':return ['PC','CP'] if verb=='build' else ['CP','PC']
    key='ohm/native-ast293/dev/debug-identity-v2/'+verb+'/'+SUBJECTS[verb][1]+'/'+PARENT+'/'+CHILD+'/'+CANDIDATE
    candidates=list(itertools.combinations(range(12),6))
    allocation=int(sha256(key.encode()).hexdigest(),16)%len(candidates)
    return ['PC' if i in candidates[allocation] else 'CP' for i in range(12)]


def register(root):
    save(root/'receipts/ast-registration.json',{'rust':{'P':PARENT,'C':CHILD},'cargo':CANDIDATE,
        'ruff':SUBJECTS,'argv':{'build':ARGS,'test':verbs.ARGS['test']},
        'orders':{v:{m:orders(v,m) for m in MODES} for v in VERBS},'native_identity_source':'0fdb71350b882f13a525ce2caa628fa3ec7825b2','endpoints':['edit-plus-repeat','edit','repeat-1','repeat-2'],'harness':fingerprint_sources(),
        'criterion':'Positive physical mechanism and complete correctness in both mirrored structural pairs. Then 2 + 12 fresh pairs independently per verb, regardless of the size of the first two wall ratios. Primary consecutive edit plus first unchanged Cargo in one dedicated installation and clock. Three additional endpoint-specific independent installations per role and pair. No prior CI data.'})


def seed(root):
    for v in VERBS:
        if v=='build':prepare_ruff(root)
        else:prepare_ruff(root,verbs.A,verbs.B,verbs.source_identity)
        parked=root/'parked-inputs'/v;parked.mkdir(parents=True)
        for n in ('ruff','seed','release-work'):(root/n).rename(parked/n)
        path=root/'receipts/ruff.json'; record=load(path);need([record['old'],record['new']]==SUBJECTS[v], 'wrong Ruff source')
        path.rename(root/'receipts'/('ruff-'+v+'.json'))


def activate(root,verb):
    state=root/'active-ast-source';old=state.read_text() if state.exists() else None
    if old!=verb:
        for n in ('ruff','seed'):
            if old:
                need(old in VERBS and not (root/n).is_symlink(),'unsafe source root')
                (root/n).rename(root/'parked-inputs'/old/n)
            (root/'parked-inputs'/verb/n).rename(root/n)
        state.write_text(verb)
    (source_values if verb=='build' else verbs.source_identity)(root/'ruff')
    need((root/'seed/registry').is_dir() and not (root/'seed').is_symlink(),'expected physical input seed')


def visit(root,verb,role,out,trace,*,clean=None,invalid=False,timed=False):
    work=root/('study-work' if verb=='build' else 'native-verbs-work')
    sdk=select(root,role)
    env=env_for(work,sdk)
    save(out/'developer-environment.json',environment_receipt(env))
    if verb=='build':
        result=installation(root,role,out,trace=trace,clean_only=clean,invalid=invalid,timed=timed)
        return result['clean-'+clean] if clean else result
    steps=[('clean',clean)] if clean else STEPS+(NEGATIVE if invalid else [])
    result=verbs.installed('test',root,role,out,steps,trace,timed=timed)
    return result['clean'] if clean else result


def product(verb,row):
    if verb=='test':return {**row['product'],'debug_identity':row.get('test_debug')}
    value=row['reader']
    return {k:v for k,v in value.items() if k in {'value','sha256','archive_sha256','archive_metadata','archive_objects','macho_text'}}


def match(verb, got, reference):
    if verb=='build':return got==reference
    return (bool(got.get('debug_identity')) and bool(reference.get('debug_identity'))
            and {k:v for k,v in got.items() if k!='raw'}=={k:v for k,v in reference.items() if k!='raw'})


def verify_values(verb,refs):
    for role in 'PC':
        a,b=(refs[role][st] for st in ('old','new'))
        if verb=='build':
            need(a['value']==EXPECTED['old'] and b['value']==EXPECTED['new'] and a['sha256']!=b['sha256']
                 and a['archive_sha256']!=b['archive_sha256'],'real library edit did not change client and library')
        else:
            need(a['raw']!=b['raw'] and (len(a['tests']),len(b['tests']))==(53,54)
                 and set(b['tests'])-set(a['tests'])=={verbs.NEW_TEST},'real test missed the edit')


def typed_fingerprint(row):
    result={}
    for key in ('dirty','roster'):
        result[key]=sha256(json.dumps(row[key],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return result


def physical(row):
    native=row['native']
    need(native['scope']=='kernel-exec' and native['cargo']==1 and all(x['stock'] for x in native['linkers']),'wrong physical observer')
    return {'full':native['full'],'link_only':native['link_only'],'links':len(native['linkers']),
            'zmij_fresh':row['fresh_zmij'],'marker':row['marker'],'typed':typed_fingerprint(row)}


def effect(verb,p,c):
    for repeat in ('repeat-1','repeat-2'):
        a,b=p[repeat],c[repeat]
        if not (a['full'].count('zmij')==1 and not b['full'].count('zmij') and not a['zmij_fresh'] and b['zmij_fresh']
                and a['marker']['hard'] and not a['marker']['recheck'] and not b['marker']['hard'] and b['marker']['recheck']
                and not (collections.Counter(b['full'])-collections.Counter(a['full']))
                and len(b['full'])<len(a['full']) and not a['link_only'] and not b['link_only'] and a['links']>=b['links']):
            return False
    return True


def structural(root,verb,out):
    all_refs={};baseline=[];errors=[];raw_differences=[]
    trace=ExecTrace()
    try:
        trace.ready()
        for i,order in enumerate(orders(verb,'structural'),1):
            pair=out/f'pair-{i:02}';refs={};visits={}
            for role in order:
                refs[role]={}
                for state in ('old','new'):
                    row=visit(root,verb,role,pair/role/('empty-'+state),trace,clean=state)
                    refs[role][state]=product(verb,row)
                rows=visit(root,verb,role,pair/role/'actual',trace,invalid=True)
                visits[role]={k:physical(row) for k,row in rows.items()}
                for phase,row in rows.items():
                    if phase=='invalid':continue
                    actual=product(verb,row);expected=refs[role][row['state']]
                    if actual!=expected:raw_differences.append(f'{i}/{role}/{phase}')
                    if not match(verb,actual,expected):
                        errors.append(f'{i}/{role}/{phase} differs from same-role empty native build')
                if i>1 and any(not match(verb,refs[role][state],all_refs[role][state]) for state in ('old','new')):
                    errors.append(f'{i}/{role} empty source changed across separate installations')
                print(verb,'structural',i,role,'captured',flush=True)
            verify_values(verb,refs)
            if i==1:all_refs=refs
            for state in ('old','new'):
                try:
                    if verb=='test':
                        proof=compare_clean(root,pair,refs,state)
                    else:
                        a,b=[refs[r][state] for r in 'PC']
                        need(a['value']==b['value'] and a['macho_text']==b['macho_text'] and bag(a)==bag(b),
                             'cross-role native instructions, object bytes or typed value changed')
                        proof={'reader_text':a['macho_text'],'ordered_object_body_hashes':bag(a),
                               'raw_reader_equal':a['sha256']==b['sha256'],'raw_archive_equal':a['archive_sha256']==b['archive_sha256']}
                    save(pair/('cross-'+state+'.json'),proof)
                except Exception as exc:errors.append(f'{i}/{state}: {exc}')
            baseline.append({'order':order,'roles':visits,'mechanism':effect(verb,visits['P'],visits['C'])})
    finally:trace.close()
    save(out/'empty-references.json',all_refs)
    return {'safe':not errors,'errors':errors,'original_raw_differences':raw_differences,'mechanism':all(r['mechanism'] for r in baseline),'pairs':baseline}


def clock(root,verb,mode,out):
    structural_root=root/'receipts'/('ast-'+verb+'-structural')
    gate=load(structural_root/'result.json')
    if not gate['safe'] or not gate['mechanism']:
        return {'acquired':False,'reason':'fresh local developer structural gate did not qualify','source':sha(structural_root/'result.json')}
    if mode=='confirm':
        pilot=root/'receipts'/('ast-'+verb+'-screen')/'result.json'
        need(load(pilot).get('valid') is True,'clock pilot missing or unsafe')
    from ast_point_clock import POINTS,run
    refs=load(structural_root/'empty-references.json');patterns=gate['pairs'];pairs=[];allocation=orders(verb,mode)
    for i,order in enumerate(allocation,1):
        pair={r:{} for r in order}
        shift=(i-1)%len(POINTS)
        for point in POINTS[shift:]+POINTS[:shift]:
            for role in order:
                d=out/f'pair-{i:02}'/point/role
                pair[role][point]=run(root,verb,role,point,d,refs[role],patterns)
                print(verb,mode,i,point,role,'verified',flush=True)
        pairs.append(pair)
    cal=load(root/'receipts/calibration/result.json')
    results={'acquired':True,'valid':True,'orders':allocation,'wall':summarize(pairs,allocation,endpoints=POINTS),
             'primary':'edit-plus-repeat','counter_scope':cal['retired_instruction_scope']}
    if cal['tree_CPU_calibrated']:
        for pair in pairs:
            for r in pair.values():
                for key in POINTS:
                    c=r[key]['cargo'];c['cpu']=c['user']+c['system']
        results['cpu_seconds']=summarize(pairs,allocation,'cpu',POINTS)
    if cal['retired_instruction_scope']=='whole-tree-calibrated':results['retired_instructions']=summarize(pairs,allocation,'instructions',POINTS)
    if mode=='confirm':
        primary=results['wall']['edit-plus-repeat']
        results['twofold_confirmed']=primary['median_CI_96.14pct'][0]>2 and primary['one_sided_balanced_sharp_2x_p']<=0.05
    return results


def execute(root,verb,mode):
    check_host(root,8)
    registration=load(root/'receipts/ast-registration.json')
    need(registration['orders'][verb][mode]==orders(verb,mode) and registration['harness']==fingerprint_sources(), 'registration inputs moved')
    need(load(root/'receipts/provider-matrix/terminal.json')['passed'] and load(root/'receipts/fixed-cargo-293.json')['commit']==CANDIDATE,
         'native provider or Cargo source failed')
    activate(root,verb)
    out=root/'receipts'/('ast-'+verb+'-'+mode);out.mkdir()
    try: result=structural(root,verb,out) if mode=='structural' else clock(root,verb,mode,out)
    except Exception as exc:
        save(out/'failure.json',{'failure':str(exc),'backtrace':traceback.format_exc()})
        raise
    save(out/'result.json',result)
    if mode=='structural':print(verb,{k:result[k] for k in ('safe','mechanism','errors')},flush=True)
    else:print(verb,mode,{k:result.get(k) for k in ('valid','acquired','twofold_confirmed')},flush=True)


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('mode',choices=('register','seed',*MODES));a.add_argument('root',type=Path);a.add_argument('verb',choices=VERBS,nargs='?')
    o=a.parse_args();root=o.root.resolve()
    if o.mode=='register':register(root)
    elif o.mode=='seed':seed(root)
    else:
        need(o.verb in VERBS,'missing enrolled subject');execute(root,o.verb,o.mode)
