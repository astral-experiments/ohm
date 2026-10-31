"""Reopen ordinary and observed macOS ready-test executions, including the original failures."""
import gzip
import hashlib
import json
import re
from pathlib import Path
import zipfile
D=Path(__file__).resolve().parent
NAME='ohm_ready_tests::uses_current_runtime_inputs_and_ignores_disabled_binaries'
TEST='03d2fa196a80c0af1c67ece2fb2cf952e15c60caae0419e115fd5a2459fd2aa5'
SUBJECTS={'parent':('2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c','bc9fe7b15f4d1e9b935f8624f8b004ce0a7d2c66'),'candidate':('c7f394c8c9aaef1272c621ff11d77dcf569ed94b','07904aadf60050fae426f31ad8fcdcce75e48c7e')}
RUNS={41147398265:('e924ae2e31a3bbde3fd37a8e3834b87b39bcd3ac',8),41147809007:('6086f83dbda1a69a8c9ccb67a1cd9f809974b3b6',24),41148226731:('caee3c4aea66e15b928ef5f4c32727dcc4f8acf7',60)}
FULL={'parent':('15ba2b680deb46d9405b37805ae6ebdf7d62f21e8b8bbcb1416cf8218e079563',4385,'ok'),'candidate':('7cf8e0ebbd8c267a607f08e4cae754a022bdab99aaf9c17682030f41aed1a52e',4384,'FAILED')}
def sha(b):return hashlib.sha256(b).hexdigest()
def one(z,run,role):
    z.testzip();assert len(z.namelist())==len(set(z.namelist()))
    j=lambda k:json.loads(z.read(k+'.json'));unzip=lambda k:gzip.decompress(z.read(k+'.gz'))
    src=j('source');binary=j('products');assert src['role']==role and binary['fixture']==src['fixture']==TEST and src['qa']==RUNS[run][0] and int(src['run'])==run
    assert src['tree']['commit']==SUBJECTS[role][0] and src['tree']['tree']==SUBJECTS[role][1] and src['uname'][0]=='Darwin' and src['uname'][2]=='24.6.0'
    assert 'commit-hash: '+SUBJECTS[role][0] in binary['version']
    raw=[json.loads(l) for l in unzip('build.stdout').splitlines()];assert raw[-1]=={'reason':'build-finished','success':True}
    for kind,name,key in [('test','testsuite','suite'),('bin','cargo','cargo')]:
        m,=[m for m in raw if m['reason']=='compiler-artifact' and m['target']['name']==name and m['target']['kind']==[kind] and m.get('executable')]
        assert not m['fresh'] and m['executable']==binary[key] and len(binary[key+'_sha256'])==64
    results=[]
    for v in range(1,RUNS[run][1]+1):
        p=f'visit-{v:02}/';r=j(p+'result')
        assert r['number']==v and r['argv'][-3:]==[NAME,'--exact','--nocapture']
        stdout=unzip(p+'stdout');stderr=unzip(p+'stderr');ct=r['control']
        assert b'running 1 test' in stdout and NAME.encode() in stdout
        fail=run==41147398265 and role=='candidate' and v==1
        assert r['exit']==(101 if fail else 0) and r['timeout_message']==fail and r['raw_pass']!=fail
        assert (b'ready test never started' in stdout+stderr)==fail
        diagnostic=(run==41147809007 and v>=5)
        assert r.get('diagnostic',False)==diagnostic and not r.get('had_stall',False)
        if fail:
            assert b'could not compile `z` (lib test)' in stderr and b'test result: FAILED. 0 passed; 1 failed;' in stdout
            assert set(ct)=={'slow-active'} and r['same_original_failure']
            out,=[(n,val) for n,val in r['files'].items() if '/build/a-' in n and n.endswith('/output')]
            assert out[1][1]==0 and not any(n.endswith('/out/value') for n in r['files'])
        else:
            assert b'test result: ok. 1 passed; 0 failed;' in stdout
            assert [ct[c][1] for c in ('a-timing','runs','current-binary','slow-finished','z-ran')]==['during','a\n','yes','yes','yes']
            assert any(n.endswith('/out/value') and y[1]==3 for n,y in r['files'].items())
            if run!=41147398265:
                snap=j(p+'final-snapshot');value,=[w for n,w in snap.items() if n.endswith('/out/value')]
                assert bytes.fromhex(value['data'])==b'new'
        results.append([v,not diagnostic,not fail,r.get('delay_ms',0)])
    terminal=j('terminal');assert terminal['role']==role and len(terminal['visits'])==len(results)
    if run!=41147398265:assert terminal['product_unchanged']
    for q,pair in zip(results,terminal['visits'],strict=True):assert pair==[q[0],0 if q[2] else 101,q[2],not q[2]]
    return {'cargo_sha256':binary['cargo_sha256'],'suite_sha256':binary['suite_sha256'],'ordinary_passed':sum(o and passed for _,o,passed,_ in results),'ordinary_total':sum(o for _,o,_,_ in results),'diagnostic_passed':sum(not o and passed for _,o,passed,_ in results),'diagnostic_total':sum(not o for _,o,_,_ in results),'stalls_observed':0 if run!=41147398265 else None,'explicit_delays':[ms for _,_,_,ms in results if ms]}
