"""Authenticate service metadata; artifact membership is part of each pinned producer job."""
import re

REPO = "astral-experiments/ohm"
ROLES = ("fa7a_stack_ctfe318", "callables_ctfe318")
COMMON = {
    "Admit this production workspace and allocate its physical emergency reserve",
    "Reconstruct and verify the exact compiler source",
    "Install native GNU bootstrap prerequisites", "Install pinned LLVM BOLT tools",
    "Prepare pinned Wild linker", "Build the production PGO and BOLT distribution",
    "Verify the production SDK and exercise the original regression",
    "Validate this role's complete capacity evidence before its SDK upload",
    "Upload the native-qualified SDK", "Retain role identity, release build and native diagnostics",
}
PRODUCERS = {
    ROLES[0]: dict(run=41374825846, head="cddb036d81e4313a8e422171f39f0840b44110db",
                   branch="charlie/codex-ctfe22-standard-20988", job="Production GNU SDK (fa7a_stack_ctfe318)",
                   id=125052685273, sdk="ctfe22-gnu-sdk-fa7a_stack_ctfe318",
                   qa="ctfe22-gnu-build-fa7a_stack_ctfe318-attempt-1",
                   prior_pair="ctfe22-gnu-pair-qa-attempt-1"),
    ROLES[1]: dict(run=41398925829, head="4e34ea9c7232977f95498d7bf48d382157e8558b",
                   branch="charlie/codex-21041-callable-production22", job="Production GNU callable SDK",
                   id=125126258067, sdk="callable-production-sdk", qa="callable-production-qa-attempt-1"),
}

def need(ok, description):
    if not ok:
        raise ValueError(description)

def service(role, run, jobs, artifacts, control):
    p = PRODUCERS[role]
    need(run["id"] == p["run"] and run["head_sha"] == p["head"] and run["head_branch"] == p["branch"]
         and run["run_attempt"] == 1 and run["status"] == "completed" and run["conclusion"] == "success"
         and run["workflow_id"] == 325165136 and run["path"] == ".github/workflows/ci.yml"
         and run["event"] == "workflow_dispatch" and run["repository"]["id"] == 1319437234
         and run["head_repository"]["id"] == 1319437234 and run["repository"]["private"] is True
         and run["repository"]["full_name"] == REPO, "unqualified producer service run")
    expected_jobs = control["jobs"] if role == ROLES[0] else {p["job"]: p["id"]}
    rows = jobs["jobs"]
    need(len(rows) == jobs["total_count"] == len(expected_jobs)
         and {r["name"]:r["id"] for r in rows} == expected_jobs, "wrong or extra producer job")
    for r in rows:
        need(r["run_id"] == p["run"] and r["head_sha"] == p["head"] and r["run_attempt"] == 1
             and r["conclusion"] == "success" and r["status"] == "completed" and r["runner_id"] > 0,
             "unqualified or unrelated producer job")
    job, = (r for r in rows if r["id"] == p["id"])
    ok = {s["name"] for s in job["steps"] if s["status"] == "completed" and s["conclusion"] == "success"}
    need(COMMON <= ok and job["labels"] == ["namespace-profile-ubuntu-24-04-16"], "missing physical build or native QA")
    expected_names = set(control["artifacts"]) if role == ROLES[0] else {p["sdk"],p["qa"]}
    arts = artifacts["artifacts"]
    need(len(arts) == artifacts["total_count"] == len(expected_names) and {a["name"]for a in arts} == expected_names
         and len({a["id"]for a in arts}) == len(arts), "unexpected producer artifact roster")
    compact = {}
    for a in arts:
        w = a["workflow_run"]
        need(w["id"] == p["run"] and w["head_sha"] == p["head"] and w["head_branch"] == p["branch"]
             and w["repository_id"] == w["head_repository_id"] == 1319437234 and a["expired"] is False
             and re.fullmatch(r"sha256:[a-f0-9]{64}", a["digest"]), "artifact belongs to a different input")
        compact[a["name"]] = {"id":a["id"], "bytes":a["size_in_bytes"], "sha256":a["digest"][7:]}
    need(190<<20 < compact[p["sdk"]]["bytes"] < 700<<20 and 0 < compact[p["qa"]]["bytes"] < 64<<20, "unexpected distribution")
    if role == ROLES[0]:
        need(compact == control["artifacts"], "control differs from the original qualified production run")
    return {"run":p["run"],"head":p["head"],"branch":p["branch"],"job":p["id"],
            "runner":job["runner_id"],"runner_name":job["runner_name"],"jobs":expected_jobs,"members":compact}
