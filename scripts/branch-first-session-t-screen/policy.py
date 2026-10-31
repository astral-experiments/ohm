"""Authenticate the F/T source run and restore both complete SDKs at the shared ordinary paths."""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
COMMON = HERE.parent / "branch-first-session-e-screen"
sys.path[:0] = [str(COMMON), str(HERE.parent / "branch-return-pmu")]
import subjects as sdk

b = sdk.b
BASE_ROLE, TREATMENT = "F", "T"
BASE = "c6fe8ecda65452c105f85367a009af80cbb5efbc"
T_BASE = "f70612039692c9ec6abf67d8921f4b5085c0f101"
T = "a653d40da8cd7e13a6e6c10ac6ebfeb224945c73"
T_TREE = "8fb5c75a2cd5fa542fbaf7d301db8bb3a88caa84"
T_COMPILER = "1de34fdeff4d471dda56dd91121f30693a59406c"
SOURCE_HEAD = "8004a7dd127f3f1df7cdfc1508daa1c4f1b44e36"
SOURCE_REF = "charlie/qa-tables-only-source-20261031"
REF = "charlie/qa-branch-first-session-t-screen-20261031"
ORDERS = {"01": ("Foff", "Fon", "Ton"), "02": ("Ton", "Fon", "Foff")}
RUNTIME = HERE / "inputs/t-source.json"
EXCLUDED = HERE / "inputs/excluded-boots.json"
BOOT_WITNESS = HERE / "inputs/e-boots.json"
OTHER_BOOTS = HERE / "inputs/additional-boots.json"
EXTRA_INPUTS = (BOOT_WITNESS, OTHER_BOOTS)
COLD_TABLE_ARM = "Ton"
PACKED_OBJECTS = frozenset()
JOB_NAME = "Exact table-only source, native regressions and mixed readers"
JOB_STEPS = (
    "Reopen the original F and K source job and its two artifacts",
    "Build the direct child of #274 and qualify the native binary",
    "Publish the qualified Linux driver capsule",
    "Preserve source and native observations",
)
DRIVER = "tables-only-linux-source-driver"
OBS = "tables-only-linux-source-observations"
HISTORIES = {"T-to-F-immediate", "T-to-F-return", "F-to-T-return", "F-to-T-aged"}


def enrollment():
    data = json.loads(RUNTIME.read_bytes())
    reviewed = data.get("reviewer")
    rec = data.get("source")
    b.need(
        data.get("schema") == 1 and isinstance(rec, dict) and isinstance(reviewed, dict),
        "T needs an independently qualified native source",
    )
    q = rec["qualified"]
    b.need(
        rec["head"] == SOURCE_HEAD
        and rec["attempt"] == 1
        and rec["run"] > 0
        and rec["job"] > 0
        and set(rec["artifacts"]) == {DRIVER, OBS}
        and q["source"] == T
        and q["members"] == 81
        and q["cargo"][0] == b.CARGO_ELF
        and q["wild"][0] == b.WILD_ELF
        and re.fullmatch("[0-9a-f]{64}", q["manifest"])
        and b.sha(HERE / "inputs/source-replay.json") == reviewed["sha256"],
        "incorrect T source enrollment",
    )
    proof = json.loads((HERE / "inputs/source-replay.json").read_bytes())
    b.need(
        proof["official"] == rec
        and proof["restored"] == q
        and proof["original_F"] == BASE
        and set(proof["mixed"]) == HISTORIES
        and proof["in_tree_tests"] == [8, 7]
        and proof["ordinary_provider_visits"] == [6, 16]
        and proof["native_values"] == [17, 29]
        and proof["cargo_sha256"] == b.CARGO_ELF
        and proof["wild_sha256"] == b.WILD_ELF,
        "independent compiler and native controls did not qualify",
    )
    boot_proof = json.loads(BOOT_WITNESS.read_bytes())
    previous = set(json.loads(sdk.EXCLUDED.read_bytes()))
    others = json.loads(OTHER_BOOTS.read_bytes())
    b.need(
        isinstance(others, dict)
        and not previous.intersection(others)
        and all(
            re.fullmatch(r"[a-f0-9-]{36}", boot)
            and item["run"] in (41222947202, 41219513694, 41219530573)
            and item["id"] > 0
            and item["job"] > 0
            and re.fullmatch(r"[a-f0-9]{64}", item["archive_sha256"])
            for boot, item in others.items()
        ),
        "unverified earlier confirmation workers",
    )
    previous.update(others)
    b.need(
        isinstance(boot_proof, dict)
        and (boot_proof["run"], boot_proof["head"])
        == (41228642029, "a6967b95ca4222e755e859ee1fb6e7839c3f8a30")
        and set(boot_proof["hosts"]) == {"01", "02"}
        and [boot_proof["hosts"][p]["job"] for p in ("01", "02")] == [124617991858, 124617991520],
        "needs both E host boot receipts",
    )
    boots = {h["boot"] for h in boot_proof["hosts"].values()}
    b.need(
        len(boots) == 2
        and not previous.intersection(boots)
        and all(
            re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", h["boot"])
            and re.fullmatch("[0-9a-f]{64}", h["archive_sha256"])
            for h in boot_proof["hosts"].values()
        )
        and set(json.loads(EXCLUDED.read_bytes())) == previous | boots,
        "two E boots or prior allocated workers omitted",
    )
    return rec


