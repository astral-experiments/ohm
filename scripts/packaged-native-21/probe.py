"""Run the same declared native, same-timestamp and undeclared input corpus on an installed Ohm."""
from __future__ import annotations
import argparse,json,os,re,shutil,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fixture import ARCHIVE,CASES,PARITY,STATES,allocated_sections,artifacts,compressed,digest,enroll_sdk,environment,form,native_state,remove_owned,source_state
from packages import need,platform_triple,save,sha


def expected(state,rust):
    return ('rust-error',None) if rust is None else ('native-error',None) if state in ('malformed','missing') else ('ok',[17 if state=='lower' else 29,rust])

def command(root,cwd,env,owner,directory,phase,state,rust,native):
    directory.mkdir(parents=True);selected='qa_release_app' if owner=='direct' else 'qa_release_test';argv=['cargo','+ohm',*(['build','--bin',selected] if owner=='direct' else ['test','--test',selected,'--no-run']),'--locked','--offline','-vv','--message-format=json'];hist=root/'script-invocations';before=hist.read_bytes() if hist.exists() else b''
    result=subprocess.run(argv,cwd=cwd,env=env,capture_output=True,timeout=150);data,err=result.stdout,result.stderr;after=hist.read_bytes() if hist.exists() else b'';need(after.startswith(before),'rewritten compiler observer');events=[json.loads(x) for x in data.splitlines()];need(result.returncode in (0,101) and events[-1]=={'reason':'build-finished','success':result.returncode==0},'wrong typed Cargo termination');out={'phase':phase,'state':state,'rust':rust,'argv':argv,'exit':result.returncode,'stderr':compressed(directory/'cargo-stderr.gz',err),'stdout':compressed(directory/'cargo-stdout.gz',data),'script_runs':(after[len(before):]).count(b'run\n'),'native':native};arts=[e for e in events if e['reason']=='compiler-artifact'];decl=[e for e in events if e['reason']=='build-script-executed'];q=[e for e in arts if e['target']['name']==selected and e['executable']];out['units']=[[e['target']['name'],e['target']['kind'],e['fresh']] for e in arts];out['real_rustc_commands']=[x.decode(errors='replace') for x in err.splitlines() if b'Running `' in x and b'--crate-name' in x];out['incremental_rustcs']=[name for x in out['real_rustc_commands'] for name in re.findall(r'--crate-name ([\w]+)',x) if re.search(r'-C ?incremental=',x)];logs='\n'.join(e['message'].get('rendered','') or e['message']['message'] for e in events if e['reason']=='compiler-message')+'\n'+err.decode(errors='replace');need('internal compiler error' not in logs.lower() and 'panicked at' not in logs.lower() and 'please submit a full bug report' not in logs.lower(),'compiler or linker panic');out['codes']=[e['message']['code']['code'] for e in events if e['reason']=='compiler-message' and e['message'].get('code')]
    out['declared_search']=[{'package':e['package_id'],'linked_paths':e['linked_paths']} for e in decl if e['linked_paths']];out['dep_info']=[]
    for store in ('target','shared'):
        for f in (root/'stores'/store).rglob('*.d'):
            if not f.is_file() or f.stat().st_size>2**20:continue
            b=f.read_bytes()
            if b'qa_release_app' in b or b'owned/src/lib.rs' in b or b'tests/contract.rs' in b:
                h=digest(b);compressed(root/'receipts'/'dep-info'/(h+'.gz'),b);out['dep_info'].append([str(f.relative_to(root/'stores')),h,b'ohm-untracked-relink-inputs' in b,b'/dev/null/ohm-recheck-dependent-links' in b])
    out['dep_info'].sort();out['product']=None
    if result.returncode==0:
        unit,=q;path=Path(unit['executable']);need(path.is_file() and path.is_relative_to(root/'stores'),'unowned output selected');b=path.read_bytes();h=digest(b);compressed(root/'receipts'/'executables'/(h+'.gz'),b);program=[str(path)]+([] if owner=='direct' else ['--exact','provider_contract','--nocapture','--test-threads=1']);proc=subprocess.run(program,cwd=cwd,env=env,capture_output=True,timeout=20);matches=re.findall(rb'QA_RESULT=([0-9]+) ([0-9]+)',proc.stdout);need(proc.returncode==0 and len(matches)==1 and not proc.stderr and (owner=='direct' or b'1 passed; 0 failed; 0 ignored' in proc.stdout),'unrecognized native execution');value=list(map(int,matches[0]));out['outcome']='ok';out['value']=value;out['product']={'path':str(path),'sha256':h,'bytes':len(b),'sections':allocated_sections(b),'program':program,'program_exit':proc.returncode,'stdout':compressed(directory/'program-stdout.gz',proc.stdout),'stderr':compressed(directory/'program-stderr.gz',proc.stderr)}
    else:
        need(not q,'failed Cargo returned its selected product as successful');out['value']=None
        if 'E0425' in out['codes'] and 'qa_missing_declared_symbol' in logs:out['outcome']='rust-error'
        elif 'qa_release_boundary' in logs and any(x in logs.lower() for x in ('linking with','linker','archive','library not found','could not find native static library')):out['outcome']='native-error'
        else:out['outcome']='unexpected-failure'
    save(directory/'observed.json',out);return out

