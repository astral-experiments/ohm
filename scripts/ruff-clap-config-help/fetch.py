"""Authenticate the Linux candidate pack from the release workflow before publication."""
import hashlib
import json
from pathlib import Path,PurePosixPath
import shutil
import stat
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parent
GH=["gh","api"]
O="repos/astral-experiments/ohm"
RUN=41691269002
ID=13265019946
HEAD="8f25c47ff9e7c4ab2f22a1cad0638a26c7e26e1c"
NAME="ohm-1.99.0-24-x86_64-unknown-linux-gnu"
HASH="37cadbdaeaf2250d05a079e0be2b287d11dcd6d206e2158700b113148e0b0c5c"
def sha(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def api(path):return json.loads(subprocess.check_output([*GH,O+path]))
run=api(f"/actions/runs/{RUN}")
assert run["head_sha"]==HEAD and run["head_branch"]=="main" and run["run_attempt"]==1
asset=api(f"/actions/artifacts/{ID}")
assert asset["name"]==NAME and asset["workflow_run"]["id"]==RUN and asset["workflow_run"]["head_sha"]==HEAD
assert asset["digest"]=="sha256:"+HASH and asset["size_in_bytes"]==357024726 and not asset["expired"]
archive=ROOT/"original-linux.zip"
if not archive.exists():
    tmp=ROOT/"original-linux.download"
    with tmp.open("xb") as f:
        subprocess.run([*GH,O+f"/actions/artifacts/{ID}/zip"],stdout=f,check=True)
    assert tmp.stat().st_size==asset["size_in_bytes"] and sha(tmp)==HASH
    tmp.rename(archive)
assert archive.stat().st_size==asset["size_in_bytes"] and sha(archive)==HASH
files={}
with zipfile.ZipFile(archive) as z:
    entries=z.infolist()
    assert len(entries)==len(set(i.filename for i in entries))
    for entry in entries:
        path=PurePosixPath(entry.filename)
        assert not path.is_absolute() and ".." not in path.parts and not stat.S_ISLNK(entry.external_attr>>16)
        if entry.is_dir():continue
        o=ROOT/"packed"/path
        o.parent.mkdir(parents=True,exist_ok=True)
        if not o.exists():
            with z.open(entry) as src,o.open("xb") as target:shutil.copyfileobj(src,target)
        assert o.stat().st_size==entry.file_size
        files[entry.filename]={"bytes":entry.file_size,"sha256":sha(o)}
(ROOT/"intake.json").write_text(json.dumps({"run":RUN,"head":HEAD,"id":ID,"zip_sha256":HASH,
                                          "zip_bytes":archive.stat().st_size,"files":files},indent=2)+"\n")
print(json.dumps(files))
