"""Report scoped native equality, preserving the original root veto and all unexplained differences."""
from pathlib import Path
import gzip,json,sys
H=Path(__file__).resolve().parent;sys.path.insert(0,str(H))
from model import digest,dump,require
from arutil import compare as archive_compare
ROLES=('stock_ctfe318','fa7a_stack_ctfe318')
NAMES=('workspace-products','registry-products','public-sidecars','terminal-extern-inputs')
PHASES=('A-cold-typed','A-cold-ordinary','B-cold-typed','B-cold-ordinary','B-first-ordinary','B-first-typed','B-first-kernel')
def read(p):return json.loads(p.read_bytes())
def compare_sets(sets_a,sets_b,raw,allow_exact_archive):
    result={}
    for name in NAMES:
        a,b=sets_a[name],sets_b[name];common=set(a)&set(b);miss=sorted(set(a)^set(b));changes={}
        for k in sorted(common):
            if a[k]==b[k]:continue
            rec={'a':a[k],'b':b[k],'verified_archive_alias':False}
            if allow_exact_archive and name in ('workspace-products','terminal-extern-inputs') and k.endswith('.rlib')and any('/'+x+'/'in k for x in('uv-version','uv-static')):
                try:rec['archive_proof']=archive_compare(raw(a[k]),raw(b[k]));rec['verified_archive_alias']=True
                except (ValueError,AssertionError,TypeError,KeyError,IndexError)as e:rec['why']=str(e)
            changes[k]=rec
        result[name]={'count':[len(a),len(b)],'raw_equal':len(common)-len(changes),'missing':miss,'differing':changes,'gate':not miss and all(r['verified_archive_alias']for r in changes.values())}
    return result
