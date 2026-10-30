"""Materialize precisely one reviewed compiler patch on the enrolled Ohm parent."""

import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PARENT = "3de892a47171543b624e0d360d6d532f2da815f7"
CHILD = "919199fc9c2b05ee49ccf7da4d53ec68ef117e5f"
TREE = "5ceae04746c68811646e38a1e1f3e3f1c1e2bcca"
EXPECTED = {"candidate.patch":"8b311ec06dfbe118770d79a5bf3ed171a86b9d73c19d3560ab02c13fc5953ad0",
            "candidate.commit":"8a0e1a8b3624dd0b32f2b5d0208483511c306aaac796c8d55d1859898f81f163"}


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
    git("update-ref","refs/heads/qa-asm-free-cgu-external-inputs",CHILD)
    git("checkout","--quiet","--detach",CHILD)
    assert git("diff","--name-only")==git("diff","--cached","--name-only")==""
    print(json.dumps({"parent":PARENT,"child":CHILD,"tree":TREE,"inputs":EXPECTED},sort_keys=True))


if __name__ == "__main__":
    materialize(Path(sys.argv[1]).resolve(strict=True))
