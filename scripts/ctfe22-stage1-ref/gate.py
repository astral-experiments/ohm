"""Discriminate real typeck providers with native self-profiles, with warm and fresh output controls."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import struct
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
TRACE_EVENTS = "generic-activity,query-provider,incr-cache-load,incr-result-hashing,query-keys"
FAMILIES = {"typeck_root", "mir_borrowck"}
CASES = {"unchanged": (889, 25), "ampersand": (889, 28), "identifier": (889, 27),
         "closing-brace": (889, 27), "landed-getter": (890, 25), "real-lifetime-change": None}
Profile = runpy.run_path(str(HERE / "profile_v9.py"))["Profile"]
Graph = runpy.run_path(str(HERE / "graph.py"))["Graph"]
KEY = "5b4a087c7571590cab3e99a499744a32"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def put(path, value):
    with path.open("x") as handle:
        json.dump(value, handle, sort_keys=True, indent=1)
        handle.write("\n")


def inputs():
    manifest = load(HERE / "registration.json")
    assert all(file_hash(HERE / name) == value for name, value in manifest["files"].items())
    data = load(HERE / "inputs.json")
    assert set(data["cases"]) == set(CASES) and len(data["states"]) == 7
    assert all(file_hash(HERE / role) == value for role, value in data["maintained_files"].items())
    return data


def required_absolute(path):
    value = Path(path)
    assert value.is_absolute(), "supply an absolute path"
    return value.resolve()


def process(argv, work, env, allow_error=False):
    with subprocess.Popen(argv, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        try:
            out, err = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        if not allow_error and proc.returncode:
            raise RuntimeError((argv, proc.returncode, err[:4096]))
        return proc.pid, proc.returncode, out, err


def profile_counts(raw, graph_raw, epoch, pid, argv, crate, version=b"1.99.0-dev"):
    assert 0 < len(raw) <= 16 << 20
    p = Profile(raw)
    meta = json.loads(p.label(100000001))
    assert meta["process_id"] == pid and meta["cmd"].rstrip(" ") == " ".join(argv)
    schema = load(HERE / "kinds.json")
    assert digest(("\n".join(schema["kinds"]) + "\n").encode()) == schema["source"]["sha256"]
    graph = Graph(graph_raw, schema["kinds"], epoch, version)
    counts = {event: Counter() for event in ("Query", "IncrementalLoadResult", "IncrementalResultHashing")}
    activity = Counter()
    for class_id, event_id, _, lo, hi, flags in struct.iter_unpack("<QQIIII", memoryview(p.entries)[8:]):
        end = hi | ((flags & 65535) << 32)
        if end >= 0xfffffffffffe:
            continue
        start = lo | ((flags & 0xffff0000) << 16)
        assert start <= end
        event = p.label(class_id)
        activity[event] += 1
        if event not in counts:
            continue
        label = p.label(event_id)
        labelled, sep, owner = label.partition("\x1e")
        node = graph.by_id.get(event_id)
        if node is None:
            # A missing graph node without a complete, another-query identity can hide a provider.
            assert labelled in schema["kinds"] and labelled not in FAMILIES and labelled != "incoherent_impls"
            continue
        family, key = node
        assert not labelled or labelled == family, (event, family, labelled, event_id)
        if family in FAMILIES:
            assert labelled == family and sep and owner == crate + "::check", (family, owner)
            counts[event][family + " " + owner] += 1
        elif family == "incoherent_impls" and key == KEY:
            assert not labelled or (sep and owner == "Ref(Not)")
            counts[event]["incoherent_impls Ref(Not)"] += 1
    assert activity["GenericActivity"] and activity["Query"], "profile lacks positive query telemetry"
    return {kind: dict(sorted(values.items())) for kind, values in counts.items()} | {"graph_session": graph.session}


def external_spans(node):
    spans = [[s["line_start"], s["column_start"]] for s in node.get("spans", [])
             if s["file_name"].endswith("workspace.rs")]
    for child in node.get("children", []):
        spans.extend(external_spans(child))
    return spans


def save_blob(directory, raw):
    assert len(raw) <= 8 << 20
    expected = digest(raw)
    if directory is not None:
        path = directory / (expected + ".gz")
        if not path.exists():
            with path.open("xb") as file:
                file.write(gzip.compress(raw, compresslevel=1, mtime=0))
    return expected


def compile_one(sdk, work, name, env, case=None, keyed=False, blobs=None):
    args = [str(sdk / "bin/rustc"), "--sysroot", str(sdk), "--edition=2024", "--crate-type=lib",
            "--emit=metadata", "--error-format=json", "--crate-name", name, "-Zthreads=1",
            "-Zincremental-verify-ich=yes", "-Cincremental=inc-" + name,
            "--remap-path-prefix=" + str(work) + "=/ohm-getter", name + ".rs"]
    if name != "workspace":
        args.extend(["--extern", "workspace=libworkspace.rmeta"])
    if keyed:
        args.extend(["-Zself-profile=keys-" + name, "-Zself-profile-events=" + TRACE_EVENTS])
    pid, code, out, err = process(args, work, env, allow_error=True)
    assert not out
    parsed = [json.loads(line) for line in err.splitlines()]
    codes = [d["code"]["code"] for d in parsed if d.get("code")]
    spans = [s for d in parsed for s in external_spans(d)]
    span = CASES.get(case) if name in ("lint", "hard") else None
    if case is not None:
        assert codes == ((["E0794"] if name == "hard" else ["late_bound_lifetime_arguments"]) if span else [])
        assert spans == ([list(span)] if span else []) and code == int(name == "hard" and span is not None)
    else:
        assert code == 0 and name != "hard"
    meta = work / ("lib" + name + ".rmeta")
    ordinary = {"exit": code, "codes": codes, "external_spans": spans, "stderr": save_blob(blobs, err),
                "metadata": save_blob(blobs, meta.read_bytes()) if code == 0 else None}
    if code == 0:
        _, _, root, noise = process([str(sdk / "bin/rustc"), "-Zls=root", str(meta)], work, env)
        assert root and not noise
        ordinary["decoded_root"] = save_blob(blobs, root)
    trace = None
    if keyed:
        path, = (work / ("keys-" + name)).rglob("*.mm_profdata")
        raw = path.read_bytes()
        graph_path, = (work / ("inc-" + name)).glob("*/s-*/dep-graph.bin")
        graph = graph_path.read_bytes()
        trace = (raw, {"pid": pid, "argv": args, "sha256": digest(raw), "graph": save_blob(blobs, graph),
                       "events": profile_counts(raw, graph, 43309, pid, args, name)})
    return ordinary, trace


def write_sources(work, text, data):
    (work / "workspace.rs").write_text(text)
    for crate, field in (("normal", "normal"), ("lint", "lint"), ("hard", "error")):
        (work / (crate + ".rs")).write_text(data["consumers"][field])


def matrix(sdk, work, env, case, seed, output, sources, data):
    before, after = sources
    # Bootstrap A independently for this seed/case; all same-seed B arms restore exactly these bytes.
    work.mkdir()
    write_sources(work, before, data)
    for crate in ("workspace", "normal", "lint"):
        compile_one(sdk, work, crate, env)
    saved = work.parent / "prior"
    work.rename(saved)
    previous = {}
    for crate in ("normal", "lint"):
        graph, = (saved / ("inc-" + crate)).glob("*/s-*/dep-graph.bin")
        previous[crate] = file_hash(graph)
    states = {}
    records = {}
    for arm in ("native", "keyed", "cold", "cold-keyed"):
        if arm.startswith("cold"):
            work.mkdir()
        else:
            shutil.copytree(saved, work)
        write_sources(work, after, data)
        states[arm] = {}
        for crate in ("workspace", "normal", "lint", "hard"):
            typed = arm in ("keyed", "cold-keyed") and crate in ("normal", "lint")
            outcome, profile = compile_one(sdk, work, crate, env, case, typed, output / "blobs")
            states[arm][crate] = outcome
            if typed:
                raw, evidence = profile
                safe = f"seed-{seed}-{case}-{arm}-{crate}.mm_profdata.gz"
                with (output / safe).open("xb") as file:
                    file.write(gzip.compress(raw, compresslevel=1, mtime=0))
                records[arm + "/" + crate] = evidence | {"file": safe}
        shutil.rmtree(work)
    shutil.rmtree(saved)
    assert states["native"] == states["keyed"] == states["cold"] == states["cold-keyed"], (seed, case, states)
    for crate in ("normal", "lint"):
        for kind in FAMILIES:
            name = kind + " " + crate + "::check"
            assert records["cold-keyed/" + crate]["events"]["Query"].get(name) == 1
            if case == "unchanged":
                assert name not in records["keyed/" + crate]["events"]["Query"]
    return {"source_A_graphs": previous, "arms": states, "profiles": records}


def bucket_states(sdk, work, env, data):
    work.mkdir()
    for name in ("roster.rs", "reader.rs"):
        shutil.copyfile(HERE / name, work / name)
    rows = []
    for i, state in enumerate(data["states"]):
        cfg = [value for name in state["cfgs"] for value in ("--cfg", name)]
        driver = [str(sdk / "bin/rustc"), "--sysroot", str(sdk)]
        _, _, out, err = process(driver + ["--crate-type=rlib", "roster.rs", *cfg], work, env)
        assert not out and not err
        stamps = {}
        for cache in ("history", "cold-" + str(i)):
            _, _, out, err = process(driver + ["-Cincremental=" + cache, "-Zincremental-verify-ich",
                                                 "--extern", "roster=libroster.rlib", "reader.rs"], work, env)
            assert not out and not err
            _, _, answer, err = process([str(work / "reader")], work, env)
            assert answer.decode().strip() == state["stdout"] and not err
            stamps[cache] = file_hash(work / "reader")
        assert len(set(stamps.values())) == 1, (i, stamps)
        rows.append(state | {"binaries": stamps})
    return rows


def sdk_identity(sdk, env, source, expected_driver):
    assert (sdk / "bin/rustc").is_file() and (source is None or re.fullmatch("[0-9a-f]{40}", source))
    driver, = sorted((sdk / "lib").glob("librustc_driver-*.so"))
    driver_hash = file_hash(driver)
    assert not expected_driver or driver_hash == expected_driver
    _, _, version, err = process([str(sdk / "bin/rustc"), "-vV"], HERE, env)
    assert not err and b"host: x86_64-unknown-linux-gnu" in version
    _, _, lib, err = process([str(sdk / "bin/rustc"), "--sysroot", str(sdk), "--print", "target-libdir"], HERE, env)
    libdir = Path(lib.decode().strip()).resolve()
    assert not err and libdir.is_relative_to(sdk)
    std = {p.name: file_hash(p) for pattern in ("libcore-*.r*", "libstd-*.r*") for p in sorted(libdir.glob(pattern))}
    assert any(k.startswith("libcore-") for k in std) and any(k.startswith("libstd-") for k in std)
    return {"path": str(sdk), "driver": driver.name, "driver_sha256": driver_hash, "rustc_sha256": file_hash(sdk / "bin/rustc"),
            "rustc_vV": version.decode(), "core_and_std": std, "source_label": source,
            "externally_supplied_driver_sha256": expected_driver}


def run(args):
    data = inputs()
    sdk, out = required_absolute(args.sdk), required_absolute(args.output)
    assert not out.exists() and not out.is_relative_to(sdk) and not sdk.is_relative_to(out)
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "RUSTC_BOOTSTRAP": "1", "LD_LIBRARY_PATH": str(sdk / "lib")}
    identity = sdk_identity(sdk, env, args.source, args.expect_driver)
    out.mkdir(parents=True)
    (out / "blobs").mkdir()
    put(out / "identity.json", identity)
    fixtures = {}
    with tempfile.TemporaryDirectory(prefix="ohm-getter-native-") as tmp:
        root = Path(tmp)
        for seed in (1, 2):
            fixtures[str(seed)] = {}
            for case, pair in data["cases"].items():
                record = matrix(sdk, root / "live", env, case, seed, out, pair, data)
                put(out / f"seed-{seed}-{case}.json", record)
                fixtures[str(seed)][case] = record
        buckets = bucket_states(sdk, root / "methods", env, data)
    completed = {"schema": 1, "enrollment": file_hash(HERE / "registration.json"), "sdk": identity,
                 "cases": fixtures, "method_changes": buckets}
    assert sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) < 96 << 20
    verify_record(out, completed)
    put(out / "complete.json", completed)
    print(json.dumps({"complete": file_hash(out / "complete.json"), "driver": identity["driver_sha256"]}))


def verify_record(out, recorded):
    data = inputs()
    assert recorded["schema"] == 1 and recorded["enrollment"] == file_hash(HERE / "registration.json")
    assert recorded["sdk"] == load(out / "identity.json")
    assert set(recorded["cases"]) == {"1", "2"}
    method_changes = recorded["method_changes"]
    assert len(method_changes) == len(data["states"]) == 7
    for i, (actual, expect) in enumerate(zip(method_changes, data["states"], strict=True)):
        assert {k: actual[k] for k in expect} == expect
        assert set(actual["binaries"]) == {"history", "cold-" + str(i)} and len(set(actual["binaries"].values())) == 1
    role_profile = {}
    recorded_blobs = set()
    for seed, states in recorded["cases"].items():
        assert set(states) == set(CASES)
        for case, record in states.items():
            assert load(out / f"seed-{seed}-{case}.json") == record
            arms = record["arms"]
            assert set(arms) == {"native", "keyed", "cold", "cold-keyed"}
            assert arms["native"] == arms["keyed"] == arms["cold"] == arms["cold-keyed"]
            assert set(arms["native"]) == {"workspace", "normal", "lint", "hard"}
            for name, stage in arms["native"].items():
                for k in ("stderr", "metadata", "decoded_root"):
                    if stage.get(k):
                        recorded_blobs.add(stage[k])
                diag_bytes = gzip.decompress((out / "blobs" / (stage["stderr"] + ".gz")).read_bytes())
                diagnostics = [json.loads(line) for line in diag_bytes.splitlines()]
                codes = [d["code"]["code"] for d in diagnostics if d.get("code")]
                assert codes == stage["codes"]
                origins = [s for d in diagnostics for s in external_spans(d)]
                coord = CASES[case] if name in ("lint", "hard") else None
                assert origins == stage["external_spans"] == ([list(coord)] if coord else [])
                assert codes == ((["E0794"] if name == "hard" else ["late_bound_lifetime_arguments"]) if coord else [])
                assert stage["exit"] == int(name == "hard" and coord is not None)
                assert bool(stage["metadata"] and stage.get("decoded_root")) == (stage["exit"] == 0)
            profiles = record["profiles"]
            assert set(profiles) == {f"{arm}/{c}" for arm in ("keyed", "cold-keyed") for c in ("normal", "lint")}
            for handle, evidence in profiles.items():
                arm, crate = handle.split("/")
                path = out / f"seed-{seed}-{case}-{arm}-{crate}.mm_profdata.gz"
                assert evidence["file"] == path.name
                raw = gzip.decompress(path.read_bytes())
                assert digest(raw) == evidence["sha256"]
                argv = evidence["argv"]
                assert argv[0] == str(Path(recorded["sdk"]["path"]) / "bin/rustc")
                assert argv[1:3] == ["--sysroot", recorded["sdk"]["path"]]
                assert argv[-1] == "-Zself-profile-events=" + TRACE_EVENTS and argv.count("--crate-name") == 1
                assert argv[argv.index("--crate-name") + 1] == crate
                recorded_blobs.add(evidence["graph"])
                graph = gzip.decompress((out / "blobs" / (evidence["graph"] + ".gz")).read_bytes())
                assert digest(graph) == evidence["graph"]
                actual = profile_counts(raw, graph, 43309, evidence["pid"], argv, crate)
                assert actual["graph_session"] == (1 if arm == "cold-keyed" else 2)
                assert actual == evidence["events"]
                for kind in FAMILIES:
                    owner = kind + " " + crate + "::check"
                    count = actual["Query"].get(owner, 0)
                    assert count in (0, 1)
                    if arm == "cold-keyed":
                        assert count == 1
                    elif case == "unchanged":
                        assert count == 0
                    label = (case, arm, crate, kind)
                    assert role_profile.setdefault(label, count) == count, (label, "independent A histories disagree")
    assert {p.stem for p in (out / "blobs").glob("*.gz")} == recorded_blobs
    assert all(digest(gzip.decompress((out / "blobs" / (v + ".gz")).read_bytes())) == v for v in recorded_blobs)
    return role_profile


def compare(args):
    before, after = map(required_absolute, (args.baseline, args.candidate))
    base, cand = [load(p / "complete.json") for p in (before, after)]
    left, right = verify_record(before, base), verify_record(after, cand)
    assert left.keys() == right.keys() and base["sdk"]["driver_sha256"] != cand["sdk"]["driver_sha256"]
    rows = []
    for (case, arm, crate, kind), count in sorted(left.items()):
        if arm == "keyed":
            updated = right[case, arm, crate, kind]
            rows.append({"case": case, "crate": crate, "provider": kind, "before": count, "after": updated})
    stage_differences = {}
    for seed in ("1", "2"):
        for case in sorted(CASES):
            one, two = [r["cases"][seed][case]["arms"]["native"] for r in (base, cand)]
            for crate in sorted(one):
                changed = [key for key in one[crate] if one[crate].get(key) != two[crate].get(key)]
                if changed:
                    stage_differences[f"{seed}/{case}/{crate}"] = changed
    return {"enrollment": base["enrollment"], "baseline": file_hash(before / "complete.json"),
            "candidate": file_hash(after / "complete.json"), "actual_providers": rows,
            "disappeared": [r for r in rows if r["before"] and not r["after"]],
            "newly_ran": [r for r in rows if not r["before"] and r["after"]],
            "unchanged": sum(r["before"] == r["after"] for r in rows),
            "within_sdk_raw_cold_agreement": True, "cross_sdk_stage_differences": stage_differences,
            "same_core_and_std": base["sdk"]["core_and_std"] == cand["sdk"]["core_and_std"],
            "runtime_first_veto_observed": False, "performance_measurements": 0}


def offline():
    data = inputs()
    nested = {"spans": [{"file_name": "normal.rs", "line_start": 4, "column_start": 11}],
              "children": [{"spans": [{"file_name": "/ohm-getter/workspace.rs", "line_start": 890, "column_start": 25}]}]}
    assert external_spans(nested) == [[890, 25]]
    rec = load(HERE / "control-result.json")
    raw = gzip.decompress((HERE / "control-query-keys.gz").read_bytes())
    assert digest(raw) == rec["profile_sha256"]
    prof = Profile(raw)
    pid = json.loads(prof.label(100000001))["process_id"]
    graph = gzip.decompress((HERE / "control-A.graph.gz").read_bytes())
    assert digest(graph) == rec["graph_sha256"]
    found = profile_counts(raw, graph, 43308, pid, rec["argv"], "normal")
    assert found["Query"]["typeck_root normal::check"] == 1 and found["Query"]["mir_borrowck normal::check"] == 1
    assert found["Query"]["incoherent_impls Ref(Not)"] == 1
    for changed_pid, changed_args in ((pid + 1, rec["argv"]), (pid, rec["argv"][:-1])):
        try:
            profile_counts(raw, graph, 43308, changed_pid, changed_args, "normal")
        except AssertionError:
            continue
        raise AssertionError("incorrect profile process or argv accepted")
    # Drop the actual typeck string from its virtual table. Its real graph node still
    # identifies a typeck provider, so a textual absence must never become a false zero.
    hit, = [i for i in prof.virtual if prof.label(i) == "typeck_root\x1enormal::check"]
    pages = [bytearray() for _ in range(3)]
    offset = 8
    while offset < len(raw):
        tag, size = struct.unpack_from("<BI", raw, offset)
        pages[tag].extend(raw[offset+5:offset+5+size])
        offset += 5 + size
    chosen, = [i for i, (key, _) in enumerate(struct.iter_unpack("<QQ", pages[2][8:])) if key == hit]
    sentinel = 95000000
    assert sentinel not in prof.virtual
    struct.pack_into("<Q", pages[2], 8 + chosen * 16, sentinel)
    hidden = raw[:8] + b"".join(struct.pack("<BI", i, len(page)) + page for i, page in enumerate(pages))
    assert Profile(hidden).label(hit) == ""
    try:
        profile_counts(hidden, graph, 43308, pid, rec["argv"], "normal")
    except AssertionError:
        pass
    else:
        raise AssertionError("a real graph-identified typeck provider with erased text became a false zero")
    return {"native_executions": 0, "control_graph_sha256": digest(graph), "source": data["source"], "cases": len(data["cases"]), "method_states": len(data["states"]),
            "profile_sha256": digest(raw), "positive_provider_occurrences": found["Query"],
            "refused": ["unrelated PID", "different rustc argv", "unlabelled graph-proved typeck provider"]}


def main():
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("offline")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("sdk")
    run_parser.add_argument("output")
    run_parser.add_argument("--source")
    run_parser.add_argument("--expect-driver")
    check = sub.add_parser("verify")
    check.add_argument("output")
    diff = sub.add_parser("compare")
    diff.add_argument("baseline")
    diff.add_argument("candidate")
    args = parser.parse_args()
    if args.action == "run":
        return run(args)
    if args.action == "verify":
        dest = required_absolute(args.output)
        verify_record(dest, load(dest / "complete.json"))
        result = {"complete": file_hash(dest / "complete.json")}
    else:
        result = offline() if args.action == "offline" else compare(args)
    print(json.dumps(result, sort_keys=True, indent=1))


if __name__ == "__main__":
    main()
