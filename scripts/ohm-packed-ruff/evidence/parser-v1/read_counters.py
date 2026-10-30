"""Independently verify both actual compiler processes for twelve instrumented returns."""

import gzip
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from read_ordinary import (
    ARMS,
    EXPECTED_CARGO,
    LIVE,
    PHASES,
    Archive,
    compare_archives,
    qualify_inputs,
    sha,
)

HEAD = "c6768ffeb54071ea77b3c056b27f179967f77c44"
ORDINARY = "6b57edb09de2a77f6dbec1fe4bb0b80c9aac845bbc7a001b3019f62e76570218"
RETURNS = ("return-A", "return-B")


def self_count(stream, pid):
    total = 0
    edge = False
    events = []
    totals = []
    pids = []
    for row in stream:
        if row.startswith(b"events: "):
            events.append(row.strip().split()[1:])
        elif row.startswith(b"totals: "):
            assert len(row.split()) == 2
            totals.append(int(row.split()[1]))
        elif row.startswith(b"pid: "):
            pids.append(row.split()[1])
        elif row.startswith(b"calls="):
            assert not edge
            edge = True
        elif re.match(rb"^[0-9+*-]", row):
            if edge:
                edge = False
            else:
                total += int(row.split()[-1])
    assert (
        not edge
        and events == [[b"Ir"]]
        and totals == [total]
        and total > 0
        and pids == [pid.encode()]
    )
    return total


def one_counter(archive, prefix, arm):
    stderr = archive.raw(prefix + "cargo.stderr")
    calls = re.findall(
        rb"^compiler ([0-9]+) ([a-z0-9_]+) ([0-9]+) ([0-9]+)$", stderr, re.M
    )
    assert len(calls) == 2 and sorted(row[1].decode() for row in calls) == LIVE
    assert re.findall(rb"^cargo ([0-9]+)$", stderr, re.M) == [b"0"] and re.findall(
        rb"^links ([0-9]+)$", stderr, re.M
    ) == [b"0"]
    counts = archive.record(prefix + "callgrind/counts.json")
    assert counts["wild_links"] == 0 and set(counts["crates"]) == set(LIVE)
    profiles = {}
    total = 0
    for proc, crate, attached, exitcode in calls:
        assert (attached, exitcode) == (b"1", b"0")
        name = crate.decode()
        pid = proc.decode()
        q = prefix + "callgrind/"
        inventory = counts["crates"][name]
        args = archive.raw(q + "rustc." + pid + ".argv")
        assert sha(args) == inventory["argv_sha256"]
        argv = args.split(b"\0")
        assert argv[argv.index(b"--crate-name") + 1] == crate and any(
            v.startswith(b"--emit=") for v in argv
        )
        assert b"-Zohm-check-relink-inputs" in argv and (
            b"-Zohm-branch-cache=yes" in argv
        ) == (arm != "Off")
        assert (
            archive.raw(q + "rustc." + pid + ".jobserver").strip()
            and archive.raw(q + "rustc." + pid + ".fds").strip()
        )
        basename = "output." + pid + "." + pid + ".gz"
        assert inventory["profile"] == basename
        assert sha(archive.raw(q + basename)) == inventory["compressed_sha256"]
        with archive.z.open(q + basename) as outer, gzip.GzipFile(
            fileobj=outer
        ) as stream:
            val = self_count(stream, pid)
        log = gzip.decompress(archive.raw(q + "valgrind." + pid + "." + pid + ".gz"))
        (recorded,) = re.findall(
            rb"^==" + proc + rb"== Collected\s+:\s+([\d,]+)\s*$", log, re.M
        )
        assert re.findall(rb"^==(\d+)== Events\s*:\s+Ir\s*$", log, re.M) == [proc]
        assert (
            val == int(recorded.replace(b",", b"")) == inventory["Ir"]
            and not inventory["fork_logs"]
        )
        profiles[name] = {
            "Ir": val,
            "argv": sha(args),
            "profile": inventory["compressed_sha256"],
            "log": sha(log),
        }
        total += val
    outputs = [
        p for p in archive.z.namelist() if p.startswith(prefix + "callgrind/output.")
    ]
    assert len(outputs) == 2
    return profiles, total


