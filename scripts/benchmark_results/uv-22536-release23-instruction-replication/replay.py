"""Reconstruct every scored visit and both machines' native gates from the service ZIPs."""
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from fractions import Fraction
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from endpoint_replay import calculate


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def checked(path, reference):
    assert path.stat().st_size == reference["bytes"] and sha(path) == reference["sha256"], path
    return path


def reopen_reader(staging, verification):
    archive = checked(HERE / "native-reader.tar.gz", verification["reader"])
    with tarfile.open(archive, "r:gz") as data:
        members = data.getmembers()
        assert len(members) == len({m.name for m in members}) and sum(m.size for m in members) < 2 << 20
        for member in members:
            path = Path(member.name)
            assert path.parts[0] == "worker" and ".." not in path.parts and not path.is_absolute()
            assert member.isfile() or member.isdir()
        data.extractall(staging, members=members, filter="data")
    worker = staging / "worker"
    for name, digest in verification["reader"]["members"].items():
        assert sha(worker / name) == digest
    assert {p.relative_to(worker).as_posix() for p in worker.rglob("*") if p.is_file()} == set(verification["reader"]["members"])
    assert sha(worker / "read_original.py") == verification["reader"]["entry_sha256"]
    return worker


def service(host, research):
    prefix = HERE / "origins" / str(host["run"])
    records = {k: checked(prefix / k, v) for k, v in host["service_files"].items()}
    run, jobs, artifact, early = [read(records[n]) for n in ("run.json", "jobs.json", "artifact.json", "boot-service.json")]
    job, = jobs["jobs"]
    assert run["event"] == "workflow_dispatch" and run["actor"]["login"] == "charliermarsh"
    assert run["repository"]["full_name"] == "astral-experiments/ohm" and run["path"] == ".github/workflows/ci.yml"
    assert run["run_attempt"] == job["run_attempt"] == 1 and run["id"] == job["run_id"] == host["run"]
    assert run["head_sha"] == job["head_sha"] == research["head"] and run["head_branch"] == research["branch"]
    assert run["conclusion"] == job["conclusion"] == "success" and job["id"] == host["job"]
    for art in (artifact, early):
        assert art["workflow_run"]["id"] == run["id"] and art["workflow_run"]["head_sha"] == run["head_sha"]
        assert art["workflow_run"]["head_branch"] == run["head_branch"] and art["workflow_run"]["repository_id"] == run["repository"]["id"]
    assert artifact["id"] == host["artifact"] and artifact["digest"] == "sha256:" + host["original"]["sha256"]
    assert artifact["size_in_bytes"] == host["original"]["bytes"]
    assert early["digest"] == "sha256:" + sha(records["boot.zip"])
    assert early["size_in_bytes"] == records["boot.zip"].stat().st_size
    with zipfile.ZipFile(records["boot.zip"]) as archive:
        assert archive.namelist() == ["accepted.json"] and archive.testzip() is None
        calibration = archive.read("accepted.json")
    return calibration, job


def birth(verification, policy):
    folder = HERE / "origins" / "pre-result"
    files = {k: checked(folder / k, ref) for k, ref in verification["birth_files"].items()}
    document = read(files["conditional-birth.json"])
    assert sha(files["conditional-birth.json"]) == policy["birth"]["sha256"]
    assert document["run"] == policy["original_run"] and document["head"] == policy["source_head"]
    assert document["first_result_unavailable"] and document["run_status"] == document["job_status"] == "in_progress"
    for filename, key in (("run.json", "service_run"), ("jobs.json", "service_jobs"), ("artifacts.json", "service_rows")):
        assert sha(files[filename]) == document[key]["sha256"]
    run = read(files["run.json"])
    job, = read(files["jobs.json"])["jobs"]
    early, = read(files["artifacts.json"])["artifacts"]
    assert run["id"] == job["run_id"] == early["workflow_run"]["id"] == document["run"]
    assert job["id"] == document["job"] and run["status"] == job["status"] == "in_progress"
    assert [early["name"]] == document["service_artifacts"] == ["uv-22536-release23-boot"]
    extension = read(files["service-guard-birth.json"])
    assert extension["original_terminal_zip_absent"] and extension["base"]["sha256"] == verification["policy"]["sha256"]
    assert extension["known_assignments"]["sha256"] == verification["service_exclusions"]["sha256"]