def supplemental():
    spec=json.loads((D/'source-job.json').read_bytes());record=json.loads((D/'full-supplemental.json').read_bytes())
    raw=gzip.decompress((D/'full-supplemental.log.gz').read_bytes())
    assert len(raw)==record['log_bytes']==561325 and sha(raw)==record['log_sha256']=='552f980e7de9ae31a3f4d42b9c9758cdf85faa040f51c00ae2679c0cf82608a1'
    assert (record['run'],record['job'],record['qa'],record['conclusion'])==(41149336548,124381841038,'f99c1d58fb79b8a79660ab1a0a8dd0438459db8e','success')
    assert spec['rerun_request']['status']==403 and spec['source']==SUBJECTS['candidate'][0] and spec['source_and_original_merge_tree']==SUBJECTS['candidate'][1]
    plain=raw.decode(errors='strict'); assert 'test '+NAME+' ... ok' in plain and 'test result: ok. 4385 passed; 0 failed; 421 ignored;' in plain
    assert 'test result: ok. 403 passed; 0 failed; 0 ignored;' in plain and 'ready test never started' not in plain
    tree_tests=['ohm_worktree::'+v for v in ['worktree_import_requires_cloning','bundled_clippy_isolation_defaults_follow_actual_snapshot_cloning','bundled_clippy_preserves_ordinary_seeds_without_importing_lint_state','clippy_isolation_overrides_are_inherited_and_child_flags_take_precedence','forced_clippy_isolation_preserves_compiler_trust_rejections','clippy_wrapper_scripts_still_deny_the_whole_seed']]
    lines=plain.splitlines();full={}
    for tag in ['ohm-1.98.0-9','ohm-1.99.0-21']:
        loc,=[i for i,l in enumerate(lines) if 'RUSTUP_TOOLCHAIN: '+tag in l]
        end=next((j for j in range(loc+1,len(lines)) if '##[group]Run ' in lines[j]),len(lines))
        block='\n'.join(lines[loc:end]);observed=re.findall(r'test (ohm_worktree::[^ ]+) \.\.\. ok',block)
        assert observed==tree_tests and re.findall(r'test result: ok\. (\d+) passed;',block)==['0',*['1']*6]
        full[tag]={'named_worktree_tests':observed,'old_profile_filter_count':0}
    record=json.loads((D/'signed-current-named.json').read_bytes());meta=record['artifact'];f=D/'signed-current-named.zip'
    assert record['source']==SUBJECTS['candidate'][0] and record['conclusion']=='success' and record['qa']=='9ee5f15b2dfb8530e839b8e2ceea9ad6127342f3'
    assert f.stat().st_size==meta['size_in_bytes']==42929 and meta['digest']=='sha256:'+sha(f.read_bytes())=='sha256:27e0c0740571fff0cca0d1b14886826bdd41e4f9ef48dc35281f713cae9263ee'
    with zipfile.ZipFile(f) as z:
        assert z.testzip() is None;pre='ready-306/record/'
        cert=json.loads(z.read('current-306/custody.json')); assert cert['tag']=='ohm-1.99.0-21'
        assert [(r['id'],r['sha256']) for r in cert['assets']]==[(693058653,'98b98b55ca70d480d6f031612edcfe2a7fa07152f9ce300bb93a60fbe28d4092'),(693058656,'b9514511839ca0dd54e3f473df508c2d43f0dfc27de90ed3926811ed063c7f73')]
        source=json.loads(z.read(pre+'source.json'));product=json.loads(z.read(pre+'products.json'));installed=json.loads(z.read(pre+'installed.json'))
        assert source['tree']['commit']==record['source'] and 'commit-hash: '+record['source'] in product['version']
        assert 'commit-hash: '+SUBJECTS['parent'][0] in installed['cargo']['version']
        assert 'ohm-1.99.0-21' in installed['rustc']['version'] and 'clippy' in installed['clippy-driver']['version']
        tm=json.loads(z.read(pre+'named-terminal.json'));assert tm['cargo']==product['cargo_sha256'] and tm['suite']==product['suite_sha256']
        names=['profile_settings::ohm_default_debuginfo','profile_settings::ohm_default_debuginfo_respects_overrides',*tree_tests]
        assert [r['name'] for r in tm['rows']]==names
        for n,r in zip(names,tm['rows'],strict=True):
            data=gzip.decompress(z.read(pre+n.replace('::','__')+'.stdout.gz'))
            assert r['argv'][1:]==[n,'--exact','--include-ignored','--nocapture'] and r['exit']==0 and r['qualified']
            assert r['actual']==[[n,'ok']] and ('test '+n+' ... ok').encode() in data and b'test result: ok. 1 passed; 0 failed; 0 ignored;' in data
    return {'suite_log_sha256':sha(raw),'full_suite_passed':4385,'full_library_passed':403,'installed_original_filter':full,'signed_current_exact_tests':names,'signed_current_archive':meta['digest']}
