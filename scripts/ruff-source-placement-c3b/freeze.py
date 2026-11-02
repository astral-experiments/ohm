"""Package the complete source commit only after independently supplied source bytes matched Git."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from source_packet import C2, PARENT, bind_packet, git, need, revision, sha, shape

ORIGINAL = HERE.parent / "ruff-source-placement"


def freeze(repo, candidate, packet_paths, dest):
    packet = shape(repo, candidate)
    bind_packet(packet, packet_paths)
    need(
        revision(repo, "HEAD") == candidate, "require a real checkout at the frozen product commit"
    )
    # The predecessor and all construction inputs stay exactly as signed and tested.
    original = json.loads((ORIGINAL / "registration.json").read_bytes())
    need(
        original["roles"]["P"]["revision"] == PARENT and original["roles"]["C"]["revision"] == C2,
        "wrong original matched factory",
    )
    names = sorted(set(original["changed_sources"]) | set(packet["changes"]))
    changes = {}
    for name in names:
        row = {}
        for role, rev in (("P", PARENT), ("C", candidate)):
            entry = git(repo, "ls-tree", rev, "--", name).decode().strip()
            if not entry:
                row[role] = None
                continue
            meta, got = entry.split("\t")
            mode, kind, oid = meta.split()
            need(
                mode == "100644" and kind == "blob" and name == got,
                "unexpected compiler source mode",
            )
            row[role] = oid
        if row["P"] != row["C"]:
            need(row["C"] is not None, "deleted native source input")
            changes[name] = row
    expected = [("M" if row["P"] else "A") + "\t" + name for name, row in changes.items()]
    actual = (
        git(repo, "diff", "--name-status", "--no-renames", PARENT, candidate).decode().splitlines()
    )
    need(actual == expected, "full product includes extra or missing changes")
    for name, oid in original["unchanged"].items():
        need(
            revision(repo, PARENT + ":" + name) == revision(repo, candidate + ":" + name) == oid,
            "changed prior source, constructor or library: " + name,
        )
    names = (
        "registration.json",
        "candidate.bundle",
        "candidate.partial.bundle",
        "source-packet.json",
    )
    need(
        all(not (dest / name).exists() for name in names),
        "refuse to replace a prior source registration",
    )
    partial = dest / "candidate.partial.bundle"
    subprocess.run(
        ["git", "-C", repo, "bundle", "create", "--version=2", partial, "HEAD", "^" + PARENT],
        check=True,
    )
    need(
        git(repo, "bundle", "list-heads", partial).decode().strip() == candidate + " HEAD",
        "wrong bundle root",
    )
    git(repo, "bundle", "verify", partial)
    need(0 < partial.stat().st_size < 4 << 20, "unexpectedly large source transport")
    reg = dict(original)
    reg.update(
        schema="ohm-osp-directional-source-v1",
        changed_sources=changes,
        roles={
            "P": original["roles"]["P"],
            "C": {
                "revision": candidate,
                "tree": packet["candidate_tree"],
                "compiler": packet["candidate_compiler_tree"],
            },
        },
        bundle={
            "bytes": partial.stat().st_size,
            "sha256": sha(partial.read_bytes()),
            "branch": "HEAD",
            "prerequisite": PARENT,
        },
        independent_C2_bundle=original["bundle"],
    )
    body = (json.dumps(packet, sort_keys=True, indent=2) + "\n").encode()
    reg["source_packet_sha256"] = sha(body)
    partial.rename(dest / "candidate.bundle")
    (dest / "source-packet.json").write_bytes(body)
    (dest / "registration.json").write_text(json.dumps(reg, sort_keys=True, indent=2) + "\n")
    print(candidate, packet["candidate_tree"], reg["bundle"]["sha256"], reg["source_packet_sha256"])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("checkout", type=Path)
    p.add_argument("candidate")
    p.add_argument(
        "--packet-file", action="append", nargs=2, required=True, metavar=("TRACKED_PATH", "FILE")
    )
    a = p.parse_args()
    need(
        len(a.packet_file) == 3 and len(dict(a.packet_file)) == 3,
        "requires three distinct independent files",
    )
    freeze(
        a.checkout.resolve(strict=True), a.candidate, {k: Path(v) for k, v in a.packet_file}, HERE
    )
