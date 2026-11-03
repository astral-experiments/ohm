"""Recover the enrolled GitHub Actions originals one at a time in a fresh directory."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def fetch(assets,directory):
    directory.mkdir(parents=True,exist_ok=True)
    cfg=json.loads(assets.read_bytes());run=41660912896
    if cfg["run"]!=run or cfg["head"]!="6021d694d1c5d2e1a661e19b14d2990e7bb30834" or len(cfg["assets"])!=6:
        raise ValueError("wrong registered cohort")
    for slot in range(6):
        a,=[r for r in cfg["assets"] if r["name"]==f"matched-ty-ide-library-confirm-{run}-{slot}"]
        size=a["size_in_bytes"];sha=a["digest"].removeprefix("sha256:");target=directory/f"{slot}.zip"
        if not (0<size<1024*2**20 and a["workflow_run"]["id"]==run):
            raise ValueError("bad source archive registration")
        def verified(f):
            with f.open("rb")as body:
                return f.stat().st_size==size and hashlib.file_digest(body,"sha256").hexdigest()==sha
        if target.exists():
            if not verified(target):raise ValueError("different pre-existing original")
            continue
        if shutil.disk_usage(directory).free < 16*2**30+size:
            raise OSError("maintain 16 GiB reserve")
        with tempfile.TemporaryDirectory(dir=directory)as staging:
            part=Path(staging)/"original.zip"
            with part.open("xb")as out:
                subprocess.run(["gh-auto","api",f"repos/astral-experiments/ohm/actions/artifacts/{a['id']}/zip"],stdout=out,check=True,timeout=900)
            if not verified(part):raise ValueError("downloaded original failed its immutable custody check")
            part.rename(target)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--assets",type=Path,required=True);p.add_argument("directory",type=Path)
    a=p.parse_args();fetch(a.assets,a.directory)
