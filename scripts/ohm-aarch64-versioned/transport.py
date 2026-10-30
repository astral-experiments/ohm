"""Apply only the authenticated direct child to its already verified source tree."""
from pathlib import Path
import gzip
import hashlib
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SOURCES = json.loads((HERE / "sources.json").read_bytes())

def apply(project, checkout):
    expected = SOURCES[project]
    parent = expected["parent"]
    child = expected["source"]
    directory = HERE / (project + "-transport")
    commit = (directory / "commit").read_bytes()
    patch = gzip.decompress((directory / "source.patch.gz").read_bytes())
    def git(*args, data=None):
        return subprocess.check_output(["git", *args], cwd=checkout, input=data)
    assert git("rev-parse", "HEAD").decode().strip() == parent
    assert not git("status", "--porcelain=v1", "--untracked-files=no")
    assert hashlib.sha256(patch).hexdigest() == expected["patch_sha256"]
    assert commit.splitlines()[:2] == [("tree " + expected["tree"]).encode(), ("parent " + parent).encode()]
    assert git("hash-object", "-t", "commit", "--stdin", data=commit).decode().strip() == child
    git("apply", "--index", "--binary", "-", data=patch)
    assert git("write-tree").decode().strip() == expected["tree"]
    assert git("hash-object", "-w", "-t", "commit", "--stdin", data=commit).decode().strip() == child
    git("update-ref", "HEAD", child, parent)
    assert git("rev-parse", "HEAD").decode().strip() == child
    assert not git("status", "--porcelain=v1", "--untracked-files=no")
    assert set(git("diff", "--name-only", parent, child).decode().splitlines()) == set(expected["paths"])
    for name, blob in expected["paths"].items():
        assert git("hash-object", name).decode().strip() == blob
    return expected

if __name__ == "__main__":
    print(json.dumps(apply(sys.argv[1], Path(sys.argv[2])), sort_keys=True))
