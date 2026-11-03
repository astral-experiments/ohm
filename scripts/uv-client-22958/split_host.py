"""Bind one contrast to a new physical assignment and the marginal's real early ZIP, when required."""

import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path
from uuid import UUID
from zipfile import ZipFile


REPOSITORY = "astral-experiments/ohm"
REPOSITORY_ID = 1319437234
BRANCH = "charlie/codex-22958-release23-split-check"
CONTRASTS = {"marginal": {"control": "S", "treatment": "F"}, "signed": {"control": "R", "treatment": "F"}}


def selector(value, contrast):
    if contrast == "marginal":
        assert value == "none"
        return None
    assert contrast == "signed"
    fields = re.fullmatch(r"([1-9][0-9]*):([1-9][0-9]*):([1-9][0-9]*):([0-9a-f]{64})", value)
    assert fields, "signed contrast requires run:job:artifact:ZIP_SHA256 from the marginal"
    run, job, artifact, digest = fields.groups()
    return {"run": int(run), "job": int(job), "artifact": int(artifact), "sha256": digest}


def baseline(lock):
    values = [v["boot"] for v in lock["excluded"].values()]
    assert len(values) == len(set(values)) >= 31 and all(str(UUID(v)) == v for v in values)
    digest = hashlib.sha256(("\n".join(sorted(values)) + "\n").encode()).hexdigest()
    assert digest == lock["boot_list_sha256"]
    return sorted(values)


def service_assignment(run, jobs, run_id, head, branch, current_runner=None):
    assert run["id"] == run_id and run["head_sha"] == head and run["head_branch"] == branch
    assert run["run_attempt"] == 1 and run["event"] == "workflow_dispatch"
    assert run["repository"]["id"] == run["head_repository"]["id"] == REPOSITORY_ID
    assert run["repository"]["full_name"] == run["head_repository"]["full_name"] == REPOSITORY
    assert run["repository"]["private"] and run["head_repository"]["private"]
    assert run["path"] == ".github/workflows/ci.yml"
    assert jobs["total_count"] == len(jobs["jobs"]) == 1
    job, = jobs["jobs"]
    assert job["run_id"] == run_id and job["head_sha"] == head and job["run_attempt"] == 1 and job["name"] == "root"
    assert job["labels"] == ["namespace-profile-ubuntu-24-04-16"]
    assert type(job["runner_id"]) is int and job["runner_id"] > 0 and job["runner_name"]
    if current_runner:
        assert job["runner_name"] == current_runner and job["status"] == "in_progress" and job["conclusion"] is None
    else:
        assert job["status"] in ("in_progress", "completed")
    return {"run": run_id, "job": job["id"], "runner_id": job["runner_id"], "runner_name": job["runner_name"], "coordinator": head}


def original_member(path, artifact, expected, head, branch, name):
    assert artifact["id"] == expected["artifact"] and artifact["name"] == name and not artifact["expired"]
    origin = artifact["workflow_run"]
    assert origin["id"] == expected["run"] and origin["head_sha"] == head and origin["head_branch"] == branch
    assert origin["repository_id"] == origin["head_repository_id"] == REPOSITORY_ID
    assert artifact["digest"] == "sha256:" + expected["sha256"]
    assert path.stat().st_size == artifact["size_in_bytes"] and 0 < path.stat().st_size < 64 << 10
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected["sha256"]
    with ZipFile(path) as z:
        member, = z.infolist()
        assert member.filename == "boot-attestation.json" and 0 < member.file_size < 32 << 10
        assert not member.flag_bits & 1 and stat.S_IFMT(member.external_attr >> 16) in (0, stat.S_IFREG)
        data = z.read(member)
    return json.loads(data), hashlib.sha256(data).hexdigest()


def from_prior(observed, assignment, artifact, requested, member_sha, lock, lock_sha, registered, current):
    assert assignment["run"] == requested["run"] and assignment["job"] == requested["job"]
    assert all(observed[k] == assignment[k] for k in assignment)
    assert observed["registered"] == registered and observed["release_lock"] == lock_sha
    assert observed["contrast"] == "marginal" and observed["control"] == "S" and observed["treatment"] == "F"
    assert observed["prior_marginal"] is None and observed["baseline_boot_list_sha256"] == lock["boot_list_sha256"]
    assert observed["excluded"] == baseline(lock) and observed["boot"] not in observed["excluded"]
    assert str(UUID(observed["boot"])) == observed["boot"] and len(set(observed["affinity"])) == len(observed["affinity"]) == 8
    assert all(re.fullmatch("[0-9a-f]{64}", observed[key]) for key in ("inherited", "threads", "blocking", "placement_sha256"))
    assert all(current[k] != observed[k] for k in ("run", "job", "runner_id", "runner_name", "boot"))
    assert current["coordinator"] == observed["coordinator"]
    return {**assignment, "boot": observed["boot"], "artifact": artifact["id"], "artifact_bytes": artifact["size_in_bytes"],
            "artifact_sha256": requested["sha256"], "member_sha256": member_sha,
            "inherited": observed["inherited"], "threads": observed["threads"], "blocking": observed["blocking"]}



