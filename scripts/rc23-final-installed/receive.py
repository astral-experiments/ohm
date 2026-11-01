"""Receive the exact ordinary build, assembly and both stock smokes for this release."""

import argparse
from functools import cache
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from verify import (
    COORDINATOR,
    GLOBAL,
    MANIFEST_SHA,
    SOURCES,
    TARGETS,
    TOOLCHAIN,
    coordinator,
    digest,
    frozen,
    head,
    names,
    require,
    save,
    sha,
    staged,
)

REPO = "astral-experiments/ohm"
REPO_ID = 1319437234
RUN, PLAN = 41351902967, 124983724367
PROVIDER = "ef93e73f36ff44577d10d9b412c78a3015896110"
SOURCE_BRANCH = "charlie/codex-rc23-formatter-qualified"
BRANCH = "charlie/qa-rc23-formatter-installed-20261101"
SOURCE_PROTOCOL = "375f7eb622fde01d5e04ae32c204c0af61b20b9295f085a26ad2a18b1b00a30f"
MIB = 1 << 20
BUILD = dict(zip(TARGETS, (124983770676, 124983770712)))
RUNNERS = dict(
    zip(
        TARGETS,
        (("namespace-profile-ubuntu-24-04-16", "ubuntu-24.04"), ("macos-15", "namespace-profile-macos-15")),
    )
)
STAMP = re.compile(r"^(?:\ufeff)?\d{4}-\d\d-\d\dT[\d:.]+Z ")
SOURCE = "cross-evidence/source.json"
SLOT = "source/reports/slot-source.json"
JOBS = {"plan": "plan", "assemble": "assemble"}
for t, (b, s) in RUNNERS.items():
    JOBS["build/" + t] = f"build ({t}, {b})"
    JOBS["smoke/" + t] = f"smoke-test ({t}, {s})"
BASE_STEPS = {
    "plan": ("Verify the published candidate and manifest", "Read and validate manifest"),
    "assemble": (
        "Download verified distribution assets",
        "Verify and assemble release assets",
        "Retain global release assets",
    ),
    "smoke": (
        "Download platform distribution assets",
        "Download universal release installer",
        "Install rust-analyzer",
        "Smoke test Ohm toolchain",
    ),
    "build": (
        "Check out the published candidate manifest and release driver",
        "Verify the published manifest and all four source pins",
        "Prepare pinned Wild linker",
        "Build optimized extended Rust distribution",
        "Write build provenance",
        "Stage versioned distribution assets",
        "Retain distribution artifacts",
        "Retain exact source verification",
    ),
}


def endpoint(gh, path, raw=False):
    return [gh, "api", *(raw_opt(gh) if raw else []), "repos/" + REPO + "/" + path]


@cache
def raw_opt(gh):
    help_text = subprocess.check_output([gh, "api", "--help"], stderr=subprocess.STDOUT, timeout=20)
    return (
        ["--allow-escape-sequences"]
        if re.search(rb"(?m)^\s*--allow-escape-sequences(?:\s|$)", help_text)
        else []
    )


def api(gh, path):
    return json.loads(subprocess.check_output(endpoint(gh, path), timeout=90))


def snapshot(gh):
    base = f"actions/runs/{RUN}"
    return [
        api(gh, p) for p in (base, base + "/attempts/1/jobs?per_page=100", base + "/artifacts?per_page=100")
    ]


def run_identity(run):
    require(
        run["repository"]["id"] == run["head_repository"]["id"] == REPO_ID,
        "different publisher repository ID",
    )
    require(
        (
            run["id"],
            run["run_attempt"],
            run["head_sha"],
            run["head_branch"],
            run["event"],
            run["path"],
            run["repository"]["full_name"],
            run["head_repository"]["full_name"],
        )
        == (RUN, 1, PROVIDER, SOURCE_BRANCH, "workflow_dispatch", ".github/workflows/ci.yml", REPO, REPO),
        "different original workflow",
    )


