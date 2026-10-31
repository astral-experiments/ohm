"""Independently reopen each exact projected executable, its native linker, original CGUs, and Cargo verdict."""
from pathlib import Path
import gzip,hashlib,json,sys,zipfile
D=Path(__file__).resolve().parent
sys.path.insert(0,str(D));from schedule import V,C,P,BAD,checks
sys.path.insert(0,str(D/'offline'));import reopen_cgu as cgu
from cgu_inputs import agrees
def sha(b):return hashlib.sha256(b).hexdigest()
def verify(z):
    def j(path):return json.loads(z.read(path))
    def raw(path):return gzip.decompress(z.read(path))
    def eq(a,b):assert a==b,(a,b)
    plans=checks();n=0;out={};marker_counts={};ndiff=0;restores=[];std={}
    summary=j('observed-terminal.json');eq(2*sum(len(s) for *_,s in plans),summary['commands'])
    product=j('release.json');proof=j('strict-build.json');assert product['sources']['strict']['source']==C and product['sources']['signed']['source']==P
    eq(proof['compiled'],product['sources']['strict']['sha256']);eq(proof['signed_runtime'],j('21/installed.json'))
    eq(j('21/custody.json')['archive_sha256'],'b9514511839ca0dd54e3f473df508c2d43f0dfc27de90ed3926811ed063c7f73')
    eq(product['rustc']['sha256'],proof['signed_runtime']['bin/rustc'])
    driver=product['driver'];eq(driver['sha256'],proof['signed_runtime']['lib/'+driver['name']])
    eq(j('strict-custody.json')['digest'],'sha256:3d0ee55fe20e680cc0c5075ea36259f5d70ccae57e34df0b4ec3d07f86c007df')
    factory=j('provider-matrix/providers.json')
    for val in (17,29):
        q=factory[str(val)];ob=z.read(f'provider-matrix/provider-{val}.o');ar=z.read(f'provider-matrix/provider-{val}.a')
        assert sha(ar)==q['archive'] and sha(ob)==q['object'] and ob in ar and ar.startswith(b'!<arch>\n')
        assert f'return {val};' in q['source'] and ob[:8]==bytes.fromhex('cffaedfe0c000001')
    for kind,place,policy,seq in plans:
        name=kind+'-'+place+'-'+policy+'-default';folder='provider-matrix/'+name
        inputs=j(folder+'/inputs.json');eq(inputs['steps'],[list(q) for q in seq])
        source=inputs['source'];main=source['src/main.rs'];assert ('cargo:rerun-if-changed={name}' in source['build.rs'])==(policy=='declared')
        barrier=main if place=='direct' else source['barrier/src/lib.rs']
        assert 'asm!("/* {0} */", inout(reg) register, options(nomem,nostack,preserves_flags))' in barrier
        if kind=='archive-owner':assert 'modifiers="-bundle"' in barrier and 'barrier::resolved()' in main and 'qa_owned_external' not in main
        transfer=json.loads(raw('switches/'+name+'.json.gz'));eq(transfer['driver']['sha256'],driver['sha256'])
        eq(transfer['old']['sha256'],product['sources']['signed']['sha256']);eq(transfer['new']['sha256'],product['sources']['strict']['sha256'])
        assert transfer['old']['path']==transfer['new']['path'] and transfer['old']['ino']!=transfer['new']['ino']
        frozen=[v for k,v in transfer['namespace'].items() if transfer['warm_return'].endswith('/'+k) and len(v)==6]
        assert any(v[-1]==transfer['warm_product'] for v in frozen)
        snapshots={t:[] for t in ('warm','empty')};previous_verified={};reports={};known={}
        stages=[folder+'/'+label+'/'+t for label,_,_ in seq for t in snapshots]
        original_links=dict(cgu.original_provider(z,stages))
        for label,native,num in seq:
            is_signed=label.startswith('signed-');poison=label.startswith('signed-poison');source_bad=num==BAD
            expected=None if source_bad or native in ('missing','malformed') else [17 if native=='lower' else 29,num]
            pair=j(folder+'/'+label+'/compared.json')
            eq(pair['archives'],{'early': factory['29']['archive'] if native=='higher' else sha(b'not a native archive\n') if native=='malformed' else None,
                                 'late':factory['17']['archive'] if native in ('lower','higher') else None})
            datum={}
            for arm in snapshots:
                where=folder+'/'+label+'/'+arm;row=j(where+'/verified.json');stdout=raw(where+'/stdout.gz');stderr=raw(where+'/stderr.gz')
                eq(sha(stdout),row['streams']['stdout']);eq(sha(stderr),row['streams']['stderr'])
                typed=[json.loads(q) for q in stdout.splitlines()];eq(typed[-1],{'reason':'build-finished','success':row['status']==0})
                errors=[(m['message'].get('code') or {}).get('code') for m in typed if m['reason']=='compiler-message' and m['message']['level']=='error']
                assert b'internal compiler error' not in (stdout+stderr).lower() and b'panicked at' not in (stdout+stderr).lower()
                es=json.loads(raw(where+'/exec.json.gz'));eq(sha(raw(where+'/exec.json.gz')),row['streams']['native_events'])
                links=[e for e in es if Path(e['path']).name in ('ld','ld-classic','ld-prime','ld64')]
                assert len(links)==len(row['native']['linkers']) and all(q['stock'] and q['sha']==product['ld']['sha256'] for q in row['native']['linkers'])
                assert all(r['path']==product['ld']['path'] and r['cdhash'] for r in links)
                actual=[]
                for e in es:
                    args=e['argv'];nm=Path(e['path']).name
                    if nm!='rustc' or '--crate-name' not in args:continue
                    unit=args[args.index('--crate-name')+1]
                    if unit=='___':continue
                    assert '/native/bin/rustc' in e['path'] and e['cdhash']
                    lt=any(p in ('-Zlink-only','link-only') or p.startswith('-Zlink-only=') for p in args)
                    actual.append([unit,'link' if lt else 'full',e['pid']])
                pids=[r[2] for r in actual];assert len(pids)==len(set(pids))
                eq(sorted(r[0] for r in actual if r[1]=='full'),row['native']['full'])
                eq(sorted(r[0] for r in actual if r[1]=='link'),row['native']['link_only'])
                val=row['answer'];status=row['status'];want=expected
                if arm=='warm' and poison and policy=='unwatched':
                    want=[17 if label=='signed-poison-higher' else 29,7]
                    eq(status,0);eq(actual,[]);eq(links,[])
                eq(status,101 if want is None else 0);eq(val,want)
                if source_bad:assert 'E0425' in errors and BAD.encode() in stdout
                elif want is None:assert 'qa_owned_external' in (stdout+stderr).decode() and ('linking with' in (stdout+stderr).decode() or 'library' in (stdout+stderr).decode())
                if status==0:
                    proc=j(where+'/program.json');eq(proc['exit'],0);eq(proc['sha256'],row['image']['raw'])
                    assert raw(where+'/program.stdout.gz').decode()==f'{val[0]} {val[1]}\n' and raw(where+'/program.stderr.gz')==b''
                    key=row['image']['raw'];eq(sha(original_links[where][0]),key)
                    if row['final_links']:
                        result=cgu.verify(z,where);eq(result['raw'],key)
                        detail=j(where+'/cgu-proof.json');previous_verified[(arm,key)]=detail
                        cert,=row['final_links'];event=cgu.observed_ld(z,where,argv_sha=cert['argv_sha'],pid=cert['pid'])
                        assert event['path']==product['ld']['path'] and '-lqa_owned_external' in event['argv']
                        assert cert['search'].index(transfer['source']+'/early')<cert['search'].index(transfer['source']+'/late')
                    else:
                        detail=previous_verified[(arm,key)];old=j(where+'/prior-cgu-proof.json');eq(old,dict(raw=key,recipe=detail['recipe'],observed_link=detail['linker_argv']))
                    snapshots[arm].append(detail)
                    if 'signed-lower'==label or 'signed-higher'==label:
                        known[arm]=key
                else:
                    assert row['image'] is None and original_links[where] is None and errors
                    snapshots[arm].append(None)
                forms=[]
                for sub,q in row['marker'].items():
                    b=raw('edge-markers/'+q['sha256']+'.d.gz');eq(q['sha256'],sha(b));rules=b.decode().splitlines()
                    if any(l.endswith(':') for l in rules):
                        paths=[l[:-1] for l in rules if l.startswith('/dev/null/ohm-') and l.endswith(':')]
                        forms.append(paths)
                if status==0:assert forms and all(paths==[V] for paths in forms),(name,label,arm,forms)
                marker_counts[tuple(tuple(a) for a in forms)]=marker_counts.get(tuple(tuple(a) for a in forms),0)+1
                if label==transfer['previous'] and arm=='warm':eq(row['image']['raw'],transfer['warm_product'])
                if label==transfer['next'] and arm=='warm':restores.append([name,label,status,val])
                datum[arm]=dict(status=status,value=val,full=sorted(r[0] for r in actual if r[1]=='full'),link_only=sorted(r[0] for r in actual if r[1]=='link'),xcode_links=len(links),final_links=len(row['final_links']),raw=row['image']['raw'] if row['image'] else None,forms=forms)
                n+=1
            a,b=snapshots['warm'][-1],snapshots['empty'][-1]
            if a and b:
                passed=agrees(a,b);eq(passed,pair['same_checked_image'])
                if poison and policy=='unwatched':
                    assert not passed and datum['warm']['raw']==known['warm']
                else:
                    assert passed,(name,label,datum)
                ndiff+=int(passed and datum['warm']['raw']!=datum['empty']['raw'])
            if not is_signed and label.startswith('strict-repeat'):
                std[name+'/'+label]=datum['warm']
            reports[label]=datum
        out[name]=reports
    eq(n,116);eq(len(restores),8)
    return {'commands':n,'cases':out,'stock_Xcode':product['ld'],'products':product['sources'],'upgrades':restores,
            'unchanged_with_strict':std,'passed_pairs_with_distinct_raw_signed_images':ndiff,'markers':[[list(k),v] for k,v in marker_counts.items()]}
class Local:
    def __init__(self,path):self.path=path;self.names={str(p.relative_to(path)) for p in path.rglob('*') if p.is_file()}
    def namelist(self):return self.names
    def read(self,name):
        if name not in self.names:raise KeyError(name)
        return (self.path/name).read_bytes()
    def __contains__(self,x):return x in self.names
if __name__=='__main__':
    p=Path(sys.argv[1])
    if p.is_dir():result=verify(Local(p))
    else:
        with zipfile.ZipFile(p) as z:result=verify(z)
    print(json.dumps(result,sort_keys=True,indent=2))
