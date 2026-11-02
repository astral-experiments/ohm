"""Reopen the physical instruction stacks and changed native archive members of the largest consumers."""
from collections import Counter
from pathlib import Path
import gzip,json,re,subprocess,sys
HERE=Path(__file__).resolve().parent;sys.path[:0]=[str(HERE),str(HERE.parent)]
import contact,reopen
from reopen_semantic import opened
spec=reopen.DIAG
def dec(s):return re.sub(r'\[[0-9a-f]{16}\]','',s)
jdoc=lambda z,k:json.loads(z.read(k))
def stable_names(m):return {contact.canonical([n])[0]:[l,h] for n,l,h in m if n.endswith('.o')}
def masks(sym,dso):
    cat=reopen.group(sym,dso)
    out=set()
    if cat:out.add(cat)
    if 'rustc_metadata::' in sym and ('rmeta::decoder' in sym or 'cstore_impl' in sym):out.add('any foreign metadata loader')
    if 'external_metadata_input_hash' in sym:out.add('named external metadata guard')
    if 'rustc_expand::' in sym or 'proc_macro' in sym or 'proc-macro' in sym:out.add('proc_macro or expand')
    if 'rustc_middle::query::on_disk_cache::CacheDecoder' in sym:out.add('incremental query cache decoder')
    return out
with opened(sys.argv[1],spec[2],spec[3]) as z:
    inv=jdoc(z,'edit/processes.json')['compilers'];names=('ruff_linter','ruff_server','ruff_python_ast');pids={c:next(t['pid'] for t in inv if t['crate']==c) for c in names}
    assert all(sum(x['crate']==k for x in inv)==1 for k in names)
    prim=Counter((p,ip) for p,ip,_,_ in reopen.primary(z));assert sum(prim.values())==23344
    picked=[(p,fs) for p,fs in reopen.chains(z) if p in pids.values()]
    assert Counter((p,fr[0][0]) for p,fr in picked)==dict((k,v) for k,v in prim.items() if k[0] in pids.values())
    syms=sorted({s for p,fr in picked for ip,s,dso in fr});dem=subprocess.check_output(['c++filt','-s','rust'],input='\n'.join(syms)+'\n',text=True).splitlines();assert len(syms)==len(dem);rename={k:dec(v) for k,v in zip(syms,dem)}
    tracks={}
    for case in ('old','edit','clean'):
        row=json.loads(gzip.decompress(z.read(case+'/delivered.json.gz')))
        tracks[case]={r['unit'][0]:r for r in row['artifacts'] if r['unit'][0] in names and r['unit'][1]==['lib']}
        assert set(tracks[case])==set(names)
    owners={}
    for own,pid in pids.items():
        union=Counter();deep=Counter();leaf=Counter();hot=Counter();scoped=Counter()
        for p,fr in picked:
            if p!=pid:continue
            decs=[(rename[s],dso) for ip,s,dso in fr]
            m=[reopen.group(s,dso) for s,dso in decs];m=[x for x in m if x]
            deep[next(iter(m),'other/unclassified')]+=1
            flags=set().union(*(masks(s,dso) for s,dso in decs));union.update(flags)
            leaf[reopen.group(*decs[0]) or 'other/unclassified']+=1;hot[decs[0][0]]+=1
            for label,ms in [('all foreign metadata decode or query color/force',{'any foreign metadata loader','rmeta decode','query color/force'}),('including incremental query cache decode',{'any foreign metadata loader','rmeta decode','query color/force','incremental query cache decoder'}),('also includes expanding all proc macros',{'any foreign metadata loader','rmeta decode','query color/force','incremental query cache decoder','proc_macro or expand'})]:
                if flags&ms:scoped[label]+=1
        files={};native={}
        for case,r in tracks.items():
            artifact_files=r[own]['files']
            f,=[e for e in artifact_files if e['path'].endswith('.rlib')];m0,=[e for e in artifact_files if e['path'].endswith('.rmeta')]
            files[case]=[f['sha256'],m0['sha256']];native[case]=stable_names(f['members']);assert len(native[case])==sum(n.endswith('.o') for n,_,_ in f['members'])
        delta=[dict(unit=k,old=v,edited=native['edit'].get(k),clean=native['clean'].get(k)) for k,v in sorted(native['old'].items()) if v!=native['edit'].get(k)]
        assert set(native['old'])==set(native['edit'])==set(native['clean']) and native['edit']==native['clean']
        e=jdoc(z,'edit/processes.json')['compilers'];owner,=[r for r in e if r['pid']==pid]
        externs=[opd.partition('=')[0] for i,opd in enumerate(owner['args']) if i and owner['args'][i-1]=='--extern']
        owners[own]=dict(pid=pid,samples=sum(deep.values()),deepest=deep,inclusive=union,primary=leaf,unions_do_not_sum=scoped,top_leaf=hot.most_common(12),
                         native_members=len(native['old']),changed_native=delta,extern_names=externs,rlib_rmeta=files)
    ds=[p for p in z.namelist() if p.endswith(('dep-graph.bin','.rmeta','.rlib','.o','.so','.mm_profdata')) or ('dep-graph' in p and not p.endswith('.json'))]
    sampled=json.loads((HERE.parent/'profile.json').read_bytes());clock=sampled['ordinary_clock']
    doc=dict(source={'run':spec[0],'artifact':spec[1],'zip_sha256':spec[3],'period':2500003,'samples':sum(prim.values()),'metered':sampled['clock'],'ordinary_workflow_instructions':clock},owners=owners,
             actual_raw_compiler_inputs_or_query_graphs=ds,
             normalized_physical_donor_totals=json.loads((HERE.parent/'ordinary.json').read_bytes())['phases']['edit']['objects'],
             top_complete_units=sorted(((k,n) for k,n in sampled['owners'].items() if k.startswith('rustc ')),key=lambda t:-t[1])[:8])
    print([(k, v['samples'],v['unions_do_not_sum'],len(v['changed_native']),v['changed_native'][0]['unit'] if v['changed_native'] else None) for k,v in owners.items()],flush=True)
    print('raw files',ds,'measurement',doc['source'],flush=True)
    Path(sys.argv[2]).write_text(json.dumps(doc,sort_keys=True,indent=2)+'\n')
