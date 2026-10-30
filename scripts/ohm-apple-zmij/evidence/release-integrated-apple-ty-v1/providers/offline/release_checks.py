"""Independently rederive the added signed-v1 and same-compiler Cargo-wrapper phases from original Apple outputs."""
import argparse,json,sys
from pathlib import Path
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from protocol import Receiver, sources, V1, V2, CASES
from native import sha,write,pretty,compact
from matrix import ORDINARY,UNWATCHED,depfile
from symbols import named
from application import open_trace, same, env, A, B, STEPS
def legacy(v,subjects,tool):
    v.legacy_comment=True # The signed scalar register comment has no MOV X29,X29 opcode.
    base='versioned/legacy/';decl=v.js(base+'terminal.json')
    assert not decl['signed_integrated_differences'] and decl['native_commands']==264 and decl['literal_commands']==36
    signed=v.js('release.json');producer=v.js(base+'producer.json')
    assert producer['source']=='7e71d3150938ff8ed82aca03416439d7e5b87ef3' and producer['rustc']['sha256']==signed['rustc']['sha256'] and producer['driver']['sha256']==signed['driver']['sha256'] and producer['std']==signed['std']
    assert 'asm!("/* {0} */", inout(reg) register, options(nomem,nostack,preserves_flags))' in producer['fixture']
    result={};files=set();all_lds=set()
    for receiver in CASES:
        each={};result[receiver]=each
        for place in ('direct','library'):
            for watch in ('declared','unwatched'):
                case=place+'-'+watch;p=base+receiver+'/'+case+'/';case_source=v.js(p+'inputs.json')
                src=case_source['source']; assert case_source['role']=='legacy' and case_source['placement']==place and case_source['watch']==watch and case_source['driver']['sha256']==producer['driver']['sha256']
                asm=src['src/main.rs' if place=='direct' else 'barrier/src/lib.rs'];assert producer['fixture'] in asm
                assert ('cargo:rerun-if-changed={name}' in src['build.rs'])==(watch=='declared') and 'cargo:rustc-link-search=native=' in src['build.rs']
                assert tuple(q[0] for q in case_source['steps'])==ORDINARY
                frozen=v.js(p+'terminal.json'); prior={'warm':{},'empty':{}};phases={}
                for phase,state,rust in case_source['steps']:
                    path=p+phase; cmp=v.js(path+'/compared.json');assert cmp==frozen[phase]
                    assert cmp['trigger_sha256']==sha(('#[inline(never)] pub fn value()->i32 {'+str(rust)+'}\n').encode())
                    val={'lower':17,'higher':29,'missing':None,'malformed':None}[state]
                    need=[0,[val,rust]] if val else [101,None]
                    arms={}
                    for slot in ('warm','empty'):
                        d=path+'/'+slot;row=v.js(d+'/verified.json');geo=v.provider_visit(d,place)
                        assert cmp[slot]==[geo['status'],geo['answer'],geo['raw']]
                        if slot=='empty' or watch=='declared' or phase not in UNWATCHED:assert cmp[slot][:2]==need,(path,slot,cmp[slot],need)
                        if geo['status']==0:
                            files.update(depfile(v,row,V1).values());image=v.image_proofs.proof(d,'edge-images',prior=prior[slot]);assert image['raw']==geo['raw']
                            geo['proof']={k:image[k] for k in ('raw','norm','output_sha','modules_sha','module_count','recipe')}
                        else:assert geo['error']
                        arms[slot]=geo
                    w,e=arms['warm'],arms['empty']
                    if w['status']==e['status']==0:
                        identical=v.image_proofs.same(w['proof'],e['proof'])
                        assert identical==cmp['same_checked_image'] and ((w['raw']==e['raw'])==cmp['same_raw'])
                    q=decl['rows'][receiver][case][phase]
                    assert q['warm']==[w['status'],w['answer']] and q['empty']==need and q['same']==cmp['same_checked_image']
                    phases[phase]={'warm':{k:w[k] for k in ('status','answer','full','link_only','ld','raw')},'empty':{k:e[k] for k in ('status','answer','full','link_only','ld','raw')},'clean':q['same'],'source':cmp['trigger_sha256'],'cargo_cdhash':e['cargo_cdhash']}
                each[case]=phases
    for c in result['signed']:
        for k,row in result['signed'][c].items():
            other=result['aware'][c][k];assert [row['warm'][i] for i in ('status','answer')]==[other['warm'][i] for i in ('status','answer')]
    literal=named(v,subjects,tool,V1)
    assert all(cd==subjects['stock_ld'] for _,cd in v.lds)
    return {'legacy_producer':producer['source'],'native':result,'raw_v1_depfiles':len(files),'named':literal}
def same_rust(v,subjects):
    saved=v.js('release-cli/terminal.json');assert saved['subjects']['rust']==subjects['rust']['C']['source'] and saved['subjects']['integrated_bytes']==subjects['cargo']['aware']['sha']
    result={};images={};
    for order in ('PC','CP'):
        each={};refs={}
        for logical in order:
            origin='release-cli/'+order+'/'+logical+'/C/';identity=v.js(origin+'installation.json')
            actual=subjects['cargo'][{'P':'signed','C':'aware'}[logical]]
            assert identity['driver']['sha256']==subjects['rust']['C']['driver'] and identity['cargo']['sha256']==actual['sha'] and actual['source'] in identity['cargo_version']
            assert env(v.js(origin+'development-environment.json'));results={};prior={}
            for group,step,rev in [('clean-old','clean',A),('clean-new','clean',B),*[('visits',st,A if st=='cold' else B) for st in STEPS]]:
                path=origin+group+'/'+step;facts,proof=open_trace(v,path,'C',rev,images,prior if group=='visits' else {},old=False)
                if group=='visits':
                    if proof is not None:assert same(proof,refs[logical,rev])
                else:refs[logical,rev]=proof
                results[group+'/'+step]={k:facts[k] for k in ('full','link_only','ld','final_links','units','dirty','verdict','objc2','cargo_cdhash','dependency_info')}
            each[logical]=results
        for rev,key in ((A,'clean-old'),(B,'clean-new')):
            a,b=[refs[r,rev] for r in 'PC'];assert a['outcome']==b['outcome'] and a['native']['modules_sha']==b['native']['modules_sha'] and a['native']['cross']==b['native']['cross']==saved['orders'][order]['cross'][key]
        for step in ('repeat-1','repeat-2'):
            p,c=[each[r]['visits/'+step] for r in 'PC'];assert (p['objc2'],c['objc2'])==(1,0) and len(c['full'])<len(p['full']) and c['ld']<=p['ld']
        result[order]=each
    return {'physical':result,'raw_complete_unique_MachO':images}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('name',choices=['legacy','cargo-cli']);p.add_argument('archive',type=Path);p.add_argument('out',type=Path);p.add_argument('--b3sum');a=p.parse_args()
    with ZipFile(a.archive) as z:
        v=Receiver(z);subjects=sources(v)
        res=legacy(v,subjects,a.b3sum) if a.name=='legacy' else same_rust(v,subjects)
    if a.out.suffix=='.gz':
        import gzip
        write(a.out,gzip.compress(compact(res).encode(),mtime=0))
    else:write(a.out,pretty(res))
    print(a.name,a.out)
