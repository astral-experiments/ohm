"""Bind the immutable source and all genuine entrypoints before touching native measurements."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
HERE=Path(__file__).resolve().parent
scope="charlie/codex-20992-production-build-guard"
manifest=HERE/"SHA256SUMS"
def sha(p):
    with p.open("rb")as f:return hashlib.file_digest(f,"sha256").hexdigest()
def main():
    assert __debug__ and not sys.flags.optimize
    rows={}
    for line in manifest.read_text().splitlines():
        digest,name=line.split("  ");assert len(digest)==64 and not Path(name).is_absolute()and ".."not in Path(name).parts and name not in rows
        rows[name]=digest
    present={x.relative_to(HERE).as_posix() for x in HERE.rglob("*") if x.is_file() and x!=manifest}
    assert present==rows.keys() and all(sha(HERE/n)==h for n,h in rows.items())
    assert sha(HERE/"protocol.json")=="d9f0648ba06a9623a55f1b1e1f11100a6d9fa20d808d38c5b9479669001094e9"
    bindings=json.loads((HERE/"physical-roles.json").read_bytes())
    assert set(bindings["roles"])=={"parent","candidate"} and len(bindings["reader_trees"])>=3
    if len(sys.argv)>1 and sys.argv[1]=="sources-only":return
    e=os.environ
    assert e["GITHUB_REPOSITORY"]=="astral-experiments/ohm"and e["GITHUB_EVENT_NAME"]=="workflow_dispatch"and e["GITHUB_REF"]=="refs/heads/"+scope and e["GITHUB_RUN_ATTEMPT"]=="1" and e["INPUT_SOURCE"]==e["GITHUB_SHA"]
    check=Path(e["GITHUB_WORKSPACE"])/"measure"
    assert subprocess.check_output(["git","-C",check,"rev-parse","HEAD"],text=True).strip()==e["GITHUB_SHA"]
    assert not subprocess.check_output(["git","-C",check,"status","--porcelain","--untracked-files=no"])
if __name__=="__main__":main()

