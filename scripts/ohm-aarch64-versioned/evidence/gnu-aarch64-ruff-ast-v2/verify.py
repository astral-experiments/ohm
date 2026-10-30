"""Reopen the per-process projections and recompute the preregistered paired estimates."""

import argparse
import copy
import hashlib
import json
import math
import re
import statistics
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ROLES = ("A", "N", "M")
CRATES = {"compact_str", "ruff_python_ast", "zmij"}
HARD = {"A": CRATES, "N": {"compact_str", "ruff_python_ast"}, "M": set()}
COUNTER_PHASES = {
    "first-real-edit": "/edit",
    "immediate-repeat": "/unchanged-1",
    "settled": "/unchanged-2",
}
NO_FLAGS = {"CI", "CARGO_INCREMENTAL", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER"}


def get(path):
    return json.loads(path.read_bytes())


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def check_role(row, role, refs):
    flanks = row["native"][role]
    assert set(flanks) == {
        "/old-empty", "/edit", "/unchanged-1", "/unchanged-2", "/invalid", "/repair",
        "/empty-edited", "-edit-cycle/old-empty", "-edit-cycle/post-settled",
    }
    for phase, native in flanks.items():
        assert re.fullmatch(r"[a-f0-9]{64}", native["native_record_sha"])
        if phase == "/invalid":
            assert (native["exit"], native["reader"], native["full_archive"]) == (101, None, None)
            continue
        assert native["exit"] == 0 and native["typed"] == 39
        assert native["reader"] == refs["old" if phase.endswith("old-empty") else "new"]
    counts = row["whole_guest_Ir_by_process"][role]
    assert set(counts) == set(COUNTER_PHASES)
    for phase, name in COUNTER_PHASES.items():
        expected = set(HARD[role])
        if phase == "first-real-edit":
            expected.add("ruff_python_ast")
        assert set(counts[phase]) == {"cargo"} | expected
        assert all(isinstance(n, int) and n > 0 for n in counts[phase].values())
        assert sorted(flanks[name]["rustc"]) == sorted(expected)
        events = {"cargo": 1, "rustup-dispatch": 1}
        if expected:
            events["rustcs"] = len(expected)
        assert flanks[name]["physical"] == events
    evidence = row["fixed_real_environment"][role]
    assert evidence["ordinary_ast"]["lto"] == "off"
    assert Path(evidence["ordinary_ast"]["incremental_directory"]).is_absolute()
    assert set(evidence["actual_environment_keys"]) == {"ast", "cargo"}
    for keys in evidence["actual_environment_keys"].values():
        assert len(keys) == len(set(keys)) and not NO_FLAGS.intersection(keys)
    actual_markers = row["versioned_markers"][role]
    assert set(actual_markers) == {"old-empty", "edit", "unchanged-1", "unchanged-2", "empty-edited"}
    for by_crate in actual_markers.values():
        assert set(by_crate) == CRATES
        for crate, descriptor in by_crate.items():
            want = "hard" if crate in HARD[role] else "versioned" if role == "M" else "legacy"
            assert descriptor["gate"] == want
            assert re.fullmatch(r"[0-9a-f]{64}", descriptor["actual_depfile_sha256"])


def read_stage(directory, stage, schedule, subjects):
    metadata = get(directory / "qualified.json")
    raw_zip = directory / "independent-readback.zip"
    entries = metadata["immutable_artifacts"]
    prefix = "gnu-versioned-" + stage + "-"
    assert set(entries) == {prefix + n for n in schedule} | {prefix + "readback"}
    assert entries[prefix + "readback"][1:] == [raw_zip.stat().st_size, sha(raw_zip)]
    rows = []
    with zipfile.ZipFile(raw_zip) as z:
        assert z.testzip() is None and len(z.namelist()) == len(set(z.namelist()))
        assert set(z.namelist()) == {"block-" + n + ".json" for n in schedule} | {"analysis.json"}
        analysis = z.read("analysis.json")
        assert hashlib.sha256(analysis).hexdigest() == metadata["analysis"]
        for n, order in sorted(schedule.items()):
            row = json.loads(z.read("block-" + n + ".json"))
            assert row["block"] == n and row["order"] == order and row["stage"] == stage
            assert row["git"] == metadata["QA"] and row["raw_archive"] == entries[prefix + n][2]
            assert row["fixed_cargo"] == subjects["cargo_elf"]
            assert row["source"] == subjects["sources"] and row["drivers"] == subjects["drivers"]
            assert row["fixed_native"] == subjects["native_readback"]
            assert set(row["same_source_complete_reader"]) == {subjects["reference"][s] for s in ("old", "new")}
            assert row["ordered_objects_sha256"] == {
                "old": subjects["reference"]["old_objects"], "edited": subjects["reference"]["new_objects"],
            }
            transitions = row["all_real_selector_transitions"]
            assert transitions["order"] == "AANNMMAMNA" and len(transitions["visits"]) == 10
            assert transitions["all_file_inodes_and_times_stable"] == 119
            assert transitions["common_physical_members"] == 118
            assert transitions["namespaces"] == row["physical_args"]["namespace_by_role"]
            assert len(set(transitions["namespaces"].values())) == 3
            assert len(row["all_native_and_counted_role_selections"]) == 17
            assert row["physical_args"]["total_argv"] == 171
            assert row["physical_args"]["namespace_only_fields"] == 42
            for role in ROLES:
                check_role(row, role, subjects["reference"])
            rows.append(row)
    return rows, json.loads(analysis)


def ratios(rows, parent, endpoint):
    result = []
    for row in rows:
        totals = {}
        for role in (parent, "M"):
            phases = row["whole_guest_Ir_by_process"][role]
            selected = (("first-real-edit", "immediate-repeat") if endpoint == "combined" else (endpoint,))
            totals[role] = sum(sum(phases[phase].values()) for phase in selected)
        ratio = totals[parent] / totals["M"]
        result.append([row["block"], totals[parent], totals["M"], ratio])
    return result


def check_statistics(rows, published, stage):
    assert len(rows) == {"pilot": 2, "confirmation": 12}[stage]
    assert len({r["git"] for r in rows}) == 1
    assert len({r["raw_archive"] for r in rows}) == len(rows)
    qualified = []
    for parent in ("N", "A"):
        for endpoint in ("first-real-edit", "combined", "settled"):
            label = f"{parent}/M:{endpoint}"
            data = ratios(rows, parent, endpoint)
            values = sorted(r[-1] for r in data)
            above = sum(r > 2 for r in values)
            qualified.append(above == len(rows))
            if stage == "pilot":
                assert published["paired_ratios"][label] == data
                print(label, *[round(r[-1], 4) for r in data])
            else:
                target = published["full_ruff_guest_instruction_ratios"][label]
                p = sum(math.comb(12, n) for n in range(above, 13)) / 4096
                assert target == {
                    "chronological_blocks": data, "range": [values[0], values[-1]],
                    "median": statistics.median(values), "simultaneous_median_interval": [values[1], values[10]],
                    "above_two": above, "one_sided_sign_against_two": p,
                }
                print(label, target["median"], target["simultaneous_median_interval"], p)
    if stage == "confirmation":
        assert published["six_endpoint_family_coverage_lower_bound"] == 1 - 6 * 26 / 4096
    passed = "all_twelve_pilot_ratios_strictly_above_two" if stage == "pilot" else "all_six_in_all_blocks_above_two"
    assert published[passed] == all(qualified)


def selftest(row, refs):
    def must_reject(key, corrupt):
        altered = copy.deepcopy(row)
        corrupt(altered)
        try:
            check_role(altered, "M", refs)
        except AssertionError:
            return
        raise AssertionError(f"verification accepted {key}")

    must_reject("discarded Cargo instructions", lambda r: r["whole_guest_Ir_by_process"]["M"]["first-real-edit"].pop("cargo"))
    must_reject("unaccounted linker", lambda r: r["native"]["M"]["/edit"]["physical"].update(link_tools=1))
    must_reject("unknown-marker substitution", lambda r: r["versioned_markers"]["M"]["edit"]["compact_str"].update(gate="legacy"))
    must_reject("false invalid success", lambda r: r["native"]["M"]["/invalid"].update(exit=0))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=("pilot", "confirmation"))
    args = ap.parse_args()
    manifest = ROOT / "SHA256SUMS"
    if manifest.exists():
        for line in manifest.read_text().splitlines():
            h, name = line.split("  ", 1)
            assert sha(ROOT / name) == h
    admissions = get(ROOT / "native/enrollment.json")
    assert sha(ROOT / "native/ruff.json") == admissions["native_readback"]
    assert sha(ROOT / "native/provider-executions.json") == admissions["provider_readback"]
    schedules = get(ROOT / "registration/fixed-schedules.json")
    rows, published = read_stage(ROOT / args.stage, args.stage, schedules[args.stage], admissions)
    selftest(rows[0], admissions["reference"])
    check_statistics(rows, published, args.stage)


if __name__ == "__main__":
    main()
