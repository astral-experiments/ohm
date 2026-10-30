"""Materialize precisely one reviewed compiler patch on the enrolled Ohm parent."""

import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PARENT = "82911b516fb35608fd70ada4deb6f8429277f410"
CHILD = "3de892a47171543b624e0d360d6d532f2da815f7"
TREE = "e5252d9b4db410b197b45fb7d599593cde3acf82"
EXPECTED = {"candidate.patch":"871a40eb48f695c1f9bc667f1874b3b60ef2754ac3eb1bccadd1f4683f3fa7b0",
            "candidate.commit":"b9dfd68f5c868f4e427d821673a574be4864cde8a32ac843ec6fc212f1642acf"}


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
    git("update-ref","refs/heads/qa-asm-free-cgu",CHILD)
    git("checkout","--quiet","--detach",CHILD)
    assert git("diff","--name-only")==git("diff","--cached","--name-only")==""
    print(json.dumps({"parent":PARENT,"child":CHILD,"tree":TREE,"inputs":EXPECTED},sort_keys=True))


if __name__ == "__main__":
    materialize(Path(sys.argv[1]).resolve(strict=True))
