"""Select one physically successful Actions producer without assuming sibling jobs have completed."""

import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stock_scope as scope

NAMES = {
    "migration-raw": "Authentic cross-version placement records on ordinary Ruff 1",
    "migration-verified": "Independently reopen both genuine placement migrations 1",
    "admit-raw": "Actual selected writer ordinary native history",
    "admit-verified": "Independently reopen selected writer ordinary native history",
    "three-raw": "Three ordinary physical writer roles in a clean boot",
    "three-verified": "Reopen the original selected-writer counts from one boot",
}
ARTIFACTS = {
    "migration-raw": "placement-stock-migration-raw",
    "migration-verified": "placement-stock-migration-verified",
    "admit-raw": "placement-stock-admission-raw",
    "admit-verified": "placement-stock-admission-verified",
    "three-raw": "placement-stock-survey-raw",
    "three-verified": "placement-stock-survey-verified",
}


def choose(meta, jobs, rows, run, head, stage, slot, kind, *, previous):
    n = scope.base.need
    tag = stage + "-" + kind
    n(
        tag in NAMES
        and (stage in ("admit", "three") and slot in (1, 2) or stage == "migration" and slot == 1),
        "unregistered receiver",
    )
    n(
        meta["id"] == run
        and meta["head_sha"] == head
        and meta["head_branch"] == scope.BRANCH
        and meta["event"] == "workflow_dispatch"
        and meta["head_repository"]["full_name"] == scope.base.REPO
        and meta["run_attempt"] == 1,
        "different release QA run",
    )
    if previous:
        n(
            meta["status"] == "completed" and meta["conclusion"] == "success",
            "prerequisite cohort failed or is incomplete",
        )
    else:
        n(
            run == int(os.environ["GITHUB_RUN_ID"])
            and head == os.environ["GITHUB_SHA"]
            and meta["status"] in ("queued", "in_progress", "completed"),
            "not the actual live acquisition",
        )
    wanted = NAMES[tag] if stage == "migration" else NAMES[tag] + " " + str(slot)
    (job,) = [j for j in jobs if j["name"] == wanted]
    n(
        job["run_id"] == run
        and job["head_sha"] == head
        and job["run_attempt"] == 1
        and job["status"] == "completed"
        and job["conclusion"] == "success",
        "missing or failed physical producer",
    )
    (row,) = [a for a in rows if a["name"] == ARTIFACTS[tag] + "-" + str(slot)]
    n(
        not row["expired"]
        and row["workflow_run"]["id"] == run
        and row["workflow_run"]["head_sha"] == head,
        "different archived run",
    )
    return row, job["id"]


def receive(run, head, stage, slot, kind, out, cap, *, previous=False):
    api = scope.receiver.api
    prefix = f"repos/{scope.base.REPO}/actions/runs/{run}"
    row, job = choose(
        api(prefix),
        api(prefix + "/attempts/1/jobs?per_page=100")["jobs"],
        api(prefix + "/artifacts?per_page=100")["artifacts"],
        run,
        head,
        stage,
        slot,
        kind,
        previous=previous,
    )
    size = row["size_in_bytes"]
    scope.base.need(
        not out.exists()
        and 0 < size <= cap
        and shutil.disk_usage(out.parent).free > (15 << 30) + size,
        "physical storage reserve or archive admission",
    )
    api(f"repos/{scope.base.REPO}/actions/artifacts/{row['id']}/zip", out)
    scope.base.need(
        out.stat().st_size == size and "sha256:" + scope.base.sha(out) == row["digest"],
        "wrong received archive",
    )
    return {k: row[k] for k in ("name", "id", "size_in_bytes", "digest")} | {"job": job}
