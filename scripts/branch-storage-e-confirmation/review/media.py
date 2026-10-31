"""Authenticate a terminal first-attempt enrollment and retain its exact original ZIPs once."""

from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import decision
import confirm_binding as r

LABEL = "Confirm corrected E whole-Ruff storage "
PREFIX = "checked-e-storage-confirmation-"
PREFLIGHT = "Verify source-pilot records and all prior integration boots"
CARGO_STEP = (
    "Compare pristine and same-branch-edited first checkouts with four native provider outcomes"
)
GH = "/home/dev-user/.local/bin/gh-auto"


def gh(args):
    return [GH, "api", f"repos/{r.REPO}/actions/{args}"]


def catalog(run, head, info, *, require_success):
    r.check(
        type(run) is int and run > 0 and re.fullmatch("[a-f0-9]{40}", head),
        "wrong future confirmation anchor",
    )
    top, jdoc, adoc = (info[n] for n in ("run", "jobs", "artifacts"))
    r.check(
        (
            top["id"],
            top["run_attempt"],
            top["head_sha"],
            top["head_branch"],
            top["event"],
            top["path"],
            top["status"],
        )
        == (run, 1, head, r.REF, "workflow_dispatch", ".github/workflows/ci.yml", "completed"),
        "unregistered or still-running workflow",
    )
    jobs = {x["name"]: x for x in jdoc["jobs"]}
    assets = {x["name"]: x for x in adoc["artifacts"]}
    pos = decision.POSITIONS
    labels = {LABEL + p for p in pos}
    names = {PREFIX + p for p in pos}
    r.check(
        PREFLIGHT in jobs
        and set(jobs) <= labels | {PREFLIGHT}
        and len(jobs) == jdoc["total_count"] == len({j["id"] for j in jobs.values()}),
        "foreign/duplicate workflow jobs",
    )
    r.check(
        len(assets) == adoc["total_count"]
        and set(assets) <= names
        and len({a["id"] for a in assets.values()}) == len(assets),
        "duplicate or unregistered ZIP",
    )
    for j in jobs.values():
        r.check(
            j["head_sha"] == head and j["run_id"] == run and j["status"] == "completed",
            "cross-attempt job",
        )
    if require_success:
        r.check(
            top["conclusion"] == "success"
            and jobs[PREFLIGHT]["conclusion"] == "success"
            and set(jobs) == labels | {PREFLIGHT}
            and set(assets) == names,
            "incomplete original cohort: no counters",
        )
    candidates = {}
    for p in pos:
        j = jobs.get(LABEL + p)
        a = assets.get(PREFIX + p)
        r.check(a is None or j is not None, "artifact has no registered producing job")
        if j is None:
            continue
        if require_success:
            r.check(
                j["conclusion"] == "success"
                and any(
                    x["name"] == CARGO_STEP and x["conclusion"] == "success" for x in j["steps"]
                ),
                "required full workload did not pass",
            )
        if a is None:
            continue
        r.check(
            a["workflow_run"]["id"] == run
            and a["workflow_run"]["head_sha"] == head
            and not a["expired"]
            and a["size_in_bytes"] in range(1, 2 << 30)
            and re.fullmatch("sha256:[a-f0-9]{64}", a["digest"]),
            "invalid official artifact",
        )
        candidates[p] = {
            "id": a["id"],
            "size": a["size_in_bytes"],
            "sha256": a["digest"][7:],
            "job": j["id"],
            "conclusion": j["conclusion"],
            "filename": f'{run}-{p}-{a["id"]}.zip',
        }
    return candidates


def verify(path, row):
    r.check(
        path.is_file() and not path.is_symlink() and path.stat().st_size == row["size"],
        "missing/truncated original ZIP",
    )
    with path.open("rb") as h:
        r.check(
            hashlib.file_digest(h, "sha256").hexdigest() == row["sha256"],
            "incorrect official ZIP digest",
        )


def collect(run, head, store, out):
    # Required locally before any success or failure intake; this never writes an external ref or starts a job.
    r.local()
    docs = {
        k: json.loads(subprocess.check_output(gh(suf)))
        for k, suf in [
            ("run", f"runs/{run}"),
            ("jobs", f"runs/{run}/attempts/1/jobs?per_page=100"),
            ("artifacts", f"runs/{run}/artifacts?per_page=100"),
        ]
    }
    rows = catalog(run, head, docs, require_success=False)
    store.mkdir(mode=0o700, exist_ok=True)
    r.check(
        store.resolve() == store
        and store.is_dir()
        and not store.is_symlink()
        and store.stat().st_uid == os.getuid(),
        "foreign media store",
    )
    missing = sum(v["size"] for v in rows.values() if not (store / v["filename"]).exists())
    r.check(shutil.disk_usage(store).free >= (4 << 30) + missing, "insufficient evidence reserve")
    for v in rows.values():
        dest = store / v["filename"]
        if not dest.exists():
            tmp = dest.with_suffix(".receiving")
            with (
                tmp.open("xb") as h,
                subprocess.Popen(gh(f'artifacts/{v["id"]}/zip'), stdout=subprocess.PIPE) as child,
            ):
                total = 0
                while b := child.stdout.read(min(1 << 20, v["size"] - total + 1)):
                    total += len(b)
                    r.check(total <= v["size"], "official transfer exceeds declared length")
                    h.write(b)
                r.check(child.wait() == 0, "artifact transport failed")
                h.flush()
                os.fsync(h.fileno())
            verify(tmp, v)
            tmp.chmod(0o440)
            tmp.rename(dest)
        verify(dest, v)
    data = (json.dumps(docs, sort_keys=True, indent=2) + "\n").encode()
    if out.exists():
        r.check(out.read_bytes() == data, "official completed catalog differs")
    else:
        with out.open("xb") as h:
            h.write(data)
    return rows
