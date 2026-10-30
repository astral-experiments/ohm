"""Preserve checked text witnesses from exact terminal hosted jobs, including failed-run siblings."""
import gzip
import hashlib
import json
from pathlib import Path
import os
import shutil
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
GH = shutil.which('gh-auto') or (str(Path.home()/'.local/bin/gh-auto')
                               if (Path.home()/'.local/bin/gh-auto').is_file() else 'gh')
BASE = 'repos/astral-experiments/ohm/actions/'
BRANCH = 'charlie/qa-gnu-atomic-ruff-db'
REC = 'observed-ruff-db/receipts/'
PREFIX = 'atomic-file-guards/'


def api(path):
    return json.loads(subprocess.check_output([GH, 'api', BASE + path]))


def extract(z, name):
    return json.loads(z.read(name))


def raw(z, name):
    return gzip.decompress(z.read(name)).decode()


def physical(kernel):
    return {'rustc': [[r['crate'],r['link_only'],r['terminal'],r['argv']] for r in kernel['rustcs']],
            'linkers': [[r['path'],r['terminal']] for r in kernel['link_tools']]}


def screen(z, kind, role):
    state = extract(z, REC + 'terminal-screen.json')
    assert (state['mode'], state['role'], state['single_baseline'], state['instrumented']) == (kind, role, False, False)
    phases = ['cold', 'edit', 'first-repeat', 'second-repeat', 'repair', 'clean']
    if kind == 'test':
        phases.append('pre-fix-method-with-new-tests')
    snapshots = {}
    for phase in phases:
        base = REC + phase + '/'
        result = extract(z,base + 'result.json')
        assert result == state['states'][phase]
        events = extract(z,base + 'kernel.json')
        assert events['cargo'][0]['terminal'] == [0]
        proof = {'roster':result['roster'], 'units':result['units'], 'sha256':result['sha256'],
                 'size':result['size'], 'full':result['full'], 'link_only':result['link_only'], 'links':result['links']}
        if phase in ('edit','first-repeat','second-repeat','repair','pre-fix-method-with-new-tests'):
            proof['physical'] = physical(events)
        if phase in ('first-repeat','second-repeat'):
            assert result['full'] == ([['portable_atomic','hard']] if role=='P' else [])
            assert result['link_only'] == (['ruff_db'] if kind=='test' else [])
            assert result['links'] == (['ld'] if kind=='test' else [])
        if phase in ('edit','repair'):
            assert 'ruff_db' in [name for name,_ in result['full']]
            assert result['links'] == (['ld'] if kind=='test' else [])
        if kind=='test':
            proof['tests']=result['test_names']
            tests=[p for p in z.namelist() if p.startswith(base+'indexed_nodes_') and p.endswith('.stdout.gz')]
            assert len(tests) == (1 if phase=='cold' else 4)
            proof['qemu']={Path(p).name[:-10]:raw(z,p) for p in tests}
        else:
            proof['archive']=extract(z,base+'archive-members.json')
            assert proof['archive']['raw']==proof['sha256']
            if phase in ('cold','edit','first-repeat','repair','clean'):
                proof['consumer']=extract(z,base+'downstream/result.json')
                assert proof['consumer'] == result['consumer']
                proof['compiled_consumer']=extract(z,base+'downstream/compile.json')
                assert proof['compiled_consumer']['archive_sha']==result['sha256']
        snapshots[phase] = proof
    invalid = [json.loads(line) for line in raw(z,REC+'invalid/stdout.gz').splitlines()]
    broken = [m['message'] for m in invalid if m['reason']=='compiler-message' and
              (m['message'].get('code') or {}).get('code')=='E0425' and 'OHM_ATOMIC_DB_MISSING_SYMBOL' in m['message']['message']]
    assert broken and invalid[-1] == {'reason':'build-finished','success':False}
    clean = snapshots['clean']
    if kind=='test':
        assert not state['mismatches_against_clean'] and len(clean['tests'])==129 and len(snapshots['cold']['tests'])==126
        assert all(snapshots[phase]['sha256']==clean['sha256'] for phase in ('edit','first-repeat','second-repeat','repair'))
    else:
        for phase in ('edit','first-repeat','second-repeat','repair'):
            objs=lambda p: sorted((n,s,h) for n,_,s,h in snapshots[p]['archive']['objects'])
            assert objs(phase) == objs('clean') and len(objs(phase))==216
        assert all(snapshots[p]['consumer']['verdicts']==clean['consumer']['verdicts'] for p in ('edit','first-repeat','repair'))
    return {'source':extract(z,REC+'enrolled.json'),'snapshots':snapshots,
            'invalid':{'message':broken,'kernel':physical(extract(z,REC+'invalid/kernel.json'))},
            'mismatches_against_clean':state['mismatches_against_clean'],
            'bootstrap':extract(z,'atomic-subjects/origin.json')}


def guards(z):
    data = {}
    assert extract(z,PREFIX+'terminal.json')['roles']==['P','C']
    for role in 'PC':
        base=PREFIX+role+'/receipts/'
        direct=extract(z,base+'direct.json')
        assert len(direct)==47
        for label in ('bundle','default','external'):
            assert direct['native/'+label] == {'embedded_object':label!='external',
                       'marker':'v2' if label=='external' and role=='C' else 'hard'}
        history=extract(z,base+'file-history.json')
        for label,want in [('cold',17),('same-inode-mtime',29),('malformed',None),('missing',None),('restored',41)]:
            for path in ('warm','empty'):
                row=history[label][path]
                assert row['exit']==(101 if want is None else 0) and row.get('qemu')==want
        data[role]={'direct':direct,'real_file':history}
    return data


def main():
    evidence=HERE/'evidence'
    table=json.loads((evidence/'sources.json').read_text())
    sources=table if not sys.argv[1:] else sys.argv[1:]
    for key in sources:
        source=table[key]
        run=api('runs/'+str(source['run']))
        assert (run['head_sha'],run['head_branch'],run['status'],run['event'])==(source['head'],BRANCH,'completed','workflow_dispatch')
        jobs=api('runs/'+str(source['run'])+'/jobs?per_page=100')['jobs']
        job,=[r for r in jobs if r['name']==source['job']]
        assert job['conclusion']=='success' and job['run_id']==source['run']
        art=api('artifacts/'+str(source['artifact']))
        assert art['workflow_run']['id']==source['run'] and art['workflow_run']['head_sha']==source['head']
        assert art['name']==source['name'] and art['digest']=='sha256:'+source['digest'] and not art['expired']
        # Read one ZIP at a time. The lib archive may retain large paired binaries; never add those to Git.
        with os.fdopen(os.memfd_create('atomic-qa-witness'),'w+b') as f:
            subprocess.run([GH,'api',BASE+'artifacts/'+str(source['artifact'])+'/zip'],stdout=f,check=True)
            f.seek(0)
            assert hashlib.file_digest(f,'sha256').hexdigest()==source['digest']
            with zipfile.ZipFile(f) as z:
                report=guards(z) if key=='guards' else screen(z,*key.split('-'))
        record={'origin':source|{'job_id':job['id'],'run_conclusion':run['conclusion']},'report':report}
        out=evidence/(key+'.json.gz')
        encoded=json.dumps(record,sort_keys=True,separators=(',',':')).encode()
        if out.exists():assert gzip.decompress(out.read_bytes())==encoded
        else:out.write_bytes(gzip.compress(encoded,compresslevel=9,mtime=0))
        print(key,out.stat().st_size)


if __name__=='__main__':main()
