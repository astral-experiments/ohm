"""Restore two independently source-qualified, isolated D/Q SDKs at the same canonical rustup path."""

import hashlib
import json
import shutil
import subprocess
import sys
from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
D = "d95494a6a63c22222806c06e3d3aa0de504d8e8a"
Q = "ed4d666c746f5ba92ac9d8086a934d1701aa6307"
Q_TREE = "18aee0a978a937dfadb1ace521440c22800354b8"
SOURCE_QA = "8df4ce6334f2bdac5d051135a3535f8bae764900"
SOURCE_RUN = 41328534716
SOURCE_JOB = 124913506341
SOURCES = {"D": D, "Q": Q}
TREES = {
    "D": "81461858540cf6f91328f7bfa1a4bcea13e4e9be",
    "Q": "9992315c8582d7a66f0f20774e503f5fcd72d6af",
}
D_MANIFEST = "5afab54e76787132fa7773d0ede79745dbb858e7870eb89f0d039428f8626981"
D_CONTENT = "f9bc1f304ad4befd1b21bb4db22379f1c0fb65392aabf9d527d038bd1c9e7456"
DRIVER = "lib/librustc_driver-c5276fb6f0cdddb4.so"
ARMS = ("Don", "Qon")


def need(ok, msg):
    if not ok:
        raise ValueError(msg)


def compact(obj):
    return hashlib.sha256(
        (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()


def content(files):
    return {k: [v[0], v[4], v[3]] for k, v in files.items()}


def read(path):
    return json.loads(path.read_bytes())


@cache
def enrolled():
    blob = (HERE / "source-enrollment.json").read_bytes()
    need(
        hashlib.sha256(blob).hexdigest()
        == "9e5e6c33ecba63c4db32471f38cdf43c517532f1d53925cf7358feb0fbe7fc03",
        "wrong original independent source report",
    )
    cert = json.loads(blob)
    source = cert["source"]
    need(
        (cert["run"], cert["job"], cert["head"]) == (SOURCE_RUN, SOURCE_JOB, SOURCE_QA)
        and source["qualified"] is True
        and source["qa"] == SOURCE_QA
        and source["run"] == str(SOURCE_RUN)
        and source["source"] == [D, Q, Q_TREE]
        and source["physical_installation_reopened"] is False
        and source["native_regression"]
        == {
            "parent": "None",
            "candidate": str(0xABCDEF0123456789),
            "test": "persist::fs::tests::resolve_complete_rows_at_the_start_of_large_packed_refs",
        }
        and source["members"] == 81
        and len(set(source["drivers"])) == 2,
        "unqualified immutable native compiler source",
    )
    return cert


def manifests():
    return {"D": D_MANIFEST, "Q": enrolled()["source"]["overlay"]}


def verify_pair(records):
    c = enrolled()["source"]
    need(set(records) == set(SOURCES), "missing either physical source SDK")
    canon = {}
    ids = {}
    for role in SOURCES:
        row = records[role]
        need(
            (row["role"], row["source"], row["driver"])
            == (role, SOURCES[role], DRIVER),
            "wrong source SDK",
        )
        canon[role] = content(row["files"])
        ids[role] = {tuple(v[1:3]) for v in row["files"].values()}
        need(
            len(row["files"]) == len(ids[role]) == 81,
            "incomplete or aliased native member",
        )
    need(
        ids["D"].isdisjoint(ids["Q"])
        and compact(canon["D"]) == D_CONTENT
        and canon["D"].keys() == canon["Q"].keys()
        and {k for k in canon["D"] if canon["D"][k] != canon["Q"][k]} == {DRIVER}
        and [canon[r][DRIVER][0] for r in ("D", "Q")] == c["drivers"],
        "SDK roster, driver or independent physical installation differs",
    )
    return records


def qualified_candidate(original):
    """Authenticate the source job's P slot before exposing that exact compiler as Q."""
    need(
        (original["role"], original["source"], original["driver"]) == ("P", Q, DRIVER)
        and original["files"][DRIVER][0] == enrolled()["source"]["drivers"][1],
        "incorrect native compiler in the source archive candidate slot",
    )
    return {**original, "role": "Q"}


def acquire(parent, source, upstream, b):
    source = Path(source).resolve(strict=True)
    need(
        b.git(source, "rev-parse", "HEAD") == SOURCE_QA,
        "other source qualification checkout",
    )
    upstream.acquire(Path(parent))
    inbox = b.ROOT / "packed-source-originals"
    inbox.mkdir()
    cert = enrolled()
    need(
        shutil.disk_usage(inbox).free
        >= (8 << 30) + sum(v["size_in_bytes"] for v in cert["artifacts"].values()),
        "insufficient complete native media/overlay capacity",
    )
    subprocess.run(
        [
            sys.executable,
            "-IB",
            HERE / "receive_q.py",
            source,
            inbox,
            b.PARK / "D",
            b.PARK / "Q",
            b.OUT / "sdk",
        ],
        check=True,
    )
    d = read(b.OUT / "sdk/D.json")
    raw = inbox / "verified-sdk/sdk/P.json"
    original = qualified_candidate(read(raw))
    q = {**original, "files": b.inventory(b.PARK / "Q")}
    need(
        content(original["files"]) == content(q["files"]),
        "restored Q differs from authenticated source",
    )
    b.verify_physical(b.PARK / "D", d["files"])
    verify_pair({"D": d, "Q": q})
    shutil.copyfile(raw, b.OUT / "sdk/q-source-slot.json")
    b.save(b.OUT / "sdk/Q.json", q)


def packed_source(role):
    import bindings as b

    return (
        read(b.OUT / "sdk/q-native-source.json"),
        {"D": "old", "Q": "new"}[role],
        SOURCES[role],
        TREES[role],
    )
