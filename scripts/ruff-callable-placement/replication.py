"""Authenticate the original test-build qualification and bind each independent pair."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile
from collections import Counter

import native
from callable_decision import key

PLAN = Path(__file__).with_name("replication.json")
REPO = "astral-experiments/ohm"


def qualify(api, scratch, block):
    plan = json.loads(PLAN.read_bytes())
    ref = plan["discovery"]
    run = api(f"repos/{REPO}/actions/runs/{ref['run']}")
    job = api(f"repos/{REPO}/actions/jobs/{ref['job']}")
    assert (run["status"], run["conclusion"], run["head_sha"], run["event"], run["head_repository"]["full_name"], run["run_attempt"]) == (
        "completed", "success", ref["qa"], "workflow_dispatch", REPO, 1)
    assert run["head_branch"] == "charlie/qa-ruff-db-link-cause-20261102"
    assert (job["run_id"], job["run_attempt"], job["head_sha"], job["conclusion"]) == (ref["run"], 1, ref["qa"], "success")
    row = api(f"repos/{REPO}/actions/artifacts/{ref['artifact']}")
    assert (row["name"], row["workflow_run"]["id"], row["expired"], row["size_in_bytes"], row["digest"]) == (
        "callable-placement-diagnostic", ref["run"], False, ref["zip_bytes"], "sha256:" + ref["zip_sha256"])
    source = scratch / "qualified-original.zip"
    api(f"repos/{REPO}/actions/artifacts/{ref['artifact']}/zip", source)
    assert native.sha(source) == ref["zip_sha256"]
    with zipfile.ZipFile(source) as z:
        assert z.namelist() == ["callable-placement.tar.zst"]
        packed = z.read("callable-placement.tar.zst")
    decision = subprocess.check_output(["tar", "--zstd", "-xOf", "-", "./decision.json"], input=packed)
    assert hashlib.sha256(decision).hexdigest() == ref["decision_sha256"]
    original = json.loads(decision)
    assert original["qualified_for_replication"] and not original["roles"]["P"]["admitted"]
    expected = sorted(key(k) for k in original["roles"]["C"]["admitted"])
    assert len(set(expected)) == len(expected) == 63
    assert 1 <= block <= len(plan["orders"]) == 6
    return list(plan["orders"][block-1]), expected


def finish(out, reports, decision, block, order, expected):
    assert decision["qualified_for_replication"]
    assert sorted(key(k) for k in decision["roles"]["C"]["admitted"]) == expected
    assert set(reports["P"]) == set(reports["C"])
    for phase in reports["P"]:
        p, c = reports["P"][phase], reports["C"][phase]
        assert (p["graph"], p["commit"], p["source"]) == (c["graph"], c["commit"], c["source"])
        if phase.startswith("empty_"):
            # autocfg salts the crate name of each probe on each clean invocation.
            def cold_calls(result):
                bins = Counter()
                for mode, crate, count in result["calls"]["rustc"]:
                    bins[mode, re.sub(r"^autocfg_[0-9a-f]{16}_([0-9]+)$", r"autocfg_\1", crate)] += count
                return result["calls"]["linkers"], bins
            assert cold_calls(p) == cold_calls(c), phase
        else:
            assert p["calls"] == c["calls"], phase
        if phase != "invalid":
            assert p["verdict"] == c["verdict"], phase
    roles = {}
    for role in order:
        d = decision["roles"][role]
        pmu = json.loads((out/f"{role}-clean/score_new/pmu.json").read_bytes())
        assert pmu["instructions"] == d["instructions"] > 0 and pmu["enabled"] == pmu["running"] > 0
        roles[role] = {k:d[k] for k in ("instructions", "same_inventory", "optional_bytes", "storage")}
        roles[role]["pmu"] = pmu
        roles[role]["edit_admissions"] = len(d["admitted"])
        roles[role]["reverse_admissions"] = len(reports[role]["return_old"]["admitted"])
    entry = json.loads((out/"entry.json").read_bytes())
    assert entry["order"] == order and entry["run"] == os.environ["GITHUB_RUN_ID"]
    native.emit(out/"pair.json", {"block":block, "order":order, "entry":entry, "plan":native.sha(PLAN),
        "decision":native.sha(out/"decision.json"), "histories":native.sha(out/"histories.json"), "roles":roles})
