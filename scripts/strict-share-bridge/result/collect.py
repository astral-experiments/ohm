"""Fetch the two enrolled GitHub artifacts without running any compiler or modifying an SDK."""

import argparse, json, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reopen as r


def api(s, buf=False):
    a = subprocess.check_output(
        [shutil.which("gh-auto") or "gh", "api", "repos/astral-experiments/ohm/" + s]
    )
    return a if buf else r.J(a)


def save(p, v):
    if p.is_file():
        assert p.read_bytes() == v
    else:
        p.write_bytes(v)


def formatted(v):
    return (json.dumps(v, sort_keys=True, indent=2) + "\n").encode()


def download(out, which, keep):
    out.mkdir(exist_ok=True, parents=True)
    run = api("actions/runs/" + str(r.RUN))
    assert (
        run["run_attempt"] == 1
        and run["head_sha"] == r.HEAD
        and run["event"] == "workflow_dispatch"
    )
    jobs = api(f"actions/runs/{r.RUN}/jobs?per_page=100")["jobs"]
    assets = api(f"actions/runs/{r.RUN}/artifacts")["artifacts"]
    assert len(jobs) == 2
    for row in which:
        stem = "share-bridge-" + row
        (job,) = [j for j in jobs if j["name"] == f"pair ({row})"]
        assert job["status"] == "completed" and job["conclusion"] == "success", job["conclusion"]
        (meta,) = [a for a in assets if a["name"] == stem and not a["expired"]]
        desc = {k: meta[k] for k in ("id", "name", "size_in_bytes", "digest", "workflow_run")}
        save(out / (stem + ".json"), formatted(desc))
        p = out / (stem + ".zip")
        contents = (
            p.read_bytes()
            if p.is_file()
            else api("actions/artifacts/" + str(meta["id"]) + "/zip", True)
        )
        bundle = r.open_archive(contents, desc, row)
        if keep and not p.exists():
            assert shutil.disk_usage(out).free > 256 * (1 << 20) + len(contents)
            save(p, contents)
        rowout = r.audit(bundle, row, desc)
        assert job["runner_name"] == "nsc-runner-" + rowout["host"]
        save(out / (stem + ".verified.json"), formatted(rowout))
        print(
            row,
            "all four check/linked arms and native provider histories independently reopened",
            flush=True,
        )
    if set(which) == {"01", "02"}:
        assert (
            run["status"] == "completed"
            and run["conclusion"] == "success"
            and len({j["runner_name"] for j in jobs}) == 2
        )
        save(
            out / "run.json",
            formatted(
                {
                    k: run[k]
                    for k in (
                        "id",
                        "event",
                        "head_sha",
                        "run_attempt",
                        "status",
                        "conclusion",
                        "created_at",
                        "updated_at",
                    )
                }
            ),
        )
        save(
            out / "jobs.json",
            formatted(
                [
                    {
                        k: j[k]
                        for k in (
                            "id",
                            "name",
                            "runner_name",
                            "run_attempt",
                            "status",
                            "conclusion",
                            "started_at",
                            "completed_at",
                        )
                    }
                    for j in jobs
                ]
            ),
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("destination", type=Path)
    p.add_argument("--rows", nargs="+", default=["01", "02"], choices=["01", "02"])
    p.add_argument("--keep", action="store_true")
    a = p.parse_args()
    download(a.destination, a.rows, a.keep)
