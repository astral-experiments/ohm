"""Verify a service-attested early and terminal ZIP received under the requested repository identity."""

from pathlib import Path
import argparse, hashlib, json, sys, zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, require, read, blob, sha
from placement import BRANCH, REPO, valid_uuid
from score import replay


def check(folder, head, lock, series):
    require(series in ("marginal.initial", "marginal.repeat"), "ineligible registered series")
    run, jobs, artifacts = (read(folder / (name + ".json")) for name in ("run", "jobs", "artifacts"))
    require(
        run["status"] == "completed"
        and run["conclusion"] == "success"
        and run["event"] == "workflow_dispatch"
        and run["run_attempt"] == 1
        and run["repository"]["full_name"] == REPO
        and run["repository"]["id"] == run["head_repository"]["id"] == 1319437234
        and (run["head_branch"], run["head_sha"]) == (BRANCH, head),
        "wrong official terminal",
    )
    require(len(jobs["jobs"]) == jobs["total_count"] == 1, "wrong job census")
    (job,) = jobs["jobs"]
    require(
        job["conclusion"] == "success"
        and job["run_id"] == run["id"]
        and job["head_sha"] == head
        and job["runner_id"] > 0
        and job["run_attempt"] == 1,
        "wrong official host",
    )
    specs = {a["name"]: a for a in artifacts["artifacts"]}
    require(len(specs) == artifacts["total_count"] == 2, "wrong service artifacts")
    proofs = {}
    for tag in ("boot", "original"):
        name = f"uv-21134-{series}-{tag}"
        a = specs[name]
        f = folder / (tag + ".zip")
        r = a["workflow_run"]
        require(
            (r["id"], r["head_sha"], r["repository_id"], r["head_repository_id"])
            == (run["id"], head, 1319437234, 1319437234)
            and blob(f) == [a["size_in_bytes"], a["digest"][7:]]
            and a["digest"].startswith("sha256:"),
            "wrong original " + name,
        )
        proofs[tag] = {"id": a["id"], "size": a["size_in_bytes"], "sha256": a["digest"][7:]}
    with zipfile.ZipFile(folder / "boot.zip") as z, zipfile.ZipFile(folder / "original.zip") as allzip:
        require(z.namelist() == ["boot-attestation.json"], "early artifact contains results")
        raw = z.read("boot-attestation.json")
        require(raw == allzip.read("boot-attestation.json"), "changed original calibration")
        boot = json.loads(raw)
        require(
            valid_uuid(boot["boot"])
            and (boot["run"], boot["job"], boot["runner_id"], boot["head"], boot["G_lock"], boot["series"])
            == (run["id"], job["id"], job["runner_id"], head, lock, series),
            "wrong calibrated placement",
        )
        saved = json.loads(allzip.read("score.json"))
    scored = replay(folder / "original.zip")
    require(json.loads(json.dumps(scored)) == saved, "original score differs from independent count")
    return {
        "run": run["id"],
        "job": job["id"],
        "runner_id": job["runner_id"],
        "head": head,
        "G_lock": lock,
        "series": series,
        "boot": boot["boot"],
        "originals": proofs,
        "score": scored,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("reviewed_head")
    parser.add_argument("G_lock")
    parser.add_argument("series")
    args = parser.parse_args()
    print(
        json.dumps(
            check(args.directory, args.reviewed_head, args.G_lock, args.series), indent=2, sort_keys=True
        )
    )
