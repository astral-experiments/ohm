"""Re-open the exact CRC typeshed inputs, physical Rust/Xcode launches, native receipts and foreground clocks."""
import argparse,gzip,hashlib,io,json,sys,zipfile
from pathlib import Path,PurePosixPath
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native import Dataset,P,C,R,digestfile,sha,pretty,write,compact
from provider import sources
from macho import section
from canonical import compare
from clocks import A,B,CMD,TESTS,PHASES,tests,typed,results,raw,rec

LOCK='583d2c16902903b32c016859c12131cb80fd8bdc4121440f359ef743675fc1c5'
LD='2b48a59af70235283aa94c43eb0dd2ef80182c106db43279db936cc87426b443'
DATA=json.loads((Path(__file__).parent/'ruff-sources.json').read_bytes())
STEPS=('cold','edit','repeat-1','repeat-2','invalid','repair')
L=PurePosixPath

def checked_product(view,rev,p,imgs,archives):
    key=p['raw'];archive=p['zip_sha256']
    if key not in imgs:
        binary=view.gz('crc-programs/'+key+'.gz')
        kind,body,_=section(binary)
        assert kind==2 and sha(binary)==key and p['text']==[len(body),sha(body)]
        imgs[key]=binary
    if archive not in archives:
        container=view.gz('crc-zips/'+archive+'.gz');assert sha(container)==archive
        with zipfile.ZipFile(io.BytesIO(container)) as st:
            assert len(st.infolist())==len(set(st.namelist()))==819 and st.testzip() is None
            for name,src in DATA[rev].items():
                content=st.read(name)
                assert len(content)==src['bytes'] and sha(content)==src['sha256']==p['inputs'][name]
                assert hashlib.sha1(b'blob '+str(len(content)).encode()+b'\x00'+content).hexdigest()==src['git_blob']
                assert st.getinfo(name).compress_type==zipfile.ZIP_DEFLATED
        archives[archive]=container
    assert archives[archive] in imgs[key] and p['tests']==TESTS
    assert p['inputs']=={a:q['sha256'] for a,q in DATA[rev].items()}

def actual(view,path):
    proof=view.js(path+'/verified.json');assert proof['command']==CMD
    msgs=list(map(json.loads,view.gz(path+'/stdout.gz').splitlines()))
    unit=lambda a:[a['package_id'],a['target']['name'],','.join(a['target']['kind']),a['features'],compact(a['profile'])]
    arts=[a for a in msgs if a['reason']=='compiler-artifact']
    reported={**proof, 'argv':CMD,'status':proof['code'],'streams':proof['streams']['streams'],'typed':sorted(unit(a) for a in arts),'dirty':sorted(unit(a) for a in arts if not a['fresh'])}
    d,_,stdout,stderr,ld=view.actual(path,'ruff',reported)
    roots=[a['argv'] for a in ld if [v for k,v in zip(a['argv'],a['argv'][1:]) if k=='-o']==[proof['output']]]
    assert roots==proof['root_link_argv']
    assert all(v['sha']==LD and v['stock'] for v in proof['native']['linkers'])
    d['build_script_ld']=sum(L(b).name=='build_script_build' for e in ld for a,b in zip(e['argv'],e['argv'][1:]) if a=='-o')
    d['root_ld']=len(roots);d['rev']=proof['rev'];d['step']=proof['step'];d['markers']=[]
    libs=[x for x in arts if x['target']['name']=='zlib_rs' and x['target']['kind']==['lib']]
    assert libs and len(libs)==len(proof['zlib'])
    for i,(lib,dep) in enumerate(zip(libs,proof['zlib'])):
        assert lib['package_id'].endswith('#zlib-rs@0.5.5') and lib['features']==dep['features'] and lib['fresh']==dep['fresh'] and dep['path'] in lib['filenames']
        b=view.gz(path+f'/zlib-{i}.dep.gz')
        assert sha(b)==dep['dep'] and b'zlib-rs-0.5.5/src/' in b
        assert dep['hard']==(b'ohm-untracked-relink-inputs' in b) and dep['recheck']==(b'/dev/null/ohm-recheck-dependent-links' in b)
        d['markers'].append({'hard':dep['hard'],'recheck':dep['recheck'],'dep':sha(b),'archive':dep['sha256'],'fresh':lib['fresh'],'features':lib['features']})
    stage=d['step']
    if stage=='invalid':
        assert d['status']==101 and not proof['product'] and not proof['output'] and not roots
        assert any((m.get('message',{}).get('code') or {}).get('code')=='E0425' for m in msgs) and b'ohm_crc_missing_rust_name' in stdout
        assert not any(a['target']['name']=='ty_vendored' and a.get('executable') for a in arts)
    else:
        assert d['status']==0 and any(a['target']['name']=='ty_vendored' and a.get('executable')==proof['output'] and a['profile']['test'] for a in arts)
        tests(view.z,view.prefix+path+'/')
        if stage in ('clean','cold','edit','repair'):assert len(roots)==1 and 'ty_vendored' in d['full']
    d['product']=proof['product']
    return proof,d

