"""Recover the two independent CLI native orders from Cargo, EndpointSecurity and original files."""
import argparse, collections, json, re, sys
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native import C, P, Dataset, compact, digestfile, pretty, sha, write
from protocol import sources
from root_qualify_objc2 import mch

L = PurePosixPath
CMD = ['cargo','+ohm','build','-p','ty','--bin','ty','--locked','--offline','-j4','--message-format=json']
A,B = '4710e1aa962b13720cf64aa84eb279c5333896d7','915bb2b4bf9ae7eee47cf55646bbfebae254a23b'
OLD = b'All checks passed!\n'
NEW = (b'@list.py:1:14: error[invalid-assignment] Object of type `Literal["literal"]` is not assignable to `int`\n'
       b'@package/main.py:1:14: error[invalid-assignment] Object of type `Literal["directory"]` is not assignable to `int`\nFound 2 diagnostics\n')
HOST = {'HOME','PATH','USER','LOGNAME','TMPDIR','SHELL','SSL_CERT_FILE','SSL_CERT_DIR','DEVELOPER_DIR','SDKROOT'}
NEED = {'RUSTUP_HOME','CARGO_HOME','CARGO_TARGET_DIR','CARGO_BUILD_BUILD_DIR','CARGO_NET_OFFLINE','CARGO_TERM_COLOR','CARGO_CACHE_AUTO_CLEAN_FREQUENCY','LC_ALL','TZ'}
STEPS = ('cold','edit','repeat-1','repeat-2','invalid','repair')

def env(row):
    assert all(len(x)==64 and int(x,16)>=0 for x in row.values())
    assert {'HOME','PATH'}|NEED<=set(row)<=HOST|NEED
    for k,v in [('CARGO_NET_OFFLINE','true'),('CARGO_TERM_COLOR','never'),('CARGO_CACHE_AUTO_CLEAN_FREQUENCY','never'),('LC_ALL','C'),('TZ','UTC')]:
        assert row[k]==sha(v.encode())
    return sorted(row)

def visits(v,path,rev,p,raws,prior,*,traced):
    key=p['raw']
    if key not in raws:
        b=v.image_proofs.raw('objc2-cli-images',key)
        raws[key]={'bytes':len(b),'text':mch(b)}
    assert p['text']==raws[key]['text']
    stdout,stderr=v.gz(path+'/ty-stdout.gz'),v.gz(path+'/ty-stderr.gz')
    assert stdout==(OLD if rev==A else NEW) and stderr==b''
    assert v.js(path+'/ty-exit.json')==p['exit']==(0 if rev==A else 1)
    assert sha(stdout)==p['stdout'] and sha(stderr)==p['stderr']
    proof=v.image_proofs.proof(path,'objc2-cli-images',prior=prior)
    assert proof['raw']==key and (proof['source']=='saved-rustc-recipe')!=(traced)
    return {'outcome':{k:d for k,d in p.items() if k!='raw'},'native':proof}

def same(a,b):
    q,p=a['native'],b['native']
    return a['outcome']==b['outcome'] and all(q[k]==p[k] for k in ('output_sha','norm','modules_sha','module_count'))

