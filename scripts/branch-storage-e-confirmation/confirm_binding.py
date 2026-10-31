"""Bind the two closed pilot studies and exclude every previous F integration worker before dispatch."""

from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
POS = tuple(f"{n:02}" for n in range(1, 13))
OLD_INTEGRATION = 41235234268
OLD_HEAD = "679e72fedd4968636469d958c38225c0ce3fefab"
OLD_REF = "charlie/qa-ruff-integration-f-confirmation-20261031"
FJOBS = dict(
    zip(
        POS,
        (
            124637562310,
            124637562320,
            124637562269,
            124637562411,
            124637562386,
            124637562347,
            124637562344,
            124637562356,
            124637562279,
            124637562289,
            124637562313,
            124637562308,
        ),
        strict=True,
    )
)
PILOTS_SHA = "c2ce851e3e5b90ec925a3aa8c1dcc6aaecee137d1c9aafca39f27fe7f38b62f5"
KNOWN_SHA = "691b1d4a6597261df2795f7cddbb0b5167ac288332014e414a7a8bc267d382e8"
PLAN = "bd0b036f8f18176404051697513ce784c38cd2669b776b22008c99578969e519"
ORDERS_SHA = "a1ed3813eafe2f80a18c8765fdb032917dd597865daaa7818f559bd5cb573652"
REPO = "astral-experiments/ohm"
REF = "charlie/qa-branch-storage-checked-confirmation-20261031"
BOOT = re.compile(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}")
DIGEST = re.compile(r"[0-9a-f]{64}")


def check(v, m):
    if not v:
        raise ValueError(m)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validated_prior(prior, registered, pilots):
    check(
        len(prior) == len(set(prior)) == 54 and all(BOOT.fullmatch(x) for x in prior),
        "earlier 54 boot witnesses",
    )
    check(
        pilots["schema"] == 1
        and {x["boot"] for p in pilots["runs"].values() for x in p["hosts"].values()} <= set(prior),
        "pilot boot missing",
    )
    check(
        isinstance(registered, dict)
        and (registered["run"], registered["head"], registered["attempt"], registered["branch"])
        == (OLD_INTEGRATION, OLD_HEAD, 1, OLD_REF),
        "awaiting genuine integration originals",
    )
    rows = registered["hosts"]
    check(set(rows) == set(POS), "all 12 previous integration workers required")
    boots = set(prior)
    ids = set()
    for pos in POS:
        e = rows[pos]
        check(
            e["job"] == FJOBS[pos]
            and e["name"] == "ruff-integration-f-confirmation-" + pos
            and e["head"] == OLD_HEAD
            and BOOT.fullmatch(e["boot"])
            and e["boot"] not in boots,
            "wrong or reused earlier boot",
        )
        check(
            e["id"] > 0
            and e["id"] not in ids
            and 0 < e["size"] < 2 << 30
            and all(
                DIGEST.fullmatch(e[k])
                for k in ("sha256", "enrollment_sha256", "worker_receipt_sha256")
            ),
            "previous original identities missing",
        )
        boots.add(e["boot"])
        ids.add(e["id"])
    return boots


def local():
    files = {
        HERE / "PLAN.md": PLAN,
        HERE / "SOURCE-ADDENDUM.md": "349a0fe529fcabb7a9c0b2c744704f80b6bcad559ed2302cb62301f62e0339e1",
        INPUTS / "orders.json": ORDERS_SHA,
        INPUTS / "pilots.json": PILOTS_SHA,
        INPUTS / "previous-boots.json": KNOWN_SHA,
        INPUTS / "integration-boots.json": "b7e6531caa7eb7db9a9a36fd18eea1d9a242383268bebe8d37692473ba34ed6d",
        INPUTS / "excluded-boots.json": "e7874956be4febf7003cef92076951c1b89a469dcdaaa17730fdc11eb703b0dc",
    }
    check(all(sha(p) == d for p, d in files.items()), "different frozen study or pilot witness")
    pilots = json.loads((INPUTS / "pilots.json").read_bytes())
    old = json.loads((INPUTS / "integration-boots.json").read_bytes())
    boots = validated_prior(json.loads((INPUTS / "previous-boots.json").read_bytes()), old, pilots)
    approved = json.loads((INPUTS / "excluded-boots.json").read_bytes())
    check(approved == sorted(boots), "incomplete final exclusions")
    return pilots, old, boots


def official(api, proof, expected_jobs):
    run = proof["run"]
    top = api(f"runs/{run}")
    jobs = api(f"runs/{run}/attempts/1/jobs?per_page=100")
    media = api(f"runs/{run}/artifacts?per_page=100")
    check(
        (
            top["id"],
            top["head_sha"],
            top["head_branch"],
            top["run_attempt"],
            top["event"],
            top["path"],
            top["status"],
            top["conclusion"],
        )
        == (
            run,
            proof["head"],
            proof["branch"],
            1,
            "workflow_dispatch",
            ".github/workflows/ci.yml",
            "completed",
            "success",
        ),
        "previous workflow unavailable or different",
    )
    js = {j["id"]: j for j in jobs["jobs"]}
    assets = {a["id"]: a for a in media["artifacts"]}
    check(
        jobs["total_count"] == len(js) == expected_jobs
        and len(assets) == media["total_count"] == len(proof["hosts"]),
        "unexpected historical job/media roster",
    )
    for pos, row in proof["hosts"].items():
        j = js[row["job"]]
        a = assets[row["id"]]
        check(
            (j["head_sha"], j["run_id"], j["status"], j["conclusion"])
            == (proof["head"], run, "completed", "success")
            and j["name"].endswith(" " + pos),
            "different historical job",
        )
        check(
            (
                a["name"],
                a["digest"],
                a["size_in_bytes"],
                a["expired"],
                a["workflow_run"]["id"],
                a["workflow_run"]["head_sha"],
            )
            == (row["name"], "sha256:" + row["sha256"], row["size"], False, run, proof["head"]),
            "different official original",
        )


def github(suffix):
    return json.loads(subprocess.check_output(["gh", "api", f"repos/{REPO}/actions/{suffix}"]))


def live():
    sys.path.insert(0, str(HERE))
    import checked_source

    checked = checked_source.enrollment()
    checked_source.official(github, checked)
    pilots, old, boots = local()
    for seed in pilots["runs"].values():
        official(github, seed, 2)
    official(github, old, 13)
    head = os.environ["GITHUB_SHA"]
    current = int(os.environ["GITHUB_RUN_ID"])
    check(
        re.fullmatch(r"[0-9a-f]{40}", head)
        and current > 0
        and head == os.environ["REVIEWED_HEAD"]
        and os.environ["GITHUB_REPOSITORY"] == REPO
        and os.environ["GITHUB_REF"] == "refs/heads/" + REF
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1",
        "unregistered confirmation execution",
    )
    runs = github(f"runs?branch={REF}&head_sha={head}&event=workflow_dispatch&per_page=100")
    check(
        runs["total_count"] == 1 and [r["id"] for r in runs["workflow_runs"]] == [current],
        "duplicate confirmation dispatch",
    )
    print("binding=" + sha(INPUTS / "integration-boots.json"))


if __name__ == "__main__":
    live()