def main():
    out={'official':{},'targeted':{}}
    for role,(digest,passed,verdict) in FULL.items():
        raw=gzip.decompress((D/f'full-original-{role}.log.gz').read_bytes());assert sha(raw)==digest
        assert (f'test {NAME} ... {verdict}').encode() in raw and (f'{passed} passed; '+('0' if role=='parent' else '1')+' failed; 421 ignored;').encode() in raw
        assert (b'ready test never started' in raw)==(role=='candidate')
        out['official'][role]={'passed':passed,'failed':role=='candidate','log_sha256':digest}
    for run,(head,n) in RUNS.items():
        path=D/str(run);catalog=json.loads((path/'run-meta.json').read_bytes());record=catalog['run']
        assert record['id']==run and record['head_sha']==head and record['run_attempt']==1 and record['conclusion']=='success'
        out['targeted'][str(run)]={}
        for artifact in catalog['artifacts']:
            role=artifact['name'].removeprefix('ready-native-');assert role in SUBJECTS
            f=path/(artifact['name']+'.zip');b=f.read_bytes();assert len(b)==artifact['size_in_bytes'] and 'sha256:'+sha(b)==artifact['digest']
            with zipfile.ZipFile(f) as zip:
                assert zip.testzip() is None
                out['targeted'][str(run)][role]=one(zip,run,role)
        assert set(out['targeted'][str(run)])==set(SUBJECTS)
    out['supplemental']=supplemental()
    print(json.dumps(out,sort_keys=True,indent=2))
if __name__=='__main__':main()
