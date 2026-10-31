"""Download original native worker packets, verify before queuing them for offline rereading."""

import argparse, json, os, shutil, subprocess, sys
from pathlib import Path

D = Path(__file__).resolve().parent
sys.path.insert(0, str(D))
import reopen as r


def fetch_api(endpoint, raw=False):
    cli = shutil.which("gh-auto") or "gh"
    b = subprocess.check_output([cli, "api", "repos/astral-experiments/ohm/" + endpoint])
    return b if raw else r.h.read(b)


def save(path, raw):
    if path.exists():
        assert path.read_bytes() == raw
    else:
        tmp = path.with_name("." + path.name + ".incoming")
        tmp.write_bytes(raw)
        tmp.replace(path)


def pretty(x):
    return (json.dumps(x, indent=2, sort_keys=True) + "\n").encode()


def main(dest, partial, keep, selected):
    dest.mkdir(exist_ok=True, parents=True)
    run = fetch_api("actions/runs/" + str(r.RUN))
    assert (
        run["head_sha"] == r.HEAD
        and run["run_attempt"] == 1
        and run["event"] == "workflow_dispatch"
    )
    jobs = fetch_api(f"actions/runs/{r.RUN}/jobs?per_page=100")["jobs"]
    byrow = {v["name"][6:8]: v for v in jobs}
    assert set(byrow) == set(r.REG)
    assets = fetch_api(f"actions/runs/{r.RUN}/artifacts?per_page=100")["artifacts"]
    assets = {m["name"]: m for m in assets}
    ready = []
    for row in sorted(r.REG) if not selected else selected:
        stem = "one-package-" + row
        job = byrow[row]
        meta = assets.get(stem)
        if job["status"] != "completed" or not meta:
            assert partial, (row, job["status"])
            continue
        assert job["conclusion"] == "success", (row, job["conclusion"])
        assert (
            meta["workflow_run"]["head_sha"] == r.HEAD
            and meta["workflow_run"]["id"] == r.RUN
            and not meta["expired"]
        )
        desc = {k: meta[k] for k in ("id", "name", "size_in_bytes", "digest", "workflow_run")}
        save(dest / (stem + ".json"), pretty(desc))
        p = dest / (stem + ".zip")
        raw = (
            p.read_bytes()
            if p.is_file()
            else fetch_api(f'actions/artifacts/{meta["id"]}/zip', True)
        )
        bs = r.open_archive(raw, desc, row)
        audit = r.audit(bs, row, desc)
        assert "nsc-runner-" + audit["host"] == job["runner_name"]
        save(dest / (stem + ".readback-v2.json"), pretty(audit))
        ready.append(row)
        if keep and not p.exists():
            assert shutil.disk_usage(dest).free > 256 * (1 << 20) + len(
                raw
            ), "keep a 256 MiB post-write reserve"
            save(p, raw)
        print(
            row,
            "physical packets, complete counter coverage and held outputs verified",
            audit["members"],
            flush=True,
        )
    if len(ready) == 12:
        assert (
            run["status"] == "completed"
            and run["conclusion"] == "success"
            and len({job["runner_name"] for job in jobs}) == len(jobs) == 12
        )
        rows = [
            r.h.read((dest / ("one-package-" + i + ".readback-v2.json")).read_bytes())
            for i in ready
        ]
        save(dest / "verified.json", pretty(r.aggregate(rows)))
        save(
            dest / "jobs.json",
            pretty(
                [
                    {
                        k: job[k]
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
                    for job in jobs
                ]
            ),
        )
        save(
            dest / "run.json",
            pretty(
                {
                    k: run[k]
                    for k in (
                        "id",
                        "head_sha",
                        "event",
                        "run_attempt",
                        "status",
                        "conclusion",
                        "created_at",
                        "updated_at",
                    )
                }
            ),
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    p.add_argument("--partial", action="store_true")
    p.add_argument("--keep", action="store_true")
    p.add_argument("--rows", nargs="*", choices=sorted(r.REG))
    a = p.parse_args()
    main(a.directory, a.partial, a.keep, a.rows)
