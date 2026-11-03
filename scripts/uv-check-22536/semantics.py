"""Native product and downstream stale-cache oracles. The generic Rust wire decoder is immutable."""
import collections,gzip,json,os,re,runpy,shutil,subprocess,tarfile
from pathlib import Path
from basis import CASE,HERE,LOCK,WORKSPACE,WUNITS,canon,digest,filehash,read,write,writez
import release23
def stash(e,f):
    n=filehash(f);d=e.cas/(n+'.gz')
    if not d.exists():
        with f.open('rb')as src,d.open('xb')as target,gzip.GzipFile(fileobj=target,mode='wb',filename='',mtime=0,compresslevel=2)as out:shutil.copyfileobj(src,out,1<<20)
    return [f.stat().st_size,n]
def products(e,paths,store=False):
    assert paths.keys()==WUNITS
    wk={n:[str(p),*(stash(e,e.target/p)if store else[(e.target/p).stat().st_size,filehash(e.target/p)])]for n,p in sorted(paths.items())}
    # Guard against a second stale output for these core normal check units.
    assert {str(f.relative_to(e.target))for n in WORKSPACE for f in (e.target/'debug/build'/n.replace('_','-')).glob('*/out/lib'+n+'-*.rmeta')}==set(paths.values())
    side={str(f.relative_to(e.target)):filehash(f)for f in e.target.rglob('*.public-api-hash')};assert len(side)==423,len(side)
    if store:
        terminal=e.target/Path(wk['uv_client'][0]).parent.parent/'fingerprint/lib-uv_client.public-api-hash'
        assert stash(e,terminal)[1]==side[str(terminal.relative_to(e.target))]
    return {'workspace':wk,'public_sidecars':dict(sorted(side.items()))}
def decoder(e):
    out=e.root/'decoder';archive=HERE/'kit/metadata-kit.tar.xz';r=read(HERE/'metadata-kit.json');assert filehash(archive)==r['kit_sha']
    if not out.exists():
        out.mkdir()
        with tarfile.open(archive)as t:
            members=t.getmembers();assert len(members)==len(r['toolkit'])==len({a.name for a in members})
            for a in members:
                assert a.isfile()and a.name in r['toolkit']and not a.name.startswith('/')and '..'not in Path(a.name).parts
                data=t.extractfile(a).read();assert digest(data)==r['toolkit'][a.name];f=out/a.name;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(data)
        (out/r['kit_module']).parent.joinpath('blobs').symlink_to(e.cas,target_is_directory=True)
    return runpy.run_path(str(out/r['kit_module']))
def typed_compare(e,a,b,d,coverage=None):
    assert a.keys()==b.keys()and a['workspace'].keys()==b['workspace'].keys()and a['public_sidecars'].keys()==b['public_sidecars'].keys()
    differences={k for k in a['public_sidecars']if a['public_sidecars'][k]!=b['public_sidecars'][k]};changed={};ctfe=[];terminal_headers=None;unresolved=[];dec=None;needs={};coverage=coverage or {};known=read(HERE/'fixed-layout-rule.json')['known_prior_physical_kinds']
    for n,r in sorted(a['workspace'].items()):
        u=b['workspace'][n];assert r[0]==u[0]
        if r==u:continue
        if dec is None:dec=decoder(e)
        crate=n.split('@')[0];x,y=r[1:],u[1:];wire=dec['check_delta'](x,y,crate);raw=[gzip.decompress((e.cas/(v[1]+'.gz')).read_bytes())for v in(x,y)]
        assert all([len(bb),digest(bb)]==v for bb,v in zip(raw,(x,y),strict=True));headers=[]
        for k,bb in enumerate(raw):
            f=e.root/'tmp'/'metadata-hash-probe.rmeta';f.write_bytes(bb)
            z=subprocess.run([e.bin,'-Zls=root',f],env=dict(e.env,RUSTC_BOOTSTRAP='1'),capture_output=True,check=True);assert not z.stderr and z.stdout;headers.append(z.stdout)
        checks=wire['checks'];equal_semantics=all(checks.values())and headers[0]==headers[1];classes=set(wire['physical_moved']);guarded=bool(classes)and n in known and classes<=set(known[n])and equal_semantics
        if guarded and not wire['exact_complete_bytes']:needs[n]=sorted(classes)
        full=equal_semantics and (wire['exact_complete_bytes']or(guarded and classes<=set(coverage.get(n,[]))))
        if not full:
            # An independent cold mismatch can only elect corrected stock through
            # a narrow public-root discrepancy in an otherwise decoded true terminal.
            aa,bb=[v.decode().splitlines()for v in headers];diff=[(j,l,m)for j,(l,m)in enumerate(zip(aa,bb,strict=True))if l!=m]
            metrics=dec['Z']['delta'](raw[0],raw[1],crate)['semantic'];alloc=metrics['allocations']
            match_public=lambda st:bool(re.match(r'^\s*(?:public_hash|public hash)\b',st,re.I))
            lit=(n=='uv_client' and len(diff)==1 and all(match_public(o)for o in diff[0][1:]) and all(v for k,v in checks.items()if k not in('native_crate_root','ctfe')) and checks['ctfe'] and not metrics['changed_RDR_key_count'] and alloc['multisets_identical'])
            (ctfe if lit else unresolved).append(n)
            if lit:terminal_headers=(aa,bb)
        changed[n]={'warm':x,'cold':y,'typed':wire,'root_sha256':[digest(g)for g in headers],'all_semantic_guards_passed':full}
    ok=not differences and not unresolved and not ctfe
    evidence=None
    if not unresolved and ctfe==['uv_client']:
        evidence=release23.terminal((a['public_sidecars'],b['public_sidecars']),a['workspace']['uv_client'][0],terminal_headers,e.cas)
    ctfe_only=evidence is not None
    out={'all_workspace':len(a['workspace']),'all_public':len(a['public_sidecars']),'exact_rmeta':len(a['workspace'])-len(changed),'changes':changed,'changed_sidecars':sorted(differences),'ctfe_terminal_only':ctfe_only,'terminal_ctfe_evidence':evidence,'accepted':ok,'unresolved':unresolved,'needs_fixed_input':needs,'allowed_only_from_actual_certificates':coverage};writez(d/'typed-warm-cold.json.gz',out);return out
