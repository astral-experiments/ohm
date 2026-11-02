"""Independently re-open the restored-environment #25492 attribution packet."""
from collections import Counter,defaultdict
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import contact
import profile_work as prof
HEAD='7f3ee9ecfb89d1443e90a5a1b9ec32259fc792b7'
ORDINARY=json.loads((HERE/'ordinary.json').read_text())
PHASES=('old','edit','unchanged','clean')
MISSING='<unresolved>'
FRAME=re.compile(rb'\s*(?:0x)?([0-9a-fA-F]+)\s+(.+?)\s+\((.*)\)\s*')
HEADLINE=re.compile(rb'\s*(\d+)\s+(\d+)(?:\s*:)?\s*')
def store(p,v):p.write_text(json.dumps(v,sort_keys=True,indent=2)+'\n')
def jd(z,p):return json.loads(z.read(p))
def compressed(z,p):return gzip.GzipFile(fileobj=z.open(p))
def compact(v):return json.dumps(v,separators=(',',':'),sort_keys=True)
def pct(n,d):return round(100*n/d,3)


def artifact_sets(z):
    snapshots={};consumer_edges={}
    for ph in PHASES:
        with compressed(z,ph+'/delivered.json.gz') as f:r=json.load(f)
        rows=r['artifacts'];by={};routes={}
        for unit in rows:
            key=compact(unit['unit']);assert key not in by
            files={}
            for x in unit['files']:
                name=Path(x['path']).name;assert name not in files and x['path'] not in routes
                files[name]=x;routes[x['path']]=(key,name)
            by[key]=files
        snapshots[ph]=by
        consumer_edges[ph]=[(r['crate'],flag,ext,unit,file) for r in r['consumer_operands'] for flag,ext,path in r['externs'] for unit,file in [routes[path]]]
    a,b,u,c=(snapshots[ph] for ph in PHASES);assert set(a)==set(b)==set(u)==set(c)
    out={};changed=set()
    for unit in sorted(a):
        assert set(a[unit])==set(b[unit])==set(u[unit])==set(c[unit])
        item={'unit':json.loads(unit),'artifacts':[]}
        for name in sorted(a[unit]):
            src=[stage[unit][name] for stage in (a,b,u,c)]
            full=[r['sha256'] for r in src];assert full[1]==full[2]
            row={'name':name,'sha256':full,'bytes':[r['bytes'] for r in src],'old_edit_equal':full[0]==full[1],'edit_clean_equal':full[1]==full[3]}
            if not row['old_edit_equal']:changed.add((unit,name))
            if 'members' in src[0]:
                olds,news,_,cleans=[v['members'] for v in src]
                ma={v[0]:v[2] for v in olds};mb={v[0]:v[2] for v in news};mc={v[0]:v[2] for v in cleans}
                if len(ma)==len(olds) and len(mb)==len(news) and len(mc)==len(cleans):
                    delta=sorted(k for k in ma.keys()|mb.keys() if ma.get(k)!=mb.get(k));cl=sorted(k for k in mb.keys()|mc.keys() if mb.get(k)!=mc.get(k));row['old_edit_different_members']=delta;row['edit_clean_different_members']=cl
                    row['ordered_member_payloads_equal']=[olds==news,news==cleans]
                    row['embedded_rmeta']=[m.get('lib.rmeta') for m in (ma,mb,mc)]
                    def native_map(m):return {contact.canonical([k])[0]:v for k,v in m.items() if k.endswith('.o')}
                    om,nm,cm=map(native_map,(ma,mb,mc))
                    if all(len(t)==sum(k.endswith('.o') for k in raw) for t,raw in [(om,ma),(nm,mb),(cm,mc)]):
                        row['canonical_native_members']=[len(om),len(nm),len(cm)]
                        row['different_native_payloads']=[sum(om.get(k)!=nm.get(k) for k in om.keys()|nm.keys()),sum(nm.get(k)!=cm.get(k) for k in nm.keys()|cm.keys())]
                else:row['member_ambiguity']='duplicate archive labels'
            item['artifacts'].append(row)
        out[unit]=item
    edges=defaultdict(set)
    for name,flag,ext,unit,file in consumer_edges['edit']:
        edges[name].add((flag,ext,json.loads(unit)[0],file,(unit,file) in changed))
    return {'delivered':list(out.values()),'offered_changed_edges_by_consumer':{k:sorted(v) for k,v in edges.items()},'changed_files':len(changed),
            'unchanged_files':sum(len(v) for v in a.values())-len(changed)}


