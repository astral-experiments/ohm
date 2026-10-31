"""Bind the independent native-provider qualification to its real job and complete original ZIP."""

import hashlib
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

import bindings as b
from bindings import need

FILE = b.HERE / "native-recheck.json"
AUDIT = b.HERE / "native-diagnostic-verified.json"
AUDIT_SHA = "f2860d5156edc217f4011b230d36e9e043fd03147798c53fb10f24d881dfef55"
BRANCH = "charlie/qa-branch-return-native-recheck-20261031"
JOB = "Genuine settled CLI, fingerprint and native provider"
ARTIFACT = "branch-return-native-recheck"


def spec(data):
    need(
        isinstance(data, dict) and data.get("independent") == b.sha(AUDIT) == AUDIT_SHA,
        "no reviewed full-Ruff native recheck",
    )
    audit = json.loads(AUDIT.read_bytes())
    need(
        (data.get("run"), data.get("head"), data.get("complete_sha256"))
        == (audit["run"], audit["head"], audit["complete"])
        and data.get("attempt") == 1
        and type(data.get("job")) is int
        and data["job"] > 0,
        "diagnostic source/attempt",
    )
    art = data["artifact"]
    need(
        art["id"] == audit["artifact"]
        and art["sha256"] == audit["sha256"]
        and type(art["size"]) is int
        and 0 < art["size"] < 2**30
        and audit["encoded_records"] == 375
        and audit["origins"]["dep-lib-zmij"] == 97
        and b.spec()["manifest"] == audit["source_manifest"],
        "mismatched native calibration/SDK",
    )
    return data


def official(run, jobs, artifacts, sealed):
    need(
        (run["id"], run["head_sha"], run["run_attempt"])
        == (sealed["run"], sealed["head"], sealed["attempt"])
        and run["head_branch"] == BRANCH
        and run["event"] == "workflow_dispatch"
        and run["status"] == "completed"
        and run["conclusion"] == "success"
        and run["repository"]["full_name"] == b.REPO,
        "unqualified native-provider recheck",
    )
    need(jobs["total_count"] == len(jobs["jobs"]) == 1, "wrong native diagnostic job set")
    job = jobs["jobs"][0]
    need(
        job["id"] == sealed["job"]
        and job["name"] == JOB
        and job["head_sha"] == sealed["head"]
        and job["status"] == "completed"
        and job["conclusion"] == "success"
        and any(
            s["name"] == "Run ordinary F-off CLI and the independent native recheck"
            and s["conclusion"] == "success"
            for s in job["steps"]
        ),
        "real diagnostic job",
    )
    need(
        artifacts["total_count"] == len(artifacts["artifacts"]) == 1,
        "wrong diagnostic artifact set",
    )
    result = artifacts["artifacts"][0]
    wanted = sealed["artifact"]
    need(
        result["name"] == ARTIFACT
        and result["id"] == wanted["id"]
        and not result["expired"]
        and result["size_in_bytes"] == wanted["size"]
        and result["digest"] == "sha256:" + wanted["sha256"]
        and result["workflow_run"]["id"] == sealed["run"]
        and result["workflow_run"]["head_sha"] == sealed["head"],
        "official diagnostic artifact",
    )


def archive(path, sealed):
    need(
        path.stat().st_size == sealed["artifact"]["size"]
        and b.sha(path) == sealed["artifact"]["sha256"],
        "official native diagnostic ZIP bytes changed",
    )
    with zipfile.ZipFile(path) as z:
        need(
            len(set(z.namelist())) == len(z.infolist()) and "failure.txt" not in z.namelist(),
            "incomplete or duplicate diagnostic",
        )
        raw = z.read("complete.json")
        reg = json.loads(z.read("registration.json"))
    need(
        hashlib.sha256(raw).hexdigest() == sealed["complete_sha256"]
        and reg["source"] == b.spec()
        and reg["ref"] == sealed["head"]
        and int(reg["run"]) == sealed["run"]
        and reg["cargo"] == b.CARGO,
        "different native recheck verdict, Cargo or SDK",
    )
    complete = json.loads(raw)
    first, results = complete["first"], complete["provider_results"]
    need(
        complete["status"] == "unscored"
        and complete["source_manifest"] == b.spec()["manifest"]
        and first["fresh"] == 374
        and first["status"] == first["runtime"] == 0
        and first["cli"] == complete["empty"]["cli"]
        and results["remove"] == first
        and results["valid"] == results["repair"]
        and results["valid"]["runtime"] == 83
        and results["valid"]["cli"] != first["cli"]
        and results["bad"] == {"status": 101, "cli": None},
        "changed, malformed, repaired and removed native replacement",
    )
    return complete


def acquire():
    sealed = spec(json.loads(FILE.read_bytes()))
    api = "repos/" + b.REPO + "/actions/"

    def get(path):
        return json.loads(subprocess.check_output(["gh", "api", api + path]))

    run = "runs/" + str(sealed["run"])
    official(get(run), get(run + "/attempts/1/jobs"), get(run + "/artifacts"), sealed)
    with tempfile.TemporaryDirectory(prefix="native-recheck-", dir=b.ROOT) as tmp:
        path = Path(tmp) / "official.zip"
        with path.open("xb") as target:
            subprocess.run(
                ["gh", "api", api + "artifacts/" + str(sealed["artifact"]["id"]) + "/zip"],
                stdout=target,
                check=True,
            )
        complete = archive(path, sealed)
    b.save(b.OUT / "native-recheck-qualification.json", {"binding": sealed, "complete": complete})