def numeric(score, preregistration):
    measurements = calculate(score, preregistration)
    assert measurements["45_verified"] and measurements["per_pid_words"] == 288
    return measurements["endpoints"]


def envelope(outcome):
    pairs = outcome["raw_control_treatment"]
    control, candidate = map(median, zip(*pairs))
    ratios = [Fraction(a, b) for a, b in pairs]
    ratio = median(ratios)
    assert ratio == Fraction(outcome["median_ratio"])
    return {"control_median": control, "full_median": candidate, "paired_ratio": str(ratio),
            "paired_factor": float(ratio), "percent_reduction": float(100 * (1 - 1 / ratio)),
            "strict_bar": outcome["strict_bar"], "over": outcome["count_strictly_over_bar"],
            "qualified": outcome["eight_strictly_over_bar"],
            "paired_ratios": [str(r) for r in ratios], "half_medians": [str(median(ratios[:4])), str(median(ratios[4:]))]}


def one(host, common, worker, staging, first_archive, previous_role):
    name = host["compressed"]["name"]
    compressed = checked(HERE / name, host["compressed"])
    outer = staging / ("actions-" + str(host["run"]) + ".zip")
    command = ["zstd", "-qdc"]
    if host["compressed"]["dictionary"]:
        assert first_archive is not None and sha(first_archive) == host["compressed"]["dictionary"]
        command.append("--patch-from=" + str(first_archive))
    command.append(str(compressed))
    with outer.open("xb") as dest:
        subprocess.run(command, stdout=dest, check=True)
    checked(outer, host["original"])
    calibration, job = service(host, common)
    cal = json.loads(calibration)
    assert cal["boot"] == host["boot"] and job["runner_id"] == host["runner_id"] and job["runner_name"] == host["runner_name"]
    enrolled = read(worker / "release23-inputs.json")
    assert sorted(cal["excluded"]) == sorted(enrolled["excluded"]) and cal["boot"] not in cal["excluded"]
    inner = staging / ("original-" + str(host["run"]) + ".zip")
    with zipfile.ZipFile(outer) as data:
        assert sorted(data.namelist()) == ["original.zip", "verified.json"] and data.testzip() is None
        inner_receipt = json.loads(data.read("verified.json"))
        assert inner_receipt["complete_score"] and inner_receipt["bytes"] <= 128 << 20
        with data.open("original.zip") as source, inner.open("xb") as dest:
            shutil.copyfileobj(source, dest)
    assert inner.stat().st_size == inner_receipt["bytes"] and sha(inner) == inner_receipt["sha256"] == host["inner"]
    with zipfile.ZipFile(inner) as archive:
        def original(path):
            return json.loads(archive.read("session-results/" + path))
        assert archive.read("session-results/calibration/accepted.json") == calibration
        material = original("release23-selection.json")
        native_gate = original("qualification/accepted.json")
        chosen = material["decision"]
        if previous_role is not None:
            assert chosen == previous_role
        assert chosen == common["native_choice"] and native_gate["control"] == chosen["control"] and native_gate["treatment"] == "F"
        transport = original("transport.json")["assigned"]
        assert [transport[k] for k in ("id", "run_id", "head_sha", "runner_id", "runner_name")] == [
            job["id"], job["run_id"], job["head_sha"], job["runner_id"], job["runner_name"]]
    raw = subprocess.check_output([sys.executable, "-ISB", worker / "read_original.py", inner, host["inner"]])
    result = json.loads(raw)
    assert result["accepted"] and result["independent_score_sha256"] == host["native_recomputed_score_sha256"]
    physical = result["physical_and_native"]
    assert physical["dedicated_boot"] == cal["boot"] and physical["live_source_histories_admitted"]
    assert physical["original_sdk_families"] == ["F", "R"] and physical["native_original_groups"] == {"signed-1": "R", "treatment": "F"}
    score = result["original"]
    assert score["control"] == chosen["control"] and score["treatment"] == "F" and score["complete_pairs"] == 8
    registration = read(worker / "registration.json")
    assert score["paired_order"] == ["".join(row) for row in registration["orders"]]
    metrics = numeric(score, registration)
    edits = {e: {k: envelope(values[k]) for k in ("wall", "sum_six", "whole")} for e, values in metrics.items()}
    named = {s + "/" + crate: envelope(metrics[{"B": "feature_B", "D": "rename_D"}[s]][crate])
             for s, crate in registration["confirmatory_per_pid_endpoints"]}
    summary = {"run": host["run"], "job": host["job"], "boot": host["boot"], "runner_id": host["runner_id"],
               "artifact": host["artifact"], "original_sha256": host["original"]["sha256"], "inner_sha256": host["inner"],
               "native_selected": chosen, "native": physical, "raw_metadata_custody": result["custody"],
               "native_original_visits": {k: sorted(v["visits"]) for k, v in material["actual_cargo_visits"].items()},
               "ordinary_and_hardware_order": score["paired_order"], "independent_A_seeds": score["unique_genuine_cold_kernel_digests"],
               "eight_raw_pairs": score["per_pair_raw"], "edits": edits, "preselected": named}
    return summary, outer, chosen