def primary(z):
    items=[]
    with compressed(z,'edit/primary-samples.txt.gz') as f:
        for line in f:
            if not line.strip():continue
            row=prof.ROW.fullmatch(line.rstrip());assert row,line[:160]
            pid,n,ip,sym,dso=row.groups();assert int(n)==prof.PERIOD
            items.append((int(pid),ip.decode().lstrip('0') or '0',sym.decode(errors='replace'),dso.decode(errors='replace')))
    return items


def chains(z):
    pid=None;frames=[]
    with compressed(z,'edit/stack-samples.txt.gz') as f:
        for line in f:
            l=line.rstrip()
            if not l:
                if pid is not None:
                    yield pid,frames;pid=None;frames=[]
                continue
            both=prof.ROW.fullmatch(l)
            header=HEADLINE.fullmatch(l)
            if both or header:
                if pid is not None:
                    yield pid,frames
                h=both or header;pid=int(h[1]);assert int(h[2])==prof.PERIOD,(h.groups(),l[:160]);frames=[]
                if both:frames.append((both[3].decode().lstrip('0') or '0',both[4].decode(errors='replace'),both[5].decode(errors='replace')))
            else:
                frow=FRAME.fullmatch(l); assert frow and pid is not None,l[:280]
                frames.append((frow[1].decode().lstrip('0') or '0',frow[2].decode(errors='replace'),frow[3].decode(errors='replace')))
                assert len(frames)<=512
        if pid is not None:yield pid,frames


def group(sym,dso):
    if any(t in sym for t in ('try_mark_green','try_mark_previous_green','try_mark_parent_green','try_mark_dep_node_green','try_force_from_dep_node')):return 'query color/force'
    if 'rmeta::encoder' in sym or '::encode_metadata' in sym or 'public_api_hasher' in sym:return 'rmeta encode/public hash'
    if 'rmeta::decoder' in sym or '::decode_metadata' in sym:return 'rmeta decode'
    if 'rustc_incremental::persist' in sym or 'dep_graph::serialize' in sym or 'dep_graph::serialized' in sym or 'DepGraphEncoder' in sym:return 'incremental graph and persistence'
    if 'rustc_codegen_ssa::back::archive' in sym or 'ArchiveBuilder' in sym or '::link_rlib' in sym:return 'archive assembly'
    if 'rustc_codegen_ssa::back::link' in sym or '::exec_linker' in sym:return 'native link preparation'
    if 'rustc_codegen_llvm' in sym or 'libLLVM' in dso or 'llvm::' in sym or 'rustc_codegen_ssa::mir' in sym:return 'native code generation'
    if 'rustc_monomorphize' in sym:return 'mono collection'
    if any(x in sym for x in ['rustc_borrowck','rustc_hir_typeck','rustc_mir_transform','rustc_type_ir','rustc_trait_selection','rustc_ast_lowering','rustc_expand','rustc_resolve','rustc_hir_analysis']):return 'front-end semantic work'
    if 'rustc_query' in sym or 'dep_graph' in sym:return 'other query or graph work'
    return None