def verify_placement(row, contrast, lock, lock_sha, registered):
    """Recheck the native boot census and both promised allocation identities off-clock."""
    assert row["contrast"] == contrast and {k:row[k] for k in ("control","treatment")} == CONTRASTS[contrast]
    assert row["release_lock"] == lock_sha and row["registered"] == registered
    assert row["baseline_boot_list_sha256"] == lock["boot_list_sha256"]
    assert row["run"] > 0 and row["job"] > 0 and row["runner_id"] > 0 and row["runner_name"]
    assert re.fullmatch("[0-9a-f]{40}",row["coordinator"]) and str(UUID(row["boot"])) == row["boot"]
    old = row["prior_marginal"]
    excluded = baseline(lock)
    if contrast == "marginal":
        assert old is None
    else:
        assert old["coordinator"] == row["coordinator"]
        assert all(old[key] != row[key] for key in ("run","job","boot","runner_id","runner_name"))
        assert str(UUID(old["boot"])) == old["boot"] and old["boot"] not in excluded
        assert old["artifact"] > 0 and 0 < old["artifact_bytes"] < 64 << 10
        for key in ("artifact_sha256","member_sha256","inherited","threads","blocking"):
            assert re.fullmatch("[0-9a-f]{64}",old[key])
        excluded.append(old["boot"])
    assert sorted(excluded) == row["excluded"] and row["boot"] not in excluded
    return row

def record(workspace, boot, contrast, lock, lock_sha, registered, donor, save):
    """Contact only Actions metadata and one small completed calibration artifact, before any clocks."""
    proof = workspace / "trait-results" / "placement"
    proof.mkdir()
    run_id, head = int(os.environ["GITHUB_RUN_ID"]), os.environ["REVIEWED_HEAD"]
    get = lambda route: donor.gh_json("api", "--method", "GET", "-H", "Cache-Control: no-cache", "repos/" + REPOSITORY + "/" + route)
    def service(run, label, live=None):
        path = "actions/runs/" + str(run)
        meta = get(path)
        for _ in range(24):
            jobs = get(path + "/attempts/1/jobs?per_page=100")
            if jobs["total_count"] and all(row.get("runner_id") for row in jobs["jobs"]):
                save(proof / (label + "-run.json"), meta)
                save(proof / (label + "-jobs.json"), jobs)
                return service_assignment(meta, jobs, run, head, BRANCH, live)
            if not live:
                break
            time.sleep(5)
        raise RuntimeError("The official Actions API did not identify the physical runner")
    current = service(run_id, "current", os.environ["RUNNER_NAME"]) | {"boot": boot}
    requested = selector(os.environ["UV_22958_PRIOR_MARGINAL"], contrast)
    previous = None
    if requested:
        assignment = service(requested["run"], "prior")
        item = get("actions/artifacts/" + str(requested["artifact"]))
        assert item["digest"] == "sha256:" + requested["sha256"] and 0 < item["size_in_bytes"] < 64 << 10
        save(proof / "prior-artifact.json", item)
        path = proof / "prior-boot.zip"
        donor.gh_bytes(f"repos/{REPOSITORY}/actions/artifacts/{requested['artifact']}/zip", path, item["size_in_bytes"], requested["sha256"])
        record, member_sha = original_member(path, item, requested, head, BRANCH, "uv-22958-release23-marginal-runner-boot")
        previous = from_prior(record, assignment, item, requested, member_sha, lock, lock_sha, registered, current)
    exclusions = sorted([*baseline(lock), *([previous["boot"]] if previous else [])])
    assert current["boot"] not in exclusions and len(exclusions) == len(set(exclusions))
    save(workspace / "trait-results/placement.json", {**current, **CONTRASTS[contrast], "contrast": contrast,
         "registered": registered, "release_lock": lock_sha, "prior_marginal": previous,
         "baseline_boot_list_sha256": lock["boot_list_sha256"], "excluded": exclusions})
