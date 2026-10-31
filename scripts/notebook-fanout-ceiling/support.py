"""Authenticate and reuse the two unchanged native experimental harnesses."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from contract import require, FEATURELESS, COLLECTOR


def hashfile(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def git(repo, *cmd):
    return subprocess.check_output(["git", "-C", repo, *cmd], text=True).strip()


def load_modules(base, collector, private, verify_git=True):
    manifest = json.loads((HERE / "sources.json").read_bytes())
    if verify_git:
        require(
            git(base, "rev-parse", "HEAD") == FEATURELESS
            and git(collector, "rev-parse", "HEAD") == COLLECTOR,
            "wrong public source release",
        )
    for label, directory in [("featureless", base), ("counter", collector)]:
        for name, digest in manifest[label].items():
            require(hashfile(directory / name) == digest, (name, "frozen original changed"))
    private.mkdir()
    for path in manifest["counter"]:
        shutil.copyfile(collector / path, private / Path(path).name)
    patch = HERE / "ledger.patch"
    subprocess.run(["git", "apply", "--no-index", "--check", patch], cwd=private, check=True)
    subprocess.run(["git", "apply", "--no-index", patch], cwd=private, check=True)
    require(
        hashfile(private / "topology.py") == manifest["joined_topology"], "topology adapter differs"
    )
    sys.path[:0] = [
        str(base / "scripts/featureless-e2e"),
        str(base / "scripts/mixed-generics-ruff"),
        str(private),
    ]
    import study, pmu, topology

    require(
        Path(study.__file__).resolve().parent == base / "scripts/featureless-e2e"
        and Path(pmu.__file__).resolve().parent == private
        and Path(topology.__file__).resolve().parent == private,
        "ambiguous Python module",
    )
    return study, pmu, topology
