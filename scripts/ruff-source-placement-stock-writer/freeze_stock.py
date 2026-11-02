"""Enroll the delivered original compiler bundle after its independent review."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stock_source as source

HERE = Path(__file__).resolve().parent


def dump(data):
    return (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()


def freeze(repo, subject, bundle, expected_bundle, reviewed, dest):
    old = json.loads((source.GUARDED_DIR / "registration.json").read_bytes())
    previous = json.loads((source.GUARDED_DIR / "protocol.json").read_bytes())
    source.need(
        old["roles"]["C"]["revision"] == source.GUARDED
        and old["roles"]["P"]["revision"] == source.PARENT,
        "incorrect original source construction",
    )
    source.need(
        bundle.is_file() and not bundle.is_symlink() and 0 < bundle.stat().st_size < 4 << 20,
        "missing or unbounded original source transport",
    )
    data = bundle.read_bytes()
    commitment = source.bundle_header(data, subject)
    source.need(commitment["sha256"] == expected_bundle, "different independent transport digest")
    proof = source.shape(repo, subject, reviewed)
    spec = list(
        source.git(repo, "diff", "--name-only", "--no-renames", "-z", source.PARENT, subject).split(
            b"\0"
        )
    )[:-1]
    changes = {}
    for rawpath in spec:
        path = rawpath.decode()
        source.need(
            path.startswith("compiler/") and ".." not in Path(path).parts,
            "outside native compiler delta",
        )
        row = {}
        for role, revision in (("P", source.PARENT), ("C", subject)):
            rec = source.git(repo, "ls-tree", revision, "--", path)
            if not rec:
                row[role] = None
            else:
                mode, kind, value = rec.rstrip(b"\n").split(b" ", 2)
                oid, name = value.split(b"\t", 1)
                source.need(
                    mode == b"100644" and kind == b"blob" and name == rawpath,
                    "unexpected changed source entry",
                )
                row[role] = oid.decode()
        source.need(row["C"] and row["P"] != row["C"], "unexpected removal or unchanged source")
        changes[path] = row
    source.need(
        set(changes) == set(old["changed_sources"]) | set(reviewed),
        "unexpected or reverted original guarded source delta",
    )
    for path, oid in old["unchanged"].items():
        source.need(
            source.oid(repo, subject + ":" + path) == oid, "an inherited construction input changed"
        )
    proof_bytes = dump(proof)
    reg = old | {
        "schema": "ohm-osp-explicit-restore-stock-writer-1",
        "changed_sources": changes,
        "roles": {
            "P": old["roles"]["P"],
            "C": {"revision": subject, "tree": proof["tree"], "compiler": proof["compiler"]},
        },
        "bundle": commitment,
        "guarded_bundle": old["bundle"],
        "source_packet_sha256": sha256(proof_bytes).hexdigest(),
    }
    trees = previous["inherited_trees"] | {
        "ruff-source-placement-c3b": source.oid(
            HERE, "ece4528e7e0e2d35a8fb4072fcb54ec7a245f5a8:scripts/ruff-source-placement-c3b"
        ),
    }
    protocol = {
        "schema": "stock-writer-native-factory-1",
        "parent": source.PARENT,
        "prior": source.GUARDED,
        "source": subject,
        "source_packet_sha256": reg["source_packet_sha256"],
        "complete_tree": proof["tree"],
        "source_mode": "One complete native P/selected stage1 plus docs; existing C3b remains a third independent physical kit.",
        "inherited_trees": trees,
        "prior_factory": {
            "run": 41492092582,
            "qa": "b49a9bb7ff0ce1e98f11b20014583b25113f5fd9",
            "artifact": 13165297730,
            "bytes": 204866679,
            "sha256": "6217d1ec9a6bd15ef1df853a9cfe5934ada3a6cba21c78b106e6717a0565b72f",
        },
        "independent_three_way": {
            "run": 41501796384,
            "source": "ece4528e7e0e2d35a8fb4072fcb54ec7a245f5a8",
            "observation_overlap": 0,
        },
    }
    members = {
        "candidate.bundle": data,
        "source-packet.json": proof_bytes,
        "registration.json": dump(reg),
        "protocol.json": dump(protocol),
    }
    source.need(
        all(not (dest / n).exists() for n in members), "refusing to replace a frozen registration"
    )
    for name, blob in members.items():
        with (dest / name).open("xb") as out:
            out.write(blob)
    source.binding(dest)
    return {k: sha256(v).hexdigest() for k, v in members.items()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("commit")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("bundle_sha256")
    parser.add_argument("reviewed_file_sha256", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            freeze(
                args.repo.resolve(strict=True),
                args.commit,
                args.bundle.resolve(strict=True),
                args.bundle_sha256,
                json.loads(args.reviewed_file_sha256.read_bytes()),
                HERE,
            ),
            sort_keys=True,
        )
    )
