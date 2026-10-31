"""Authenticate and decode the two original native jobs. Never run a payload from either ZIP."""

import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media import CFG, REPO, archive_origin, need, save, sha
from reopen import load
from supplement import read, worktree

RUN = 41250511954
HEAD = "cce370a71a4292c14e58bbfc2c62e8b641e712d9"
BRANCH = "charlie/qa-rc22-native-static-worktree-20261031"
GNU = "x86_64-unknown-linux-gnu"
APPLE = "aarch64-apple-darwin"
IDS = {
    GNU: (
        124682878056,
        "nsc-runner-sdu12go0peo22",
        13061012439,
        16920219,
        "e4049b6b5c9fed4c089aafdb3f5d3c048577d5acf08a714a82948263e156f770",
    ),
    APPLE: (
        124682878215,
        "nsc-runner-5jdglub6ic7co",
        13061087498,
        123855,
        "1e761d6a1d6c30660067e48bd6895c26e036276a9ed67e207b9db727dccdc7ba",
    ),
}
RED = "Independently decode new native product, commands and same-inode outputs"
COMMON = [
    "Check first-parent source and reviewer tests",
    "Authenticate original release and preceding QA ZIP",
    "Reopen physical distribution contents",
    "Retain original, partial, or complete QA receipts only",
]
STEPS = {
    GNU: [
        "Checkout exact Cargo delta and receiver",
        "Checkout exact Cargo source seed",
        "GNU static build prerequisites and exact upstream analyzer",
        "Build only four-fix Cargo with authenticated native static settings",
        "Entire GNU release smoke and same-PATH worktree on the new private ELF",
    ],
    APPLE: [
        "Authenticate previous native Apple four-fix Cargo",
        "Apple original package same-PATH linked Git worktree",
        "Apple private four-fix same-PATH linked Git worktree",
    ],
}


def official(run, job, art, target):
    jid, runner, aid, size, digest = IDS[target]
    need(
        (
            run["id"],
            run["head_sha"],
            run["head_branch"],
            run["path"],
            run["event"],
            run["status"],
            run["conclusion"],
            run["run_attempt"],
        )
        == (RUN, HEAD, BRANCH, ".github/workflows/ci.yml", "workflow_dispatch", "completed", "failure", 1)
        and run["repository"]["full_name"] == run["head_repository"]["full_name"] == REPO,
        "different native run",
    )
    need(
        (
            job["id"],
            job["name"],
            job["runner_name"],
            job["run_id"],
            job["head_sha"],
            job["run_attempt"],
            job["status"],
            job["conclusion"],
        )
        == (jid, "Native package supplement (" + target + ")", runner, RUN, HEAD, 1, "completed", "failure"),
        "different native job",
    )
    steps = {s["name"]: s["conclusion"] for s in job["steps"]}
    need(
        len(steps) == len(job["steps"])
        and [k for k, v in steps.items() if v == "failure"] == [RED]
        and all(steps.get(n) == "success" for n in COMMON + STEPS[target])
        and all(steps.get(n) == "skipped" for n in STEPS[APPLE if target == GNU else GNU]),
        "different terminal steps",
    )
    need(
        (
            art["id"],
            art["name"],
            art["size_in_bytes"],
            art["digest"],
            art["expired"],
            art["workflow_run"]["id"],
            art["workflow_run"]["head_sha"],
        )
        == (aid, "rc22-native-static-worktree-" + target, size, "sha256:" + digest, False, RUN, HEAD),
        "different official native ZIP",
    )


def capture(dest):
    dest.mkdir()
    gh = ["gh", "api", "repos/" + REPO + "/actions/"]

    def command(path):
        return gh[:2] + [gh[2] + path]

    def api(path):
        return json.loads(subprocess.check_output(command(path)))

    run = api(f"runs/{RUN}")
    jobs = api(f"runs/{RUN}/jobs")["jobs"]
    artifacts = api(f"runs/{RUN}/artifacts")["artifacts"]
    need(len(jobs) == len(artifacts) == 2, "wrong original roster")
    save(dest / "run.json", run)
    save(dest / "artifacts.json", artifacts)
    for target, (jid, _, aid, size, digest) in IDS.items():
        (job,) = [j for j in jobs if j["id"] == jid]
        (art,) = [a for a in artifacts if a["id"] == aid]
        official(run, job, art, target)
        save(dest / f"job-{jid}.json", job)
        raw = dest / f"{RUN}-{aid}.zip"
        with (
            raw.open("xb") as out,
            subprocess.Popen(command(f"artifacts/{aid}/zip"), stdout=subprocess.PIPE) as p,
        ):
            while chunk := p.stdout.read(1 << 20):
                need(out.tell() + len(chunk) <= size, "oversized ZIP")
                out.write(chunk)
            need(p.wait() == 0 and out.tell() == size, "incomplete ZIP")
        need(sha(raw) == digest, "original SHA mismatch")


