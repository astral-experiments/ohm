"""Install this comparison from same-run source-built kits with the original whole-file identities."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/'ohm-gnu-syscall/source-rebuild')]
import sdk
from kits import unpack_parent
from rebuild import rt

TMP=Path(os.environ['RUNNER_TEMP'])
HEAD=os.environ['GITHUB_SHA']
PARENT_KIT='gnu-atomic-source-parent-sdk'
CANDIDATE_KIT='gnu-atomic-registered-compiler'
API='repos/astral-experiments/ohm/actions/'


def pack():
    expected=sdk.MEMBERS['common']|{sdk.DRIVER:sdk.patched_record()['driver']}
    observed=rt.load(rt.LOG/'physical-sdk.json')
    assert observed=={'files':expected,'differences':{}}
    selected=rt.load(rt.LOG/'selected.json')
    assert selected['role']=='patched' and selected['commit']==sdk.SOURCE['parent']['source']
    out=TMP/'atomic-source-parent';out.mkdir();payload=out/'sdk.tar.zst'
    subprocess.run(['tar','--zstd','--hard-dereference','-cf',payload,'-C',rt.SDK,*sorted(expected)],check=True)
    rt.save(out/'source.json',{'run':int(os.environ['GITHUB_RUN_ID']),'head':HEAD,'source':selected['commit'],
                'tree':sdk.SOURCE['parent']['tree'],'members':len(expected),'archive_sha256':rt.sha(payload),'bytes':payload.stat().st_size})


def restore(p,c,run,origin):
    prior=sdk.patched_record();expected=sdk.MEMBERS['common']|{sdk.DRIVER:prior['driver']}
    blob=p/'sdk.tar.zst';seal=json.loads((p/'source.json').read_text())
    assert seal=={'run':run,'head':HEAD,'source':prior['source'],'tree':prior['tree'],'members':119,
                  'archive_sha256':rt.sha(blob),'bytes':blob.stat().st_size}
    work=TMP/'qualified-syscall';(work/'receipts').mkdir(parents=True)
    parent=work/'candidate-sdk'
    unpack_parent(blob,parent,expected)
    root=TMP/'atomic-subjects';root.mkdir()
    sdk.install(root,parent,c,origin|{'mode':'locally-source-built','head':HEAD,'run':run,'parent_enrollment':seal})
    record=work/'receipts/candidate.json';sdk.census.save(record,prior)
    with Path(os.environ['GITHUB_ENV']).open('a') as f:
        print('CENSUS_SDK='+str(parent),'CENSUS_CANDIDATE_RECORD='+str(record),
              'CENSUS_ROOT='+str(TMP/'observed-ruff-db'),sep='\n',file=f)


def pull(run):
    api=lambda path:json.loads(subprocess.check_output(['gh','api',API+path]))
    r=api('runs/'+str(run))
    assert (r['head_sha'],r['head_branch'],r['event'],r['status'],r['conclusion'])==(HEAD,'charlie/qa-gnu-atomic-ruff-db','workflow_dispatch','completed','success')
    jobs=api('runs/'+str(run)+'/jobs?per_page=100')['jobs']
    assert {j['name'] for j in jobs if j['conclusion']=='success'}=={'compile','source-cargo','source-parent','source-qualification (P)','source-qualification (C)'}
    arts=api('runs/'+str(run)+'/artifacts?per_page=100')['artifacts']
    with tempfile.TemporaryDirectory(dir=TMP) as scratch:
        root=Path(scratch);origin={}
        for name,members in [(PARENT_KIT,{'sdk.tar.zst','source.json'}),(CANDIDATE_KIT,{'atomic-candidate.json','driver.zst'})]:
            row,=[a for a in arts if a['name']==name]
            assert not row['expired'] and (row['workflow_run']['id'],row['workflow_run']['head_sha'])==(run,HEAD)
            incoming=root/(name+'.zip')
            with incoming.open('xb') as f:subprocess.run(['gh','api',API+'artifacts/'+str(row['id'])+'/zip'],stdout=f,check=True)
            assert 'sha256:'+rt.sha(incoming)==row['digest']
            with zipfile.ZipFile(incoming) as z:
                assert len(z.namelist())==len(members) and set(z.namelist())==members
                z.extractall(root/name)
            origin[name]={'id':row['id'],'digest':row['digest']}
        restore(root/PARENT_KIT,root/CANDIDATE_KIT,run,{'artifacts':origin})


def retain():
    work=Path(os.environ['CENSUS_ROOT'])
    record=json.loads((work/'receipts/terminal-screen.json').read_text())
    assert record['mode']=='build' and record['role'] in ('P','C')
    out=TMP/'atomic-code-witness';out.mkdir()
    facts={}
    for phase in ('cold','edit','first-repeat','repair','clean'):
        path=work/'products'/('downstream-'+phase)
        claim=record['states'][phase]['consumer']
        with path.open('rb') as f:header=f.read(20)
        assert header[:7]==bytes.fromhex('7f454c46020101') and header[18:20]==bytes.fromhex('b700')
        assert rt.sha(path)==claim['elf'] and path.stat().st_size==claim['bytes']
        unique=out/(claim['elf']+'.zst')
        if not unique.exists():subprocess.run(['zstd','-q','-3',path,'-o',unique],check=True)
        facts[phase]={'sha256':claim['elf'],'bytes':claim['bytes'],'compressed':rt.sha(unique),'verdicts':claim['verdicts']}
    assert all(facts[p]==facts['clean'] for p in ('edit','first-repeat','repair')) and facts['cold']['sha256']!=facts['clean']['sha256']
    sdk.census.save(out/'source-consumers.json',facts)


if __name__=='__main__':
    if sys.argv[1:]==['pack']:pack()
    elif sys.argv[1:]==['retain']:retain()
    elif sys.argv[1:]==['restore']:
        restore(TMP/'new-source-parent',TMP/'new-source-candidate',int(os.environ['GITHUB_RUN_ID']),{'same_dispatch':True})
    else:
        assert len(sys.argv)==3 and sys.argv[1]=='pull' and sys.argv[2].isascii() and sys.argv[2].isdecimal()
        pull(int(sys.argv[2]))
