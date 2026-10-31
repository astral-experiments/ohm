"""Reopen the historical Ruff trees and all locked dependency hashes from Git objects."""
import hashlib
import os
from pathlib import Path
import subprocess
import tomllib

from replay_metrics import REVS, need


TREES = {"A": "2b61306d708a211b3725c8d920e7590be6da41ad",
         "B": "97ca36909f1ae8fa028b2c1f48f452fbdcdbbd4c"}
LOCK = "839edc8250480bb523619b8d24bd57176a6e1f57c152cca85c5adc61ea5f94eb"
FILE = "crates/ruff_python_parser/src/lib.rs"
RUFF = Path("/home/dev-user/code/oss/ruff")


def source(repo=RUFF):
    def git(*args):
        return subprocess.check_output(["git", "--no-optional-locks", "-C", repo, *args],
                                       env=os.environ | {"GIT_NO_LAZY_FETCH": "1"})
    need(git("rev-parse", REVS["B"] + "^").decode().strip() == REVS["A"], "Ruff historical parent")
    trees = {role: git("rev-parse", rev + "^{tree}").decode().strip() for role, rev in REVS.items()}
    changes = git("diff", "--name-status", REVS["A"], REVS["B"]).decode().splitlines()
    need(trees == TREES and len(changes) == 169, "Ruff historical tree/transition")
    locks = [git("show", rev + ":Cargo.lock") for rev in REVS.values()]
    need(locks[0] == locks[1] and hashlib.sha256(locks[0]).hexdigest() == LOCK, "Ruff dependency lock")
    pins = {r["name"] + "-" + r["version"] + ".crate": r["checksum"]
            for r in tomllib.loads(locks[0].decode())["package"] if "checksum" in r}
    need(len(pins) == 505 and all(len(v) == 64 for v in pins.values()), "complete historical registry")
    digests = {role: hashlib.sha256(git("show", rev + ":" + FILE)).hexdigest()
               for role, rev in REVS.items()}
    return {"commits": REVS, "trees": trees, "changed": changes, "archives": pins, "lock": LOCK}, digests