def job_identity(job, key):
    require(
        (job["name"], job["run_id"], job["run_attempt"], job["head_sha"], job["status"], job["conclusion"])
        == (JOBS[key], RUN, 1, PROVIDER, "completed", "success"),
        ("failed or foreign producer", key),
    )
    expected_id = PLAN if key == "plan" else BUILD.get(key.removeprefix("build/"))
    require(
        job["id"] > 0 and (expected_id is None or job["id"] == expected_id), "different first-attempt job"
    )
    role = key.split("/")[0]
    steps = BASE_STEPS[role]
    if role == "build":
        llvm = (
            "Install pinned LLVM BOLT tools"
            if key.endswith(TARGETS[0])
            else "Install matching LLVM tools for native PGO"
        )
        steps = steps[:2] + (llvm,) + steps[2:]
        crash = [s for s in job["steps"] if s["name"] == "Capture macOS compiler crash"]
        require(
            len(crash) == 1 and (crash[0]["status"], crash[0]["conclusion"]) == ("completed", "skipped"),
            "extra diagnostic build",
        )
    picked = [(s["name"], s["status"], s["conclusion"]) for s in job["steps"] if s["name"] in steps]
    require(
        picked == [(n, "completed", "success") for n in steps],
        ("missing original successful steps", key, picked),
    )
    return job["id"]


def asset_records(run, data):
    limits = {TOOLCHAIN + "-global": 2 * MIB}
    for t in TARGETS:
        limits[TOOLCHAIN + "-" + t] = 1200 * MIB
        limits["rc23-final-source-" + t] = 4 * MIB
    require(data["total_count"] == len(data["artifacts"]), "partial official artifact page")
    out = {}
    for a in data["artifacts"]:
        n = a["name"]
        w = a["workflow_run"]
        require(
            n in limits
            and n not in out
            and not a["expired"]
            and (w["id"], w["head_sha"], w["head_branch"]) == (RUN, PROVIDER, SOURCE_BRANCH)
            and w["repository_id"] == w["head_repository_id"] == run["repository"]["id"],
            "foreign or duplicate artifact",
        )
        require(
            a["id"] > 0
            and 0 < a["size_in_bytes"] <= limits[n]
            and re.fullmatch("sha256:[0-9a-f]{64}", a["digest"]),
            "unbounded or unsigned artifact",
        )
        out[n] = {"id": a["id"], "bytes": a["size_in_bytes"], "sha256": a["digest"][7:]}
    require(len({x["id"] for x in out.values()}) == len(out), "repeated official artifact ID")
    return out


def official(run, jobs, artifacts):
    run_identity(run)
    require(
        (run["status"], run["conclusion"]) == ("completed", "success"), "original workflow has not succeeded"
    )
    require(jobs["total_count"] == len(jobs["jobs"]) == len(JOBS), "incomplete two-native-job workflow")
    byname = {j["name"]: j for j in jobs["jobs"]}
    require(set(byname) == set(JOBS.values()), "different native topology")
    j = {k: job_identity(byname[n], k) for k, n in JOBS.items()}
    require(len(set(j.values())) == len(JOBS), "duplicate job ID")
    assets = asset_records(run, artifacts)
    require(
        set(assets)
        == {TOOLCHAIN + "-global"}
        | {p + t for p in (TOOLCHAIN + "-", "rc23-final-source-") for t in TARGETS},
        "incomplete original release archive roster",
    )
    return {
        "repo": REPO,
        "run": RUN,
        "attempt": 1,
        "head": PROVIDER,
        "coordinator": COORDINATOR,
        "manifest_sha256": MANIFEST_SHA,
        "jobs": j,
        "artifacts": assets,
    }


def bounded_stream(cmd, out, cap, floor, destination):
    h = hashlib.sha256()
    total = 0
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as p:
        try:
            while chunk := p.stdout.read(MIB):
                total += len(chunk)
                require(
                    total <= cap and shutil.disk_usage(destination).free >= floor + len(chunk),
                    "stream exceeds custody reserve or permitted size",
                )
                out.write(chunk)
                h.update(chunk)
            require(p.wait(timeout=180) == 0, "official original transport failed")
        except BaseException:
            p.kill()
            p.wait()
            raise
    return total, h.hexdigest()


def publish(temp, path):
    # A failed transport remains in its partial file and cannot masquerade as a complete original.
    # Concurrent receivers may publish one usable path but must never overwrite another receipt.
    try:
        os.link(temp, path)
    except FileExistsError:
        require(digest(temp) == digest(path), "conflicting concurrent original")
    Path(temp).unlink()