def profile(z):
    pts=primary(z);n=len(pts);r=jd(z,'edit/sample-ledger.json');assert r['qualifies'] and r['samples']==n and r['period']==prof.PERIOD and not r['invalid_count']
    with compressed(z,'edit/physical.perf.data.gz') as raw:assert hashlib.file_digest(raw,'sha256').hexdigest()==r['raw_sha256']
    owner={int(k):v for k,v in r['pid_owner'].items()};co=Counter(owner[p] for p,*_ in pts);assert co==r['owner_sample_counts']
    count=sum(k['instructions'] for k in [jd(z,'edit/clock.json')]);assert count==r['clock_in_profiled_child']
    sym={v[2] for v in pts}
    depth=Counter();inventory=Counter()
    for p,frames in chains(z):
        depth[len(frames)]+=1
        if frames:inventory[p,frames[0][0]]+=1
        sym.update(s[1] for s in frames)
    primary_inventory=Counter((p,ip) for p,ip,_,_ in pts)
    assert sum(depth.values())==n and inventory==primary_inventory,('stack/header mismatch',len(primary_inventory),len(inventory),sum((primary_inventory-inventory).values()),depth.most_common(8))
    names=sorted(sym);inp=('\n'.join(names)+'\n').encode()
    dec=subprocess.run(['c++filt','-s','rust'],input=inp,capture_output=True,check=True).stdout.decode().splitlines();assert len(dec)==len(names)
    unm={k:re.sub(r'\[[0-9a-f]{16}\]','',v) for k,v in zip(names,dec)}
    by_owner=defaultdict(Counter);by_pid=defaultdict(Counter);leaf=Counter();disjoint=Counter();inclusive=Counter();funcs=Counter();symbol_by_phase=defaultdict(Counter);unmapped=Counter()
    for p,frames in chains(z):
        own=owner[p];ip,s,dso=frames[0]
        candidates=[group(unm[sym],module) for _,sym,module in frames];candidates=[v for v in candidates if v]
        bottom=group(unm[s],dso) or 'other/unclassified';best=next(iter(candidates),'other/unclassified')
        if own=='Wild':bottom=best='Wild';candidates=['Wild']
        elif own.startswith('child of rustc '):bottom=best='external child of rustc';candidates=[best]
        if unm[s] in ('[unknown]','0x0','unknown'):unmapped[own]+=1
        leaf[bottom]+=1;disjoint[best]+=1;inclusive.update(set(candidates));by_owner[own][best]+=1;by_pid[p][best]+=1;funcs[own,unm[s],Path(dso).name]+=1;symbol_by_phase[best][unm[s]]+=1
    assert sum(disjoint.values())==sum(leaf.values())==n
    invocations=[]
    for pc in jd(z,'edit/processes.json')['compilers']:
        a=pc['args'];kind=a[a.index('--crate-type')+1] if '--crate-type' in a else None
        invocations.append({'pid':pc['pid'],'crate':pc['crate'],'kind':kind,'features':sorted(v for v in a if v.startswith('feature=')),'sample_classes':by_pid[pc['pid']]})
    return {'per_compiler_invocation':invocations,'period':r['period'],'samples':n,'coverage_fraction':r['coverage'],'profiled_clock':count,'ordinary_clock':ORDINARY['phases']['edit']['clock']['instructions'],
            'class_exclusive_leaf':leaf,'class_disjoint_deepest_recognized_stack':disjoint,'inclusive_union_per_class_do_not_sum':inclusive,
            'by_owner_disjoint_stack':by_owner,'owner_samples':co,'unknown_leaf_by_owner':unmapped,'stack_depth':depth,
            'top_owner_leaf_functions':[list(k)+[v] for k,v in funcs.most_common(85)],
            'top_leaf_by_exclusive_stack_class':{k:v.most_common(6) for k,v in symbol_by_phase.items()}}


# These are the two finished, immutable attempts. The sampler's final raw-name
# assertion is independently tested below before any primary sample is decoded.
DIAG=(41466356507,13154575612,33709414,'2500e9d894aff9bf31314ae4e03a7e37e81d36ed9210b6a832902b72e8193e73',HEAD,'failure','ruff-line-end-25492-profile','Isolated restored-environment Rust compiler profile on Ruff 25492')
REF=(contact.RUN,contact.ART,6857620,contact.DIGEST,contact.HEAD,'success','ruff-line-end-25492-baseline','Ordinary Rust compiler baseline on Ruff 25492')
BRANCH='charlie/qa-ruff-line-end-25492-20261102'


def get(endpoint):
    return json.loads(subprocess.check_output(['gh','api','repos/astral-experiments/ohm/actions/'+endpoint]))


