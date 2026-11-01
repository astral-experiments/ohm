"""Verify both original result ZIPs against their official job, then replay the frozen source reader."""

import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import zipfile

import binding as b
import reopen


REPOSITORY = "astral-experiments/ohm"
ARTIFACTS = ("packed-ref-source-and-driver", "packed-ref-sdk-and-resources")
JOB_NAME = "Build and qualify the bounded packed Git ref reader"
STEPS = {
    "Reopen reviewed source and retained compiler verifier",
    "Restore the authenticated D and E source SDKs",
    "Build the candidate and exercise the original and corrected native unit suites",
    "Reopen both physical SDKs and the native regression plus three run-makes",
}


def check_job(head, run_id, job_id, run, jobs, artifacts):
    b.need(
        (
            run["id"],
            run["head_sha"],
            run["head_branch"],
            run["run_attempt"],
            run["event"],
            run["path"],
            run["status"],
            run["conclusion"],
        )
        == (
            run_id,
            head,
            b.REF.removeprefix("refs/heads/"),
            1,
            "workflow_dispatch",
            ".github/workflows/ci.yml",
            "completed",
            "success",
        )
        and run["repository"]["full_name"]
        == run["head_repository"]["full_name"]
        == REPOSITORY,
        "wrong reviewed job, source or scope",
    )
    b.need(jobs["total_count"] == len(jobs["jobs"]) == 1, "extra or missing source job")
    (job,) = jobs["jobs"]
    b.need(
        (
            job["id"],
            job["run_id"],
            job["head_sha"],
            job["name"],
            job["status"],
            job["conclusion"],
            job["labels"],
        )
        == (
            job_id,
            run_id,
            head,
            JOB_NAME,
            "completed",
            "success",
            ["namespace-profile-ubuntu-24-04-16"],
        )
        and job["run_attempt"] == 1
        and job["head_branch"] == run["head_branch"]
        and all(
            s["status"] == "completed" and s["conclusion"] == "success"
            for s in job["steps"]
        )
        and STEPS <= {s["name"] for s in job["steps"]},
        "source and native observations did not all complete",
    )
    media = artifacts["artifacts"]
    b.need(
        artifacts["total_count"] == len(media) == len(ARTIFACTS)
        and {a["name"] for a in media} == set(ARTIFACTS),
        "wrong official ZIP set",
    )
    for a in media:
        origin = a["workflow_run"]
        b.need(
            not a["expired"]
            and (origin["id"], origin["head_sha"], origin["head_branch"])
            == (run_id, head, run["head_branch"])
            and origin["repository_id"]
            == origin["head_repository_id"]
            == run["repository"]["id"],
            "foreign archive",
        )
    return {
        a["name"]: {k: a[k] for k in ("id", "size_in_bytes", "digest")} for a in media
    }


def extract(path, root, record, kinds):
    b.need(
        path.is_file()
        and not path.is_symlink()
        and 0 < path.stat().st_size == record["size_in_bytes"] <= 512 * 2**20
        and "sha256:" + b.sha(path) == record["digest"],
        "not the exact complete official ZIP",
    )
    root.mkdir()
    total = 0
    with zipfile.ZipFile(path) as z:
        b.need(
            len(z.namelist()) == len(set(z.namelist())) and len(z.namelist()) < 3000,
            "bad ZIP inventory",
        )
        for entry in z.infolist():
            n = PurePosixPath(entry.filename)
            b.need(
                not n.is_absolute()
                and str(n) == entry.filename.rstrip("/")
                and ".." not in n.parts
                and n.parts
                and "\\" not in entry.filename,
                "invalid ZIP path",
            )
            if entry.is_dir() or n.parts[0] not in kinds:
                continue
            total += entry.file_size
            b.need(
                stat.S_ISREG(entry.external_attr >> 16)
                and total <= 512 * 2**20
                and entry.file_size <= 256 * 2**20,
                "nonregular or oversized member",
            )
            dest = root / n
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(entry) as src, dest.open("xb") as out:
                shutil.copyfileobj(src, out, 1 << 20)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=int)
    parser.add_argument("job", type=int)
    parser.add_argument("source_zip", type=Path)
    parser.add_argument("sdk_zip", type=Path)
    parser.add_argument("scratch", type=Path)
    args = parser.parse_args()
    head = b.rev(b.HERE, "HEAD")

    def get(suffix):
        return json.loads(
            subprocess.check_output(
                ["gh-auto", "api", "repos/" + REPOSITORY + "/actions/" + suffix],
                cwd=b.HERE,
            )
        )

    root = "runs/" + str(args.run)
    catalog = check_job(
        head,
        args.run,
        args.job,
        get(root),
        get(root + "/attempts/1/jobs?per_page=100"),
        get(root + "/artifacts?per_page=100"),
    )
    with tempfile.TemporaryDirectory(dir=args.scratch) as tmp:
        raw = Path(tmp) / "source"
        logs = Path(tmp) / "logs"
        extract(
            args.source_zip,
            raw,
            catalog[ARTIFACTS[0]],
            {"host-entry", "P", "source-qualified.json"},
        )
        extract(args.sdk_zip, logs, catalog[ARTIFACTS[1]], {"sdk"})
        result = reopen.verify(raw, logs, None)
        published = reopen.load(raw / "source-qualified.json")
        b.need(
            result["qa"] == head
            and result["run"] == str(args.run)
            and published == result | {"physical_installation_reopened": True},
            "inconsistent published and independently reopened source",
        )
        print(
            json.dumps(
                {
                    "run": args.run,
                    "job": args.job,
                    "head": head,
                    "artifacts": catalog,
                    "source": result,
                },
                sort_keys=True,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
