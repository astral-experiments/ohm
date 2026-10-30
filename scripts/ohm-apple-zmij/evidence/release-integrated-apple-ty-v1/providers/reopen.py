"""Reproduce the compact observations from the complete native GitHub artifact."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from project import project

def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--b3sum", default=shutil.which("b3sum"), help="BLAKE3 command for Cargo's LNK1 integrity check")
    args = parser.parse_args()
    if not args.b3sum:
        parser.error("b3sum is required to check the original LNK1 records")
    observation = (HERE / "observations.json.gz").read_bytes()
    anchor = json.loads(gzip.decompress(observation))["archive"]
    assert args.archive.stat().st_size == anchor["bytes"]
    with args.archive.open("rb") as archive:
        assert hashlib.file_digest(archive, "sha256").hexdigest() == anchor["sha256"]
    inner = hashlib.sha256()
    with ZipFile(args.archive) as archive:
        members = [i for i in archive.infolist() if not i.is_dir()]
        assert len({i.filename for i in members}) == len(members) == anchor["members"]
        for entry in sorted(members, key=lambda i: i.filename):
            path = PurePosixPath(entry.filename)
            assert not path.is_absolute() and ".." not in path.parts
            with archive.open(entry) as f:
                digest = hashlib.file_digest(f, "sha256").hexdigest()
            inner.update((digest + "  " + entry.filename + "\n").encode())
    assert inner.hexdigest() == "710e7d322fb1b5b693e88ddbd7b7c523078f00701bc584efe4e1b7949e58c355"
    with tempfile.TemporaryDirectory() as scratch:
        dest = Path(scratch)
        for script, arguments in (
            ("matrix.py", [args.archive, dest]),
            ("symbols.py", [args.archive, dest, "--b3sum", args.b3sum]),
            ("release_checks.py", ["legacy", args.archive, dest / "legacy.json.gz", "--b3sum", args.b3sum]),
        ):
            subprocess.run([sys.executable, "-IB", HERE / "offline" / script, *arguments], check=True)
        assert project(dest) == observation
    print(f'Reopened {len(members):,} originals and reproduced the {len(observation):,}-byte projection.')

if __name__ == "__main__":
    run()
