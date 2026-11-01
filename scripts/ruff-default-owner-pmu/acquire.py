"""Authenticate the signed GNU package, six excluded workers and this fresh worker."""

import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as c


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", "repos/" + c.REPO + "/" + path]))


def enrollment(prior, jobs, artifacts, excluded, current, this_jobs, env, boot):
    c.need(
        prior["id"] == c.PREVIOUS
        and prior["head_sha"] == c.PREVIOUS_HEAD
        and prior["run_attempt"] == 1
        and prior["event"] == "workflow_dispatch"
        and prior["status"] == "completed",
        "six-host run not terminal",
    )
    c.need(
        len(jobs) == len(excluded) == len(artifacts) == 6 and {j["id"] for j in jobs} == set(c.BLOCKED_JOBS),
        "incomplete previous six jobs, artifacts or boot records",
    )
    c.need(
        len(this_jobs) == 1
        and current["id"] == int(env["GITHUB_RUN_ID"])
        and current["head_sha"] == env["REVIEWED_HEAD"] == env["GITHUB_SHA"]
        and current["run_attempt"] == 1
        and current["event"] == "workflow_dispatch"
        and current["head_branch"] == c.BRANCH
        and env["GITHUB_REPOSITORY"] == c.REPO
        and env["GITHUB_REF"] == "refs/heads/" + c.BRANCH
        and env["GITHUB_RUN_ATTEMPT"] == "1"
        and env["GITHUB_JOB"] == "diagnostic",
        "wrong current job/attempt",
    )
    this = this_jobs[0]
    c.need(
        this["name"] == "Signed GNU Ruff first-A instruction owners"
        and this["runner_name"] == env["RUNNER_NAME"]
        and this["runner_id"] > 0
        and this["id"] not in c.BLOCKED_JOBS,
        "current assigned worker",
    )
    by_job = {j["id"]: j for j in jobs}
    earlier = []
    for i, (record, job_id) in enumerate(zip(excluded, c.BLOCKED_JOBS, strict=True), 1):
        job = by_job[job_id]
        pos = f"{i:02}"
        (art,) = [a for a in artifacts if a["name"] == "gnu-sorted-packed-ruff-cli-confirmation-" + pos]
        c.need(
            set(record) == {"job", "artifact", "digest", "boot"}
            and record["job"] == job_id
            and record["artifact"] == art["id"]
            and record["digest"] == art["digest"]
            and len(record["digest"]) == 71
            and record["digest"].startswith("sha256:")
            and str(uuid.UUID(record["boot"])) == record["boot"]
            and art["size_in_bytes"] > 0
            and job["name"] == "GNU sorted packed Ruff CLI confirmation " + pos
            and job["status"] == "completed"
            and job["runner_name"]
            and job["runner_id"] > 0
            and job["completed_at"]
            and dt.datetime.fromisoformat(job["completed_at"]) <= dt.datetime.fromisoformat(this["started_at"]),
            "incorrect excluded job, boot catalog or overlapping job time",
        )
        earlier.append(
            dict(**record, runner=job["runner_name"], runner_id=job["runner_id"], ended=job["completed_at"])
        )
    c.need(
        len({x["boot"] for x in earlier})
        == len({x["runner"] for x in earlier})
        == len({x["runner_id"] for x in earlier})
        == 6
        and str(uuid.UUID(boot)) == boot
        and boot not in {x["boot"] for x in earlier}
        and this["runner_name"] not in {x["runner"] for x in earlier}
        and this["runner_id"] not in {x["runner_id"] for x in earlier},
        "old boot or runner",
    )
    c.need(this["id"] != c.REFUSED["job"] and current["id"] != c.REFUSED["run"]
           and boot != c.REFUSED["boot"] and this["runner_name"] != c.REFUSED["runner"]
           and this["runner_id"] != c.REFUSED["runner_id"]
           and dt.datetime.fromisoformat(this["started_at"]) >= dt.datetime.fromisoformat(c.REFUSED["ended"]),
           "overlapping or repeated worker from the rejected metadata-probe census")
    return dict(
        excluded_run=c.PREVIOUS,
        excluded_refusal=c.REFUSED,
        excluded=earlier,
        run=current["id"],
        head=current["head_sha"],
        job=this["id"],
        boot=boot,
        runner=this["runner_name"],
        runner_id=this["runner_id"],
        started=this["started_at"],
    )


