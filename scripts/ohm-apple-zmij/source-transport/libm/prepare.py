"""Materialize precisely one reviewed compiler patch on the enrolled Ohm parent."""

import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PARENT = "82911b516fb35608fd70ada4deb6f8429277f410"
CHILD = "3dd3afd368045b5158dbb77972a164a97f7f4927"
TREE = "a048dedc1e7fd1885faabe7848da1b551ca97285"
EXPECTED = {"candidate.patch":"1045e8f35925750e26690b7dfed1e0c87046b01435725a54952b241eb57f19f6",
            "candidate.commit":"22bb8829c6a2fc4e84f7763a14442588930d5bcbf45d2e3e7a99f35c605f16af"}


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
    git("update-ref","refs/heads/qa-libm-candidate",CHILD)
    git("checkout","--quiet","--detach",CHILD)
    assert git("diff","--name-only")==git("diff","--cached","--name-only")==""
    print(json.dumps({"parent":PARENT,"child":CHILD,"tree":TREE,"inputs":EXPECTED},sort_keys=True))


if __name__ == "__main__":
    materialize(Path(sys.argv[1]).resolve(strict=True))
