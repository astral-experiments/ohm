"""Re-run the frozen two-pair decision on the exact four previously published raw projections."""

import json
from pathlib import Path
import os
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decision
import receiver
from common import BRANCH, HERE, REPO, enrollment, need, save, sha


def select(registered, run_meta, job_rows, artifacts, slot):
    run, head = registered["raw_run"], registered["raw_qa"]
    need(
        run_meta["id"] == run
        and run_meta["head_sha"] == head
        and run_meta["head_branch"] == BRANCH
        and run_meta["event"] == "workflow_dispatch"
        and run_meta["head_repository"]["full_name"] == REPO
        and run_meta["run_attempt"] == 1
        and run_meta["status"] == "completed"
        and run_meta["conclusion"] == "failure",
        "different original physical run",
    )
    jobs = {j["id"]: j for j in job_rows}
    statuses = {}
    for i in (1, 2):
        spec = registered["slots"][str(i)]
        statuses[spec["raw_job"]] = (
            "success",
            f"Reversible source placement ordinary Cargo ldv-placement-score block {i}",
        )
        statuses[spec["verified_job"]] = (
            "success",
            f"Independent whole placement artifact and native reader ldv-placement-score {i}",
        )
    statuses[registered["closed_failed_decision_job"]] = (
        "failure",
        "Read both fresh ordinary hardware pairs and all registered secondary outcomes",
    )
    need(
        {j["id"] for j in job_rows if j["conclusion"] != "skipped"} == set(statuses),
        "another native or failed job",
    )
    for job, (conclusion, name) in statuses.items():
        actual = jobs[job]
        need(
            actual["status"] == "completed"
            and actual["conclusion"] == conclusion
            and actual["name"] == name
            and actual["run_id"] == run
            and actual["run_attempt"] == 1
            and actual["head_sha"] == head,
            "old failure outside the final aggregate, or wrong native reader",
        )
    spec = registered["slots"][str(slot)]
    for kind in ("raw", "verified"):
        expected = spec[kind]
        (row,) = [a for a in artifacts if a["name"] == expected["name"]]
        need(
            not row["expired"]
            and row["workflow_run"]["id"] == run
            and row["workflow_run"]["head_sha"] == head
            and {k: row[k] for k in expected} == expected,
            "different physical raw or verified artifact",
        )
    return spec["verified"]


def run():
    reg = enrollment()
    j = json.loads((HERE / "attempts/closed-hardware.json").read_bytes())
    need(
        all(sha(HERE / k) == v for k, v in j["unchanged_sources_sha256"].items()),
        "changed scoring code, sources or enrollment",
    )
    with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as tmp:
        root = Path(tmp)
        run = j["raw_run"]
        head = j["raw_qa"]
        path = f"repos/{REPO}/actions/runs/{run}"
        meta = receiver.api(path)
        jobs = receiver.api(path + "/attempts/1/jobs?per_page=100")["jobs"]
        artifacts = receiver.api(path + "/artifacts?per_page=100")["artifacts"]

        def receive(run_id, orig_head, stage, slot, kind, dest, cap):
            need(
                (run_id, orig_head, stage, kind) == (run, head, "score", "verified")
                and slot in (1, 2),
                "can reopen only the two successful readers of the frozen hardware run",
            )
            row = select(j, meta, jobs, artifacts, slot)
            size = row["size_in_bytes"]
            need(
                0 < size <= cap <= 8 << 20
                and shutil.disk_usage(dest.parent).free > (15 << 30) + size,
                "original 15-GiB receiver floor",
            )
            receiver.api(f"repos/{REPO}/actions/artifacts/{row['id']}/zip", dest)
            need(
                dest.stat().st_size == size and "sha256:" + sha(dest) == row["digest"],
                "changed closed projection",
            )
            return row

        # Only replace the transport that ordinarily demands a live producing workflow ID.
        # The previous native gate, actual closure, data checks, arithmetic and original rule run intact.
        decision.originals.fetch = receive
        result = decision.decide(run, head, j["successful_native_run"], root)
        need(result["source"] == reg["roles"], "different physical compiler pair")
        result["original_decision_refusal"] = j["closed_failed_decision_job"]
        result["reader_run"] = int(os.environ["GITHUB_RUN_ID"])
        result["reader_qa"] = os.environ["GITHUB_SHA"]
        save(Path(sys.argv[1]), result)
        print("Original two-pair primary 2x eligibility:", result["two_pair_primary_screen"])


if __name__ == "__main__":
    run()
