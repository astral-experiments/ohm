"""Reopen the fixed and signed native executable identities, command streams, mounts and inodes."""
import gzip
import hashlib
import json
import re
from pathlib import Path
import sys
import zipfile
HERE=Path(__file__).resolve().parent
BASE='2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c'
DIST='6f550de85f95440a61b5bd1a9d2ab0528d4fcaf674fdc008f5e986d2138be6c4'
INITIAL='2802082f3ba36be5af9bab9fa6c33bc78afb203c'
FINAL='c7f394c8c9aaef1272c621ff11d77dcf569ed94b'
PANICS={'util::counter::tests::counter_zero_slot','util::dependency_queue::test::rejects_cycle','util::git::tests::duplicate_registration_is_rejected','util::io::tests::over_the_limit'}
PRIVATE='workspace::build_cache_gc::worktrees::idle::tests::stock_build_can_finish_opening_a_profile_after_discovery'
HEALTHY=b'healthy ordinary unrelated owned GC output '*2
SENTINEL_SHA='3dd2105c63e6b65c5cacda5697bbb6ac16805ce336ba39a4aa0da43fa5464e45'
SIGNED='4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e'
def h(b):return hashlib.sha256(b).hexdigest()
def opened(path,s):
    raw=path.read_bytes();assert h(raw)==s['sha256'] and len(raw)==s['bytes']
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None and len(z.namelist())==len(set(z.namelist()))
        return {n:(gzip.decompress(z.read(n)) if n.endswith('.gz') else z.read(n)) for n in z.namelist()}
def units(n,b,spec,qa):
    u=json.loads(b['unit.json'])
    assert u['candidate']==spec['head'] and u['qa']==qa and '--lib' in u['cmd'] and '--no-run' in u['cmd']
    records=[json.loads(l) for l in b['unitcompile.stdout.gz'].splitlines()]
    assert records[-1]=={'reason':'build-finished','success':True}
    product,=[r for r in records if r['reason']=='compiler-artifact' and r['target']['name']=='cargo' and 'lib' in r['target']['kind'] and r['profile']['test'] and r.get('executable')]
    assert not product['fresh'] and {'all-static','ohm-defaults'}<=set(product['features'])
    listing={line[:-6] for line in b['unit-list.gz'].decode().splitlines() if line.endswith(': test')}
    assert set(u['names'])==listing
    initial=spec['head']==INITIAL
    focus={name for name in listing if name.startswith('workspace::build_cache_gc::' if initial else 'workspace::build_cache_gc')}
    assert len(focus)==(56 if initial else 62) and len(listing)==411
    assert set(u['gc'])==focus and any(x.endswith('::mount_path::tests::renamed_parent_and_final_symlink') for x in focus)
    assert any(x.endswith('::shared_cleanup_preserves_a_nested_mount_in_active_and_retired_trees') for x in focus)
    results={}
    for name,raw,stem,selection in [('namespace-overlay',b,'namespace-overlay',focus),('tmpfs',b,'tmpfs',focus),('full-ext4',n,'packet/units/full-ext4',listing)]:
        d=json.loads(raw[stem+'.json']);stdout=raw[stem+'.stdout.gz'];stderr=raw[stem+'.stderr.gz']
        captures=re.findall(rb'^test (.+?) \.\.\. (ok|FAILED|ignored.*)$',stdout,re.M)
        seen={m[0].decode():m[1].decode() for m in captures}
        assert len(captures)==len(seen) and d['binary_sha']==u['sha'] and d['actual']==seen
        suffix=' - should panic'
        suffixed={k.removesuffix(suffix) for k in seen if k.endswith(suffix)}
        assert suffixed==(PANICS if name=='full-ext4' else set())
        logical={k.removesuffix(suffix) if k.endswith(suffix) else k:v for k,v in seen.items()}
        assert len(logical)==len(seen) and set(logical)==selection
        if not initial:
            assert d['logical_names']==logical and d['raw_names_equal']==(set(seen)==selection)
        fails={k for k,v in logical.items() if v!='ok'}
        assert fails==({PRIVATE} if name=='namespace-overlay' else set()),(name,fails)
        expected_exit=101 if fails else 0;expected_summary=[['FAILED' if fails else 'ok',str(len(logical)-len(fails)),str(len(fails)),'0']]
        summary=[[x.decode() for x in m] for m in re.findall(rb'test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored;',stdout)]
        assert d['exit']==expected_exit and summary==d['terminal_summary']==expected_summary
        if fails:
            assert b'worktrees/idle/mod.rs:500:13' in stdout and b'assertion failed: plan.lock_profiles' in stdout
        assert d['f_filesystem']=={'namespace-overlay':'overlayfs','tmpfs':'tmpfs','full-ext4':'ext2/ext3'}[name]
        results[name]={'selected':len(selection),'passed':len(logical)-len(fails),'failed':sorted(fails),'filesystem':d['f_filesystem'],'exit':d['exit']}
    flags=json.loads(b['unit-native-results.json'])
    assert flags['namespace-overlay'] is False and flags['tmpfs'] is True
    if not initial:
        assert flags['actual_overlay_failures']==[PRIVATE] and flags['old_private_overlay_failure_reproduced'] and flags['shared_and_other_focus_tests_green']
    ext=json.loads(n['packet/units/ext4-result.json'])
    assert ext['full']==(not initial) and ext['cargo_sha']==u['sha'] and ext['source']['mode_path_sha256_inventory']==spec['inventory']
    return {'suite_sha':u['sha'],'tested':results}

