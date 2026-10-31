"""Verify official material in a token-bearing setup step, or seal only private run output."""

import argparse, hashlib, io, json, os, subprocess, sys, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support as q


def request(endpoint):
    return subprocess.check_output(["gh", "api", "repos/astral-experiments/ohm/actions/" + endpoint])


def official(lane):
    doc = lambda endpoint: json.loads(request(endpoint))
    run = doc("runs/" + str(lane["run"]))
    q.require(
        run["id"] == lane["run"]
        and run["head_sha"] == lane["head"]
        and run["run_attempt"] == 1
        and run["status"] == "completed",
        "official host provenance",
    )
    if "job" in lane:
        job = doc("jobs/" + str(lane["job"]))
        q.require(
            job["run_id"] == lane["run"]
            and job["head_sha"] == lane["head"]
            and job["conclusion"] == "success",
            "exact named qualification job",
        )
    else:
        q.require(run["conclusion"] == "success", "structural P/C run failed")
    artifact = doc("artifacts/" + str(lane["artifact"]))
    q.require(
        artifact["workflow_run"]["id"] == lane["run"]
        and artifact["workflow_run"]["head_sha"] == lane["head"]
        and not artifact["expired"]
        and artifact["digest"] == "sha256:" + lane["sha256"]
        and 0 < artifact["size_in_bytes"] < 64 * 2**20,
        "original official source",
    )
    raw = request("artifacts/" + str(lane["artifact"]) + "/zip")
    q.require(len(raw) == artifact["size_in_bytes"] and q.digest(raw) == lane["sha256"], "original ZIP")
    if "receipt_member" in lane:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            q.require(
                z.namelist().count(lane["receipt_member"]) == 1
                and q.digest(z.read(lane["receipt_member"])) == lane["receipt_sha256"],
                "independently approved native/source receipt",
            )
    return raw


def acquire(a):
    permit = q.gate(a.clearance)
    q.require(
        os.environ.get("GH_TOKEN")
        and os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
        and os.environ["GITHUB_REF_NAME"] == q.REG["ref"]
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1",
        "invalid runner admission",
    )
    for lane in permit["required"].values():
        official(lane)
    raw = official(
        {
            "run": q.REG["structural_run"],
            "head": q.REG["structural_head"],
            "artifact": q.REG["structural_artifact"]["id"],
            "sha256": q.REG["structural_artifact"]["sha256"],
        }
    )
    with a.original.open("xb") as f:
        f.write(raw)
    q.archive_oracle(a.original)
    q.require(q.head(a.qual) == q.REG["provider_head"], "wrong qualification source")
    module = a.qual / "scripts/ohm-musl-ast-pair"
    bindings = subprocess.check_output(
        [
            sys.executable,
            "-IB",
            module / "lookup.py",
            str(q.REG["provider_run"]),
            q.REG["provider_head"],
        ],
        cwd=a.qual,
        text=True,
    )
    env = dict(l.split("=", 1) for l in bindings.splitlines())
    q.require(
        env
        == {
            "SOURCE_RUN": str(q.REG["source_run"]),
            "SOURCE_HEAD": q.REG["source_head"],
            "PROVIDER_RUN": str(q.REG["provider_run"]),
            "PROVIDER_HEAD": q.REG["provider_head"],
            "TRANSFER_ID": str(q.REG["transfer"]["id"]),
            "TRANSFER_DIGEST": q.REG["transfer"]["archive"],
            "TRANSFER_SEAL": q.REG["transfer"]["identity"],
        },
        "composite provider and source identity",
    )
    with Path(os.environ["GITHUB_ENV"]).open("a") as f:
        f.write(bindings)
    subprocess.run(
        [sys.executable, "-IB", module / "restore.py", "P"],
        cwd=a.qual,
        env=os.environ | env,
        check=True,
    )


def seal(root):
    # Emitting into a distinct evidence folder excludes the live source, registry and Cargo roots.
    output = root / "evidence"
    output.mkdir(parents=True, exist_ok=True)
    for name in ("counts", "flanks"):
        src = root / name
        if src.is_dir():
            src.rename(output / name)
    for save in list(output.glob("counts/*/kernel-*/proc")):
        # Keep the archival copy of every raw per-PID file. Never touch an unfinished group.
        arch = save.parent / "processes.tar.gz"
        if arch.is_file() and (save.parent / "kernel.json").is_file():
            import tarfile

            with tarfile.open(arch, "r:gz") as archive:
                members = {m.name: m for m in archive if m.isfile()}
                paths = list(save.iterdir())
                q.require(
                    set(members) == {x.name for x in paths}
                    and all(
                        hashlib.file_digest(archive.extractfile(members[x.name]), "sha256").hexdigest()
                        == q.file_sha(x)
                        for x in paths
                    ),
                    "lossless original raw trace",
                )
            # Keep this copy task-private for the lifetime of the worker but exclude it from delivery.
            destination = root / "unpacked-traces" / save.parent.parent.name / save.parent.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            save.rename(destination)
    rows = []
    for p in sorted(output.rglob("*")):
        if p.is_file():
            q.require(not p.is_symlink(), "unexpected symlink in original evidence")
            rows.append(f"{q.file_sha(p)}  {p.relative_to(output).as_posix()}\n")
    with (output / "POSITION.sha256").open("x") as f:
        f.writelines(rows)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest="action", required=True)
    a = subs.add_parser("acquire")
    for k in ["qual", "original", "clearance"]:
        a.add_argument("--" + k, required=True, type=Path)
    s = subs.add_parser("seal")
    s.add_argument("root", type=Path)
    v = p.parse_args()
    acquire(v) if v.action == "acquire" else seal(v.root)
