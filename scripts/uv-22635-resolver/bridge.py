"""Enroll the authentic existing production Rust pair and signed −22 Cargo on an isolated reviewed branch."""
from pathlib import Path
import os,sys
H=Path(__file__).resolve().parent
sys.path.insert(0,str(H));from model import require
sys.path.insert(0,str(H.parent/'uv-22635-discovery'))
import importlib.util
spec=importlib.util.spec_from_file_location('qualified_22635_bridge',H.parent/'uv-22635-discovery/bridge.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
def host():
    e=os.environ;w=Path(e['GITHUB_WORKSPACE']).resolve(strict=True);tmp=Path(e['RUNNER_TEMP']).resolve(strict=True)
    repo='astral-experiments/ohm';ref='refs/heads/charlie/codex-uv-22635-resolver-admission'
    require(__debug__ and e['GITHUB_REPOSITORY']==repo and e['GITHUB_EVENT_NAME']=='workflow_dispatch'and e['GITHUB_REF']==ref and e['GITHUB_RUN_ATTEMPT']=='1'and e['GITHUB_SHA']==e['REVIEWED_HEAD']and e['GITHUB_WORKFLOW_REF']==repo+'/.github/workflows/ci.yml@'+ref,'private branch/head/attempt guard')
    return w,tmp
base.host=host
if __name__=='__main__':require(sys.argv[1:]==['admit'],'admit only');base.admission()
