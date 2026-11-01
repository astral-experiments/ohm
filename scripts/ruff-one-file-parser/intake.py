"""Enroll a distinct host after the preceding two studies and restore the original signed SDK."""

import datetime as dt
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import protocol as p
import acquire

c, f = p.c, p.f


def excluded_host(catalog, expected):
    run, jobs, artifacts = catalog
    (job,) = jobs
    (asset,) = artifacts
    f.require(
        run["id"] == job["run_id"] == asset["workflow_run"]["id"] == expected["run"]
        and run["head_sha"] == asset["workflow_run"]["head_sha"] == expected["head"]
        and run["head_branch"] == expected["branch"] and run["run_attempt"] == 1
        and run["path"] == ".github/workflows/ci.yml" and run["event"] == "workflow_dispatch"
        and run["repository"]["full_name"] == c.REPO
        and run["status"] == job["status"] == "completed"
        and run["conclusion"] == job["conclusion"] == "failure"
        and (job["id"], job["name"], job["runner_name"], job["runner_id"], job["completed_at"])
            == (expected["job"], expected["name"], expected["runner"], expected["runner_id"], expected["ended"])
        and (asset["id"], asset["name"], asset["digest"], asset["size_in_bytes"])
            == (expected["artifact"], expected["archive_name"], expected["digest"], expected["size"])
        and not asset["expired"],
        "wrong original refused replay",
    )
    return expected


def enroll(book, head, runner, boot):
    assigned = book["jobs"]
    (this,) = assigned
    now, first, six = book["current"], book["first"], book["six"]
    (earlier,) = book["first_jobs"]
    (art,) = book["first_artifacts"]
    spec = book["previous"]
    prev = spec["first"]
    f.require(
        set(spec) == {"six", "first"} and set(prev) == {"run", "job", "artifact", "digest", "boot"},
        "wrong prior custody",
    )
    f.require(
        first["head_sha"] == p.FIRST
        and first["path"] == now["path"] == six["path"] == ".github/workflows/ci.yml"
        and first["head_branch"] == c.BRANCH
        and first["status"] == earlier["status"] == "completed"
        and (first["id"], earlier["id"], art["id"], art["digest"])
        == (prev["run"], prev["job"], prev["artifact"], prev["digest"])
        and earlier["run_id"] == art["workflow_run"]["id"] == first["id"]
        and art["workflow_run"]["head_sha"] == p.FIRST
        and art["name"] == "signed-gnu-ruff-default-first-a-owners"
        and art["size_in_bytes"] > 0
        and not art["expired"]
        and len(prev["digest"]) == 71
        and prev["digest"].startswith("sha256:"),
        "first-A study or archive",
    )
    env = dict(
        GITHUB_RUN_ID=str(first["id"]),
        REVIEWED_HEAD=p.FIRST,
        GITHUB_SHA=p.FIRST,
        GITHUB_REPOSITORY=c.REPO,
        GITHUB_REF="refs/heads/" + c.BRANCH,
        GITHUB_RUN_ATTEMPT="1",
        GITHUB_JOB="diagnostic",
        RUNNER_NAME=earlier["runner_name"],
    )
    fixed = c.read(p.HERE / "excluded-hosts.json")
    f.require(spec == fixed["previous"] and set(book["replays"]) == set(fixed["replays"]),
              "different predeclared original hosts")
    replays = [excluded_host(book["replays"][k], shadow) for k, shadow in sorted(fixed["replays"].items())]
    old = acquire.enrollment(
        six,
        book["six_jobs"],
        book["six_artifacts"],
        spec["six"],
        first,
        book["first_jobs"],
        env,
        prev["boot"],
    )
    all_old = [
        *replays,
        *old["excluded"],
        dict(boot=old["boot"], runner=old["runner"], runner_id=old["runner_id"]),
    ]
    f.require(
        now["head_sha"] == head
        and now["head_branch"] == p.BRANCH
        and now["run_attempt"] == 1
        and now["event"] == "workflow_dispatch"
        and now["id"] not in {first["id"], six["id"], *(r["run"] for r in replays)}
        and now["repository"]["full_name"] == c.REPO
        and not book["initial_artifacts"]
        and this["run_id"] == now["id"]
        and this["name"] == p.JOB
        and this["runner_name"] == runner
        and this["runner_id"] > 0
        and this["id"] not in {prev["job"], *c.BLOCKED_JOBS, *(r["job"] for r in replays)}
        and all(dt.datetime.fromisoformat(r["ended"]) <= dt.datetime.fromisoformat(this["started_at"]) for r in replays)
        and dt.datetime.fromisoformat(earlier["completed_at"])
        <= dt.datetime.fromisoformat(this["started_at"])
        and str(uuid.UUID(boot)) == boot
        and all(
            v["boot"] != boot and v["runner"] != runner and v["runner_id"] != this["runner_id"]
            for v in all_old
        ),
        "overlap, reassigned earlier boot, or incorrect new job",
    )
    return dict(
        head=head, run=now["id"], job=this["id"], runner=runner, boot=boot, first=prev, six=spec["six"], refused_replays=replays
    )


def main():
    env = os.environ
    head = env["REVIEWED_HEAD"]
    run = int(env["GITHUB_RUN_ID"])
    root = Path(env["RUNNER_TEMP"]) / "ohm-branch-object-qa"
    out = root / "logs"
    f.require(
        c.git(p.HERE, "rev-parse", "HEAD").decode().strip() == head == env["GITHUB_SHA"]
        and env["GITHUB_REF"] == "refs/heads/" + p.BRANCH
        and env["GITHUB_REPOSITORY"] == c.REPO
        and env["GITHUB_JOB"] == "diagnostic"
        and env["GITHUB_RUN_ATTEMPT"] == "1",
        "reviewed checkout and job",
    )
    previous = json.loads(env["EXCLUDED_BOOT_CUSTODY"])
    prior = int(previous["first"]["run"])
    api = acquire.api

    def catalog(i):
        route = f"actions/runs/{i}"
        return (
            api(route),
            api(route + "/attempts/1/jobs?per_page=100")["jobs"],
            api(route + "/artifacts?per_page=100")["artifacts"],
        )

    six, ss, sa = catalog(c.PREVIOUS)
    first, fs, fa = catalog(prior)
    now, ns, na = catalog(run)
    book = dict(
        replays={k: catalog(v["run"]) for k, v in c.read(p.HERE / "excluded-hosts.json")["replays"].items()},
        six=six,
        six_jobs=ss,
        six_artifacts=sa,
        first=first,
        first_jobs=fs,
        first_artifacts=fa,
        current=now,
        jobs=ns,
        initial_artifacts=na,
        previous=previous,
    )
    c.save(out / "catalog.json", book)
    c.save(
        out / "enrollment.json",
        enroll(
            book, head, env["RUNNER_NAME"], Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        ),
    )
    sys.path.insert(0, str(p.HERE.parent / "ruff-repair-tables-pilot"))
    import guards

    state = guards.resources(root, out)
    c.save(out / "resources-before-sdk.json", state)
    guards.admit(state, entry=True)
    f.require(
        min(state["work"], state["receipts"]) >= 25 << 30, "25 GiB free before restoring the signed SDK"
    )
    acquire.install(root, out)


if __name__ == "__main__":
    main()
