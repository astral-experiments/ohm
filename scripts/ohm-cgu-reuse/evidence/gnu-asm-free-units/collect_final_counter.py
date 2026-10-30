"""Reopen available original archives for one source-pinned run, then check its complete decision."""
import argparse
import shutil
import concurrent.futures
from functools import partial
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile

HERE=Path(__file__).resolve().parent
REPO='repos/astral-experiments/ohm'
RUNS={
    41088653170: ('1f5a25f23bdfabafc1fb2a0b06d33e7095b14115', 'charlie/qa-cgu-host-llvm-inputs'),
    41102102686: ('09d6e06d339b23e8785530f22e531fc0e96959ec', 'charlie/proof-gnu-asm-free-codegen-units-20261030'),
}
RUST='f69f7b7cf6de57972b310900decfac2d3a0c6fd6'
GH=(shutil.which('gh-auto') or shutil.which('gh') or 'gh')


def fetch(key):
    return subprocess.check_output([GH, 'api', REPO+'/'+key])


def read_artifact_index(run, qa, branch):
    response=json.loads(fetch(f'actions/runs/{run}'))
    assert response['head_sha']==qa and response['event']=='workflow_dispatch'
    assert response['head_branch']==branch
    artifacts=json.loads(fetch(f'actions/runs/{run}/artifacts?per_page=100'))
    assert artifacts['total_count']==len(artifacts['artifacts'])
    index={a['name']:a for a in artifacts['artifacts']}
    assert len(index)==artifacts['total_count']
    return response, index


def integrity(a, run, qa):
    assert a['workflow_run']['id']==run and a['workflow_run']['head_sha']==qa and not a['expired']
    assert a['size_in_bytes']>0 and re.fullmatch(r'sha256:[0-9a-f]{64}',a['digest'])
    return a['digest'].removeprefix('sha256:')


def reopen(job, *, run, qa):
    a,output,blocks=job
    sha=integrity(a, run, qa)
    if not output.exists():
        subprocess.run(['python3','-B',str(HERE/'reopen_final_counter.py'),str(a['id']),sha,
                        str(output),'--qa',qa,'--candidate',RUST],check=True)
    r=json.loads(output.read_text())
    assert (r['qa'],r['source'],r['artifact'],r['sha'],r['archive_bytes'])==(qa,RUST,a['id'],sha,a['size_in_bytes'])
    assert {int(k) for k in r['blocks']}==set(blocks)
    return a['name']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    p.add_argument('--run', type=int, choices=RUNS, default=41088653170)
    args=p.parse_args()
    args.directory.mkdir(parents=True,exist_ok=True)
    qa,branch=RUNS[args.run]
    run,index=read_artifact_index(args.run, qa, branch)
    jobs=[]
    if 'cgu-ir-pilot' in index:
        jobs.append((index['cgu-ir-pilot'],args.directory/'pilot.json',(-2,-1)))
    for i in range(12):
        a=index.get(f'cgu-ir-observations-{i}')
        if a is not None:
            jobs.append((a,args.directory/f'confirmed-{i}.json',(i,)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for name in pool.map(partial(reopen, run=args.run, qa=qa),jobs):print('Validated',name,flush=True)
    final=index.get('cgu-ir-confirmation')
    if final is None:
        print('Run:',run['status'],run['conclusion'],'archives reopened:',len(jobs))
        return
    assert len(jobs)==13,'Final decision arrived without every raw archive'
    digest=integrity(final, args.run, qa)
    b=fetch(f'actions/artifacts/{final["id"]}/zip')
    assert hashlib.sha256(b).hexdigest()==digest and len(b)==final['size_in_bytes']
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        assert z.namelist()==['decision.json']
        body=z.read('decision.json')
    hosted=args.directory/'hosted-decision.json'
    if hosted.exists():assert hosted.read_bytes()==body
    else:
        with hosted.open('xb') as stream:stream.write(body)
    result=args.directory/'independent-decision.json'
    if not result.exists():
        subprocess.run(['python3','-B',str(HERE/'compose_final_counter.py'),str(args.directory),
                        str(hosted),str(result),'--qa',qa],check=True)
    print('Complete',result,flush=True)


if __name__=='__main__':
    main()
