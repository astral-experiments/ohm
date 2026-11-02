"""Authenticate a fresh nonrelease job against the published signed GNU distribution."""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0] / "ruff-cgu-inputs"))
import acquire_cgu as a

BRANCH = "charlie/qa-ruff-query-item-dictionary-20261102"
JOB = "Signed GNU Ruff workspace stable query item dictionary"
ARTIFACT = "signed-gnu-ruff-workspace-query-items"
spec = json.loads((HERE / "keys.json").read_bytes())


def authenticate():
    a.verify_inherited_sources()
    a.BRANCH, a.JOB = BRANCH, JOB
    os.environ["EXCLUDED_BOOT_CUSTODY"] = json.dumps(spec["previous_boots"])
    with a.registration():
        a.acquire.main()
    out = Path(os.environ["RUNNER_TEMP"]) / "ohm-branch-object-qa/logs"
    current = a.c.read(out / "enrollment.json")
    prior = spec["provisional_trace"]
    a.c.need(all(prior[k] != current[k] for k in ("run", "job", "runner", "runner_id", "boot")), "profile must have independent runner identity")
    artifact = a.acquire.api("actions/artifacts/" + str(spec["provisional_archive"]["id"]))
    run = a.acquire.api("actions/runs/" + str(prior["run"]))
    a.c.need(
        run["id"] == prior["run"] and run["status"] == "completed" and run["conclusion"] == "failure"
        and run["head_repository"]["full_name"] == a.c.REPO
        and artifact["workflow_run"]["id"] == prior["run"] and not artifact["expired"]
        and all(artifact[k] == v for k,v in spec["provisional_archive"].items()),
        "registered refused selection trace"
    )
    a.c.save(out / "selection-origin.json", {"run":run, "artifact":artifact, "status":"provisional, refused"})
    a.c.save(out / "diagnostic.json", {"commit":os.environ["GITHUB_SHA"], "branch":BRANCH, "job":JOB,
                                      "artifact":ARTIFACT, "keys_sha256":a.c.sha(HERE/"keys.json")})


if __name__ == "__main__":
    authenticate()
