"""Verify original public-GC effects directly in an Actions evidence ZIP, offline."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile
SOURCES={'signed':'2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c','shared-fix':'c7f394c8c9aaef1272c621ff11d77dcf569ed94b','standalone':'bcac7f31560d4cccb26ef2237b43858f32179330','combined':'3239cc06edcc11db2c3ca134c9af6115eb756b0b'}
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
        assert data
        testn=[n for n in z.namelist() if n.endswith('/suite-verdict.json') or n=='suite-verdict.json']
        if testn:
            assert len(testn)==1 and len(data)==1;role,=data
            n,=testn;suite=json.loads(z.read(n));prefix=n.removesuffix('suite-verdict.json')
            orig=json.loads((HERE/'failed-original.json').read_bytes());assert orig==suite['previous']
            assert suite['source']['head']==SOURCES[role] and 'overlay' in suite['actual_filesystem']
            for tag,expected in [('old-twelve',sorted(orig['names'])),('profile-unit',['workspace::build_cache_gc::worktrees::idle::tests::stock_build_can_finish_opening_a_profile_after_discovery'])]:
                raw=gzip.decompress(z.read(prefix+tag+'.stdout.gz')); cmd=json.loads(z.read(prefix+tag+'.json'))
                rows=dict(re.findall(r'(?m)^test (\S+) \.\.\. (ok|FAILED|ignored)$',raw.decode()));assert sorted(rows)==expected and cmd['exit']==suite['jobs'][tag]['exit'] and rows==suite['jobs'][tag]['rows']
                assert hashlib.sha256(raw).hexdigest()==cmd['stdout']
                data[role][tag]={'exit':cmd['exit'],'outcomes':rows}
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
