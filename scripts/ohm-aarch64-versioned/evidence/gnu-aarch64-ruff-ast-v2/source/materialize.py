"""Rebuild the measured product Git objects in a new bare repository using a read-only public base."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess


def git(repository, *args, data=None):
    return subprocess.check_output(
        ["git", "--no-lazy-fetch", "-C", str(repository), *args], input=data
    ).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", choices=("rust", "cargo"))
    parser.add_argument("public_repository", type=Path)
    parser.add_argument("fresh_bare_repository", type=Path)
    args = parser.parse_args()

    donor = args.public_repository.resolve(strict=True)
    dest = args.fresh_bare_repository.resolve()
    assert not dest.exists() and dest.parent.is_dir() and donor not in dest.parents
    base_objects = Path(os.fsdecode(git(donor, "rev-parse", "--path-format=absolute", "--git-path", "objects")))
    assert base_objects.is_dir() and "\n" not in str(base_objects)
    root = Path(__file__).resolve().parent / "transport"
    history = json.loads((root / "history.json").read_bytes())
    roles = ("N", "M-old", "V") if args.project == "rust" else ("reader",)
    base = history[roles[0]]["parent"]
    assert git(donor, "rev-parse", "--verify", base + "^{commit}").decode() == base

    subprocess.run(["git", "init", "--quiet", "--bare", "--template=", str(dest)], check=True)
    (dest / "objects/info/alternates").write_text(str(base_objects) + "\n")
    git(dest, "read-tree", base)
    previous = base
    for role in roles:
        entry = history[role]
        patch = gzip.decompress((root / role / "source.patch.gz").read_bytes())
        commit = (root / role / "commit").read_bytes()
        assert entry["project"] == args.project and entry["parent"] == previous
        assert hashlib.sha256(patch).hexdigest() == entry["patch_sha256"]
        assert commit.splitlines()[:2] == [
            ("tree " + entry["tree"]).encode(), ("parent " + previous).encode(),
        ]
        git(dest, "apply", "--cached", "--binary", "-", data=patch)
        assert git(dest, "write-tree").decode() == entry["tree"]
        assert git(dest, "hash-object", "-w", "-t", "commit", "--stdin", data=commit).decode() == entry["source"]
        git(dest, "update-ref", "refs/heads/" + role, entry["source"], "0" * 40)
        previous = entry["source"]
        print(f"{role} {entry['source']} {entry['tree']}")


if __name__ == "__main__":
    main()
