"""Recompute the paired ordinary Cargo clocks and hardware counts from an original Actions ZIP."""
import argparse
import hashlib
import json
import statistics
import struct
from pathlib import Path
from zipfile import ZipFile


def require(predicate, message):
    if not predicate:
        raise ValueError(message)


def get(archive, name):
    return json.loads(archive.read(name))


def clock(archive, base, package, subcommand):
    rec = get(archive, base + "/wall/ordinary.json")
    require(rec["argv"] == rec["invoked"], "ordinary Cargo had a launcher")
    require(rec["mode"] == "native" and not rec["deadline_fired"], "invalid ordinary visit")
    require(rec["argv"][1:] == [subcommand, "-p", package, "--locked", "--offline", "-j8"], "different Cargo command")
    require(not any(rec["env"].get(k) for k in ("RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "CARGO_BUILD_RUSTC_WRAPPER", "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER")), "compiler wrapper")
    require(rec["exit"] == 0 and rec["end_ns"] - rec["start_ns"] == rec["ns"] > 0, "ordinary clock")
    stderr = archive.read(base + "/wall/cargo.stderr")
    require(b"Finished" in stderr, "Cargo completion record")
    return rec


def check(archive, spec):
    rows = []
    crates = set(spec["crates"])
    times = []
    for number, declared in enumerate(spec["order"]):
        row = {}
        for arm in ("parent", "candidate"):
            base = "uv-client/pair-" + str(number) + "-" + spec["roles"][arm]
            normal = clock(archive, base, "uv-client", "check")
            require(normal["boot"] == spec["boot"], "ordinary boot")
            require(normal["start_ns"] not in times, "repeated ordinary interval")
            times.append(normal["start_ns"])
            whole = get(archive, base + "/clock/whole-clock.json")
            require(whole["enabled"] == whole["running"] > 0 and whole["event_errno"] == whole["code"] == 0, "whole Cargo hardware coverage")
            children = get(archive, base + "/scoped/per-rustc.json")
            events = get(archive, base + "/scoped/kernel-events.json")
            require(children["root"] == events["root"], "scoped root PID")
            execs = {e[0]: e[3] for e in events["events"]
                     if len(e) == 4 and e[1] >> 16 == 4 and isinstance(e[3], dict)
                     and e[3]["exe"].endswith("/rustc") and "--crate-name" in e[3]["argv"]}
            require(set(children["targets"]) == crates and len(execs) == len(crates), "wrong dirty targets")
            counters = {}
            pids = set()
            for name, target in children["targets"].items():
                pid = target["pid"]
                e = execs[pid]
                require(e["file"] == target["file"] and e["exe"] == target["exe"] and e["argv"] == target["argv"], "rustc image/argv mismatch")
                require(e["argv"][e["argv"].index("--crate-name") + 1] == name and pid not in pids, "duplicate/wrong rustc")
                count, enabled, running, event = struct.unpack("<QQQQ", bytes.fromhex(target["raw_hex"]))
                require(enabled == running == target["time_enabled_ns"] == target["time_running_ns"] > 0, "rustc hardware coverage")
                require(event == target["event_id"] and count == target["instructions"] > 0, "rustc hardware event")
                counters[name] = count
                pids.add(pid)
            require(counters == get(archive, base + "/scoped/counts.json"), "on-runner count mismatch")
            row[arm] = {"wall_ns": normal["ns"], "cargo_instructions": whole["instructions"],
                        "per_rustc": counters, "rustc_instructions": sum(counters.values()), "start_ns": normal["start_ns"]}
        observed = sorted(row, key=lambda k: row[k]["start_ns"])
        require(observed == declared, "physical parent/candidate order differs from registration")
        rows.append(row)
    return rows


def build(archive, spec):
    rows = []
    for number, declared in enumerate(spec["order"], 1):
        row = {}
        for pos, arm in enumerate(declared, 1):
            base = f"pair-{number:02}/{pos}-{arm}/ordinary/native"
            r = get(archive, base + "/record.json")
            require(r["argv"][1:] == ["build", "--locked", "--offline", "-j8", "-p", "uv-cli"], "different Cargo build")
            require(r["exit"] == 0 and r["end_monotonic_ns"] - r["start_monotonic_ns"] == r["wall_ns"] > 0, "ordinary build clock")
            require(b"Finished" in archive.read(base + "/stderr"), "Cargo completion record")
            row[arm] = {"wall_ns": r["wall_ns"], "start_ns": r["start_monotonic_ns"]}
        require(sorted(row, key=lambda k: row[k]["start_ns"]) == declared, "build order")
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("series", choices=("marginal", "build", "cumulative"))
    parser.add_argument("zip", type=Path, nargs="?", help="original service archive; marginal/build default to their compact authenticated packet")
    args = parser.parse_args()
    spec = json.loads(Path(__file__).with_name("series.json").read_text())[args.series]
    source = args.zip
    if source is None:
        require("packet" in spec, "supply the original service archive or use the standalone direct verifier")
        source = Path(__file__).with_name(spec["packet"])
    with source.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    allowed = {spec["zip_sha256"], spec.get("packet_sha256")}
    require(digest in allowed, "different original or compact packet")
    with ZipFile(source) as archive:
        require(len(archive.namelist()) == len(set(archive.namelist())), "duplicate archive member")
        if digest == spec.get("packet_sha256"):
            require(set(archive.namelist()) == set(spec["members"]), "unexpected compact member set")
        for name, expected in spec.get("members", {}).items():
            require(hashlib.sha256(archive.read(name)).hexdigest() == expected, "changed original member " + name)
        rows = build(archive, spec) if args.series == "build" else check(archive, spec)
    out = {"rows": rows, "parent_over_candidate": {}}
    for metric in ("wall_ns", "rustc_instructions", "cargo_instructions"):
        if metric in rows[0]["parent"]:
            ratios = [r["parent"][metric] / r["candidate"][metric] for r in rows]
            out["parent_over_candidate"][metric] = {"pairs": ratios, "median": statistics.median(ratios)}
    print(json.dumps(out, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