def download(gh, a, path, floor):
    if not path.exists():
        require(
            shutil.disk_usage(path.parent).free >= floor + a["bytes"], "insufficient free bytes for original"
        )
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=path.name + ".partial-", delete=False
        ) as out:
            result = bounded_stream(
                endpoint(gh, f"actions/artifacts/{a['id']}/zip", True), out, a["bytes"], floor, path.parent
            )
            require(result == (a["bytes"], a["sha256"]), "original ZIP checksum mismatch")
            out.flush()
            os.fsync(out.fileno())
        publish(out.name, path)
    require(path.stat().st_size == a["bytes"] and digest(path) == a["sha256"], "stored original ZIP mismatch")


def log(gh, j, out):
    if not out.exists():
        with tempfile.NamedTemporaryFile(
            dir=out.parent, prefix=out.name + ".partial-", delete=False
        ) as stream:
            # A blank gzip header name makes the sealed bytes deterministic even across private temp paths.
            with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as zipped:
                bounded_stream(
                    endpoint(gh, f"actions/jobs/{j}/logs", True), zipped, 150 * MIB, 512 * MIB, out.parent
                )
            stream.flush()
            os.fsync(stream.fileno())
        publish(stream.name, out)
    data = gzip.decompress(out.read_bytes())
    require(len(data) <= 150 * MIB, "excessive native log")
    return data


def rows(log):
    return [STAMP.sub("", s) for s in log.decode("utf-8", "strict").splitlines()]


def upload(lines, name, a):
    i, n, h = a["id"], a["bytes"], a["sha256"]
    (end,) = [
        j
        for j, x in enumerate(lines)
        if x == f"Artifact {name} has been successfully uploaded! Final size is {n} bytes. Artifact ID is {i}"
    ]
    previous = max(
        (j for j, x in enumerate(lines[:end]) if "has been successfully uploaded!" in x), default=-1
    )
    window = lines[previous + 1 : end]
    require(
        [x for x in window if x.startswith("SHA256 digest of uploaded artifact is ")]
        == ["SHA256 digest of uploaded artifact is " + h]
        and window.count(f"Artifact {name} successfully finalized. Artifact ID {i}") == 1
        and f"Artifact download URL: https://github.com/{REPO}/actions/runs/{RUN}/artifacts/{i}"
        in lines[end + 1 : end + 8],
        ("different original upload", name),
    )


def members(z, limits):
    have = {}
    for x in z.infolist():
        n = x.filename
        require(
            n in limits
            and n not in have
            and not x.is_dir()
            and not x.flag_bits & 1
            and stat.S_IFMT(x.external_attr >> 16) in (0, stat.S_IFREG)
            and 0 < x.file_size <= limits[n],
            ("unrecognized, duplicate or unsafe ZIP member", n),
        )
        have[n] = x
    require(set(have) == set(limits), "missing original ZIP members")
    return have


def native_source(z, manifest, t):
    members(z, {SOURCE: 128 * 1024, SLOT: 2 * MIB})
    source = z.read(SOURCE)
    protocol = (HERE / "provider-source.json").read_bytes()
    require(sha(protocol) == SOURCE_PROTOCOL, "source protocol changed")
    p = json.loads(protocol)
    trees = {k: {"revision": v["end"], "tree": v["tree"]} for k, v in p["sources"].items()}
    expected = {
        "target": t,
        "source_trees": trees,
        "manifest": manifest,
        "coordinator": COORDINATOR,
        "manifest_sha256": MANIFEST_SHA,
        "workflow": PROVIDER,
        "run": str(RUN),
        "attempt": "1",
    }
    require(
        json.loads(source) == expected and {k: v["revision"] for k, v in trees.items()} == SOURCES,
        "native source or builder mismatch",
    )
    return {"source_sha256": sha(source), "source_trees": trees, "prior_transport_sha256": sha(z.read(SLOT))}


