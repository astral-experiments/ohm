"""Run the physical native and hardware readback on the two authenticated original Ruff jobs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = "repos/astral-experiments/ohm/actions/artifacts/"

def download(expected, path):
    artifact, run, head, tag, size, digest = expected
    if not (isinstance(artifact,int) and isinstance(run,int) and 0 < size <= 600*2**20 and len(digest) == 64):
        raise ValueError("unexpected artifact identity or size")
    api=REPO+str(artifact)
    metadata=json.loads(subprocess.check_output(["gh","api",api]))
    if not (metadata["id"]==artifact and metadata["workflow_run"]["id"]==run and metadata["workflow_run"]["head_sha"]==head
            and metadata["name"]==tag and metadata["size_in_bytes"]==size and metadata["digest"]=="sha256:"+digest):
        raise ValueError("different GitHub source, role, or content")
    with path.open("xb") as f:
        subprocess.run(["gh","api",api+"/zip"],stdout=f,check=True)
    with path.open("rb") as f:
        if path.stat().st_size!=size or hashlib.file_digest(f,"sha256").hexdigest()!=digest:
            raise ValueError("different downloaded artifact bytes")
    return digest

def main():
    binding=json.loads((HERE/"physical-bindings.json").read_bytes())
    temporary=Path(os.environ["RUNNER_TEMP"])/"owner-reopen"
    temporary.mkdir()
    output=temporary/"verified";output.mkdir()
    if set(binding)!={"29697","29604"}:
        raise ValueError("different declared edit set")
    for case,row in sorted(binding.items()):
        directory=temporary/case;directory.mkdir()
        if shutil.disk_usage(directory).free<=15*2**30:
            raise ValueError("reader disk reserve")
        archive=directory/"ordinary.zip";digest=download(row["ordinary"],archive)
        args=[sys.executable,"-IB",HERE.parent/"reopen.py",archive,"--case",case,"--sha256",digest,
              "--work",directory/"native-check","--output",output/(case+".json")]
        if "diagnostic" in row:
            trace=directory/"lifetimes.zip";trace_sha=download(row["diagnostic"],trace)
            args.extend(["--diagnostic",trace,"--diagnostic-sha256",trace_sha])
        subprocess.run(args,check=True)

if __name__=="__main__":
    main()