def bundle(view,role):
    path='native-input/'+role+'/';history=view.js(path+'terminal.json');result={}
    want={'initial':17,'unchanged':17,'replace':29,'malformed':None,'missing':None,'repair':29,'empty-reference':29}
    assert set(history)==set(want)
    for s,value in want.items():
        p=path+s+'/';d=view.js(p+'verified.json');assert d==history[s]
        streams={k:view.gz(p+a+'.gz') for k,a in [('stdout','stdout'),('stderr','stderr'),('native_events','exec.json')]}
        assert {k:sha(v) for k,v in streams.items()}==d['streams']['streams']
        msgs=list(map(json.loads,streams['stdout'].splitlines()));es=json.loads(streams['native_events'])
        assert msgs[-1]=={'reason':'build-finished','success':value is not None} and d['cargo_exit']==(0 if value else 101)
        assert d.get('value')==value
        if value:
            body=view.gz(p+'bundled-library.dep.gz')
            assert sha(body)==d['bundled_dep_sha256'] and b'ohm-untracked-relink-inputs' in body
        else:assert b'qa_answer' in streams['stdout']+streams['stderr']
        lds=[x for x in es if L(x['path']).name=='ld']
        assert [x['argv'] for x in lds]==[x['argv'] for x in d['native']['linkers']]
        assert all(q['stock'] and q['sha']==LD for q in d['native']['linkers'])
        result[s]={'status':d['cargo_exit'],'value':value,'archive':d['archive'],'binary':d.get('executable'),'ld':len(lds),'full':d['native']['full'],'link_only':d['native']['link_only']}
    assert result['initial']['archive']!=result['replace']['archive'] and result['repair']['binary']==result['empty-reference']['binary']
    return result