def verify(root):
    info=read(root/'collection.json');case=read(H/'case.json');expected=read(root/'intake.json');post=read(root/'final-sdk.json')
    require(info.get('scored')is False and info['source']==case['source']and set(info['roles'])==set(ROLES),'not an unscored authenticated admission')
    require(all(expected[k]==case[k]for k in ('installed','build_head','build_run','sdk_lock_sha256','signed_cargo_sha256')),'production SDK or signed Cargo changed')
    require(set(post)==set(ROLES)and all(post[r]['runtime']==case['installed'][r]['runtime']and post[r]['files']>60 for r in ROLES),'final material changed')
    require(digest((root/'A-B.patch').read_bytes())==case['source']['patch']and digest(dump(read(root/'registry.json')))==case['registry_canon_sha256'],'historical source or registry changed')
    failed=info['errors'];out={}
    def raw(row):
        n,q=row;b=gzip.decompress((root/'blobs'/(q+'.gz')).read_bytes());require(len(b)==n and digest(b)==q,'damaged raw product');return b
    for role in ROLES:
        d=root/role
        if role in failed:out[role]={'collection_error':failed[role],'gate':False};continue
        obs=read(d/'observed.json');ws=read(d/'witnesses.json');sets={p:{k:read(d/p/(k+'.json'))for k in NAMES}for p in PHASES}
        custody={}
        for v in sets.values():
            for group in ('workspace-products','public-sidecars','terminal-extern-inputs'):
                for row in v[group].values():
                    size,h=row
                    if h not in custody:raw(row);custody[h]=size
                    require(custody[h]==size,'size conflict for retained content')
        require(obs['role']==role and obs['native_scored']is False,'incorrect native attribution')
        inputs=read(d/'B-first-typed/witness-inputs.json');coords=[obs['terminal'],*obs['providers']]
        require(inputs['terminal']=='uv_resolver'and inputs['uv-resolver']==[coords[0]]and inputs['uv-workspace']==coords[1:],'wrong primary metadata')
        cp={}
        for lab,a,b,alias in [('same-restored-B-typed','B-first-ordinary','B-first-typed',False),('same-restored-B-kernel','B-first-ordinary','B-first-kernel',False),('independent-A-bare-vs-typed','A-cold-ordinary','A-cold-typed',True),('independent-B-bare-vs-typed','B-cold-ordinary','B-cold-typed',True),('first-B-vs-independent-bare-B','B-first-ordinary','B-cold-ordinary',True)]:
            cp[lab]=compare_sets(sets[a],sets[b],raw,alias)
        diagnostics={}
        for phase,state,tag in [('A-cold-typed','A','parent'),('B-cold-typed','B','clean-child'),('B-first-typed','B','edited')]:
            rows=[read(p)for p in sorted((d/phase/'consumer-receipts').glob('*.json'))];positive=[];negative=[]
            for rr in rows:
                expected=rr['expected'];path=rr['actual_metadata'];k=next((p for p in coords if path.endswith('/'+p)),None);require(k is not None and sets[phase]['workspace-products'][k][1]==rr['metadata_sha256'],'unbound downstream metadata')
                if expected is None and rr['exit']==0:positive.append(k)
                elif expected==['E0308','mismatched types']and rr['exit']==1:
                    errors=[q for q in map(json.loads,rr['stderr'].splitlines())if q.get('level')=='error'and q.get('code')];require([x['code']['code']for x in errors]==['E0308']and 'mismatched types'in errors[0]['message'],'wrong negative observation');negative.append(k)
            required={'edit':22635,'member':'seeds','virtual_root_reuses_cache':True,'member_reuses_cache':True,'cache_value_stores_project_name':state=='B'}
            diagnostics[phase]={'positive':positive,'negative_E0308':negative,'native_provider_fixture':ws[tag],'passed':set(positive)==set(coords)and negative==[coords[0]]and ws[tag]==required}
        fc={p:{k:sets[p]['workspace-products'][k]for k in coords}for p in PHASES};same=all(x['gate']for cm in cp.values()for x in cm.values())
        rosters=[read(d/p/'roster.json')for p in('A-cold-typed','B-cold-typed','B-first-typed')];profiles=all(v==rosters[0]for v in rosters)
        argv=read(d/'B-first-typed/actual-argv.json');copies=read(d/'B-first-kernel/kernel-compilers.json')
        kernel=sorted(a for pid,a in copies)==sorted(argv)and len({pid for pid,_ in copies})==len(copies)
        messages=[read(d/p/'messages.json')for p in('A-cold-typed','B-cold-typed','B-first-typed')];workspace_messages=lambda v:sorted((r for r in v if r['package_id'].startswith('path+file:')),key=dump)
        same_diag=workspace_messages(messages[1])==workspace_messages(messages[2])
        out[role]={'terminal':obs['terminal'],'providers':obs['providers'],'full_raw_or_strict_alias_comparisons':cp,'all_native_artifact_choices_match':profiles,'warm_and_independent_cold_workspace_diagnostics_match':same_diag,'phase_selected_outputs':fc,'terminal_first_B_vs_cold_B_raw':fc['B-first-ordinary'][coords[0]]==fc['B-cold-ordinary'][coords[0]],'native_controls':diagnostics,'unique_verified_retained_raws':len(custody),'kernel_processes':len(copies),'kernel_equals_full_verbose_argv':kernel,'native_gates':obs['gates'],'gate':same and profiles and kernel and same_diag and all(d['passed']for d in diagnostics.values())and all(obs['gates'].values())}
    return {'schema':1,'admission_only':True,'scored_samples':0,'prior_workspace_raw_veto':'preserved','roles':out,'eligible_for_prospective_package_screen':len(out)==2 and all(v['gate']for v in out.values())}
if __name__=='__main__':
    root=Path(sys.argv[1]).resolve(strict=True);v=verify(root)
    with (root/'package-admission.json').open('x')as f:json.dump(v,f,sort_keys=True,indent=2);f.write('\n')
    print('unscored package admission',v['eligible_for_prospective_package_screen'])
