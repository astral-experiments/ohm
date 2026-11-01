"""Create the two source-bound inputs from a local, already-reviewed Git commit, once."""

from pathlib import Path
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import types

here = Path(__file__).resolve().parent


def freeze(repo, commit):
    if not re.fullmatch("[0-9a-f]{40}", commit):
        raise SystemExit("pass a complete source commit")
    git = lambda *args, data=None: subprocess.check_output(
        ["git", "-C", repo, *args],
        input=data,
        env=os.environ | {"GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "file"},
    )
    tree = git("rev-parse", commit + "^{tree}").decode().strip()
    ids = types.ModuleType("source_ids")
    ids.NEW, ids.TREE, ids.SOURCE_RECEIPT = commit, tree, None
    sys.modules["source_ids"] = ids
    spec = importlib.util.spec_from_file_location("enrollment_build_binding", here / "binding.py")
    binding = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(binding)
    source = binding.inspect_source(repo)
    object_ids = source["pack_objects"]
    pack = git(
        "pack-objects",
        "--window=0",
        "--threads=1",
        "--delta-base-offset",
        "--stdout",
        data=("\n".join(object_ids) + "\n").encode(),
    )
    obj = {
        "source": source,
        "pack": {"bytes": len(pack), "sha256": binding.digest(pack), "count": len(object_ids)},
    }
    receipt = (json.dumps(obj, sort_keys=True, indent=2) + "\n").encode()
    pins = (
        "# Frozen local source; regenerated only on an independent QA enrollment.\n"
        f"NEW = {commit!r}\nTREE = {tree!r}\nSOURCE_RECEIPT = {binding.digest(receipt)!r}\n"
    )
    media = [
        (here / "inputs/child.pack", pack),
        (here / "inputs/product.json", receipt),
        (here / "source_ids.py", pins.encode()),
    ]
    if not all(not p.exists() for p, _ in media) or len(pack) > 256 * 1024:
        raise ValueError("existing enrollment or unexpectedly large source")
    for path, body in media:
        with path.open("xb") as target:
            target.write(body)
    print(binding.digest(receipt), len(object_ids), len(pack))


if __name__ == "__main__":
    freeze(Path(sys.argv[1]).resolve(), sys.argv[2])
