"""Use the immutable #337/C2 construction and physically verify the entire guarded C3b commit."""

import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from source_packet import C2, ORIGINAL_QA, PARENT, QA_BRANCH, revision, shape

ORIGINAL = HERE.parent / "ruff-source-placement"
sys.path.insert(0, str(ORIGINAL))
import common
import factory as matched


def fetch(repo, path, rev, commitment):
    common.need(
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_size == commitment["bytes"]
        and common.sha(path) == commitment["sha256"],
        "unbound compiler source transport",
    )
    common.need(
        common.git(repo, "bundle", "list-heads", str(path)) == rev + " HEAD", "wrong bundle head"
    )
    common.git(repo, "bundle", "verify", str(path))
    common.git(repo, "fetch", "--no-tags", "--no-recurse-submodules", str(path), "HEAD")
    common.need(revision(repo, "FETCH_HEAD") == rev, "wrong materialized Git commit")


def verified_sources(rust, reg):
    # Start with the complete source-verified #337 constructor. The reference C2
    # transport authenticates the three-file delta even when C3b is a sibling of C2.
    matched.previous.bundle(rust)
    common.need(
        revision(rust, "FETCH_HEAD") == PARENT
        and common.sha(common.LEGACY / "candidate.bundle") == reg["previous_bundle_sha256"],
        "wrong first source segment",
    )
    fetch(rust, ORIGINAL / "candidate.bundle", C2, reg["independent_C2_bundle"])
    candidate = reg["roles"]["C"]["revision"]
    fetch(rust, HERE / "candidate.bundle", candidate, reg["bundle"])
    source = shape(rust, candidate)
    frozen = HERE / "source-packet.json"
    common.need(
        common.sha(frozen) == reg["source_packet_sha256"]
        and source == json.loads(frozen.read_bytes()),
        "fresh full source, true ancestry or three physical files differ from the frozen packet",
    )
    changes = reg["changed_sources"]
    common.need(
        common.git(rust, "diff", "--name-status", "--no-renames", PARENT, candidate).splitlines()
        == [("M" if row["P"] else "A") + "\t" + path for path, row in sorted(changes.items())],
        "unregistered compiler edit",
    )
    for role, row in reg["roles"].items():
        rev = row["revision"]
        common.need(
            [revision(rust, rev + "^{tree}"), revision(rust, rev + ":compiler")]
            == [row["tree"], row["compiler"]],
            "different complete compiler tree",
        )
        for path, objects in changes.items():
            oid = objects[role]
            expected = "100644 blob " + oid + "\t" + path if oid else ""
            common.need(
                common.git(rust, "ls-tree", rev, "--", path) == expected,
                "altered source blob: " + path,
            )
        common.need(
            all(revision(rust, rev + ":" + key) == sha for key, sha in reg["unchanged"].items()),
            "different coalescer, LLVM, std, Cargo or bootstrap",
        )
    logs = Path(os.environ["RUNNER_TEMP"]) / "ohm-branch-object-qa/logs"
    common.save(logs / "c3b-actual-source.json", source)


def main():
    # The historical constructor code and all of its native tracing remain
    # unchanged. Only the registry location and full-commit source ingress vary.
    common.need(
        revision(HERE, "HEAD:scripts/ruff-source-placement")
        == "0cc1467837102b563b445be2193cd155006517a2",
        "different C2 factory source",
    )
    common.HERE = HERE
    common.BRANCH = QA_BRANCH
    reg = common.enrollment()
    packet = json.loads((HERE / "source-packet.json").read_bytes())
    common.need(
        packet["original_C2_QA"] == ORIGINAL_QA
        and packet["candidate"] == reg["roles"]["C"]["revision"]
        and reg["schema"] == "ohm-osp-directional-source-v1"
        and reg["source_packet_sha256"] == common.sha(HERE / "source-packet.json"),
        "unexpected independent product enrollment",
    )
    matched.HERE = HERE
    matched.verified_sources = verified_sources
    ws = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    root = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "ohm-branch-object-qa"
    {"preflight": matched.setup, "build": matched.source_build}[sys.argv[1]](ws, root, reg)


if __name__ == "__main__":
    main()
