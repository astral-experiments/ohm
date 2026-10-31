"""Score only two verified native readbacks from the official attempt-1 ZIPs at this exact head."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import reopen
from graph import need

LABEL="Screen F root workspace check "
PREFIX="ruff-root-check-f-screen-"


def bind(run,jobs,artifacts,run_id,head):
    repo=reopen.s.b.REPO
    need((run['id'],run['head_sha'],run['head_branch'],run['run_attempt'],run['repository']['full_name'],run['event'],run['path'],run['display_title'])==
         (run_id,head,reopen.s.BRANCH,1,repo,'workflow_dispatch','.github/workflows/ci.yml',f'Two fresh root Ruff check screenings {head}'),'different GitHub workflow')
    need(run['status']=='completed' and run['conclusion']=='success','incomplete or rejected official experiment')
    js={j['name']:j for j in jobs['jobs']}; zs={z['name']:z for z in artifacts['artifacts']}
    need(jobs['total_count']==len({j['id'] for j in js.values()})==len(js)==2 and set(js)=={LABEL+p for p in reopen.s.ORDERS} and
         artifacts['total_count']==len({z['id'] for z in zs.values()})==len(zs)==2 and set(zs)=={PREFIX+p for p in reopen.s.ORDERS},'missing, duplicate or extra original')
    names={j['runner_name'] for j in js.values()}
    need(run_id!=reopen.s.PREFLIGHT['run'] and len(names)==2 and all(names) and not names & reopen.s.PREVIOUS_RUNNERS,'previous or shared preflight worker')
    enrolled={}
    for pos in reopen.s.ORDERS:
        j,z=js[LABEL+pos],zs[PREFIX+pos]
        need(j['run_id']==run_id and j['head_sha']==head and j['run_attempt']==1 and j['status']=='completed' and j['conclusion']=='success','different original job')
        need(z['workflow_run']['id']==run_id and z['workflow_run']['head_sha']==head and not z['expired'] and
             type(z['size_in_bytes']) is int and z['size_in_bytes']>0 and re.fullmatch(r'sha256:[0-9a-f]{64}',z['digest']),'invalid original receipt')
        enrolled[pos]={'job':j['id'],'runner':j['runner_name'],'archive':{k:z[k] for k in ('name','id','size_in_bytes','digest')}}
    return enrolled


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=int,required=True);p.add_argument('--zip-directory',type=Path,required=True);p.add_argument('--readback-directory',type=Path,required=True)
    p.add_argument('--corrected-e-originals',type=Path,required=True)
    p.add_argument('--gh',default='gh-auto');args=p.parse_args()
    head=subprocess.check_output(['git','-C',HERE,'rev-parse','HEAD'],text=True).strip()
    need(not subprocess.check_output(['git','-C',HERE,'status','--porcelain','--',HERE]),'reader sources changed')
    def api(resource):
        return json.loads(subprocess.check_output([args.gh,'api',f'repos/{reopen.s.b.REPO}/actions/runs/{args.run}'+resource],cwd=HERE))
    refs=bind(api(''),api('/attempts/1/jobs?per_page=100'),api('/artifacts?per_page=100'),args.run,head)
    # Seal all competing physical identities before reading a root outcome.
    competing=reopen.boots.capture(args.corrected_e_originals,args.gh)
    workers=[]
    for pos,r in refs.items():
        z=r['archive'];file=args.zip_directory/f"{args.run}-{z['id']}.zip"
        with file.open('rb') as f:
            need(file.stat().st_size==z['size_in_bytes'] and hashlib.file_digest(f,'sha256').hexdigest()==z['digest'][7:],'incorrect complete official ZIP')
            with zipfile.ZipFile(f) as archive:
                names=archive.namelist()
                need(len(names)==len(set(names)) and not {'rejected.txt','failure.txt'}.intersection(names) and
                     {'enrollment.json','complete.json','independent-screen.json'}<=set(names),'incorrect archive terminal')
                orig=json.loads(archive.read('independent-screen.json'));en=json.loads(archive.read('enrollment.json'));end=json.loads(archive.read('complete.json'))
        local=json.loads((args.readback_directory/f'worker-{pos}.json').read_bytes())
        need(local==orig and en['runner']==r['runner'] and (orig['run'],orig['head'],orig['position'],orig['boot'])==(args.run,head,pos,en['boot']) and en['attempt']==1 and
             end['qualified'] and end['boot']==orig['boot'] and end['head']==head and end['position']==pos,'independent original readback differs')
        workers.append(local)
    print(json.dumps({'originals':refs,'corrected_e_identity':competing,**reopen.decide(*workers,competing)},sort_keys=True))


if __name__=='__main__':main()