def extract(package, output):
    c.need(
        package.stat().st_size == c.SDK["asset"]["size"] and c.sha(package) == c.SDK["asset"]["sha256"],
        "GNU release bytes",
    )
    output.mkdir(parents=True)
    selected = {row[0]: name for name, row in c.SDK["members"].items()}
    c.need(len(selected) == 79, "native component inventory")
    seen = set()
    with tarfile.open(package, "r|gz") as t:
        for member in t:
            name = selected.get(member.name)
            if name is None:
                continue
            path = output / name
            _, mode, size, digest = c.SDK["members"][name]
            c.need(
                name not in seen
                and member.isreg()
                and member.mode == mode
                and member.size == size
                and Path(name).as_posix() == name
                and ".." not in Path(name).parts
                and not Path(name).is_absolute(),
                "native package member",
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            with t.extractfile(member) as src, path.open("xb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            path.chmod(mode)
            c.need(c.sha(path) == digest, "extracted member bytes")
            seen.add(name)
    c.need(seen == set(c.SDK["members"]), "incomplete native distribution")
    return verify_sdk(output)


def verify_sdk(folder):
    values = {}
    for name, (_, mode, size, digest) in c.SDK["members"].items():
        path = folder / name
        s = path.stat()
        c.need(
            path.is_file()
            and not path.is_symlink()
            and (s.st_mode & 0o7777, s.st_size, c.sha(path)) == (mode, size, digest),
            "signed installed member: " + name,
        )
        values[name] = [digest, s.st_dev, s.st_ino, mode, size, s.st_mtime_ns, s.st_ctime_ns]
    c.need(
        set(values) == {str(x.relative_to(folder)) for x in folder.rglob("*") if x.is_file() or x.is_symlink()},
        "additional SDK entries",
    )
    return values


def main():
    from common import save

    root = Path(os.environ["RUNNER_TEMP"]).resolve() / "ohm-branch-object-qa"
    out = root / "logs"
    job = int(os.environ["GITHUB_RUN_ID"])
    os.umask(0o022)
    c.need(
        root.is_dir()
        and not root.is_symlink()
        and c.git(HERE, "rev-parse", "HEAD").decode().strip() == os.environ["GITHUB_SHA"],
        "fresh hosted source",
    )
    prior = api(f"actions/runs/{c.PREVIOUS}")
    old_jobs = api(f"actions/runs/{c.PREVIOUS}/attempts/1/jobs?per_page=100")["jobs"]
    old_art = api(f"actions/runs/{c.PREVIOUS}/artifacts?per_page=100")["artifacts"]
    current = api(f"actions/runs/{job}")
    this_jobs = api(f"actions/runs/{job}/attempts/1/jobs?per_page=100")["jobs"]
    c.need(api(f"actions/runs/{job}/artifacts")["total_count"] == 0, "artifacts precede current enrollment")
    excluded = json.loads(os.environ["EXCLUDED_BOOT_CUSTODY"])
    state = enrollment(
        prior,
        old_jobs,
        old_art,
        excluded,
        current,
        this_jobs,
        os.environ,
        Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    )
    save(out / "enrollment.json", state)
    save(
        out / "catalog.json",
        dict(
            prior=prior, jobs=old_jobs, artifacts=old_art, excluded=excluded, current=current, this_jobs=this_jobs
        ),
    )
    asset = api("releases/assets/" + str(c.SDK["asset"]["id"]))
    expected = c.SDK["asset"]
    c.need(
        asset["id"] == expected["id"]
        and asset["name"] == expected["name"]
        and asset["size"] == expected["size"]
        and asset["digest"] == "sha256:" + expected["sha256"],
        "official release asset",
    )
    package = root / expected["name"]
    with package.open("xb") as f:
        subprocess.run(
            [
                "gh",
                "api",
                "-H",
                "Accept: application/octet-stream",
                "repos/" + c.REPO + "/releases/assets/" + str(asset["id"]),
            ],
            stdout=f,
            check=True,
        )
    sdk = root / "home/.rustup/toolchains/ohm"
    values = extract(package, sdk)
    save(out / "sdk.json", values)
    save(out / "asset.json", expected)
    proxies = root / "home/.cargo/bin"
    proxies.mkdir(parents=True)
    rustup = Path(shutil.which("rustup")).resolve(strict=True)
    shutil.copyfile(rustup, proxies / "rustup")
    (proxies / "rustup").chmod(0o755)
    c.need(c.sha(rustup) == c.sha(proxies / "rustup"), "rustup shim")
    for name in ("cargo", "rustc", "rustdoc"):
        (proxies / name).symlink_to("rustup")
    save(out / "proxy.json", {"host": str(rustup), "sha256": c.sha(rustup)})
    package.unlink()


if __name__ == "__main__":
    main()