def run(root,role):
    root=root.resolve(strict=True);env=environment(root,role);enroll_sdk(root,role,env);originals=artifacts(root,env);out=root/'receipts'/role;outcomes={}
    for owner,watch in CASES:
        case=out/(owner+'-'+watch);policy='parity' if watch in ('same-mtime','undeclared') else 'declared';steps=PARITY if policy=='parity' else STATES
        remove_owned(root,'fixture');remove_owned(root,'stores');cwd=form(root,owner,watch);source_state(cwd,7);native_state(cwd,watch,'lower',originals);subprocess.run(['cargo','+ohm','generate-lockfile','--offline'],cwd=cwd,env=env,capture_output=True,check=True,timeout=30);case.mkdir();save(case/'source.json',{str(p.relative_to(cwd)):p.read_text() for p in cwd.rglob('*') if p.is_file() and p.suffix in ('.rs','.toml','.lock')});started=0
        warm={};refs={};summary=[]
        def visit(label,state,rust,seq,empty=False,preserve=False):
            nonlocal started
            if empty:remove_owned(root,'stores')
            store=root/'stores';store.mkdir(exist_ok=True);snapshot={d:(len(list((store/d).iterdir())) if (store/d).is_dir() else 0) for d in ('target','shared')};need(not empty or not any(snapshot.values()),'clean build was populated');
            if started and time.time_ns()-started<35_000_000:time.sleep(.05)
            started=time.time_ns();n=native_state(cwd,watch,state,originals,preserve=preserve);source_state(cwd,rust);here=case/seq/label;q=command(root,cwd,env,owner,here,label,state,rust,n);save(here/'entry-count.json',snapshot);return q
        for i,(label,state,rust) in enumerate(steps):
            warm[label]=visit(label,state,rust,'warm',empty=i==0,preserve=(watch=='same-mtime' and label=='changed-native'))
        for state,rust in dict.fromkeys((s,v) for _,s,v in steps):
            name=state+'-'+str(rust);refs[(state,rust)]=visit(name,state,rust,'empty',empty=True)
        aa=visit('independent-old','lower',7,'empty',empty=True);baseline=refs[('lower',7)];need(aa['outcome']==baseline['outcome']=='ok' and aa['value']==baseline['value']==[17,7],'two independent empty original states failed');
        aa_diff=[k for k in sorted(aa['product']['sections'].keys()|baseline['product']['sections'].keys()) if aa['product']['sections'].get(k)!=baseline['product']['sections'].get(k)]
        for label,state,rust in steps:
            q=warm[label];ref=refs[(state,rust)];want,val=expected(state,rust);need(ref['outcome']==want and ref['value']==val,f'{role}/{owner}/{watch}/{label} independent empty reference failed {ref["outcome"]} {ref["value"]}');diff=[];raw=None
            if q['product'] and ref['product']:
                x=q['product'];y=ref['product'];raw=x['sha256']==y['sha256'];diff=[k for k in sorted(x['sections'].keys()|y['sections'].keys()) if x['sections'].get(k)!=y['sections'].get(k)]
            ok=(q['outcome'],q['value'])==(want,val);summary.append({'phase':label,'state':state,'rust':rust,'warm':[q['outcome'],q['value']],'empty':[ref['outcome'],ref['value']],'verdict_matches':ok,'raw_equal':raw,'different_sections':diff,'warm_script_runs':q['script_runs']})
        cold=warm['cold'];compiler='qa_release_app' if owner=='direct' else 'owned';need(compiler in cold['incremental_rustcs'] and 'trigger' in cold['incremental_rustcs'],'normal developer compilation was not incremental');data={'scope':policy,'rows':summary,'clean_old_AA_different_sections':aa_diff,'clean_old_AA_same_raw':aa['product']['sha256']==baseline['product']['sha256'],'all_declared_verdicts_match':all(v['verdict_matches'] for v in summary) if policy=='declared' else None};save(case/'result.json',data);outcomes[owner+'-'+watch]=data;print('role',role,owner,watch,[(v['phase'],v['warm']) for v in summary if not v['verdict_matches']], 'clean A/A variation',aa_diff,flush=True)
        remove_owned(root,'stores');remove_owned(root,'fixture')
    save(out/'terminal.json',outcomes)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('role',choices=['20','21']);p.add_argument('root',type=Path);args=p.parse_args()
    try:run(args.root,args.role)
    except Exception as exc:
        import traceback
        save(args.root/'receipts'/args.role/'failure.json',{'failed':str(exc),'traceback':traceback.format_exc()});raise