def verify(n,b,c):
    j=lambda k:json.loads(n[k+'.json'])
    d=j('packet/build');s=j('packet/spec');end=j('packet/terminal')
    assert d==json.loads(b['build.json']) and d['parent']==s['parent']==BASE
    assert c['candidate'] in (INITIAL,FINAL) and c['status']=='completed'
    initial=c['candidate']==INITIAL
    assert (c['run'],c['qa'],c['conclusion'])==((41145906532,'c80d81f5d2f95fb30f7f132ad67884d5e70c0f0a','failure') if initial else (41146551109,'5032f93b1a2e08f3bc2f6ed6425df3f6e28bead9','success'))
    assert end['qa']==c['qa']==d['qa'] and end['roles']=={'fixed':0,'signed':1 if initial else 0}
    assert d['candidate']==s['head']==c['candidate']==d['tree']['commit'] and d['tree']['tree']==s['tree']
    assert d['tree']['mode_path_sha256_inventory']==s['inventory'] and d['tree']['lock']==s['lock_sha256']
    assert d['env']['CFG_RELEASE_CHANNEL']=='dev' and d['env']['CFG_RELEASE']=='1.99.0-dev'
    assert d['args'][:4]==['cargo','+ohm','-Zohm-defaults=no','build'] and '--release' in d['args'] and '--locked' in d['args']
    compiled=[json.loads(l) for l in b['compile.stdout.gz'].splitlines()]
    assert compiled[-1]=={'reason':'build-finished','success':True}
    last,=[r for r in compiled if r['reason']=='compiler-artifact' and r['target']['name']=='cargo' and r['target']['kind']==['bin']]
    assert not last['fresh'] and {'all-static','ohm-defaults'}<=set(last['features'])
    assert j('receipts/21/custody')['archive_sha256']==DIST
    signed=j('receipts/21/installed');assert signed['bin/cargo']==SIGNED
    output={}
    for role in ('signed','fixed'):
        fixed=role=='fixed';pre='packet/'+role+'/'
        read=lambda s:j(pre+s)
        ident=read('identity');outer=read('outer');r=read('result')
        assert outer['before']==outer['after']==ident['parent_namespace']!=ident['namespace'] and not outer['residual'] and outer['exit']==end['roles'][role]
        assert not r['errors'] and not r['residual_mounts'] and ident['uid']>0
        assert r['issues']==(['marked-trash-mounted unrelated eligible sibling'] if initial and not fixed else [])
        assert set(r['cases'])=={'eligible-mounted','marked-trash-mounted','separate-device','symlink','private','overlay','held-profile-lock'}
        assert ident['expected']==(s['head'] if fixed else BASE) and ident['cargo']['sha256']==(d['compiled'] if fixed else SIGNED)
        assert 'commit-hash: '+ident['expected'] in ident['version'] and ident['rustc']['sha256']==signed['bin/rustc']
        assert d['compiled']==d['delivered']!=SIGNED
        assert all(ident[k]['sha256']==(d['signed_runtime'][key]) for k,key in [('rustc','bin/rustc'),('wild','lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd')])
        cmdsets=[k for k in n if k.startswith(pre) and k.endswith('/command.json')]
        commands={}
        expected_exe=Path(ident['base'])/'rustup/toolchains/ohm/bin/cargo'
        for path in cmdsets:
            key=path.removeprefix(pre).removesuffix('/command.json');raw=json.loads(n[path]);stem=pre+key+'/'
            stdout=n[stem+'stdout.gz'];err=n[stem+'stderr.gz'];trace=n[stem+'native.trace.gz'].decode().splitlines()
            assert raw['stdout']==h(stdout) and raw['stderr']==h(err) and raw['uid']==ident['uid']
            seen=[]
            for l in trace:
                k=re.search(r'^(\d+)\s+[0-9.]+\s+execve\("'+re.escape(str(expected_exe))+r'", (\[.*?\]),.*\) = 0$',l)
                if k:seen.append((int(k[1]),json.loads(k[2])))
            assert len(seen)==1 and seen[0][1][1:]==raw['argv'][2:],(key,seen,raw['argv'])
            commands[key]=(raw,stdout,err.decode(),trace,seen[0][0])
        assert len(commands)==18,(role,sorted(commands))
        phases={}
        for case in ('eligible-mounted','marked-trash-mounted','separate-device'):
            t=read(case);dry=commands[case+'-dry'];real=commands[case+'-real'];a=t['base'];v=t['view'];p=t['parent']
            assert dry[0]['exit']==0 and '--dry-run' in dry[0]['argv'] and '--dry-run' not in real[0]['argv']
            assert t['preview']==dry[2] and t['actual']==real[2] and t['actual_exit']==real[0]['exit']
            assert a['dev']==v['dev'] and a['ino']==v['ino'] and a['nlink']==v['nlink']==1 and a['sha256']==v['sha256']==SENTINEL_SHA and a['size']==v['size']==137
            assert a['mount_id']!=v['mount_id'] and (p['dev']!=a['dev'])==(case=='separate-device')
            healthy_removed=t['healthy_after'] is None
            assert t['real_ran'] and (healthy_removed or (not fixed and case=='marked-trash-mounted' and t['healthy_after']['sha256']==h(HEALTHY) and t['healthy_after']['size']==len(HEALTHY)))
            protected=fixed or case=='separate-device'
            assert t['protected_plus_healthy']==protected and t['admitted']!=protected
            nfiles,nbytes=(1,len(HEALTHY)) if protected else (2,137+len(HEALTHY))
            assert re.search(r'Summary\s+'+str(nfiles)+r' files?, '+str(nbytes)+r'B total',dry[2])
            if not fixed and case!='marked-trash-mounted':assert t['old_mount']['path']==t['view_name']!=t['new_mount']['path']
            held=t['held'];assert held['hash']==a['sha256'] and (a['dev'],a['ino'])==(held['dev'],held['ino'])
            deleted=[l for l in real[3] if re.search(r'\bunlink(?:at)?\(',l) and 'QA_SENTINEL' in l and re.search(r'= 0$',l)]
            assert any(re.search(r'\bunlink(?:at)?\(',l) and 'healthy' in l and re.search(r'= 0$',l) and l.startswith(str(real[4])+' ') for l in real[3])==healthy_removed
            if protected:
                assert not deleted and t['external_after']==a and held['nlink']==1 and t['actual_exit']==0
                if fixed:
                    assert t['old_mount']['path']==t['new_mount']['path']==t['view_name']
                    assert 'would cross mount at ' in dry[2] and 'would cross mount at ' in real[2]
                    for cmd in (dry,real):
                        assert any('openat2(' in l and all(f in l for f in ('RESOLVE_BENEATH','RESOLVE_NO_XDEV','RESOLVE_NO_SYMLINKS')) and l.startswith(str(cmd[4])+' ') for l in cmd[3])
            else:
                assert len(deleted)==1 and deleted[0].startswith(str(real[4])+' ') and t['external_after'] is None and held['nlink']==0 and t['actual_exit']==101
                assert any(l.startswith(str(real[4])+' ') and 'EBUSY' in l and 'mounted' in l for l in real[3])
            phases[case]={'held_links':held['nlink'],'external_intact':t['external_after'] is not None,'native_unlink':deleted,'exit':t['actual_exit'],
                'healthy_removed':healthy_removed,'same_mount_position':t['old_mount']['path']==t['new_mount']['path']}
        x=read('symlink');assert x['before']==x['after'] and x['exit']==0 and not x['healthy'] and x['links_exist']==[False,False]
        assert x['preview']==commands['symlink-dry'][2] and x['exit']==commands['symlink-real'][0]['exit'] and re.search(r'Summary\s+3 files,',x['preview'])
        y=read('private');assert y['before']==y['after'] and y['before']['mount_id']!=y['view']['mount_id'] and y['remaining_mount']['path']==y['original_mount']
        assert y['exit']==0 and not y['healthy'] and 'would cross mount at ' in commands['private-dry'][2] and 'would cross mount at ' in commands['private-real'][2]
        assert y['preview']==commands['private-dry'][2] and y['actual']==commands['private-real'][2] and commands['private-enroll'][0]['exit']==0
        z=read('overlay');assert z['parent']['mount_id']==z['before']['mount_id'] and z['parent']['dev']!=z['before']['dev']
        assert z['parent']['filesystem']==z['before']['filesystem']=='overlay' and z['productive_preview']==fixed and z['old_rejection']!=fixed
        assert z['exit']==commands['overlay-real'][0]['exit']==0 and (z['after'] is None)==fixed and z['original_lower_after']['sha256']==z['before']['sha256']
        assert z['preview']==commands['overlay-dry'][2] and z['actual']==commands['overlay-real'][2] and re.search(r'Summary\s+1 file, 137B' if fixed else r'Summary\s+0 files',z['preview'])
        lock=read('held-profile-lock');assert lock['while_held']==lock['after_release']==[0,0] and lock['before']==lock['while_held_file'] and lock['after_release_file'] is None
        for phase,files in [('while-held',0),('after-release',1)]:
            assert all(commands['held-profile-lock-'+mode+'-'+phase][0]['exit']==0 for mode in ('dry','real'))
            assert re.search(r'Summary\s+'+str(files)+r' files?',commands['held-profile-lock-dry-'+phase][2])
        output[role]={'commands':len(commands),'cargo':ident['cargo']['sha256'],'rustc':ident['rustc'],'driver':ident['driver'],'wild':ident['wild'],'boundaries':phases,
                      'overlay_file_removed':z['after'] is None,'symlink_destinations_preserved':True,'private_mount_preserved':True,'held_lock_preserved':True}
    for kind in ('rustc','driver','wild'):
        for key in ('dev','ino','sha256'):assert output['fixed'][kind][key]==output['signed'][kind][key]
    output['opened_source_tree']=s['tree'];output['source_files']=d['tree']['files']
    output['native_unit_suites']=units(n,b,s,c['qa'])
    return output