def small(gh, snap, target, path, root, training):
    run, jobs, arts = snap
    run_identity(run)
    (job,) = [j for j in jobs["jobs"] if j["name"] == JOBS["build/" + target]]
    require(
        job["id"] == BUILD[target]
        and job["run_id"] == RUN
        and job["run_attempt"] == 1
        and job["head_sha"] == PROVIDER
        and job["status"] == "completed",
        "native job still active or different",
    )
    path.mkdir(exist_ok=True)
    jid = job["id"]
    store_once(path / "official-job.json", job)
    raw = log(gh, jid, path / "original-job.log.gz")
    lines = rows(raw)
    aa = asset_records(run, arts)
    pkg, src = TOOLCHAIN + "-" + target, "rc23-final-source-" + target
    if job["conclusion"] != "success":
        if src in aa:
            download(gh, aa[src], path / (str(aa[src]["id"]) + ".zip"), 512 * MIB)
        store_once(
            path / "refused.json",
            {
                "job": jid,
                "target": target,
                "conclusion": job["conclusion"],
                "raw_sha256": sha(raw),
                "steps": [s for s in job["steps"] if s["conclusion"] == "failure"],
                "source_artifact": aa.get(src),
            },
        )
        raise ValueError("native producer refused; originals retained")
    job_identity(job, "build/" + target)
    for n in (pkg, src):
        upload(lines, n, aa[n])
    source_zip = path / (str(aa[src]["id"]) + ".zip")
    download(gh, aa[src], source_zip, 512 * MIB)
    with zipfile.ZipFile(source_zip) as z:
        proof = native_source(z, coordinator(root), target)
    verdict = (
        "verified ohm-rust {rust} with ohm-cargo {cargo}, ohm-rust-clippy {clippy}, and ohm-rustfmt {rustfmt}"
    ).format(**SOURCES)
    require(
        lines.count(verdict) == 1 and lines.count(training.COVERED) == 1,
        "missing final source or executed tools",
    )
    trace = training.roster(lines, target)
    require(len(trace["rows"]) == 27 and len(trace["finished"]) == 9, "incomplete natural PGO")
    result = {
        "target": target,
        "job": jid,
        "archive": aa[pkg],
        "source_artifact": aa[src],
        "raw_log_sha256": sha(raw),
        "native_training": trace,
        "six_tools": training.COVERED,
        **proof,
    }
    store_once(path / "verified.json", result)
    return {k: v for k, v in result.items() if k != "native_training"} | {
        "training_sha256": sha(json.dumps(trace, sort_keys=True).encode())
    }


def store_once(path, obj):
    if path.exists():
        require(
            json.loads(path.read_bytes()) == json.loads(json.dumps(obj)),
            "changed previously qualified original",
        )
    else:
        save(path, obj)


def hosted(root, target, work, report):
    e = os.environ
    require(
        (
            e.get("GITHUB_ACTIONS"),
            e.get("GITHUB_REPOSITORY"),
            e.get("GITHUB_EVENT_NAME"),
            e.get("GITHUB_RUN_ATTEMPT"),
            e.get("GITHUB_JOB"),
            e.get("GITHUB_REF"),
        )
        == ("true", REPO, "workflow_dispatch", "1", "native", "refs/heads/" + BRANCH),
        "native import requires exact first-party manual QA",
    )
    ev = json.loads(Path(e["GITHUB_EVENT_PATH"]).read_bytes())
    require(
        ev["inputs"]["reviewed_head"] == e["GITHUB_SHA"] == head(root / "qa-code")
        and ev["repository"]["full_name"] == REPO
        and Path(e["GITHUB_WORKSPACE"]).resolve(strict=True) == root,
        "unreviewed consumer",
    )
    hosts = {("Linux", "x86_64", "Linux"): TARGETS[0], ("Darwin", "arm64", "macOS"): TARGETS[1]}
    require(
        hosts.get((platform.system(), platform.machine(), e["RUNNER_OS"])) == target, "wrong physical host"
    )
    temp = Path(e["RUNNER_TEMP"]).resolve(strict=True)
    require(
        work.parent.resolve(strict=True) == report.parent.resolve(strict=True) == temp
        and work.name == "rc23-original"
        and report.name == "rc23-final-reports"
        and ".." not in (*work.parts, *report.parts)
        and not work.exists()
        and not work.is_symlink()
        and report.is_dir()
        and not report.is_symlink(),
        "invalid independent import roots",
    )