def download(directory, spec):
    run,art,size,digest,head,conclusion,name,job_name=spec
    info=get(f'runs/{run}')
    assert (info['head_sha'],info['head_branch'],info['run_attempt'],info['status'],info['conclusion'])==(head,BRANCH,1,'completed',conclusion)
    job,=[v for v in get(f'runs/{run}/jobs?per_page=100')['jobs'] if v['name']==job_name]
    assert (job['status'],job['conclusion'])==('completed',conclusion)
    matches=[a for a in get(f'runs/{run}/artifacts?per_page=100')['artifacts'] if a['name']==name]
    item,=matches
    assert not item['expired'] and (item['id'],item['size_in_bytes'],item['digest'])==(art,size,'sha256:'+digest)
    assert (item['workflow_run']['id'],item['workflow_run']['head_sha'])==(run,head)
    file=directory/(str(art)+'.zip')
    with file.open('xb') as out:
        subprocess.run(['gh','api',f'repos/astral-experiments/ohm/actions/artifacts/{art}/zip'],stdout=out,check=True)
    assert file.stat().st_size==size
    with file.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==digest
    return file


def normalize_roster(raw):
    # Only the documented random locked-autocfg UUID may vary in this second
    # summary. contact.commands separately verifies its output path and probe
    # index, ordered arguments and every physical environment.
    return sorted((f'autocfg_<uuid>_{m[1]}' if (m:=contact.PROBE.fullmatch(crate)) else crate,link_only) for crate,link_only in raw)


def check_shape(left,right):
    for key in ('dirty','products','wild'):
        assert left[key]==right[key],key
    assert normalize_roster(left['roster'])==normalize_roster(right['roster'])
    a,b=(Counter(tuple(x) for x in v['roster']) for v in (left,right))
    only_left=list((a-b).elements());only_right=list((b-a).elements())
    assert all(contact.PROBE.fullmatch(k) and not l for k,l in only_left+only_right)
    assert normalize_roster(only_left)==normalize_roster(only_right)
    return {'ordinary_only_raw_probe_names':sorted(only_left),'profile_only_raw_probe_names':sorted(only_right),
            'canonical_roster_sha256':contact.digest(normalize_roster(left['roster'])),'products':left['products'],
            'dirty':len(left['dirty']),'rustc':len(left['roster']),'wild':left['wild']}


def self_test():
    left={'dirty':['z'],'wild':1,'products':3,'roster':[['autocfg_0123456789abcdef_0',False],['z',False]]}
    right={**left,'roster':[['autocfg_fedcba9876543210_0',False],['z',False]]}
    check_shape(left,right)
    for change in ({'products':4},{'dirty':['w']},{'wild':0},{'roster':[['z',False]]},
                   {'roster':[['autocfg_fedcba9876543210_1',False],['z',False]]},
                   {'roster':[['autocfg_fedcba9876543210_0',True],['z',False]]},
                   {'roster':[['autocfg_fedcba9876543210_0',False],['w',False]]}):
        try:check_shape(left,{**right,**change})
        except AssertionError:continue
        raise AssertionError(change)


def cargo_roster(archive,phase):
    with compressed(archive,phase+'/cargo.stdout.gz') as f:rows=[json.loads(line) for line in f]
    assert rows[-1]=={'reason':'build-finished','success':True}
    units=[row for row in rows if row['reason']=='compiler-artifact']
    return sorted(compact([row['package_id'],row['target'],row['features'],row['profile'],row['fresh']]) for row in units)