def unpack(raw, dest):
    with zipfile.ZipFile(raw) as z:
        rows = z.infolist()
        need(
            len(rows) == len(set(z.namelist())) < 400 and sum(x.file_size for x in rows) < 150 << 20,
            "excessive or duplicate ZIP",
        )
        for row in rows:
            p = PurePosixPath(row.filename)
            need(
                not p.is_absolute()
                and ".." not in p.parts
                and not stat.S_ISLNK(row.external_attr >> 16)
                and not (row.flag_bits & 1),
                "unsafe ZIP",
            )
            if row.is_dir():
                continue
            f = dest / p
            f.parent.mkdir(parents=True, exist_ok=True)
            with z.open(row) as src, f.open("xb") as out:
                shutil.copyfileobj(src, out)


def provenance(folder, target):
    jid, runner, *_ = IDS[target]
    enroll = load(folder / "enrollment.json")
    need(
        enroll
        == {
            "GITHUB_SHA": HEAD,
            "GITHUB_REF": "refs/heads/" + BRANCH,
            "GITHUB_RUN_ID": str(RUN),
            "GITHUB_RUN_ATTEMPT": "1",
            "RUNNER_NAME": runner,
            "OHM_QA_TARGET": target,
        },
        "unmatched native input",
    )
    t = CFG["targets"][target]
    sources = [
        (t["platform"], "Retain distribution artifacts"),
        (CFG["global"], "Retain global release assets"),
    ]
    if target == APPLE:
        sources.append((t["native"], "Publish reusable native SDK"))
    for spec, step in sources:
        receipt = load(folder / f"official-{spec['artifact']}.json")
        archive_origin(spec, receipt["run"], receipt["job"], receipt["artifact"], step)
    catalog = load(folder / "archive-binaries.json")
    with zipfile.ZipFile(folder / "previous-qa.zip") as old:
        need(
            json.loads(old.read("archive-binaries.json")) == catalog
            and len(catalog) == (120 if target == GNU else 119)
            and json.loads(old.read("release.json")) == load(folder / "release.json"),
            "changed native distribution",
        )


def mutations(folder):
    actual = load(folder / "worktree-commands.json")
    need(
        len(actual) == 15 and actual[-2]["status"] == 101 and actual[-1]["status"] == 0,
        "wrong enrolled native trace",
    )
    worktree(folder)
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp)
        for n in ("worktree.json", "worktree-registry.json"):
            shutil.copyfile(folder / n, path / n)
        cases = {
            "missing_diagnostic": actual[:-2] + actual[-1:],
            "missing_git_seal": actual[:-1],
            "false_git_common_dir": actual[:-1] + [actual[-1] | {"stdout": "/wrong/.git\n"}],
            "wrong_exit": actual[:-2] + [actual[-2] | {"status": 0}, actual[-1]],
            "wrong_diagnostic": actual[:-2]
            + [actual[-2] | {"stdout": actual[-2]["stdout"].replace("E0277", "E0308")}, actual[-1]],
        }
        for name, events in cases.items():
            save(path / "worktree-commands.json", events)
            try:
                worktree(path)
            except ValueError as exc:
                need(str(exc) == "wrong typed negative", "unrelated mutation refusal")
                continue
            raise ValueError("accepted mutation " + name)
    return list(cases)


def review(inputs, out):
    run = load(inputs / "run.json")
    arts = load(inputs / "artifacts.json")
    result = {}
    need(len(arts) == 2, "wrong ZIP count")
    for target, (jid, _, aid, size, digest) in IDS.items():
        (art,) = [a for a in arts if a["id"] == aid]
        official(run, load(inputs / f"job-{jid}.json"), art, target)
        raw = inputs / f"{RUN}-{aid}.zip"
        need(raw.stat().st_size == size and sha(raw) == digest, "wrong original bytes")
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            unpack(raw, data)
            provenance(data, target)
            # The original native summary refused the final Git command before writing its certificate.
            need(not (data / "supplement-verified.json").exists(), "unexpected previous certificate")
            summary = read(data)
            proofs = {}
            for role in ["static-fourfix"] if target == GNU else ["packaged", "fourfix"]:
                cell = data / role / ("full" if target == GNU else "focus")
                proofs[role] = mutations(cell)
            result[target] = {
                "job": jid,
                "original_job_conclusion": "failure",
                "original_failure": RED,
                "zip_sha256": digest,
                "artifact": aid,
                "original_bytes": size,
                "replayed": summary,
                "rejected_mutations": proofs,
            }
    save(out, {"run": RUN, "head": HEAD, "reader_head": os.environ.get("GITHUB_SHA"), "results": result})
    print("Accepted both original ZIPs and rejected all fifteen real-transcript mutations.")


if __name__ == "__main__":
    if sys.argv[1] == "capture" and len(sys.argv) == 3:
        capture(Path(sys.argv[2]))
    elif sys.argv[1] == "review" and len(sys.argv) == 4:
        review(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        raise SystemExit("capture DEST or review ORIGINALS OUTPUT")
