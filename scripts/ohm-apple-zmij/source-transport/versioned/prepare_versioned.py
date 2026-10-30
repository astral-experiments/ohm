"""Recover the exact private QA commits from their authenticated parents and frozen content."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

FILES = Path(__file__).resolve().parent
SOURCES = json.loads((FILES / "subjects.json").read_bytes())
def git(repo, *argv, data=None):
    return subprocess.check_output(["git", "-C", str(repo), *argv], input=data)
def text(repo, *argv):
    return git(repo, *argv).decode().strip()
def prepare(repo, role):
    expected = SOURCES[role]
    assert not text(repo, "diff", "--name-only") and not text(repo, "diff", "--cached", "--name-only")
    git(repo, "checkout", "--quiet", "--detach", expected["base"])
    patch = gzip.decompress((FILES / (role + ".patch.gz")).read_bytes())
    raw = (FILES / (role + ".commit")).read_bytes()
    assert hashlib.sha256(patch).hexdigest() == expected["patch_sha256"]
    assert hashlib.sha256(raw).hexdigest() == expected["commit_sha256"]
    git(repo, "apply", "--index", "-", data=patch)
    assert text(repo, "diff", "--cached", "--name-only").splitlines() == sorted(expected["files"])
    assert text(repo, "write-tree") == expected["tree"]
    assert git(repo, "hash-object", "-t", "commit", "-w", "--stdin", data=raw).decode().strip() == expected["source"]
    rev = expected["source"]
    assert text(repo,"rev-parse",rev+"^")==expected["base"] and text(repo,"rev-parse",rev+"^{tree}")==expected["tree"]
    for name,blob in expected["files"].items():
        assert text(repo, "rev-parse", rev+":"+name)==blob
    git(repo,"update-ref","refs/heads/qa-versioned-"+role,rev)
    git(repo,"checkout","--quiet","--detach",rev)
    assert text(repo,"write-tree")==expected["tree"] and not text(repo,"status","--porcelain","--untracked-files=no")
    return expected

def materialize(repo, kind):
    if kind == "rust":
        assert text(repo,"rev-parse","HEAD")==SOURCES["rust-objc"]["base"]
        roles=("rust-parent","rust-objc")
    else:
        assert kind=="cargo" and text(repo,"rev-parse","HEAD")==SOURCES["cargo-gnu"]["base"]
        roles=("cargo-gnu","cargo-apple")
    result=[prepare(repo,r) for r in roles]
    if kind=="rust":
        p,c=result
        assert p["files"]["compiler/rustc_interface/src/passes.rs"]==c["files"]["compiler/rustc_interface/src/passes.rs"]
        assert git(repo,"diff","--name-only",p["source"],c["source"])==git(repo,"diff","--name-only",p["base"],c["base"])
        assert text(repo,"rev-parse",p["source"]+":library")==text(repo,"rev-parse",c["source"]+":library")
    return result
if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("kind",choices=("rust","cargo"));ap.add_argument("repo",type=Path);args=ap.parse_args()
    print(json.dumps(materialize(args.repo.resolve(),args.kind),sort_keys=True))
