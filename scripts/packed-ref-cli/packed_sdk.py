"""Restore two independently source-qualified, isolated D/P SDKs at the same canonical rustup path."""

import hashlib
import json
import shutil
import subprocess
import sys
from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
D = "d95494a6a63c22222806c06e3d3aa0de504d8e8a"
P = "70a0f8090d1e2d9bd822720eb39076c409667edd"
P_TREE = "be66e74941aed13a5a89797504dca2076b414da9"
SOURCE_QA = "f93028872101f65e1c748217ac20ddb73a49bab1"
SOURCE_RUN = 41323607555
SOURCE_JOB = 124898828506
SOURCES = {"D": D, "P": P}
TREES = {
    "D": "81461858540cf6f91328f7bfa1a4bcea13e4e9be",
    "P": "a2c0e754472a6ed281f4b484d0564f1c7fe37c4c",
}
D_MANIFEST = "5afab54e76787132fa7773d0ede79745dbb858e7870eb89f0d039428f8626981"
D_CONTENT = "f9bc1f304ad4befd1b21bb4db22379f1c0fb65392aabf9d527d038bd1c9e7456"
DRIVER = "lib/librustc_driver-c5276fb6f0cdddb4.so"
ARMS = ("Don", "Pon")


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
        == "ebee7fef60f5e97328341110943b6724cacbb0e9b8ac5cc1a657f2fa8b4d859a",
        "wrong original independent source report",
    )
    cert = json.loads(blob)
    source = cert["source"]
    need(
        (cert["run"], cert["job"], cert["head"]) == (SOURCE_RUN, SOURCE_JOB, SOURCE_QA)
        and source["qualified"] is True
        and source["qa"] == SOURCE_QA
        and source["run"] == str(SOURCE_RUN)
        and source["source"] == [D, P, P_TREE]
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
    return {"D": D_MANIFEST, "P": enrolled()["source"]["overlay"]}


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
        ids["D"].isdisjoint(ids["P"])
        and compact(canon["D"]) == D_CONTENT
        and canon["D"].keys() == canon["P"].keys()
        and {k for k in canon["D"] if canon["D"][k] != canon["P"][k]} == {DRIVER}
        and [canon[r][DRIVER][0] for r in ("D", "P")] == c["drivers"],
        "SDK roster, driver or independent physical installation differs",
    )
    return records


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
            HERE / "receive_p.py",
            source,
            inbox,
            b.PARK / "D",
            b.PARK / "P",
            b.OUT / "sdk",
        ],
        check=True,
    )
    d = read(b.OUT / "sdk/D.json")
    from_original = read(inbox / "verified-sdk/sdk/P.json")
    p = {**from_original, "files": b.inventory(b.PARK / "P")}
    need(
        content(from_original["files"]) == content(p["files"]),
        "restored P differs from authenticated source",
    )
    b.verify_physical(b.PARK / "D", d["files"])
    verify_pair({"D": d, "P": p})
    b.save(b.OUT / "sdk/P.json", p)


def packed_source(role):
    import bindings as b

    return (
        read(b.OUT / "sdk/p-native-source.json"),
        {"D": "old", "P": "new"}[role],
        SOURCES[role],
        TREES[role],
    )
