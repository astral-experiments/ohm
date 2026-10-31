"""Disjointness from the earlier corrected E enrollment, using only pre-outcome identities."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from graph import need

REPO='astral-experiments/ohm'
RUN=41243597545
HEAD='b1f863353a63c91bebf5d2bc2ca68a4aca93f6bb'
BRANCH='charlie/qa-branch-storage-checked-confirmation-20261031'
JOB='Confirm corrected E whole-Ruff storage '
PREFIX='checked-e-storage-confirmation-'
POSITIONS=tuple(f'{i:02d}' for i in range(1,13))
UUID=re.compile('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
SHA=re.compile('[0-9a-f]{64}')
PRIOR='e7874956be4febf7003cef92076951c1b89a469dcdaaa17730fdc11eb703b0dc'
SELF='0d904d06ee675ac44edcd18ff82d17397159f3783163e459a79ef9dfdc11d28c'


def prior():
    data=(HERE/'excluded-boots.json').read_bytes();boots=json.loads(data)
    p=json.loads((HERE/'boot-provenance.json').read_bytes());missing=set(p['added'])
    need(hashlib.sha256(data).hexdigest()==PRIOR and len(boots)==len(set(boots))==66 and len(missing)==13 and
         all(UUID.fullmatch(b) for b in boots) and not missing-set(boots) and p['E_registration']==HEAD,'incorrect predecessor enrollment')
    former=(json.dumps(sorted(set(boots)-missing),indent=2)+'\n').encode()
    need(hashlib.sha256(former).hexdigest()==SELF,'former 53 were changed')
    return set(boots)


def validate(ledger,root_boots):
    need((ledger['repository'],ledger['run'],ledger['head'],ledger['branch'],ledger['attempt'])==(REPO,RUN,HEAD,BRANCH,1) and
         set(ledger['hosts'])==set(POSITIONS),'incomplete or foreign E boot identities')
    rows=ledger['hosts'];hist=prior();ids=[rows[p]['boot'] for p in POSITIONS]
    need(len(set(ids))==12 and not hist.intersection(ids) and all(UUID.fullmatch(b) for b in ids),'E installation could not be certified')
    need(len({r['job'] for r in rows.values()})==len({r['artifact'] for r in rows.values()})==12 and
         all(SHA.fullmatch(r['archive_sha256']) and r['bytes']>0 and set(r['identity_sha256'])=={'enrollment.json','meter-ready.json','host.json'} and
             all(SHA.fullmatch(h) for h in r['identity_sha256'].values()) for r in rows.values()),'missing source-bound E archive identity')
    need(len(root_boots)==2 and all(UUID.fullmatch(b) for b in root_boots) and not (hist|set(ids)).intersection(root_boots),
         'root F pair unqualified: an enrolled E or prior boot is shared or missing')
    return sorted(ids)


def extract(archive,j,z,position):
    need(archive.is_file() and archive.stat().st_size==z['size_in_bytes']>0,'missing complete E original')
    with archive.open('rb') as f:
        h=hashlib.file_digest(f,'sha256').hexdigest()
        need(z['digest']=='sha256:'+h,'E archive SHA256 differs')
        with zipfile.ZipFile(f) as zz:
            names=('enrollment.json','meter-ready.json','host.json')
            need(all(zz.namelist().count(n)==1 and 0<zz.getinfo(n).file_size<2**20 for n in names),'missing or ambiguous E identity')
            raw={n:zz.read(n) for n in names}
    en,meter,host=(json.loads(raw[n]) for n in names)
    b=en['boot'];need((en['run'],en['head'],en['attempt'],en['position'])==(RUN,HEAD,1,position) and UUID.fullmatch(b) and
                      b==meter['boot']==host['raw_system']['/proc/sys/kernel/random/boot_id'],'wrong E enrollment or kernel identity')
    return {'job':j['id'],'artifact':z['id'],'bytes':z['size_in_bytes'],'archive_sha256':h,'boot':b,
            'identity_sha256':{n:hashlib.sha256(v).hexdigest() for n,v in raw.items()}}


def capture(directory,gh):
    # Do not request any job verdict, performance result, full worker receipt, measurement or step.
    def api(path,fields):
        return json.loads(subprocess.check_output([gh,'api',f'repos/{REPO}/actions/runs/{RUN}'+path,'--jq',fields],cwd=HERE))
    run=api('','{id, head_sha, head_branch, run_attempt, event, status, path, repository: .repository.full_name}')
    need((run['id'],run['head_sha'],run['head_branch'],run['run_attempt'],run['repository'],run['event'],run['status'],run['path'])==
         (RUN,HEAD,BRANCH,1,REPO,'workflow_dispatch','completed','.github/workflows/ci.yml'),'wait for all original E positions')
    jobs=api('/attempts/1/jobs?per_page=100','[.jobs[] | {id, name, run_id, run_attempt, head_sha, status}]')
    archives=api('/artifacts?per_page=100','[.artifacts[] | {id, name, size_in_bytes, digest, expired, workflow_run}]')
    rows={}
    for p in POSITIONS:
        j,=[j for j in jobs if j['name']==JOB+p];z,=[z for z in archives if z['name']==PREFIX+p]
        need((j['run_id'],j['head_sha'],j['run_attempt'],j['status'])==(RUN,HEAD,1,'completed') and not z['expired'] and
             (z['workflow_run']['id'],z['workflow_run']['head_sha'])==(RUN,HEAD),'different or unavailable original E position')
        rows[p]=extract(directory/f"{RUN}-{z['id']}.zip",j,z,p)
    need(len(archives)==12 and len(jobs)==13,'extra or incomplete E media/job')
    return {'repository':REPO,'run':RUN,'head':HEAD,'branch':BRANCH,'attempt':1,'hosts':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('originals',type=Path);p.add_argument('--gh',default='gh-auto');args=p.parse_args()
    print(json.dumps(capture(args.originals,args.gh),sort_keys=True))