def prior():
    payload=(HERE/'prior-namespace.zip').read_bytes()
    assert h(payload)=='8910ab7e26efa9583c73de5a0c0eb92d60ffa7304da2ea8251d3172673d90536' and len(payload)==34103
    with zipfile.ZipFile(HERE/'prior-namespace.zip') as z:
        stdout=z.read('original.txt'); assert z.read('original.status').strip()==b'101'
        priorfail={x.decode() for x in re.findall(rb'^test (\S+) \.\.\. FAILED',stdout,re.M)}
        assert len(priorfail)==14 and PRIVATE in priorfail and b'46 passed; 14 failed' in stdout
        assert z.read('tmpfs.status').strip()==b'0' and b'60 passed; 0 failed' in z.read('tmpfs.txt')
    return priorfail

if __name__=='__main__':
    previous=prior();out={'prior_namespace_overlay_failed':sorted(previous),'cohorts':{}}
    for label in ['first','final']:
        root=HERE/label
        c=json.loads((root/'custody.json').read_bytes())
        n=opened(root/'native.zip',c['native']); b=opened(root/'build.zip',c['build'])
        result=verify(n,b,c)
        names=set(json.loads(b['unit.json'])['gc'])
        still_failed=set(result['native_unit_suites']['tested']['namespace-overlay']['failed'])
        result['prior_overlay_failures_now_passed']=sorted((previous&names)-still_failed)
        result['prior_overlay_failures_not_enrolled']=sorted(previous-names)
        result['run']=c['run'];result['qa']=c['qa'];result['candidate']=c['candidate'];result['workflow_conclusion']=c['conclusion']
        out['cohorts'][label]=result
    assert out['cohorts']['first']['fixed']['cargo']!=out['cohorts']['final']['fixed']['cargo']
    assert out['cohorts']['first']['native_unit_suites']['suite_sha']!=out['cohorts']['final']['native_unit_suites']['suite_sha']
    print(json.dumps(out,sort_keys=True,indent=2))