def open_trace(v,path,r,rev,raws,prior,*,old=False):
    q=v.js(path+'/verified.json');assert q['command']==CMD and q['rev']==rev
    msgs=list(map(json.loads,v.gz(path+'/stdout.gz').splitlines()))
    units=[m for m in msgs if m['reason']=='compiler-artifact']
    assert len(units)==q['units'] and sorted(u['target']['name'] for u in units if not u['fresh'])==q['dirty']
    unit=lambda a:[a['package_id'],a['target']['name'],','.join(a['target']['kind']),a['features'],compact(a['profile'])]
    typed=sorted(unit(a) for a in units);dirty=sorted(unit(a) for a in units if not a['fresh'])
    d,_,stdout,stderr,linkers=v.actual(path,'Ruff CLI',dict(q,argv=CMD,status=q['code'],streams=q['streams']['streams'],typed=typed,dirty=dirty))
    assert all(row['sha']==v.js('observer.json')['ld'] for row in q['native']['linkers'])
    outputs=[e['argv'][e['argv'].index('-o')+1] for e in linkers]; final=[p for p in outputs if re.fullmatch(r'ty(?:-[0-9a-f]{16})?',L(p).name)]
    assert q['links']==final
    ob,=[u for u in units if u['target']['name']=='objc2' and u['target']['kind']==['lib']]; row,=q['objc2']; assert ob['package_id'].endswith('#objc2@0.6.3') and row['archive'] in ob['filenames']
    marker=v.gz(path+'/objc2-0.dep.gz')
    assert row['dep']==sha(marker) and row['features']==ob['features'] and row['fresh']==ob['fresh'] and len(row['sha256'])==64
    assert row['hard']==(b'ohm-untracked-relink-inputs' in marker)==(r=='P') and row['recheck']==(b'/dev/null/ohm-recheck-dependent-links-v2:' in marker.splitlines())==(r=='C') and b'/dev/null/ohm-recheck-dependent-links:' not in marker.splitlines()
    assert d['full'].count('objc2')==int(not ob['fresh'])
    roots=[u for u in units if u['target']['name']=='ty' and u['target']['kind']==['bin'] and u['executable'] and not u['profile']['test']]
    events=json.loads(v.gz(path+'/exec.json.gz'))
    roots_ex=[]
    for e in events:
        a=e['argv'];opts=list(zip(a,a[1:])); values=[y for x,y in opts if x=='-C']+[x[2:] for x in a if x[:2]=='-C' and x!='-C']
        if e['path'].endswith('/native/bin/rustc') and ('--crate-name','ty') in opts and not any('link-only' in x for x in a):
            paths=[x[12:] for x in values if x.startswith('incremental=')]
            if not old: assert len(paths)==1 and '/objc2-work/' in paths[0]
            roots_ex.append({'pid':e['pid'],'argv':sha(json.dumps(a,separators=(',',':')).encode()),'incremental':paths[0] if paths else None,'bin':('--crate-type','bin') in opts})
    if not old and v.exists(path+'/development-emitters.json'):
        evidence=v.js(path+'/development-emitters.json');assert len(roots_ex)==len(evidence)>0
        for row,e in zip(roots_ex,evidence):
            assert (e['pid'],e['directory'],sha(json.dumps(e['argv'],separators=(',',':')).encode()))==(row['pid'],row['incremental'],row['argv'])
            assert e['crate']=='ty' and all(int(s['work_products'],16) and s['objects']>0 and s['graph_bytes']>0 for s in e['sessions'])
            row['sessions']=[{'objects':s['objects'],'wp':s['work_products'],'graph_bytes':s['graph_bytes']} for s in e['sessions']]
    step=q['step'];checked=None
    if step=='invalid':
        assert not roots and not final and q['product'] is None and q['code']==101
        assert any((m['message'].get('code') or {}).get('code')=='E0425' and 'ohm_objc2_response_file_missing' in m['message']['message'] for m in msgs if m['reason']=='compiler-message')
    else:
        root,=roots;assert root['executable'].endswith('/target/debug/ty') and q['code']==0 and q['product']
        if step in ('cold','clean','edit'):assert len(final)==1 and len(roots_ex)>0 and any(e['bin'] for e in roots_ex)
        if not old:
            checked=visits(v,path,rev,q['product'],raws,prior,traced=True)
            proof=checked['native']; assert proof['raw']==q['cgu']['raw'] and proof['norm']==q['cgu']['same_path_image'] and proof['modules_sha']==sha(compact(q['cgu']['modules']).encode())
            if final:assert proof['output_sha']==sha(final[0].encode()) and q['cgu']['cross_path_image']==proof['cross']
    for row in roots_ex:
        inc=row.pop('incremental');row['incremental_sha256']=sha(inc.encode()) if inc else None
    d.update({'step':step,'units':len(units),'dirty':q['dirty'],'final_links':len(final),'objc2':d['full'].count('objc2'),
              'objc2_marker':sha(marker),'root_emitters':roots_ex,'verdict':None if q['product'] is None else q['product']['exit']})
    return d,checked

def reopen(v,*,old=False):
    role_table={r:{'sdk':v.js('versioned/sdk-'+r+'.json')} for r in 'PC'};raws={};rows={};refs={};envs={}
    for order in ('PC','CP'):
        by={}
        for r in order:
            base=f'objc2-cli/{order}/{r}/'
            assert v.js(base+'installation.json')==role_table[r]['sdk']
            if not old:envs[order+'/'+r]=env(v.js(base+'development-environment.json'))
            prior={}
            for group,step,rev in [('clean-old','clean',A),('clean-new','clean',B),*[('visits',s,A if s=='cold' else B) for s in STEPS]]:
                foot=base+group+'/'+step
                x,check=open_trace(v,foot,r,rev,raws,prior if group=='visits' else {},old=old)
                if group!='visits':by[r,rev]=check
                if not old and check and group=='visits':assert same(check,by[r,rev]),(order,r,step)
                rows[foot]={'observation':x,'product':check}
            if not old:
                assert by[r,A]['native']['raw']!=by[r,B]['native']['raw'];refs.update({(order,r,tag):by[r,tag] for tag in (A,B)})
        if not old:
            rep=v.js('objc2-cli/'+order+'-closed.json')
            for rev,group in [(A,'clean-old'),(B,'clean-new')]:
                left,right=[by[r,rev] for r in 'PC']
                assert left['outcome']==right['outcome'] and left['native']['modules_sha']==right['native']['modules_sha']
                assert left['native']['cross']==right['native']['cross']==rep['cross'][group]
    return rows,refs,raws,envs

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('archive',type=Path);parser.add_argument('dest',type=Path);parser.add_argument('--prior-kernel-only',action='store_true');a=parser.parse_args()
    with ZipFile(a.archive) as z:
        v=Dataset(z);row,refs,imgs,envs=reopen(v,old=a.prior_kernel_only)
        summary={'source':None if a.prior_kernel_only else sources(v),'archive':digestfile(a.archive),'rows':row,'images':imgs,'environment':envs}
    a.dest.mkdir(exist_ok=True,parents=True);write(a.dest/'application.json',pretty(summary))
    print([(k,len(b['observation']['full']),b['observation']['link_only'],b['observation']['ld'],b['observation']['objc2']) for k,b in row.items() if k.endswith('/visits/repeat-1')])