def stage(a):
    hosted(a.root, a.target, a.work, a.reports)
    reviewed = json.loads(
        frozen(a.root / "qa-code", "scripts/rc23-final-installed/bindings.json", os.environ["GITHUB_SHA"])
    )
    live = snapshot(a.gh)
    actual = official(*live)
    require(
        reviewed["official"] == actual and set(reviewed["native"]) == set(TARGETS),
        "official originals changed",
    )
    for t in TARGETS:
        r = reviewed["native"][t]
        require(
            r["target"] == t
            and r["job"] == BUILD[t]
            and r["archive"] == actual["artifacts"][TOOLCHAIN + "-" + t]
            and r["source_artifact"] == actual["artifacts"]["rc23-final-source-" + t],
            "receipt is for a different build",
        )
    require(
        shutil.disk_usage(a.work.parent).free >= 10 * (1 << 30), "less than 10 GiB before native installs"
    )
    a.work.mkdir(mode=0o700)
    release = a.work / "release"
    release.mkdir()
    for name, inventory in ((TOOLCHAIN + "-" + a.target, names(a.target)), (TOOLCHAIN + "-global", GLOBAL)):
        key = actual["artifacts"][name]
        p = a.work / (str(key["id"]) + ".zip")
        download(a.gh, key, p, 4 << 30)
        with zipfile.ZipFile(p) as z:
            have = members(z, {n: (1200 * MIB if n.endswith(".tar.gz") else 2 * MIB) for n in inventory})
            for n, member in have.items():
                require(
                    shutil.disk_usage(release).free >= (4 << 30) + member.file_size,
                    "insufficient space for imported package",
                )
                with z.open(member) as src, (release / n).open("xb") as dest:
                    shutil.copyfileobj(src, dest, MIB)
        if a.target == TARGETS[0] and name == TOOLCHAIN + "-" + a.target:
            # Reopen the identical local ZIP in the GNU cross-target fixture after installation.
            (raw_row,) = [r for r in live[2]["artifacts"] if r["name"] == name and r["id"] == key["id"]]
            save(a.reports / "original-gnu-catalog.json", raw_row)
        else:
            p.unlink()
    save(
        a.reports / "source-bound-media.json",
        {
            "binding_sha256": digest(HERE / "bindings.json"),
            "source": reviewed["native"][a.target],
            "files": staged(a.root, release, a.target),
        },
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("capture", "bind", "stage"))
    p.add_argument("--gh", required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--target", choices=TARGETS)
    p.add_argument("--reports", type=Path)
    p.add_argument("--training-source", type=Path)
    a = p.parse_args()
    a.root = a.root.resolve(strict=True)
    if a.action == "stage":
        require(a.target and a.reports, "missing native role and reports")
        stage(a)
        return
    require(
        a.training_source and head(a.training_source) == "4fe6d1c04b8226928fb0c57800a864269d7001e8",
        "different PGO reader",
    )
    source = a.training_source / "scripts/rc23-expanded-inputs"
    for n in ("pgo.py", "materialize.py", "registration.json"):
        frozen(a.training_source, "scripts/rc23-expanded-inputs/" + n, head(a.training_source))
    sys.path.insert(0, str(source))
    import pgo

    a.work.mkdir(exist_ok=True)
    snap = snapshot(a.gh)
    if a.action == "capture":
        require(a.target, "missing native target")
        small(a.gh, snap, a.target, a.work / a.target, a.root, pgo)
    else:
        result = official(*snap)
        # Preserve the official inputs themselves alongside the compact proof for offline replay.
        if not (a.work / "official-api.json").exists():
            save(a.work / "official-api.json", dict(zip(("run", "jobs", "artifacts"), snap, strict=True)))
        original = json.loads((a.work / "official-api.json").read_bytes())
        require(
            official(original["run"], original["jobs"], original["artifacts"]) == result,
            "original API binding changed",
        )
        native = {t: small(a.gh, snap, t, a.work / t, a.root, pgo) for t in TARGETS}
        raw = log(a.gh, result["jobs"]["assemble"], a.work / "assembly.log.gz")
        upload(rows(raw), TOOLCHAIN + "-global", result["artifacts"][TOOLCHAIN + "-global"])
        store_once(
            a.work / "bindings.json", {"official": result, "native": native, "assembly_log_sha256": sha(raw)}
        )


if __name__ == "__main__":
    main()
