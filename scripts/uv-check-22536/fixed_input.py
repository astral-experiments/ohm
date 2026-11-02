"""Reproduce each exceptional compiler metadata layout from the same unmodified, immutable inputs."""
from pathlib import Path
import gzip,json,os,shutil,subprocess
from basis import HERE,canon,digest,filehash,read,write,writez
from semantics import decoder,probe,stash
RULE=read(HERE/'fixed-layout-rule.json');WRAP=HERE/'kit/fixed-wrapper.py'
def inputs(argv):
    out={}
    for i,x in enumerate(argv[:-1]):
        if x=='--extern'and '='in argv[i+1]:
            p=Path(argv[i+1].split('=',1)[1]);assert p.is_absolute()and p.is_file();out[str(p)]=[p.stat().st_size,filehash(p)]
    return out
def native_header(e,p):
    # This invocation only reads the finished .rmeta. Its private environment
    # is never inherited by the Cargo child producing either compared artifact.
    z=subprocess.run([e.bin,'-Zls=root',p],env=dict(e.env,RUSTC_BOOTSTRAP='1'),capture_output=True,check=True);assert not z.stderr and z.stdout;return z.stdout
def certify(e,role,state,folder,paths,forms,before,oracle,needs,*,preserve_original=False):
    assert role in('R','S','F')and state in'BCD'and filehash(WRAP)==RULE['wrapper']and os.access(WRAP,os.X_OK)
    src=e.source(state);folder.mkdir();saved=e.bank/('fixed-'+role+'-'+state);assert not saved.exists()
    form_file=folder/'forms.json';write(form_file,forms);complete={}
    def restore():
        e.reset();shutil.copytree(saved,e.target,dirs_exist_ok=True,symlinks=True)
    if preserve_original:os.rename(e.target,saved)
    else:shutil.copytree(e.target,saved,symlinks=True)
    try:
        dec=decoder(e)
        for owner,wanted in needs.items():
            restore()
            known=RULE['known_prior_physical_kinds'][owner];assert set(wanted)<=set(known);orig,=forms[owner];unit=Path(orig[orig.index('--out-dir')+1]).parent;assert unit.parent==e.target/'debug/build'/owner.replace('_','-')and len(unit.name)==16
            p=e.target/paths[owner];ref=before['workspace'][owner][1:];old_header=native_header(e,p);fixed=inputs(orig);seen=set();coverage=set();w=[]
            for i,n in enumerate(RULE['sequence']):
                restore();assert e.source(state)==src and stash(e,p)==ref and inputs(orig)==fixed;inc,=(e.target/'debug/incremental').glob(owner+'-*');assert inc.is_dir()and(unit/'fingerprint').is_dir()
                shutil.rmtree(inc);shutil.rmtree(unit);d=folder/(owner+'-'+str(i));d.mkdir();logs=d/'argv';logs.mkdir()
                env=dict(e.env,RUSTC_WRAPPER=str(WRAP),OHM_22958_FORMS=str(form_file),OHM_22958_OWNER=owner,OHM_22958_THREADS=str(n),OHM_22958_LOGS=str(logs));assert 'RUSTC_BOOTSTRAP'not in env and env.keys()-e.env.keys()=={'RUSTC_WRAPPER','OHM_22958_FORMS','OHM_22958_OWNER','OHM_22958_THREADS','OHM_22958_LOGS'}
                with (d/'stdout').open('xb')as so,(d/'stderr').open('xb')as se:z=subprocess.run(e.argv,cwd=e.src,env=env,stdout=so,stderr=se,timeout=900)
                assert z.returncode==0 and not(d/'stdout').stat().st_size
                marks=[read(f)for f in logs.glob('*.json')];selected,=[r for r in marks if r['name']==owner];assert selected['original']==orig and selected['executed']==orig+['-Zthreads='+str(n)]and selected['cwd']==str(e.src)and selected['inputs']==inputs(orig)==fixed
                result=stash(e,p);seen.add(result[1]);actual_header=native_header(e,p);writez(d/'actual-headers.json.gz',{'before_raw':ref,'after_raw':result,'before':old_header.decode().splitlines(),'after':actual_header.decode().splitlines(),'only_diagnostic_argv_addition':selected['executed'][len(orig):],'held_inputs':digest(canon(fixed)),'scope':{'role':role,'state':state,'owner':owner,'original_arglist_sha256':digest(canon(orig)),'bootstrap':env.get('RUSTC_BOOTSTRAP')}})
                if actual_header!=old_header:
                    for label,o in [('baseline',ref),('observed',result)]:
                        physical=e.cas/(o[1]+'.gz')
                        if physical.stat().st_size<=512<<10:shutil.copy2(physical,d/(label+'.rmeta.gz'))
                    raise AssertionError(('native header changed under diagnostic',state,role,owner,n))
                assert probe(e,state,forms,d)==oracle
                if result!=ref:
                    comp=dec['check_delta'](ref,result,owner);assert all(comp['checks'].values())and set(comp['physical_moved'])<=set(known);coverage.update(comp['physical_moved'])
                else:comp={'exact_bytes':True}
                w.append({'threads':n,'result':result,'argv':digest(canon(selected['executed'])),'inputs':digest(canon(fixed)),'semantic':comp,'other_unit_names':[r['name']for r in marks if r is not selected]})
            assert len(seen)>=2 and set(wanted)<=coverage,(owner,state,role,wanted,sorted(coverage));complete[owner]={'held_inputs':fixed,'checked_argv':orig,'coverage':sorted(coverage),'original_native_header':digest(old_header),'rows':w}
    finally:
        if preserve_original:
            if e.target.exists():shutil.rmtree(e.target)
            os.rename(saved,e.target)
        else:restore();shutil.rmtree(saved)
    result={'role':role,'source':src,'state':state,'rule':filehash(HERE/'fixed-layout-rule.json'),'covered':complete}
    writez(folder/'fixed-input.json.gz',result);return result
