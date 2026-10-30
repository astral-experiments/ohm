"""Authenticate both immutable enrollment attempts and independently verify the completed native artifacts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from native_proof import direct,named,provider
from verify_ruff import verify as ruff
from ruff_subjects import REG

GH_REPO='astral-experiments/ohm'
FIRST=(41083038179,'743fcbf759fef2c367210f7078742af76964e564')
FRESH=(41083924872,'17cb902d39dca47550a9f51b6a983f7c6c1fa645')
MODES=('signed','classic','aware','migrate-signed','migrate-classic','legacy-writer')
H=lambda b:hashlib.sha256(b).hexdigest()
def dump(path,v):
    data=(json.dumps(v,sort_keys=True,indent=2)+'\n').encode()
    if path.exists():assert path.read_bytes()==data
    else:path.open('xb').write(data)
    return H(data)
def fetch(gh,route):
    return json.loads(subprocess.check_output([gh,'api',f'repos/{GH_REPO}/'+route]))
def state(gh,run,head):
    task=fetch(gh,f'actions/runs/{run}')
    assert task['head_sha']==head and task['repository']['full_name']==GH_REPO and task['status']=='completed'
    jobs=fetch(gh,f'actions/runs/{run}/jobs?per_page=100')['jobs']
    jobs={v['name'].rsplit(' ',1)[1]:(v['conclusion'],v['id']) for v in jobs}
    files=fetch(gh,f'actions/runs/{run}/artifacts?per_page=100')['artifacts']
    out={}
    for f in files:
        assert not f['expired'] and f['workflow_run']['id']==run and f['workflow_run']['head_sha']==head and f['name'] not in out
        out[f['name']]=[f['id'],f['size_in_bytes'],f['digest'].removeprefix('sha256:')]
    return {'run':run,'QA':head,'workflow':task['conclusion'],'jobs':jobs,'artifacts':out}
def reopen(gh,row,operation):
    i,n,h=row;assert 0<n<768*2**20
    with tempfile.TemporaryFile() as f:
        subprocess.run([gh,'api',f'repos/{GH_REPO}/actions/artifacts/{i}/zip'],stdout=f,check=True)
        assert f.tell()==n;f.seek(0);assert hashlib.file_digest(f,'sha256').hexdigest()==h;f.seek(0)
        if operation is ruff:return ruff(f)
        with zipfile.ZipFile(f) as z:
            assert len(z.namelist())==len(set(z.namelist()))
            return operation(z)
def collect(gh,dest,first_only=False):
    dest.mkdir(parents=True,exist_ok=True)
    prior=state(gh,*FIRST)
    assert prior['workflow']=='failure'
    assert set(prior['jobs'])==set(MODES)|{'direct','named'} and set(prior['artifacts'])=={'gnu-versioned-native-'+n for n in prior['jobs']}
    previous=json.loads((HERE/'previous-depfile-readback.json').read_bytes())
    for mode in prior['jobs']:
        success=mode in ('named','direct');assert prior['jobs'][mode][0]==('success' if success else 'failure')
        entry=previous['two_native_terminals' if success else 'six_authentic_reader_replays'][mode]
        assert 'sha256:'+prior['artifacts']['gnu-versioned-native-'+mode][2]==entry['artifact']
    proof={}
    for mode,check in [('named',named),('direct',direct)]:
        data=reopen(gh,prior['artifacts']['gnu-versioned-native-'+mode],check);proof[mode]=dump(dest/(mode+'.json'),data)
    dump(dest/'initial-native-attempt.json',prior)
    if first_only:return
    fresh=state(gh,*FRESH);dump(dest/'fresh-native-state.json',fresh)
    modes=set(MODES)|{'ruff'};assert set(fresh['jobs'])==modes and set(fresh['artifacts'])=={'gnu-versioned-rerun-'+n for n in modes}
    for mode in sorted(modes):
        if fresh['jobs'][mode][0]!='success':continue
        check=ruff if mode=='ruff' else lambda z:provider(z,mode)
        data=reopen(gh,fresh['artifacts']['gnu-versioned-rerun-'+mode],check)
        proof[mode]=dump(dest/(mode+'.json'),data)
    assert fresh['workflow']=='success' and set(fresh['jobs'][m][0] for m in modes)=={'success'} and set(proof)==modes|{'direct','named'}
    rosters={n:json.loads((dest/(n+'.json')).read_bytes())['total_Cargo'] for n in MODES}
    assert rosters=={'signed':108,'classic':108,'aware':108,'migrate-signed':42,'migrate-classic':42,'legacy-writer':36}
    verify=json.loads((dest/'ruff.json').read_bytes())
    prov=dump(dest/'providers.json',{'source':REG['source'],'all_independent_readbacks':{k:v for k,v in proof.items() if k!='ruff'},'native_command_counts':rosters,
                                   'direct_compiler_commands':58,'named_collision_Cargo':12,'source_runs':[prior,fresh]})
    receipt={'run':FRESH[0],'QA':FRESH[1],'immutable_artifacts':fresh['artifacts'],'inherited_native_run':prior,
             'native_readback':proof['ruff'],'provider_readback':prov,'native_terminal':verify['terminal'],'actual_argc':verify['argv_count'],
             'cargo_elf':verify['cargo'],'native_members':proof,**{k:verify[k] for k in ('sources','drivers','namespace_positions','normalized_argv_sha256','reference')}}
    print('Native admissions:',rosters,'Ruff',receipt['sources'],dump(dest/'admissible-native.json',receipt))
if __name__=='__main__':
    assert len(sys.argv) in (3,4) and (len(sys.argv)==3 or sys.argv[3]=='--initial')
    collect(sys.argv[1],Path(sys.argv[2]),len(sys.argv)==4)
