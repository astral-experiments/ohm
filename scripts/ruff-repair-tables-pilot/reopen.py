"""Portable receiver for an original pilot artifact directory and its companion source observations."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_metadata, placement, roles, overlay, stat, protocol as P, source_binding as reg

need = P.need


def read(p):
    with gzip.open(p, "rb") if p.suffix == ".gz" else p.open("rb") as f:
        return json.load(f)


def data(p):
    return gzip.decompress(p.read_bytes())


def digest(b):
    return hashlib.sha256(b).hexdigest()


def folded(value):
    return digest((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())


def same_qualified_producer(src, sdk):
    q = read(sdk / "R-source-qualified.json")
    need(
        q["old"] == reg.P
        and q["new"] == reg.R
        and q["members"] == 81
        and len(q["run_make"]) == 7
        and len(q["units"]["rustc_incremental"]) == 11
        and q["units"]["rustc_fs_util"] == [],
        "wrong compiler tests or source",
    )
    source = read(src / "R/source.json")
    product = read(HERE / "inputs/product.json")
    need(
        source["product"] == product
        and q["source"] == reg.sha(src / "R/source.json")
        and q["tests"] == reg.sha(src / "R/checked-in-tests.json")
        and q["mixed"] == reg.sha(src / "R/mixed.json")
        and q["native"] == reg.sha(src / "R/native-shadow/complete.json"),
        "different native.source or mixed controls",
    )
    a, b = (read(sdk / (k + ".json")) for k in ("E", "R"))
    reg.check_sdk_sources(a, b)
    need(
        set(a["files"]) == set(b["files"])
        and len(a["files"]) == 81
        and a["driver"] == b["driver"]
        and a["files"][a["driver"]][0] == q["old_driver"][0]
        and b["files"][b["driver"]][0] == q["new_driver"][0]
        and all(a["files"][n][0] == b["files"][n][0] for n in a["files"] if n not in set(q["changed"]))
        and set(q["changed"]) <= {a["driver"], "bin/rustdoc"}
        and a["driver"] in q["changed"],
        "SDK member/driver drift",
    )
    old, new = ({n: [x[0], x[4], x[3]] for n, x in d["files"].items()} for d in (a, b))
    need(
        q["overlay"] == overlay.verify(src / "R/overlay", old, new, b["driver"]),
        "measured SDK cannot be reconstructed",
    )
    return q


def hardware(raw, status):
    fields = {
        "start",
        "stop",
        "user_us",
        "system_us",
        "instructions",
        "enabled",
        "running",
        "event_errno",
        "code",
    }
    need(
        set(raw) == fields
        and all(type(n) is int for n in raw.values())
        and raw["code"] == status
        and raw["instructions"] > 0
        and raw["enabled"] == raw["running"] > 0
        and raw["stop"] > raw["start"]
        and raw["user_us"] + raw["system_us"] > 0
        and raw["event_errno"] == 0,
        "hardware counter multiplexed, truncated or unauthenticated",
    )
    return raw["instructions"]


def peak(raw):
    samples = raw["samples"]
    need(
        raw["namespace"] != raw["outside_namespace"]
        and raw["argv"] == P.COMMAND
        and raw["exit"] == 0
        and raw["reaped"][str(raw["main_pid"])] == 0
        and len(samples) >= 3,
        "incomplete peak native command",
    )
    acc = [raw["before"]["allocated"], raw["after"]["allocated"]]
    values = {"allocated_peak": max(acc), "allocated_including_deleted_peak": max(acc)}
    for field in ("pss", "rss", "pss_anon"):
        for s in samples:
            need(
                sum(x[field] for x in s["processes"].values()) == s[field]
                and all(
                    x["rss"] >= x["pss"] >= x["pss_anon"] >= 0 and x["threads"] > 0
                    for x in s["processes"].values()
                ),
                "foreign per-process rollup or wrong simultaneous total",
            )
        values[field + "_peak"] = max(s[field] for s in samples)
    values["allocated_peak"] = max(acc + [s["allocated"] for s in samples])
    values["allocated_including_deleted_peak"] = max(
        acc + [s["allocated"] + s["open_deleted"] for s in samples]
    )
    need(
        all(raw[k] == n for k, n in values.items())
        and raw["sampled_deleted_accounting_complete"] == not_any_unknown(samples),
        "sampled high-water differs from native observations",
    )
    values["all_deleted_mappings_accounted"] = not_any_unknown(samples)
    values["max_working_table_pairs_observed"] = max(
        sum(
            any(dict(f).get(g, 0) > 0 and dict(f).get("ohm-packed-" + g, 0) > 0 for g in placement.GRAPH)
            for f in s["working_tables"].values()
        )
        for s in samples
    )
    need(
        all(
            0 < s["runnable_window_ns"] <= 500_000_000
            and s["request_ns"] <= s["quiescent_ns"] <= s["resume_ns"]
            for s in samples
        ),
        "sampling resolution outside registration",
    )
    return values


def not_any_unknown(samples):
    return not any(s["unresolved_deleted_maps"] for s in samples)


def process(stdout, stderr, rc):
    import source_state

    d = [json.loads(x) for x in stdout.splitlines()]
    need(
        d[-1] == {"reason": "build-finished", "success": rc == 0}
        and b"internal compiler error" not in stderr,
        "missing native Cargo verdict",
    )
    tagged = [
        e["message"]
        for e in d
        if e["reason"] == "compiler-message"
        and e["message"].get("level") == "error"
        and e["message"].get("code")
    ]
    if rc:
        need(
            len(tagged) == 1
            and tagged[0]["code"]["code"] == "E0308"
            and any(
                s["is_primary"]
                and s["file_name"] == source_state.PARSER
                and s["line_start"] == 626
                and any(t["text"].strip() == source_state.BAD.decode().strip() for t in s["text"])
                for s in tagged[0]["spans"]
            ),
            "wrong actual Ruff diagnostic",
        )
    else:
        need(not tagged, "successful arm returned error")
    return d


def checked(folder, root, messages):
    got = read(folder / "checked.json.gz")
    need(
        set(got["providers"]) == set(check_metadata.PROVIDERS) and len(got["typed"]) == 10,
        "short typed check",
    )
    for name, row in got["providers"].items():
        start = read(folder / ("listing-" + name + ".json.gz"))
        cmd = start["argv"]
        path = Path(cmd[-1])
        selected, unit = check_metadata.target_provider(
            [m for m in messages if m["reason"] == "compiler-artifact"], name
        )
        need(selected == path and unit == row["unit"], "wrong returned host/target Cargo metadata")
        body = data(root / "check-bodies" / (row["sha256"] + ".gz"))
        desc = check_metadata.listing(
            name,
            path,
            body,
            data(folder / ("listing-" + name + ".stdout.gz")),
            data(folder / ("listing-" + name + ".stderr.gz")),
            start["exit"],
        )
        need(
            cmd == ["rustc", "+ohm", "-Zls=root", str(path)] and all(desc[k] == row[k] for k in desc),
            "foreign metadata file/decoder",
        )
        for tag, rc in (("accepted", 0), ("refused", 1)):
            label = "api-" + name + "-" + tag
            good, bad, expression = check_metadata.APIS[name]
            need(
                (folder / (label + ".rs")).read_text()
                == check_metadata.client_source(good if rc == 0 else bad, expression),
                "different native client source",
            )
            n = read(folder / (label + ".json.gz"))
            sout = data(folder / (label + ".stdout.gz"))
            serr = data(folder / (label + ".stderr.gz"))
            need(
                got["typed"][name + "-" + tag] == [rc, digest(sout), digest(serr)]
                and n["exit"] == rc
                and n["expected"] == rc
                and any(arg == name + "=" + str(path) for arg in n["argv"]),
                "wrong typed API input or actual native status",
            )
            if rc:
                errors = [json.loads(x) for x in serr.splitlines()]
                coded = [d for d in errors if d.get("code") and d["level"] == "error"]
                need(
                    len(coded) == 1
                    and coded[0]["code"]["code"] == "E0308"
                    and any(
                        s["is_primary"] and Path(s["file_name"]).name == name + ".rs" and s["line_start"] == 2
                        for s in coded[0]["spans"]
                    ),
                    "wrong negative API",
                )
            else:
                need(not serr, "positive public API emitted warnings/errors")
    return got


def decoded_body(file, hashed):
    proc = subprocess.Popen(["zstd", "-dcq", file], stdout=subprocess.PIPE)
    with proc.stdout as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    need(
        proc.wait() == 0 and actual == hashed and file.name == hashed + ".zst",
        "changed whole native reference",
    )


def ordinary(folder, arm, phase, root, refs):
    v = read(folder / "visit.json")
    intent = read(folder / "intent.json.gz")
    call = read(folder / "command.json")
    out, err = data(folder / "cargo.stdout.gz"), data(folder / "cargo.stderr.gz")
    rc = 101 if "invalid" in phase else 0
    need(
        v["arm"] == arm
        and v["phase"] == phase
        and intent["expected"] == v["rc"] == call["status"] == rc
        and call["stdout_sha256"] == digest(out)
        and call["stderr_sha256"] == digest(err)
        and intent["argv"] == (P.CHECK if phase in ("stage-check", "clean-check-B") else P.COMMAND),
        "wrong actual command",
    )
    msgs = process(out, err, rc)
    ledger = read(folder / "path-inodes.json.gz")
    blocks = {}
    for row in ledger.values():
        key = tuple(row[:2])
        need(blocks.setdefault(key, row[4]) == row[4], "physical inode changed in a single sample")
    need(
        sum(blocks.values()) * 512 == v["allocated"] == read(folder / "storage.json")["allocated"],
        "settled allocated bytes differ",
    )
    if intent["method"] == "measured":
        prefix = intent["launch"][: -len(P.COMMAND)]
        need(
            len(prefix) == 2
            and Path(prefix[0]).name == "plain"
            and Path(prefix[1]).name == "clock.json"
            and intent["launch"][2:] == P.COMMAND
            and hardware(read(folder / "clock.json"), rc) == v["instructions"],
            "instrumented or incomplete measured command",
        )
    else:
        need(
            v["instructions"] is None and not (folder / "clock.json").exists(),
            "off-clock role received PMU data",
        )
    recorded = read(folder / "output-roles.json.gz")
    work = Path(intent["env"]["CARGO_TARGET_DIR"]).parent
    need(work / "build" == Path(intent["env"]["CARGO_BUILD_BUILD_DIR"]), "mismatched physical root pair")

    def owned(name, *, directory=False):
        path = Path(name)
        need(
            path.is_absolute()
            and ".." not in path.parts
            and any(path.is_relative_to(work / p) for p in ("target", "build")),
            "foreign raw Cargo path",
        )
        rel = str(path.relative_to(work))
        row = ledger.get(rel)
        need(
            row is not None and (stat.S_ISDIR(row[3]) if directory else stat.S_ISREG(row[3])),
            "missing or symlinked returned native output",
        )
        return rel

    need(
        roles.described(msgs, Path(intent["cwd"]), owned) == recorded,
        "raw Cargo output paths do not match full inode roster",
    )
    expected = len([m for m in msgs if m["reason"] == "compiler-artifact"])
    need(
        len(recorded["units"]) == expected
        and folded(recorded) == v["output_roles"]
        and all(Path(f).parts[0] in ("target", "build") for r in recorded["units"] for f in r[5])
        and all(Path(row[1]).parts[0] in ("target", "build") for row in recorded["out_dirs"]),
        "invalid per-unit physical placement",
    )
    if rc:
        return v
    if phase in ("stage-check", "clean-check-B"):
        check = checked(folder, root, msgs)
        if phase == "clean-check-B":
            refs[arm, "check"] = check
        else:
            check_metadata.equivalent(check, refs[arm, "check"])
        return v
    key = (arm, P.branch(phase), P.state(phase))
    typed = read(folder / "roster.json.gz")
    native = read(folder / "native.json.gz")
    need(
        expected == 375
        and len(typed["members"]) == 375
        and sum(not m["fresh"] for m in msgs if m["reason"] == "compiler-artifact")
        == v["dirty"]
        == len(typed["dirty"])
        and folded(typed["members"]) == v["graph"]
        and folded(typed["dirty"]) == v["dirty_digest"]
        and native["reader"]["whole"] == v["reader"]
        and native["cli"]["whole"] == v["cli"]
        and native["typed"]
        == ("Expr=64 valid=1 rejected" if P.branch(phase) == "A" else "Expr=56 valid=1 rejected"),
        "unexpected physical typed or linked body",
    )
    answer = (v["graph"], v["reader"], v["cli"], v["up035"], v["output_roles"], v["native_output"])
    if phase.startswith("clean-"):
        refs[key] = answer
    else:
        need(refs[key] == answer, ("warm results differ from own complete independent clean", arm, phase))
    if intent["method"] == "peak":
        true = peak(read(folder / "peak.json.gz"))
        need(all(v["peak"][k] == x for k, x in true.items()), "wrong physical observation")
    return v


def main(root, source):
    result = read(root / "complete.json")
    identity = read(root / "enrollment.json")
    q = same_qualified_producer(source, root / "sdk")
    need(
        q["qa"] == identity["head"]
        and q["run"] == identity["run"]
        and identity["source"] == result["qualification"] == reg.sha(root / "sdk/R-source-qualified.json")
        and identity["plan"] == reg.sha(HERE / "PLAN.md")
        and identity["previous"] == reg.sha(HERE / "inputs/previous.json"),
        "source/plan enrollment drifted",
    )
    excluded = read(HERE / "inputs/previous.json")["old_excluded_boots"]
    need(
        identity["meter"]["boot"] not in excluded
        and identity["runner"] != reg.REFUSED_RUNNER
        and identity["attempt"] == 1
        and identity["job"] == "pilot"
        and identity["command"] == P.COMMAND,
        "unregistered host",
    )
    meters = {}
    storage = {}
    peaks = {}
    refs = {}
    roles = list(P.ROLES) if result["Roff_run"] else list(P.ROLES[:2])
    need(
        roles == result["measured_roles"] and list(P.PEAK_ROLES) == result["observed_roles"],
        "unregistered arms",
    )
    for arm in roles:
        for n in ("clean-A", "clean-B", "clean-private-B", "clean-check-B"):
            ordinary(root / "empty" / arm / n, arm, n, root, refs)
        cross = check_metadata.cross(refs["Eon", "check"], refs[arm, "check"])
        need(
            cross == read(root / "empty" / arm / "cross-checked.json")
            and (arm == "Roff" or cross["complete_byte_and_listing_equality"]),
            "independent cross-role checked metadata gate",
        )
        meters[arm] = {}
        storage[arm] = {}
        for lane, phases in (("measured", P.MAIN), ("single-checkout", P.ORDINARY)):
            for name in phases:
                v = ordinary(root / lane / arm / name, arm, name, root, refs)
                meters[arm][name] = v["instructions"]
                storage[arm][name] = v["allocated"]
    if result["Roff_run"]:
        for name in ("stage-check", "stage-build"):
            ordinary(root / "default-stage" / name, "Roff", name, root, refs)
    for arm in P.PEAK_ROLES:
        peaks[arm] = {}
        for n in P.PEAK:
            f = root / "observed" / arm / n
            v = ordinary(f, arm, n, root, refs)
            if n in ("repair", "private-UP035-B"):
                peaks[arm][n] = v.get("peak")
            if n in ("repair", "verify-repair"):
                donors = read(f / "before-donors.json.gz")
                new = read(f / "newly-finalized.json.gz")
                need(
                    set(donors) == set(new)
                    and len(new) == 16
                    and {(t["fresh"]["crate"], t["target"]) for t in new.values()} == placement.EXPECTED
                    and all(
                        t["donor"] == donors[k]
                        and t["donor"]["latest"] == t["donor"]["two_paths"][-1]
                        and len(t["donor"]["two_paths"]) == 2
                        and all(row["mask"] == 3 for row in t["donor"]["streams"].values())
                        and t["fresh"]["actual"]
                        == ("packed" if arm == "Ron" and t["target"] == "lib" else "raw")
                        for k, t in new.items()
                    ),
                    "missing actual 15 library / one binary repair identity",
                )
                if n == "verify-repair":
                    with gzip.open(f / "exec.raw.gz", "rt") as stream:
                        trace = placement.returned(stream)
                    visible = Path(read(f / "intent.json.gz")["env"]["CARGO_TARGET_DIR"]).parent
                    need(
                        all(
                            t["observed_reads"] == placement.positive_read(trace, donors[k], visible, k)
                            for k, t in new.items()
                        ),
                        "wrong selected donor file/lock from real native rustc",
                    )
    need(peaks == result["sampled_observations"], "misreported unscored sampled evidence")
    allnative = {item[i] for k, item in refs.items() if len(k) == 3 for i in (1, 2)}
    for digest_ in sorted(allnative):
        decoded_body(root / "native-bodies" / (digest_ + ".zst"), digest_)
    early = P.early(meters)
    need(
        early == read(root / "early.json")["conditions"]
        and result["Roff_run"] == all(q["passed"] for q in early.values()),
        "early role stopping rule changed",
    )
    if result["Roff_run"]:
        end = P.final(meters, storage, peaks)
        need(
            result["conditions"] == end["conditions"]
            and result["decision"] == ("screen-pass" if end["passed"] else "reject"),
            "integer final decision mismatch",
        )
    else:
        need(
            result["decision"] == "reject"
            and result["conditions"] == early
            and not (root / "measured/Roff").exists(),
            "incorrect early admission",
        )
    print(
        json.dumps(
            {
                "source": reg.R,
                "driver": q["new_driver"][0],
                "run": q["run"],
                "head": q["qa"],
                "decision": result["decision"],
                "measured_roles": roles,
                "whole_native_bodies": len(allnative),
                "sampled_intervals_only": True,
                "Roff_run": result["Roff_run"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
