"""Stream and authenticate the two artifacts. Preserve raw ZIPs only within the chosen budget."""

from pathlib import Path
import argparse, json, shutil, subprocess, sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reopen as r


def api(s, raw=False):
    data = subprocess.check_output(
        [shutil.which("gh-auto") or "gh", "api", "repos/astral-experiments/ohm/" + s]
    )
    return data if raw else r.J(data)


def save(p, data):
    if not isinstance(data, bytes):
        data = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()
    if p.exists():
        assert p.read_bytes() == data, p
    else:
        p.write_bytes(data)


def collect(out, which, keep):
    out.mkdir(exist_ok=True, parents=True)
    status = api("actions/runs/" + str(r.RUN))
    jobs = api(f"actions/runs/{r.RUN}/jobs?per_page=100")["jobs"]
    assets = api(f"actions/runs/{r.RUN}/artifacts")["artifacts"]
    assert (
        status["head_sha"] == r.HEAD
        and status["run_attempt"] == 1
        and status["event"] == "workflow_dispatch"
    )
    assert len(jobs) == 2 and len({j["runner_name"] for j in jobs}) == 2
    outrows = []
    for row in which:
        (job,) = [j for j in jobs if j["name"] == f"pair ({row})"]
        assert job["conclusion"] == "success", (row, job["conclusion"])
        label = "actual-compiler-loop-" + row
        (obj,) = [v for v in assets if v["name"] == label and not v["expired"]]
        desc = {
            k: obj[k] for k in ("id", "name", "size_in_bytes", "digest", "workflow_run")
        }
        data = out / (label + ".zip")
        bits = (
            data.read_bytes()
            if data.is_file()
            else api("actions/artifacts/" + str(obj["id"]) + "/zip", True)
        )
        packet = r.opened(bits, desc, row)
        if keep and not data.exists():
            assert shutil.disk_usage(out).free > 256 * 2**20 + len(bits), (
                "low free space, use in-memory mode and save raw archives off-host"
            )
            save(data, bits)
        save(out / (label + ".json"), desc)
        verified = r.audit(packet, row, desc)
        assert "nsc-runner-" + verified["host"] == job["runner_name"]
        save(out / (label + ".verified.json"), verified)
        outrows.append(verified)
        print(row, "reopened", verified["members"], "members", flush=True)
        del bits, packet
    if set(r.ORDER) == set(which):
        assert status["conclusion"] == "success"
        save(out / "verified.json", r.final(outrows))
        save(
            out / "run.json",
            {
                k: status[k]
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
            },
        )
        save(
            out / "jobs.json",
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
            ],
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument(
        "--rows", nargs="+", choices=tuple(r.ORDER), default=list(r.ORDER)
    )
    parser.add_argument("--keep", action="store_true")
    parser.add_argument(
        "--run",
        type=int,
        default=r.RUN,
        help="A fresh manual run of the exact same workflow revision",
    )
    a = parser.parse_args()
    r.RUN = a.run
    collect(a.out, a.rows, a.keep)
