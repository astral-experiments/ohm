"""Verify original public-GC effects directly in an Actions evidence ZIP, offline."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile
SOURCES={'signed':'2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c','shared-fix':'c7f394c8c9aaef1272c621ff11d77dcf569ed94b','standalone':'bcac7f31560d4cccb26ef2237b43858f32179330','combined':'3239cc06edcc11db2c3ca134c9af6115eb756b0b','final':'f1f1cde375c2562e4a39d12f8835092a106a4fb8'}
KNOWN={'signed':'4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e','shared-fix':'2e78b6774f1a04e6ce60ed82d3287808a09e157f433287c72f7cec1b40e598d5'}
HERE=Path(__file__).resolve().parent

def row(zipfile_path):
    with zipfile.ZipFile(zipfile_path) as z:
        assert z.testzip() is None
        data={}
        for n in z.namelist():
            assert not Path(n).is_absolute() and '..' not in Path(n).parts
            if not n.endswith('/observation.json'):continue
            subject=json.loads(z.read(n));role=subject['role'];fs=subject['filesystem'];states=subject['states'];h=subject['held_descriptors'];prefix=n.removesuffix('observation.json')
            assert subject['source']==SOURCES[role] and fs in ('ext4','overlay')
            candidate=role not in KNOWN
            if candidate:
                build=json.loads(z.read(prefix+'build.json'));spec=json.loads((HERE/'sources'/role/'candidate-source/spec.json').read_bytes())
                assert subject['cargo_sha256']==build['compiled']==build['delivered'] and build['candidate']==spec['head']==SOURCES[role]
                assert build['qa']==subject['qa'] and build['tree']['tree']==spec['tree'] and build['tree']['mode_path_sha256_inventory']==spec['inventory']
            else:
                assert KNOWN[role]==subject['cargo_sha256']
            init=states['initial'];dirent={}
            for key,s in init.items():
                assert s['fstat']==s['lstat']==s['fstatat'] and s['mount_id']==init['target']['mount_id']
                dirent[key]=[s['d_ino'],*s['fstat'][:2],s['mount_id']]
            assert (dirent['profile'][0]!=dirent['profile'][2])==(fs=='overlay')
            assert (dirent['inside'][1]!=dirent['profile'][1])==(fs=='overlay')
            assert len(subject['records'])>=1
            assert set(subject['commands'])=={'version','enroll','held-dry','held-real','released-dry','released-real'}
            physical={}
            for phase,c in subject['commands'].items():
                out,err=[gzip.decompress(z.read(prefix+phase+'.'+key+'.gz')) for key in ('stdout','stderr')]
                native=gzip.decompress(z.read(prefix+phase+'.trace.gz'));lines=native.splitlines()
                assert hashlib.sha256(native).hexdigest()==c['trace_sha256'] and c['exit']==0 and c['stdout'].encode()==out and c['stderr'].encode()==err
                alias=(Path(subject['paths']['target']).parent.parent/'rustup/toolchains/ohm/bin/cargo')
                aa=[l for l in lines if ('execve("'+str(alias)+'"').encode() in l and l.rstrip().endswith(b'= 0')]
                assert len(aa)==1 and c['argv'][1]=='+ohm';pid=int(aa[0].split()[0])
                if phase=='version':assert ('commit-hash: '+SOURCES[role]).encode() in out
                if phase=='enroll':
                    es=[json.loads(l) for l in out.splitlines()]
                    assert any(e.get('target',{}).get('name')=='private_gc_probe' and e.get('fresh') is False for e in es)
                if phase.startswith(('held','released')):
                    assert str(subject['paths']['target']).encode() in err
                    assert ('--dry-run' in c['argv'])==phase.endswith('-dry')
                    unlink=[l for l in lines if b'unlinkat(' in l and b'"private-visible-output"' in l and l.rstrip().endswith(b'= 0')]
                    busy=[l for l in lines if b'flock(' in l and b'.cargo-artifact-lock' in l and (b'EAGAIN' in l or b'EWOULDBLOCK' in l)]
                    nox=[l for l in lines if b'openat2(' in l and b'"private-visible-output"' in l and b'RESOLVE_NO_XDEV' in l and b' = -1' not in l]
                    should_remove=fs=='ext4' or candidate
                    assert bool(unlink)==(should_remove and phase=='released-real'),(role,fs,phase,unlink)
                    if phase.startswith('held'):
                        assert bool(busy)==should_remove,(role,fs,phase,busy)
                    if candidate and fs=='overlay' and phase.startswith('released'):
                        assert nox
                    physical[phase]={'cargo_pid':pid,'unlink':len(unlink),'locked':len(busy),'noxdev_leaf_opens':len(nox),'summary':err.decode().strip().splitlines()[-1]}
                elif phase=='version' or phase=='enroll':
                    physical[phase]={'cargo_pid':pid}
            assert states['held-dry']==init and states['released-dry']==states['held-real']
            assert all(states[phase]['outside']==init['outside'] for phase in states)
            for k in ('inside','root_output','sibling'):
                assert states['held-real'][k]==init[k]
                assert (states['released-real'][k] is None)==(fs=='ext4' or candidate)
            assert h['held-real']['payload'][2]==1 and h['released-real']['payload'][2]==int(not(candidate or fs=='ext4'))
            assert all(states['released-real'][key]==init[key] for key in ['old_lock','held_lock'])
            data[role]={'source':subject['source'],'cargo':subject['cargo_sha256'],'fs':fs,'qa':subject['qa'],'identities':dirent,'payload_nlink_held_released':[h[k]['payload'][2] for k in ('held-real','released-real')],'physical':physical}
        testn=[n for n in z.namelist() if n.endswith('/suite-verdict.json') or n=='suite-verdict.json']
        if testn:
            assert len(testn)==1
            n,=testn;suite=json.loads(z.read(n));prefix=n.removesuffix('suite-verdict.json')
            source=suite['source']['head'];role,=[k for k,v in SOURCES.items() if v==source]
            spec=json.loads((HERE/'sources'/role/'candidate-source/spec.json').read_bytes())
            assert suite['source']==spec
            if role not in data:
                proof=json.loads(z.read(prefix+'restored-source.json'))
                assert proof['commit']==source and proof['tree']==spec['tree'] and proof['mode_path_sha256_inventory']==spec['inventory']
                data[role]={'source':source,'fs':'overlay'}
            orig=json.loads((HERE/'failed-original.json').read_bytes());assert orig==suite['previous']
            assert 'overlay' in suite['actual_filesystem'] and 'commit-hash: b940084d' in suite['official_rust']
            for tag in ('official-build','official-version'):
                cmd=json.loads(z.read(prefix+tag+'.json'));assert cmd['exit']==0 and cmd['args'][1]=='+1.99.0'
                for stream in ('stdout','stderr'):
                    assert hashlib.sha256(gzip.decompress(z.read(prefix+tag+'.'+stream+'.gz'))).hexdigest()==cmd[stream]
            phases={'old-twelve':set(orig['names']),'profile-unit':{'workspace::build_cache_gc::worktrees::idle::tests::stock_build_can_finish_opening_a_profile_after_discovery'}}
            if role=='final':
                names=gzip.decompress(z.read(prefix+'gc-lib-list.stdout.gz')).decode().splitlines()
                expected={name.removesuffix(': test') for name in names if name.startswith('workspace::build_cache_gc') and name.endswith(': test')}
                assert len(expected)==63 and 'workspace::build_cache_gc::worktrees::at::tests::private_directory_and_entry_lookup_refuse_a_nested_mount' in expected
                phases['all-gc-library']=expected
            assert set(phases)==set(suite['jobs'])
            for tag,expected in phases.items():
                raw=gzip.decompress(z.read(prefix+tag+'.stdout.gz'));cmd=json.loads(z.read(prefix+tag+'.json'))
                rows=dict(re.findall(r'(?m)^test (\S+) \.\.\. (ok|FAILED|ignored)$',raw.decode()))
                assert set(rows)==expected and cmd['exit']==suite['jobs'][tag]['exit'] and rows==suite['jobs'][tag]['rows']
                assert hashlib.sha256(raw).hexdigest()==cmd['stdout'] and set(cmd['args'][cmd['args'].index('--exact')+1:])==expected
                err=gzip.decompress(z.read(prefix+tag+'.stderr.gz'));assert hashlib.sha256(err).hexdigest()==cmd['stderr']
                failures={name for name,result in rows.items() if result!='ok'}
                expected_fail={'ohm_build_gc::max_age_applies_to_targets_contexts_dependencies_and_thinlto'} if (role,tag)==('standalone','old-twelve') else set()
                assert failures==expected_fail and cmd['exit']==(101 if failures else 0)
                data[role][tag]={'exit':cmd['exit'],'outcomes':rows,'binary_sha256':suite['jobs'][tag]['binary']}
        for n in z.namelist():
            if not n.endswith('reattached-result.json'):continue
            a=json.loads(z.read(n));pre=n.removesuffix('reattached-result.json');ident=json.loads(z.read(pre+'identity.json'))
            role,=[k for k,v in SOURCES.items() if v==ident['expected']]
            mode='enosys' if 'enosys' in n else 'native'
            if role not in data:data[role]={'source':SOURCES[role],'cargo':ident['cargo']['sha256'],'fs':'ext4'}
            if role in KNOWN:assert data[role]['cargo']==KNOWN[role]
            if role=='combined':assert data[role]['cargo']=='84be921330ca5354552dea4ad1c5ba16556c97fc02e9be9c72093029bde23473'
            assert 'commit-hash: '+SOURCES[role] in ident['version'].splitlines() and ident['uid']>0 and ident['namespace']!=ident['parent_namespace']
            b=a['binding'];events=a['events'];assert ident['cargo']['sha256']==b['sha256']==data[role]['cargo']
            assert ident['cargo']['filesystem']=='ext4' and z.read(pre+'cargo.stderr').decode()==a['err'] and z.read(pre+'cargo.stdout').decode()==a['stdout']
            count=[(i,e) for i,e in enumerate(events) if 'mountinfo' in e];assert [e['mountinfo'] for _,e in count]==list(range(1,len(count)+1)) and b['mountinfo_reads']>=2
            assert all(e['pid']==b['pid'] for e in events)
            orig=b['before_dir'];barrier=b['bound_dir'];ex=b['outside_dir'];assert orig==ex and orig['mount']!=barrier['mount'] and (orig['device'],orig['inode'])==(barrier['device'],barrier['inode'])
            leaf=b['before_leaf'];assert leaf==b['outside_leaf'] and leaf['nlink']==1 and leaf['mount']!=b['bound_leaf']['mount'] and (leaf['inode'],leaf['device'],leaf['size'],leaf['sha256'])==tuple(b['bound_leaf'][k] for k in ('inode','device','size','sha256'))
            assert leaf['sha256']==a['physical_held_after']['sha256']
            passed=role=='final';opened=[(i,e) for i,e in enumerate(events) if e.get('kind') in ('openat','openat2')]
            assert opened and sum(i<opened[0][0] for i,_ in count)==b['mountinfo_reads']
            deleted=[e for e in events if e.get('kind')=='unlinkat-payload' and e['return']==0]
            if passed:
                assert a['exit']==0 and not deleted and a['outside_after']==leaf and a['physical_held_after']['nlink']==1
                assert any(e['kind']=='openat2' and e['resolve']&1 and e['return']==(-38 if mode=='enosys' else -18) for _,e in opened)
                if mode=='enosys':
                    assert any(e.get('kind')=='mount-id-open' and e['return']>=0 for e in events)
            else:
                assert a['exit']==101 and len(deleted)==1 and 'Device or resource busy' in a['err'] and a['outside_after'] is None and a['physical_held_after']['nlink']==0
                assert any(e['kind']=='openat' and e['return']>=0 and e['resolve']==0 for _,e in opened)
            data[role]['reattached_'+mode]={'exit':a['exit'],'before':orig,'bound':barrier,'pid':b['pid'],'raw_opens':[e for _,e in opened],'outside_before':leaf,'outside_after':a['outside_after'],'held_after':a['physical_held_after'],'successful_unlinks':len(deleted),'mountinfo_reads':len(count)}
        assert data
        matches=[n for n in z.namelist() if n.endswith('fixed/result.json')]
        if matches:
            assert len(matches)==1 and len(data)==1;role,=data
            n,=matches;item=json.loads(z.read(n)); assert item['exit']==0 and item['healthy'] is False and item['before']==item['after'] and item['view']['mount_id']!=item['before']['mount_id'] and (item['view']['dev'],item['view']['ino'])==(item['before']['dev'],item['before']['ino'])
            assert 'would cross mount at ' in item['actual'] and item['before']['nlink']==1
            data[role]['external_bind']={k:item[k] for k in ('before','after','view','exit','healthy')}
        return {'zip':Path(zipfile_path).name,'zip_sha256':hashlib.sha256(Path(zipfile_path).read_bytes()).hexdigest(),'observations':data}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('files',nargs='+',type=Path);a=ap.parse_args()
    print(json.dumps([row(f) for f in a.files],sort_keys=True,indent=2))
