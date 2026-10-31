"""Prove a single manual dispatch on the expected checkout, with frozen sources."""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))

from acquire import HERE, REPO, api, need, sha

BRANCH = "charlie/qa-rc22-apple-declared-link-smoke-20261031"
OBSERVER = "14c9d13d68f3dd21c53f1ef6c3721de8363c0123"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args], text=True).strip()


def validate_inputs(repo, observer):
    reg = json.loads((HERE / "registration.json").read_bytes())
    old = repo / "scripts/smoke-test-relink.sh"
    new = HERE / "proposed-release-relink.sh"
    for path, key in [(old, "original_smoke"), (new, "corrected_smoke")]:
        need(
            sha(path) == reg[key]["sha256"] and git(repo, "hash-object", str(path)) == reg[key]["blob"],
            ("wrong frozen release-smoke program", key),
        )
    path = "scripts/ohm-apple-zmij"
    need(
        git(observer, "rev-parse", "HEAD") == OBSERVER
        and git(observer, "rev-parse", "HEAD:" + path) == reg["observer"]["tree"],
        "unregistered observer checkout",
    )
    for module in ("execs", "pilot", "cgu_inputs", "macho_paths"):
        need(
            git(observer, "hash-object", str(observer / path / (module + ".py")))
            == reg["observer"][module],
            module,
        )
    need(not git(observer, "status", "--porcelain", "--", path), "edited observer inputs")
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        key, name = line.split("  ")
        need(Path(name).name == name and sha(HERE / name) == key, ("dirty protocol", name))


def live():
    repo = Path(os.environ["GITHUB_WORKSPACE"])
    expected = os.environ["REVIEWED_HEAD"]
    run = int(os.environ["GITHUB_RUN_ID"])
    need(
        os.environ["GITHUB_REPOSITORY"] == REPO
        and os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH
        and os.environ["GITHUB_SHA"] == expected
        and git(repo, "rev-parse", "HEAD") == expected,
        "outside source-bound enrollment",
    )
    query = urlencode(
        {"head_sha": expected, "branch": BRANCH, "event": "workflow_dispatch", "per_page": 100}
    )
    runs = api("runs?" + query)
    need(
        runs["total_count"] == len(runs["workflow_runs"]) == 1,
        "duplicate dispatch, including completed runs",
    )
    r = runs["workflow_runs"][0]
    need(
        r["id"] == run
        and r["run_attempt"] == 1
        and r["head_sha"] == expected
        and r["path"] == ".github/workflows/ci.yml",
        "foreign workflow",
    )
    jobs = api(f"runs/{run}/attempts/1/jobs?per_page=100")
    need(jobs["total_count"] == len(jobs["jobs"]) == 1, "unexpected job roster")
    job = jobs["jobs"][0]
    need(
        job["head_sha"] == expected
        and job["run_attempt"] == 1
        and job["run_id"] == run
        and job["runner_name"] == os.environ["RUNNER_NAME"]
        and job["name"] == "Actual rc22 Apple distribution and checked native linkers"
        and job["labels"] == ["namespace-profile-macos-15"]
        and os.environ["RUNNER_OS"] == "macOS"
        and os.environ["RUNNER_ARCH"] == "ARM64",
        "foreign live native CI identity",
    )
    fixed = json.loads((HERE / "registration.json").read_bytes())["corrected_smoke"]

    def content(name):
        part = "repos/" + REPO + "/contents/" + name + "?ref=" + fixed["coordinator"]
        row = json.loads(subprocess.check_output(["gh", "api", part]))
        return (row["sha"], base64.b64decode(row["content"]))

    blob, smoke = content("scripts/smoke-test-relink.sh")
    need(
        blob == fixed["blob"] and smoke == (HERE / "proposed-release-relink.sh").read_bytes(),
        "wrong #225 smoke at exact commit",
    )
    _, manifest = content("toolchains/1.99.0/22.json")
    pins = json.loads(manifest)["sources"]
    need(
        pins["rust"]["revision"] == fixed["manifest_rust"]
        and pins["cargo"]["revision"] == fixed["cargo"],
        "wrong #225 toolchain source pins",
    )
    validate_inputs(repo, repo / "observer")
    return {
        "run": run,
        "attempt": 1,
        "head": expected,
        "branch": BRANCH,
        "workflow": r["path"],
        "receipt_url": r["html_url"],
        "job": job["id"],
        "runner": os.environ["RUNNER_NAME"],
        "os": os.environ["RUNNER_OS"],
        "arch": os.environ["RUNNER_ARCH"],
    }


if __name__ == "__main__":
    print(json.dumps(live(), sort_keys=True))