def authenticated(original,z):
    assert original.testzip() is None and z.testzip() is None
    a,b=(jd(p,'admission.json') for p in (original,z))
    assert (a['head'],b['head'],int(a['run']),int(b['run']))==(REF[4],DIAG[4],REF[0],DIAG[0])
    for k in ('old','new','lock','env','cargo','rustc'):assert a[k]==b[k],k
    assert a['boot']!=b['boot'] and len(a['selected_cpus'])==len(b['selected_cpus'])==4
    assert jd(original,'registry.json')==jd(z,'registry.json')
    for p in (original,z):
        assert jd(p,'catalog.json')['digest']=='sha256:3de34fa8799dbc8f05069bf7916012597061a9adc69b0ff0898aca936d16ee68'
    assert jd(original,'source-provenance.json')==jd(z,'source-provenance.json')
    gates=jd(z,'comparison-gates.json')
    refused=[(name,k) for name,val in gates.items() for k,passed in val.items() if not passed]
    assert refused==[('four_phases','same_dirty_owners_and_wild')],refused
    out={'raw_gates':gates,'producer_conclusion':'failure','admission':b,'sha256s':{'ordinary':REF[3],'profile':DIAG[3]},'phases':{}}
    for phase in PHASES:
        name=phase+'/summary.json'
        lo,hi=jd(original,name),jd(z,name)
        shape=check_shape(lo,hi)
        units=cargo_roster(original,phase)
        assert cargo_roster(z,phase)==units and len(units)==shape['products']
        shape['full_cargo_unit_sha256']=contact.digest(units)
        cols=[]
        for p in (original,z):
            rows,_=contact.commands(p.read,phase)
            assert len(rows['rustc'])==shape['rustc'] and len(rows['wild'])==shape['wild']
            cols.append(rows)
        stored=jd(z,phase+'/native-roster.json')
        assert cols[0]==cols[1]==stored['ordinary']==stored['diagnostic'] and not stored['mismatches']
        shape['full_native_argv_env_sha256']=contact.digest(cols[0])
        for name in ('watch','proxy','signed_cargo'):
            ll,rr=(jd(p,phase+'/exec-env.json')[name] for p in (original,z))
            assert (ll['path'],ll['env'])==(rr['path'],rr['env'])
        def objects(p):
            return {unit:{file:(v['sha256'],v.get('physically_reused')) for file,v in data['objects'].items()} for unit,data in jd(p,phase+'/objects.json').items()}
        assert objects(z)==objects(original)
        shape['native_donors_and_bytes_sha256']=contact.digest(objects(z))
        x,y=(jd(p,phase+'/verdict.json') for p in (original,z))
        for k in ('cli_cases','cli_version','typed_by_features'):assert x[k]==y[k],k
        shape['typed_by_features']=y['typed_by_features']
        shape['cli_verdict_sha256']=contact.digest(y['cli_cases'])
        out['phases'][phase]=shape
    different=[ph for ph in PHASES if out['phases'][ph]['ordinary_only_raw_probe_names']]
    assert different==['old','clean'],different
    states=[jd(z,ph+'/'+f) for ph in PHASES for f in ('tools-before-cargo.json','tools-after-cargo.json')]
    states.extend(jd(z,p) for p in ('tools-before-symbolize.json','tools-after-symbolize.json'))
    assert all(s0==states[0] for s0 in states) and len(states[0])>=30
    out['tool_identity_count']=len(states[0]);out['tool_state_sha256']=contact.digest(states[0])
    out['clocks']={ph:jd(z,ph+'/clock.json') for ph in PHASES}
    for v in out['clocks'].values():assert v['instructions']>0 and v['enabled']==v['running']>0 and v['event_errno']==v['code']==0
    args=jd(z,'edit/command.json')['argv']
    assert '--no-buildid-cache' in args and args[args.index('/usr/bin/env')+1]=='-i'
    out['delivery']=artifact_sets(z)
    out['attribution']=profile(z)
    return out


def main(output):
    import tempfile
    destination=Path(output)
    destination.mkdir(exist_ok=False)
    with tempfile.TemporaryDirectory() as root:
        old,profiled=[download(Path(root),spec) for spec in (REF,DIAG)]
        with zipfile.ZipFile(old) as left,zipfile.ZipFile(profiled) as right:
            result=authenticated(left,right)
    for key in ('delivery','attribution'):
        store(destination/(key+'.json'),result.pop(key))
    store(destination/'readback.json',result)


if __name__=='__main__':
    self_test()
    if sys.argv[1:]!=['test']:main(sys.argv[1])
