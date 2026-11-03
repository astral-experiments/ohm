"""Reopen unwrapped Cargo clocks, per-rustc events and the corresponding native products."""
import hashlib
import json
from pathlib import Path
import runpy
import struct
from zipfile import ZipFile


COMPILERS = ("uv_configuration", "uv_client")
METRICS = (*COMPILERS, "sum_two", "whole", "wall")
DONOR = "a0c0b7900b62d889b61f5f4fcdd3512291c3d143c3c1a3cd7501d181e82df20f"
VERDICT = "fb1a90bcccfcb2415900371b275d58767264fd9719a784f4556fd2c385f13e1d"
COMMAND = ["/tmp/uv-workflow-search/sdk/bin/cargo", "check", "-p", "uv-client", "--locked", "--offline", "-j8"]
EDIT = "362613dbf38f60fe285cdd6bca53641149a23c04"


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def member(archive, name):
    return json.loads(archive.read(name))


def open_arm(z, pair, role, boot, affinity):
    prefix = f"native-22958/{pair}-{role}/"
    seed = member(z, prefix + "seed.json")["sha256"]
    proof = member(z, prefix + "native-before-score.json")
    assert proof["same_seed"] and proof["canonical"]
    forms = member(z, prefix + "kernel-B/forms.json")
    assert set(forms) == set(COMPILERS) and all(len(argvs) == 1 for argvs in forms.values())
    selectors = {crate: argvs[0] for crate, argvs in forms.items()}
    request = member(z, prefix + "scoped-request.json")
    assert request["selectors"] == selectors and request["command"] == COMMAND
    material = member(z, prefix + "kernel-B/products.json")
    assert material == member(z, prefix + "bare-B/products.json") and len(material["workspace"]) == 39
    assert {k: len(v) for k, v in material["externs"].items()} == {"uv_configuration": 30, "uv_client": 64}
    visits = member(z, prefix + "visit-order.json")
    assert [v[0] for v in visits] == ["wall", "whole", "threads"]
    assert all(a[1] < a[2] <= b[1] < b[2] for a, b in zip(visits, visits[1:]))
    for kind, _, _ in visits:
        directory = prefix + kind + "/"
        checked = member(z, directory + "verified.json")
        products = z.read(directory + "products.json")
        assert checked["same_seed"] and checked["seed"] == seed and checked["boot"] == boot
        assert checked["source"] == EDIT and checked["measured"] == digest(products) and json.loads(products) == material
        witness = member(z, directory + "native/witness.json")["codes"]
        assert witness["schema"] == [0, []] and witness["client-negative"] == [1, ["E0308"]]

    threads = member(z, prefix + "threads/per-rustc.json")
    assert threads["scope"] == "retired userspace instructions in the selected process and its threads"
    assert set(threads["targets"]) == set(COMPILERS)
    pids = {threads["root"]}
    measured = {}
    for crate, row in threads["targets"].items():
        assert row["argv"] == selectors[crate] and row["pid"] > 0 and row["pid"] not in pids
        pids.add(row["pid"])
        count, enabled, running, event = struct.unpack("<4Q", bytes.fromhex(row["raw_hex"]))
        assert count == row["instructions"] > 0 and event == row["event_id"] > 0
        assert enabled == running == row["time_enabled_ns"] == row["time_running_ns"] > 0
        measured[crate] = count
    measured["sum_two"] = sum(measured.values())
    whole = member(z, prefix + "whole/whole-clock.json")
    assert whole["code"] == whole["event_errno"] == 0 and whole["enabled"] == whole["running"] > 0
    assert whole["instructions"] > 0
    measured["whole"] = whole["instructions"]
    clock = member(z, prefix + "wall/ordinary.json")
    assert clock["wait"] == "os.waitpid(child.pid, 0)" and clock["mode"] == "native"
    assert clock["pid"] > 0 and clock["exit"] == 0 and clock["argv"] == clock["invoked"] == COMMAND
    assert clock["cpus"] == affinity and clock["boot"] == boot
    assert visits[0][1] <= clock["start_ns"] < clock["end_ns"] <= visits[0][2]
    assert clock["end_ns"] - clock["start_ns"] == clock["ns"] > 0
    measured["wall"] = clock["ns"]
    stderr = z.read(prefix + "wall/cargo.stderr")
    line, = [v for v in stderr.decode().splitlines() if v.startswith("    Finished `dev` profile [unoptimized + debuginfo] target(s) in ")]
    cargo = dict(pair=pair, role=role, finished=line, stderr_sha256=digest(stderr), blocking_ns=clock["ns"])
    return seed, visits[0][1], visits[-1][2], measured, cargo


def reopen(path, expected, roles, orders, boot, donor, verdict_source):
    assert file_hash(path) == expected and file_hash(donor) == DONOR and file_hash(verdict_source) == VERDICT
    previous = runpy.run_path(str(donor))
    previous["controls"]()
    roster = previous["verify_all_compilers"]
    roster.__globals__["ROLES"] = tuple(roles)
    assert list(roles) in (["R", "F"], ["S", "F"]) and len(orders) == 8
    verdict = runpy.run_path(str(verdict_source))["verdict"]
    with ZipFile(path) as archive:
        assert len(archive.namelist()) == len(set(archive.namelist()))
        original = member(archive, "native-22958/score.json")
        guards = member(archive, "native-22958/all-native-guards.json")
        attestation = member(archive, "boot-attestation.json")
        assert guards["orders"] == orders and guards["roles"] == list(roles)
        assert original["complete"] and guards["independent"] == original["independent_histories"] == 16
        assert original["boot"] == guards["boot"] == attestation["boot"] == boot
        assert original["actual_signed_Cargo"] == COMMAND
        rows = {metric: [] for metric in METRICS}
        seeds = set()
        previous_end = 0
        lines = []
        for pair, order in enumerate(orders, 1):
            assert sorted(order) == sorted(roles)
            arms = {}
            for role in order:
                seed, start, end, arms[role], line = open_arm(archive, pair, role, boot, attestation["affinity"])
                assert seed not in seeds and previous_end <= start < end
                seeds.add(seed)
                previous_end = end
                lines.append(line)
            for metric in METRICS:
                rows[metric].append([arms[role][metric] for role in roles])
        assert len(seeds) == 16 and lines == original["observed_Cargo_Finished_lines"]
        metrics = original["metrics"]
        for metric, pairs in rows.items():
            observed = previous["score"](pairs)
            reported = metrics[metric]
            assert pairs == reported["control_and_treatment"]
            assert observed["paired_speedups"] == reported["paired_control_over_treatment"]
            assert observed["paired_median_speedup"] == reported["median_speedup"]
            assert observed["both_hold_median_speedups"] == reported["half_medians_speedup"]
        decision = verdict({k: {"control_and_treatment": v} for k, v in rows.items()})
        assert decision["qualifies_2x_on_this_host"] == original["primary_wall_twofold_all_eight"]
        if "predeclared" in original:
            assert decision == original["predeclared"]
        traces = roster(archive)
    return {"original_sha256": expected, "boot": boot, "pairs": 8, "raw": rows, "verdict": decision,
            "compiler_traces": len(traces), "compiler_executions": sum(len(t["units"]) for t in traces)}