def activate(arm, rows, folder):
    manifest = (
        b.spec()["manifest"] if arm[0] == BASE_ROLE else enrollment()["qualified"]["manifest"]
    )
    return b.activate(arm, rows, folder, permitted=ORDERS["01"], source_manifest=manifest)


def live(rec):
    def api(path):
        return json.loads(
            subprocess.check_output(
                ["gh", "api", f"repos/{b.REPO}/actions/runs/{rec['run']}" + path]
            )
        )

    check_live(rec, api(""), api("/attempts/1/jobs"), api("/artifacts"))


def check_live(rec, run, jobs, artifacts):
    b.need(
        (
            run["id"],
            run["head_sha"],
            run["run_attempt"],
            run["head_branch"],
            run["event"],
            run["status"],
            run["conclusion"],
            run["path"],
        )
        == (
            rec["run"],
            SOURCE_HEAD,
            1,
            SOURCE_REF,
            "workflow_dispatch",
            "completed",
            "success",
            ".github/workflows/ci.yml",
        )
        and jobs["total_count"] == len(jobs["jobs"]) == 1,
        "foreign native workflow run",
    )
    (job,) = jobs["jobs"]
    b.need(
        (job["id"], job["name"], job["conclusion"], job["head_sha"], job["run_id"])
        == (rec["job"], JOB_NAME, "success", SOURCE_HEAD, rec["run"])
        and all(
            [s["conclusion"] for s in job["steps"] if s["name"] == step] == ["success"]
            for step in JOB_STEPS
        ),
        "did not actually pass T source/native gates",
    )
    b.need(
        artifacts["total_count"] == len(artifacts["artifacts"]) == 2
        and {a["name"] for a in artifacts["artifacts"]} == {DRIVER, OBS},
        "foreign source media",
    )
    for a in artifacts["artifacts"]:
        b.need(
            not a["expired"]
            and a["workflow_run"]["id"] == rec["run"]
            and a["workflow_run"]["head_sha"] == SOURCE_HEAD
            and {k: a[k] for k in ("id", "size_in_bytes", "digest")} == rec["artifacts"][a["name"]],
            "source archive identity changed",
        )


def acquire(source):
    rec = enrollment()
    live(rec)
    b.prepare_checkout(source, rec["head"], "scripts")
    where, transfer, original = sdk.original_sdk(source, "F", BASE)
    target = b.ROOT / "T-transfer"
    incoming = b.ROOT / "T-archives"
    incoming.mkdir()
    sdk.download(rec["artifacts"], incoming)
    sdk.extract_delta(incoming / (DRIVER + ".zip"), target, "T")
    m = json.loads((target / "manifest.json").read_bytes())
    q = rec["qualified"]
    b.need(
        b.sha(target / "manifest.json") == q["manifest"]
        and (
            m["source"]["source"],
            m["source"]["base"],
            m["source"]["original"],
            m["source"]["tree"],
            m["source"]["compiler"],
        )
        == (T, T_BASE, BASE, T_TREE, T_COMPILER),
        "native T source differs",
    )
    with zipfile.ZipFile(incoming / (OBS + ".zip")) as z:
        b.need(
            len(z.namelist()) == len(set(z.namelist()))
            and z.getinfo("T/qualified.json").file_size < 65536
            and json.loads(z.read("T/qualified.json")) == q,
            "native T terminal differs",
        )
        for member, field in [
            ("T/mixed/complete.json", "mixed"),
            ("T/checked-in-tests.json", "tests"),
            ("T/native-shadow/complete.json", "native"),
        ]:
            b.need(
                z.getinfo(member).file_size < 256 * 1024
                and hashlib.sha256(z.read(member)).hexdigest() == m[field],
                "actual T source gate differs",
            )
    b.PARK.mkdir()
    b.SDK.parent.mkdir(parents=True)
    anchor = b.spec()
    fargs = [
        "--qa",
        anchor["head"],
        "--run",
        str(anchor["run"]),
        "--attempt",
        "1",
        "--manifest",
        anchor["manifest"],
    ]
    targs = [
        "--qa",
        rec["head"],
        "--run",
        str(rec["run"]),
        "--attempt",
        "1",
        "--manifest",
        q["manifest"],
    ]
    sdk.capture(
        [
            sys.executable,
            "-IB",
            source / "scripts/branch-return-source/restore.py",
            transfer,
            b.PARK / "F",
            "F",
            *fargs,
        ],
        where / "reopen-F",
    )
    restored = json.loads(
        sdk.capture(
            [
                sys.executable,
                "-IB",
                source / "scripts/tables-only-source/qualify.py",
                "restore",
                transfer,
                target,
                b.PARK / "T",
                *targs,
            ],
            where / "reopen-T",
        )
    )
    b.need(restored == q, "independent physical T restoration differs")
    roles = {"F": (original["roles"]["F"], original["files"]["F"]), "T": (m["source"], m["files"])}
    return sdk.physical_roles(roles, original["driver"], where)


if __name__ == "__main__":
    print("source_head=" + enrollment()["head"])
