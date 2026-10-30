"""Reopen every complete hosted registered block in chronological assignment order."""
import hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import reopen
repo='astral-experiments/ohm'
def get(path):
    return json.loads(subprocess.check_output(['gh','api','repos/'+repo+'/'+path]))
def main():
    action=os.environ['GITHUB_RUN_ID'];code=os.environ['GITHUB_SHA']
    run=get('actions/runs/'+action)
    assert run['head_sha']==code and run['repository']['full_name']==repo
    folder=Path(os.environ['RUNNER_TEMP'])/'gnu-heldout-review';folder.mkdir()
    result=folder/'output';result.mkdir()
    rows=[]
    roster={a['name']:a for a in get('actions/runs/'+action+'/artifacts?per_page=100')['artifacts']}
    assert set(roster)=={'gnu-full-ruff-block-'+n for n in reopen.schedule},list(roster)
    for number in sorted(reopen.schedule):
        a=roster['gnu-full-ruff-block-'+number]
        assert not a['expired'] and a['workflow_run']['head_sha']==code and a['workflow_run']['id']==int(action)
        name=folder/('enrolled-'+number+'.zip')
        assert 0<a['size_in_bytes']<768*2**20 and shutil.disk_usage(folder).free>16*2**30+a['size_in_bytes']
        with name.open('xb') as dst:
            subprocess.run(['gh','api','repos/'+repo+'/actions/artifacts/'+str(a['id'])+'/zip'],stdout=dst,check=True)
        assert name.stat().st_size==a['size_in_bytes']
        one=reopen.reopen(name,number,code,a['digest'].removeprefix('sha256:'))
        rows.append(one);reopen.dump(one,result/('block-'+number+'.json'))
        name.unlink()
    final=reopen.analyze(rows);reopen.dump(final,result/'analysis.json')
    assert final['all_six_in_all_blocks_above_two'],'genuine numerical nonqualification, retained in result'
if __name__=='__main__':main()
