"""On the pilot worker, reconstruct the separate signed discovery before artifact upload."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from reopen import AUTH,check,run
import shutil,tempfile,zipfile
root=Path(os.environ["RUNNER_TEMP"])/"ohm-foreign-join";proof=root/"published"
env=dict(os.environ,GH_TOKEN=os.environ["OHM_SDK_READ_TOKEN"])
def gh(path,**kw):return subprocess.run(["gh","api","repos/astral-experiments/ohm/"+path],env=env,check=True,**kw)
n=13221544253;v=json.loads(gh(f"actions/artifacts/{n}",capture_output=True).stdout)
check(v["id"]==n and v["digest"]=="sha256:"+AUTH and v["size_in_bytes"]==149582004 and v["workflow_run"]["id"]==41617340678 and not v["expired"],"unregistered signed source profile")
check(shutil.disk_usage(root).free > 15*2**30 + 160*2**20,"insufficient signed replay disk reserve")
with tempfile.TemporaryDirectory(dir=root)as d:
    tmp=Path(d);path=tmp/"original.zip"
    with path.open("xb")as stream:gh(f"actions/artifacts/{n}/zip",stdout=stream)
    with path.open("rb")as stream:check(path.stat().st_size==v["size_in_bytes"] and hashlib.file_digest(stream,"sha256").hexdigest()==AUTH,"wrong signed ZIP")
    with zipfile.ZipFile(path)as z:state=run(z,tmp)
(proof/"signed-discovery-reopened.json").write_text(json.dumps(state,sort_keys=True,indent=2)+"\n")