def verify(ordinary_path, count_path, expected):
    for path, digest in ((ordinary_path, ORDINARY), (count_path, expected)):
        with Path(path).open("rb") as f:
            assert hashlib.file_digest(f, "sha256").hexdigest() == digest
    ordinary = Archive(ordinary_path)
    refs = qualify_inputs(ordinary, HEAD)
    capture = Archive(count_path)
    orders = [list(ARMS), list(reversed(ARMS))]
    plan = capture.record("plan.json")
    assert plan == {"orders": orders, "command": EXPECTED_CARGO, "phases": list(PHASES)}
    output = {
        "ordinary": ORDINARY,
        "instrumented": expected,
        "head": HEAD,
        "mirrors": [],
    }
    for i, order in enumerate(orders, 1):
        visits = {}
        for arm in order:
            stem = f"triplet-{i:02}-{arm}/"
            all_steps = capture.record(stem + "installation.json")
            for phase in PHASES:
                args = capture.record(stem + phase + "/cargo.json")
                rows = list(
                    map(
                        json.loads,
                        capture.raw(stem + phase + "/cargo.stdout").splitlines(),
                    )
                )
                ok = phase != "invalid"
                assert args["exit"] == (0 if ok else 101) and rows[-1] == {
                    "reason": "build-finished",
                    "success": ok,
                }
                if not ok:
                    assert any(
                        (r.get("message", {}).get("code") or {}).get("code") == "E0308"
                        and any(
                            "ohm_branch_switch_invalid" in t["text"]
                            for s in r["message"]["spans"]
                            for t in s["text"]
                        )
                        for r in rows
                    )
                    continue
                where = stem + phase + "/"
                row = capture.record(where + "result.json")
                assert all_steps[phase] == row
                dirty = sorted(
                    r["target"]["name"]
                    for r in rows
                    if r["reason"] == "compiler-artifact" and not r["fresh"]
                )
                assert dirty == row["dirty"] and not row["traced"]
                branch = (
                    "B-as-A"
                    if phase == "dirty-B-as-A"
                    else "A" if phase in ("empty-A", "return-A") else "B"
                )
                clean = refs[arm, branch]
                assert (
                    row["executable"] == clean["reader_sha256"]
                    and row["expr"] == clean["typed_size"]
                )
                assert (
                    capture.raw(where + "read-native.stdout").decode().strip()
                    == f"Expr={row['expr']} valid=1 rejected"
                )
                assert (
                    compare_archives(
                        clean["archives"],
                        capture.record(where + "archive-index.json.gz"),
                    )
                    == row["metadata_differences"]
                )
                assert capture.record(where + f"layout-{row['expr']}.json")["exit"] == 0
                assert (
                    capture.record(where + f"layout-{120-row['expr']}.json")["exit"]
                    == 1
                )
                assert row["counted"] == (phase in RETURNS)
                if phase in RETURNS:
                    assert (
                        dirty == LIVE
                        and args["argv"][-len(EXPECTED_CARGO) :] == EXPECTED_CARGO
                    )
                    prof, total = one_counter(capture, where, arm)
                    assert row["compiler_Ir"] == {k: v["Ir"] for k, v in prof.items()}
                    visits.setdefault(phase, {})[arm] = {
                        "total": total,
                        "rustcs": prof,
                        "allocated": row["allocated"],
                    }
                else:
                    assert args["argv"] == EXPECTED_CARGO and row["compiler_Ir"] is None
        output["mirrors"].append(visits)
    summary = capture.record("result.json")
    assert summary["metric"] == "complete rustc Ir" and summary["cohort"] == "counter"
    output["Off_over_Packed"] = {}
    output["Full_over_Packed"] = {}
    for ph in RETURNS:
        vals = [
            v[ph]["Off"]["total"] / v[ph]["Packed"]["total"] for v in output["mirrors"]
        ]
        assert vals == summary["performance"][ph]["individual"]
        output["Off_over_Packed"][ph] = vals
        output["Full_over_Packed"][ph] = [
            v[ph]["Full"]["total"] / v[ph]["Packed"]["total"] for v in output["mirrors"]
        ]
    return output


if __name__ == "__main__":
    ordinary, counts, sha256, dest = sys.argv[1:]
    observations = verify(ordinary, counts, sha256)
    with Path(dest).open("x") as out:
        json.dump(observations, out, sort_keys=True, indent=2)
        out.write("\n")
