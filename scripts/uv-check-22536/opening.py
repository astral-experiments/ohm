"""Run genuine unscored native source/metadata gates before admitting any external clock."""
import json,os,shutil,subprocess
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from basis import CASE,HERE,LOCK,PLAN,Env,SIX,WORKSPACE,canon,digest,filehash,kernel,read,readz,setup,shape,write,writez
import semantics
import fixed_input
def changed_forms(row):
    return {k:v for k,v in row['forms'].items()if k in SIX}
def source_result(e,state,scope):
    record=semantics.products(e,scope,store=True)
    return record
def reproduce(e,role,d):
    e.choose(role);d.mkdir();e.source('A');e.reset();a=kernel(e,d/'cold-A','cold');paths=a['workspace_rmeta_from_argv'];products=source_result(e,'A',paths)
    initial=semantics.probe(e,'A',a['forms'],d/'cold-A');writez(d/'cold-A/products.json.gz',products)
    kernel(e,d/'noedit-A','unchanged');assert semantics.products(e,paths)==products
    warm={};forms={};outcomes={};semantic={};quiet={'A':True}
    for state in 'BCD':
        e.source(state);rec=kernel(e,d/('warm-'+state),'edited');assert rec['workspace_rmeta_from_argv']=={n:paths[n]for n in SIX}
        forms[state]=changed_forms(rec);warm[state]=source_result(e,state,paths);writez(d/('warm-'+state)/'products.json.gz',warm[state])
        outcomes[state]=semantics.probe(e,state,forms[state],d/('warm-'+state))
        kernel(e,d/('noedit-'+state),'unchanged');assert semantics.products(e,paths)==warm[state];quiet[state]=True
    for state in 'BCD':
        e.source(state);e.reset();cold=kernel(e,d/('fresh-'+state),'cold');assert cold['workspace_rmeta_from_argv']==paths
        val=source_result(e,state,paths);writez(d/('fresh-'+state)/'products.json.gz',val);assert semantics.probe(e,state,cold['forms'],d/('fresh-'+state))==outcomes[state]
        loc=d/('fresh-'+state);pre=loc/'literal';pre.mkdir();r=semantics.typed_compare(e,warm[state],val,pre)
        coverage={}
        if r['needs_fixed_input']:
            certificate=fixed_input.certify(e,role,state,loc/'fixed',paths,cold['forms'],val,outcomes[state],r['needs_fixed_input']);coverage={k:v['coverage']for k,v in certificate['covered'].items()}
        r=semantics.typed_compare(e,warm[state],val,loc,coverage);semantic[state]={k:r[k]for k in ('accepted','ctfe_terminal_only','unresolved','exact_rmeta','all_workspace','all_public')}
    answer={'role':role,'states':CASE['states'],'normal_roster':SIX,'actual_unchanged':quiet,'real_external_apis':{'A':initial,**outcomes},'semantic':semantic,'passes':all(r['accepted']for r in semantic.values()),'only_known_ctfe':(any(r['ctfe_terminal_only']for r in semantic.values())and all(r['accepted']or r['ctfe_terminal_only']for r in semantic.values())),'native_workspace':len(paths)};write(d/'verdict.json',answer);return answer
def qualify(e,include_upstream=True):
    import runpy
    gates=e.results/'qualification';gates.mkdir();kit=HERE/'kit/ctfe';receipt=read(HERE/'ctfe-authority.json');assert all(filehash(kit/n)==h for n,h in receipt['real_inputs'].items());ctfe_runner=runpy.run_path(str(kit/'ctfe_check.py'))['main']
    def linked318(role):
        sdk=Path(e.inp['sdks'][role]);dest=gates/('actual-ctfe-'+role+'.json');commit=LOCK['roles'][role]['source']['commit'];ctfe_runner(sdk,commit,dest);native=read(dest)
        historic=receipt['native_originals']['R'if role=='R'else'S'];assert native['source_commit']==commit and native['rustc_launcher_sha256']==LOCK['roles'][role]['runtime']['bin/rustc']['sha256']and native['checks']==historic['checks']and native['matches_official_regression']==(role!='R')
        assert len(native['visits'])==5 and all(len(x['commands'])==4 and all(a['exit']==0 for a in x['commands'])for x in native['visits'].values());return filehash(dest)
    canonical={'R':linked318('R'),'F':linked318('F')};r=reproduce(e,'R',gates/'signed-1');e.reset()
    if r['passes']:control='R'
    else:
        assert r['only_known_ctfe'],'untimed signed control had an unexplained failure'
        twin=reproduce(e,'R',gates/'signed-2');e.reset();assert twin['only_known_ctfe']and {s for s,x in r['semantic'].items()if x['ctfe_terminal_only']}=={s for s,x in twin['semantic'].items()if x['ctfe_terminal_only']}
        canonical['S']=linked318('S');fixed=reproduce(e,'S',gates/'corrected');e.reset();assert fixed['passes'];control='S'
    full=reproduce(e,'F',gates/'treatment');assert full['passes'];e.reset()
    parent=gates/('signed-1'if control=='R'else'corrected');surfaces={}
    for state in 'BCD':
        sides=[]
        for folder in(parent,gates/'treatment'):
            rec=readz(folder/('warm-'+state)/'argv.json.gz');assert sorted(rec['forms'])==SIX and not rec['all_other_rustcs'];sides.append({n:shape(a[0])for n,a in rec['forms'].items()})
        assert sides[0]==sides[1],(state,'cross-role compiler surface');surfaces[state]=digest(canon(sides[0]))
    witness={}
    if include_upstream:
        for role in (control,'F'):
            e.choose(role);rows={}
            for state in 'ABCD':
                directory=gates/(role+'-upstream-'+state);semantics.upstream(e,state,directory);rows[state]=read(directory/'accepted.json')['passed_rank_tests']
            e.reset();shutil.rmtree(e.root/'fixture-target');witness[role]=rows
        assert witness[control]==witness['F']=={'A':0,'B':1,'C':1,'D':1}
    data={'plan':CASE['protocol'],'control':control,'treatment':'F','signed_result':r,'canonical_ctfe_source_receipts':canonical,'all_live_sources_semantically_admitted':True,'actual_role_argv':surfaces,'upstream_rank_witnesses':witness,'suitable_to_score':include_upstream}
    write(gates/'accepted.json',data);return data
if __name__=='__main__':
    import sys
    request=read(sys.argv[2]);e=Env(request)
    if sys.argv[1]=='prepare':setup(e)
    elif sys.argv[1]=='qualify':qualify(e)
    elif sys.argv[1]=='one':reproduce(e,sys.argv[3],e.results/('opening-'+sys.argv[3]))
    else:raise SystemExit('prepare|qualify|one config.json [role]')
