"""Bind the hosted whole-rustc profiles and recompute the compact paired result independently."""
import argparse
import io
import json
import re
import subprocess
import sys
import zipfile
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from score import ART, JOB, configure, original as score_readback


def digest(b):
    return sha256(b).hexdigest()


def persist(path, wire):
    if path.exists():
        assert path.read_bytes() == wire
    else:
        with path.open("xb") as f:
            f.write(wire)


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def collect(gh, run, git, stage, out):
    assert re.fullmatch("[a-f0-9]{40}", git)
    configure()
    schedule = score_readback.fixed.options(stage)
    agreement = json.loads((HERE / "admissible-native.json").read_bytes())

    def api(path):
        return subprocess.check_output([gh, "api", "repos/astral-experiments/ohm/" + path])

    wf = json.loads(api(f"actions/runs/{run}"))
    assert (wf["head_sha"], wf["status"], wf["repository"]["full_name"]) == (git, "completed", "astral-experiments/ohm")
    out.mkdir(parents=True, exist_ok=True)
    job_table = json.loads(api(f"actions/runs/{run}/jobs?per_page=100"))["jobs"]
    prefix = JOB + stage + " Ruff block "
    jobs = {r["name"].removeprefix(prefix): r["conclusion"] for r in job_table if r["name"].startswith(prefix)}
    assert set(jobs) == set(schedule) and all(r["status"] == "completed" for r in job_table)
    raw_prefix = ART + stage + "-"
    compact = raw_prefix + "readback"
    metadata = json.loads(api(f"actions/runs/{run}/artifacts?per_page=100"))["artifacts"]
    artifacts = {r["name"]: r for r in metadata}
    assert len(artifacts) == len(metadata)
    assert all((r["workflow_run"]["head_sha"], r["workflow_run"]["id"], r["expired"]) == (git, run, False) for r in metadata)
    labels = {k:[v["id"], v["size_in_bytes"], v["digest"].removeprefix("sha256:")] for k,v in artifacts.items()}
    persist(out / "terminal-state.json", encode({"stage":stage,"git":git,"run":run,"workflow":wf["conclusion"],
                                                 "block_jobs":jobs,"artifacts":labels}))
    expected = {raw_prefix + n for n in schedule} | {compact}
    assert set(artifacts) <= expected
    if compact not in artifacts:
        print("Independent readback did not produce a projection.", wf["conclusion"], jobs)
        return False
    ident, size, expected_sha = labels[compact]
    assert 0 < size < 8 * 2**20
    wire = api(f"actions/artifacts/{ident}/zip")
    assert len(wire) == size and digest(wire) == expected_sha
    persist(out / "independent-readback.zip", wire)
    with zipfile.ZipFile(io.BytesIO(wire)) as z:
        names = z.namelist()
        assert len(set(names)) == len(names)
        if "analysis.json" not in names:
            print("Hosted independent reader stopped before its numeric calculation.", wf["conclusion"], jobs, names)
            return False
        assert set(artifacts) == expected and all(v == "success" for v in jobs.values())
        assert set(names) == {"analysis.json"} | {f"block-{n}.json" for n in schedule}
        rows = []
        for n, order in sorted(schedule.items()):
            r = json.loads(z.read(f"block-{n}.json"))
            assert (r["git"],r["block"],r["order"],r["stage"]) == (git,n,order,stage)
            assert r["fixed_cargo"] == agreement["cargo_elf"] and r["fixed_native"] == agreement["native_readback"]
            assert (r["source"],r["drivers"]) == (agreement["sources"],agreement["drivers"])
            assert r["raw_archive"] == labels[raw_prefix + n][2]
            transitions = r["all_real_selector_transitions"]
            assert transitions["order"] == "AANNMMAMNA" and len(transitions["visits"]) == 10
            assert transitions["all_file_inodes_and_times_stable"] == 119 and transitions["common_physical_members"] == 118
            assert transitions["namespaces"] == r["physical_args"]["namespace_by_role"] and len(r["all_native_and_counted_role_selections"]) == 17
            assert r["physical_args"]["total_argv"] == agreement["actual_argc"]
            assert r["physical_args"]["namespace_only_fields"] == len(agreement["namespace_positions"])
            for role in "ANM":
                e = r["fixed_real_environment"][role]
                assert e["ordinary_ast"]["lto"] == "off" and e["ordinary_ast"]["incremental_directory"].startswith("/")
                for keys in e["actual_environment_keys"].values():
                    assert not {"CI", "CARGO_INCREMENTAL", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS","RUSTC_WRAPPER"}.intersection(keys)
                assert set(r["whole_guest_Ir_by_process"][role]) == {"first-real-edit","immediate-repeat","settled"}
            rows.append(r)
        if stage == "pilot":
            observed = score_readback.pilot(rows, schedule)
            passed = observed["all_twelve_pilot_ratios_strictly_above_two"]
        else:
            analyze = score_readback.reader["analyze"]
            analyze.__globals__["schedule"] = schedule
            observed = analyze(rows)
            observed.update(stage=stage, fixed_cargo=agreement["cargo_elf"], native=agreement["native_readback"])
            passed = observed["all_six_in_all_blocks_above_two"]
        raw_analysis = z.read("analysis.json")
        assert observed == json.loads(raw_analysis)
    assert (wf["conclusion"] == "success") == passed
    persist(out / "score.json", raw_analysis)
    receipt = {"run":run, "QA":git, "immutable_artifacts":labels, "analysis":digest(raw_analysis)}
    persist(out / ("qualified-" + stage + ".json" if passed else "numerical-rejection.json"), encode(receipt))
    print(stage, passed, receipt["analysis"], "raw_bytes", sum(labels[raw_prefix+n][1] for n in schedule))
    if stage == "pilot":
        for key, v in observed["paired_ratios"].items():
            print(key, *(row[-1] for row in v))
    else:
        for key, group in observed["full_ruff_guest_instruction_ratios"].items():
            print(key, group["median"], group["simultaneous_median_interval"], group["range"], group["one_sided_sign_against_two"])
    return passed


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("gh")
    p.add_argument("run", type=int)
    p.add_argument("git")
    p.add_argument("stage", choices=("pilot", "confirmation"))
    p.add_argument("out", type=Path)
    args = p.parse_args()
    sys.exit(0 if collect(args.gh,args.run,args.git,args.stage,args.out) else 1)
