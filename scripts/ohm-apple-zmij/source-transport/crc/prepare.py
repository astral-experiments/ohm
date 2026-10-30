"""Materialize precisely one reviewed compiler patch on the enrolled Ohm parent."""

import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PARENT = "444c0273a2e2bc0b161e988d43c882349bc2d7a6"
CHILD = "82911b516fb35608fd70ada4deb6f8429277f410"
TREE = "3fa42b8f3381f4b4cfaf24d3a2391e195448fe94"
EXPECTED = {"candidate.patch":"540ce4f94f5a04634a17edb6bc42391322203c8fd86d7adb5932cd7d5156b060",
            "candidate.commit":"f63b32b8b2290efdef0704fd8406782fab7cec55e6f676d6c2a1a8df1cff962a"}


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
    git("update-ref","refs/heads/qa-crc-candidate",CHILD)
    git("checkout","--quiet","--detach",CHILD)
    assert git("diff","--name-only")==git("diff","--cached","--name-only")==""
    print(json.dumps({"parent":PARENT,"child":CHILD,"tree":TREE,"inputs":EXPECTED},sort_keys=True))


if __name__ == "__main__":
    materialize(Path(sys.argv[1]).resolve(strict=True))
