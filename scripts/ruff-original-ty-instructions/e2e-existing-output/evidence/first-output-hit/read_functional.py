"""Independently reopen the one-target native proof, retaining incomplete roles on refusal."""
from pathlib import Path
import gzip,hashlib,json,re,sys,zipfile
N=Path(__file__).resolve().parent
runtime=N/'functional-screen' if (N/'functional-screen').is_dir()else N.parent.parent
sys.path.insert(0,str(runtime));from bound_inputs import receive
sys.path.insert(0,str(N if (N/'read_relation.py').is_file()else N.parent/'jobserver-groups'));from read_relation import validated_container
def sha(v):return hashlib.sha256(v).hexdigest()
def main(p,head,run,digest):
    zpath=Path(p)
    with zpath.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==digest
    results={'archive':{'sha256':digest,'bytes':zpath.stat().st_size},'prices':{},'stages':{},'terminal':None}
    with zipfile.ZipFile(zpath)as z:
        all_=set(z.namelist());assert len(all_)==len(z.namelist()) and z.testzip()is None
        def data(n):return gzip.decompress(z.read(n))if n.endswith('.gz')else z.read(n)
        def row(n):return json.loads(data(n))
        reg=row('registration.json');assert reg['head']==head and str(reg['run'])==str(run)and reg['never_skip']==False
        results.update(registration=reg,complete='complete.json'in all_)
        verdicts={}
        for n in sorted(x for x in all_ if x.endswith('/test-list')):
            key=n.rsplit('/',1)[0];raw=data(n);assert sha(raw)==reg['reference']['list']
            names=[x.removesuffix(b': test')for x in raw.splitlines()if x.endswith(b': test')];assert len(set(names))==len(names)==200 and names.count(b'commands::debug_command')==1
            out=data(key+'/stdout');is_bad=key=='withheld-old-fails'
            assert (b'test result: FAILED. 0 passed; 1 failed;' if is_bad else b'test result: ok. 1 passed; 0 failed;')in out
            verdicts[key]={'names':len(names),'expected_failure':is_bad,'stdout':sha(out),'stderr':sha(data(key+'/stderr'))}
        results['verdicts']=verdicts
        for n in sorted(x for x in all_ if x.endswith('/resources.json')):
            tag=n.split('/')[0];res=row(n);d={'resources':res};results['stages'][tag]=d
            q=tag+'/stdout.jsonl';cargo=[json.loads(x)for x in data(q).splitlines()] if q in all_ else []
            if cargo:d['cargo_terminal']=cargo[-1]
            if tag+'/hardware.json'in all_:
                hw=row(tag+'/hardware.json');assert 0<hw['instructions'] and 0<hw['running']<=hw['enabled'] and hw['running']>=.98*hw['enabled']
                price=dict(hw);price['elapsed_ns']=int(data(tag+'/hardware.json.elapsed-ns'));assert price['elapsed_ns']>0;results['prices'][tag]=price
            prefix=tag+'/link-actor.tsv.gz'
            if prefix not in all_:continue
            raw=data(prefix);reports=[line.decode().split('\t')for line in raw.splitlines()]
            ops=lambda name:[f[1:]for f in reports if f[0]==name]
            d['accepted']=ops('ACCEPT');d['published']=ops('FRESH-PUBLISH');d['refused']=ops('MISS');d['verified']=ops('VERIFIED')
            if tag in ('save','malformed'):
                assert not d['published'] and cargo[-1]=={'reason':'build-finished','success':False};continue
            context,_=receive(raw.decode());d['input_proof']={k:context[k]for k in ('key','parts','inputs','bytes','requests','denied_lookups')};d['worker_count']=int(context['context']['TYPED'][0][4])
            if context['context']['GROUPINPUT']:
                planned=ops('PROJECTED-GROUP');physical=ops('ACTUAL-GROUP')
                assert len(planned)==int(context['context']['GROUPINPUT'][0][3]) and (not physical if d['published']else physical==planned)
                d['source_groups']={'count':len(planned),'typed_order':context['context']['GROUPINPUT'][0]}
            for actor in ('source','signed'):
                path=tag+'-'+actor+'-container.json.gz'
                if path in all_:
                    e=row(path);validated_container(e);d[actor+'_elf']={k:e[k]for k in ('sha256','size','buildid','zeroed_complete_buildid')}
            complete=tag+'-complete.json'
            if complete not in all_:continue
            record=row(complete);d['stored']=record.get('canonical_storage');d['input_eligible']=record.get('handoff',{}).get('candidate_requested')
            if d.get('source_elf')and d.get('signed_elf'):assert d['source_elf']==d['signed_elf'],tag
            if d['published']:
                assert len(d['published'])==len(d['accepted'])==1 and d['source_elf']['size']==int(d['published'][0][0])
                meter=record['ordinary_clock'];outer=results['prices'][tag];assert meter['retired_user']==outer['instructions'] and not meter['serial_signed_control_ran']
                charge=meter['coordinator_thread'];assert 0<charge['running']<=charge['enabled'] and charge['instructions']>0
                assert meter['cargo_and_coordinator_user_instructions']==outer['instructions']+charge['instructions'];outer['coordinator_instruction_charge']=charge['instructions']
        if results['complete']:
            complete=row('complete.json');stages=results['stages'];h=[k for k,v in stages.items()if v.get('published')];assert set(h)=={'warm2','warm-repeat','capability'}
            assert stages['old']['source_elf']['sha256']==reg['reference']['old']
            for tag in ('edit',*h):assert stages[tag]['source_elf']['sha256']==reg['reference']['new']
            for stage in ('signed-independent-new','signed-untouched-warm1','signed-untouched-warm2'):
                assert complete[stage]['sha256']==reg['reference']['new'] and complete[stage]['executable_count']==102
            assert complete['four']['exit']==83 and set(('withheld-old-fails','signed-independent-new-verdict'))<=set(verdicts)
            assert len(complete['warm2']['canonical_storage']['same_image_in_both_output_roots'])==1 and complete['capability']['old_capability'][-1]==0
            results['terminal']='qualified one-target functional study'
    return results
if __name__=='__main__':print(json.dumps(main(*sys.argv[1:]),indent=2,sort_keys=True))