def probe(e,state,forms,d):
    src=CASE['states'][state]['source'];assert e.source(state)==src;a,=forms['uv_client'];search=[]
    for i,v in enumerate(a[:-1]):
        if v=='-L':search+=['-L',a[i+1]]
    dep,=[s.split('=',1)[1]for i,s in enumerate(a)if i and a[i-1]=='--extern'and s.startswith('uv_distribution_types=')]
    assert (e.target in Path(dep).parents and Path(dep).is_file())and search
    dst=e.root/'tmp'/('probe-'+state);dst.mkdir(exist_ok=True);data={}
    snippets={'baseline':'pub fn api() { let _=d::VariantsJsonContent::from_slice(b"{}"); }'}
    for k in ('VariantPreferences','SupportedVariantProperties'):
        snippets[k]='pub fn api(m: &d::VariantsJsonContent) { let p=d::'+k+'::default(); let _=m.score_variant(&"gpu".parse().unwrap(), &p); }'
    for k,body in snippets.items():
        f=dst/'probe.rs';f.write_text('extern crate uv_distribution_types as d;\n'+body+'\n');argv=[str(e.bin),'--edition=2024','--crate-type=lib','--crate-name','uv_22536_external_api','--emit=metadata','--out-dir',str(dst),'--error-format=json','--extern','uv_distribution_types='+dep,*search,str(f)]
        proc=subprocess.run(argv,env=e.env,capture_output=True);expected=k=='baseline'or(k=='VariantPreferences'and state in'BC')or(k=='SupportedVariantProperties'and state=='D')
        found=[json.loads(v)for v in proc.stderr.splitlines()];codes=[x['code']['code']for x in found if isinstance(x.get('code'),dict)]
        assert (proc.returncode==0)==expected and (expected or any(u in('E0425','E0432','E0433')for u in codes)and any(k in x.get('message','')for x in found)),(state,k,proc.returncode,codes,[x.get('message')for x in found])
        data[k]={'accepted':expected,'codes':codes,'source_sha256':filehash(f),'metadata_sha256':filehash(dep),'stderr_sha256':digest(proc.stderr)}
    write(d/'live-api.json',data);return {k:[v['accepted'],v['codes']]for k,v in data.items()}
def upstream(e,state,out):
    e.source(state);r=CASE['upstream_rank_test'][state];assert filehash(e.src/r['file'])==r['bytes_sha256']
    env=dict(e.env,CARGO_TARGET_DIR=str(e.root/'fixture-target'));args=[e.argv[0],'test','-p','uv-distribution-types','--test','variants_json','--locked','--offline','-j8','--','--exact','rank_variants']
    out.mkdir();so=out/'stdout';se=out/'stderr'
    with so.open('xb')as a,se.open('xb')as b:proc=subprocess.run(args,cwd=e.src,env=env,stdout=a,stderr=b,timeout=1800)
    text=so.read_text();n=1 if r['expects_rank_variants']else 0;assert proc.returncode==0 and f'test result: ok. {n} passed; 0 failed;'in text and ('test rank_variants ... ok'in text)==bool(n),(state,proc.returncode)
    write(out/'accepted.json',{'revision':r,'source':CASE['states'][state],'argv':args,'passed_rank_tests':n,'stdout':filehash(so),'stderr':filehash(se)})