def analyze(archive):
    with zipfile.ZipFile(archive) as z:
        view=Dataset(z);sub=sources(view);cfg=view.js('ruff.json')
        assert (cfg['old'],cfg['new'],cfg['lock'])==(A,B,LOCK)
        imgs={};archives={};mirror={};rows={};stats={};refs={};traces={};ident=None;terminal={};cohorts={};crosses={}
        for order in ('PC','CP'):
            orderroot='crc-clock-before/'+order
            records={}
            for role in order:
                rolepath=orderroot+'/'+role
                if not view.exists(rolepath+'/driver.json'):continue
                idt=view.js(rolepath+'/driver.json');assert idt['role']==role and idt['sdk']['driver']['sha256']==sub['rust'][role]['driver'] and idt['sdk']['cargo']['sha256']==sub['cargo_sha256']
                cn={}
                phases=[('clean-old','clean',A),('clean-new','clean',B)]
                phases += [('visits',s,A if s=='cold' else B) for s in STEPS]
                for tag,s,rev in phases:
                    p=rolepath+'/'+tag+'/'+s
                    if not view.exists(p+'/verified.json'):continue
                    v,d=actual(view,p);assert d['rev']==rev,(p,d['rev'],rev)
                    if ident is None:ident=d['cargo_cdhash']
                    assert d['cargo_cdhash']==ident
                    if s!='invalid':
                        checked_product(view,rev,d['product'],imgs,archives)
                        if tag!='visits':
                            cn[rev]=d['product']
                            crosses[order,role,rev]=(imgs[d['product']['raw']],v['output'],v['root_link_argv'][0])
                        else:assert d['product']==cn[rev]
                    if tag=='visits':
                        records.setdefault((role,'visits'),[]).append(s)
                        if s!='invalid':
                            _,sig,_=typed(z,view.prefix+p+'/')
                            assert traces.setdefault((role,s),sig)==sig
                    rows[order+'/'+role+'/'+tag+'/'+s]=d
                if len(cn)==2:
                    assert cn[A]['raw']!=cn[B]['raw'] and cn[A]['zip_sha256']!=cn[B]['zip_sha256']
                    for rev,prod in cn.items():assert refs.setdefault((role,rev),prod)==prod
                if records.get((role,'visits'))==list(STEPS):
                    for step in ('repeat-1','repeat-2'):
                        row=rows[order+'/'+role+'/visits/'+step]
                        prior=rows[order+'/'+role+'/visits/'+('edit' if step=='repeat-1' else 'repeat-1')]
                        row['prior_seal_hit']=bool(row['driver_processes'] and not row['root_ld'] and row['product']['raw'] in row['receipt_products'] and set(row['seals'])&set(prior['seals']))
            if not view.exists(orderroot+'/verdict.json'):continue
            vv=view.js(orderroot+'/verdict.json');phase={}
            for step in ('edit','repeat-1','repeat-2'):
                p,c=(rows[order+'/'+r+'/visits/'+step] for r in 'PC')
                native={}
                for r,row in zip('PC',(p,c)):
                    marker=row['markers'];native[r]={'full':row['full'],'link_only':row['link_only'],'ld':row['ld'],'root_ld':row['root_ld'],
                        'build_script_ld':row['build_script_ld'],'driver':row['driver_processes'],'sealed_output':row['product']['raw'] in row['receipt_products'],
                        'zlib_full':row['full'].count('zlib_rs'),'hard':[d['hard'] for d in marker],'recheck':[d['recheck'] for d in marker]}
                assert native==vv[step]['roles']
                qualified=bool(p['full']==['build_script_build','ty_vendored','zlib_rs','zlib_rs'] and c['full']==['build_script_build','ty_vendored']
                    and len(p['markers'])==len(c['markers'])==2 and all(x['hard'] for x in p['markers']) and all(not x['hard'] and x['recheck'] for x in c['markers'])
                    and all(not r['link_only'] and r['ld']==2 and r['root_ld']==r['build_script_ld']==r['driver']==1 and r['sealed_output'] for r in native.values()))
                assert qualified==vv[step]['passed'];phase[step]=qualified
            mirror[order]=phase
            for rev in (A,B):
                match=compare({r:crosses[order,r,rev] for r in 'PC'})
                assert match==view.js(orderroot+'/'+rev+'-cross.json')
                stats[order+'/'+rev]=[match['canonical_sha256'],match['raw_difference_bytes']]
        if view.exists('declared-crc-subject.json'):
            reg=view.js('declared-crc-subject.json')
            assert len(mirror)==2 and len(rows)==32 and reg['rust']==[P,C] and reg['cargo']==R and reg['ruff']==[A,B]
            assert reg['structural']==all(all(x.values()) for x in mirror.values())
            assert reg['provider']==sha(view.raw('provider-matrix/terminal.json'))
            bundles={r:bundle(view,r) for r in 'PC'}
        else:bundles={}
        for mode in ('screen','confirmation'):
            if not view.exists('crc-clock-'+mode+'/result.json'):continue
            outcome,_=results(z,mode,refs,traces)
            cohorts[mode]=outcome
        if view.exists('crc-clock-confirmation/result.json'):
            for r in 'PC':
                p='crc-clock-confirmation/terminal-clean/'+r
                _,d=actual(view,p)
                assert d['product']==refs[r,B] and d['root_ld']==1
                terminal[r]=d
        return {'raw_sha256':digestfile(archive),'sources':sub,'images':{k:len(b) for k,b in imgs.items()},'zips':{k:len(b) for k,b in archives.items()},'physical_native':rows,'structural':mirror,'cross_native':stats,'bundled':bundles,'clocks':cohorts,'terminal_native':terminal,'terminal_gates':view.js('terminal-gates.json') if view.exists('terminal-gates.json') else None}

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('archive',type=Path);ap.add_argument('out',type=Path);a=ap.parse_args()
    data=analyze(a.archive);write(a.out,pretty(data));print(json.dumps({'commands':len(data['physical_native']),'structural':data['structural'],'pilot':data['clocks'].get('screen',{}).get('passed'),'confirm':data['clocks'].get('confirmation',{}).get('passed'),'terminal_gates':data['terminal_gates']},sort_keys=True))
