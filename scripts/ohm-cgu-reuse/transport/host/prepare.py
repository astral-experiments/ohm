"""Materialize precisely one reviewed compiler patch on the enrolled Ohm parent."""

import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PARENT = "919199fc9c2b05ee49ccf7da4d53ec68ef117e5f"
CHILD = "f69f7b7cf6de57972b310900decfac2d3a0c6fd6"
TREE = "8bccbaf63ee04a8eff02fcbede57a4512633c530"
EXPECTED = {"candidate.patch":"5310ecc10c774c04b95c779971332c59f3a37e2147e1ca3b774ca41ca9c6aa8b",
            "candidate.commit":"3174c8f094c523d17e6eee46b52f3af262bace623eafa4e20f392d9a5fd217e1"}


def materialize(repo):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args],text=True).strip()
    patch = gzip.decompress((HERE/"candidate.patch.gz").read_bytes())
    assert hashlib.sha256(patch).hexdigest()==EXPECTED["candidate.patch"]
    assert hashlib.sha256((HERE/"candidate.commit").read_bytes()).hexdigest()==EXPECTED["candidate.commit"]
    assert git("rev-parse","HEAD")==PARENT and git("diff","--name-only")==git("diff","--cached","--name-only")==""
    subprocess.run(["git", "-C", str(repo), "apply", "--index", "-"], input=patch, check=True)
    assert git("write-tree")==TREE
    assert git("hash-object","-t","commit","-w",str(HERE/"candidate.commit"))==CHILD
    assert git("rev-parse",CHILD+"^")==PARENT and git("rev-parse",CHILD+"^{tree}")==TREE
    git("update-ref","refs/heads/qa-asm-free-cgu-cpu-inputs",CHILD)
    git("checkout","--quiet","--detach",CHILD)
    assert git("diff","--name-only")==git("diff","--cached","--name-only")==""
    print(json.dumps({"parent":PARENT,"child":CHILD,"tree":TREE,"inputs":EXPECTED},sort_keys=True))


if __name__ == "__main__":
    materialize(Path(sys.argv[1]).resolve(strict=True))