def replay(verification):
    research = verification["study"]
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        worker = reopen_reader(staging, verification)
        source = read(worker / "release23-inputs.json")
        assert source["signed_cargo"] == research["signed_cargo"] and {r: source["roles"][r]["source"] for r in ("R", "F")} == research["rust"]
        assert read(worker / "case.json")["states"] == research["uv_states"]
        policy = read(checked(HERE / "conditional-policy.json", verification["policy"]))
        extra = read(checked(HERE / "expanded-service-exclusions.json", verification["service_exclusions"]))
        assert policy["source_head"] == research["head"] and policy["enrollment"] == research["enrollment"]
        birth(verification, policy)
        hosts = verification["hosts"]
        assert 1 <= len(hosts) <= 2
        a = hosts[0]
        assert a["boot"] not in source["excluded"] and set(source["excluded"]) | {a["boot"]} == set(policy["physical_boots"])
        assert len(source["excluded"]) == 35 and len(policy["physical_boots"]) == 36
        if len(hosts) == 2:
            b = hosts[1]
            assert b["boot"] not in policy["physical_boots"]
            assert b["runner_id"] not in extra["extended_service_ids"] and b["runner_name"] not in extra["extended_service_names"]
            assert len(extra["extended_service_ids"]) == len(extra["extended_service_names"]) == 37
            assert a["run"] != b["run"] and a["job"] != b["job"]
        values = []
        original = previous = None
        for host in hosts:
            summary, archive, chosen = one(host, research, worker, staging, original, previous)
            values.append(summary)
            if original is None:
                original, previous = archive, chosen
        triggers = []
        for value in values:
            names = [k for k, v in value["preselected"].items() if v["qualified"]]
            names.extend(e + "/wall" for e in ("feature_B", "rename_D", "production_B_plus_D") if value["edits"][e]["wall"]["qualified"])
            triggers.append(sorted(names))
        assert triggers[0] == ["D/uv_metadata"]
        repeated = sorted(set(triggers[0]).intersection(triggers[1])) if len(triggers) == 2 else []
        return {"study": research, "hosts": values, "qualifying_on_each_host": triggers, "replicated_endpoints": repeated}


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Use Python's ordinary assertions")
    summary = replay(read(HERE / "verification.json"))
    assert summary == read(HERE / "two-host.json")
    print(json.dumps({"accepted": True, "runs": [v["run"] for v in summary["hosts"]],
                      "reproduced": summary["replicated_endpoints"], "rustc_counts_reopened": 288 * len(summary["hosts"])}, sort_keys=True))
