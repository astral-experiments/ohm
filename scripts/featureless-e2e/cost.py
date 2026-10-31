"""Acquire hardware scopes with ordinary no-ptrace flanks. Preserve an unqualified result verbatim."""

import json
import os
from pathlib import Path
import statistics
import subprocess

import counter
from kits import need, write
import state as s


def run_scope(destination, counter_bin, mode, selector, command, cwd=None, env=None):
    destination.mkdir(parents=True)
    trace = destination / "trace"
    trace.mkdir()
    p = subprocess.run([counter_bin, trace, mode, selector, "-", *command], cwd=cwd, env=env,
                       capture_output=True, timeout=3900)
    s.payload(destination / "stdout.gz", p.stdout)
    s.payload(destination / "stderr.gz", p.stderr)
    write(destination / "command.json", {"argv": list(map(str, command)), "status": p.returncode, "observer": mode})
    return p


def fields(path):
    return [v.split("\t") for v in path.read_text().splitlines()]


def parsed(d):
    rows = fields(d / "trace/counts.tsv")
    values = {k: list(map(int, v)) for k, *v in rows}
    need(set(values) == {"root", "whole", *counter.NAMES, *["hit-" + r for r in counter.NAMES]}
         and len(values) == len(rows), "counter roster")
    cmd = json.loads((d / "command.json").read_text())
    need(values["root"][1] == cmd["status"] == 0, "foreground did not succeed")
    events = []
    for seq, pid, dev, ino, role, native, image in fields(d / "trace/exec.tsv"):
        args = (d / "trace" / f"args-{int(seq):04d}").read_bytes()
        need(args.endswith(b"\0"), "incomplete kernel argv")
        events.append((int(pid), (int(dev), int(ino)), int(role), image, list(map(os.fsdecode, args[:-1].split(b"\0")))))
    pairs = fields(d / "trace/spawn.tsv")
    parents = {int(c): int(p) for k, p, c in pairs}
    need(len(parents) == len(pairs) and all(k in {"1", "2", "3"} for k, *_ in pairs), "ambiguous process tree")
    return cmd, values, events, parents


def ancestry(pid, root, parents):
    seen = set()
    while pid != root:
        need(pid not in seen and pid in parents, "disconnected kernel ancestry")
        seen.add(pid)
        pid = parents[pid]
    return seen | {root}


def hardware(v):
    need(len(v) == 4 and v[0] == 0 and v[1] > 0 and v[2] == v[3] > 0, "unavailable or multiplexed PMU")
    return v[1]


def measured(d, enrollment=None, nested=False):
    command, values, events, parents = parsed(d)
    whole = hardware(values["whole"])
    if command["observer"] == "sham":
        need(not events and not parents and all(values["hit-" + r] == [0, 0]
             and values[r] == [0, 0, 0, 0] for r in counter.NAMES), "observer affected sham")
        return {"whole": whole}
    roots = []
    counts = []
    for i, name in enumerate(counter.NAMES):
        row, = [row for row in events if row[2] == i]
        need(values["hit-" + name] == [1, row[0]], "wrong scope PID")
        roots.append(row)
        counts.append(hardware(values[name]))
    e2e, gen, cc, wild = [r[0] for r in roots]
    root = values["root"][0]
    topology = [ancestry(pid, root, parents) & {e2e, gen, cc, wild} for pid in (e2e, gen, cc, wild)]
    need(topology == [{e2e}, {gen}, {e2e, cc}, {e2e, cc, wild}], "scope ancestry")
    need(whole >= counts[0] + counts[1] and counts[0] >= counts[2] >= counts[3], "overlapping counter totals")
    packed = dict(zip(("e2e", "generator", "gcc", "wild"), counts))
    packed.update(whole=whole, e2e_less_gcc=counts[0] - counts[2])
    if nested:
        return packed
    rust, wildpath, generator, program, gcc = enrollment["paths"]
    identities = enrollment["fixed_identities"]
    for row, name, path in ((roots[0], "rustc", rust), (roots[2], "gcc", gcc), (roots[3], "wild", wildpath)):
        need(list(row[1]) == identities[name] and row[3] == path, "wrong physical scope " + name)
    need(roots[1][3] == generator and roots[1][4] == [generator], "wrong generator execution")
    need(roots[0][4][roots[0][4].index("--crate-name")+1] == "e2e"
         and ("crates/ty_server/tests/e2e/main.rs" in roots[0][4] or program + ".rlink" in roots[0][4]),
         "wrong full or link-only test")
    for row in [roots[2], roots[3]]:
        need(row[4].count("-o") == 1 and row[4][row[4].index("-o")+1] == program, "wrong native output")
    collectors = [row for row in events if Path(row[3]).name == "collect2" and "-o" in row[4]
                  and row[4][row[4].index("-o")+1] == program]
    need(len(collectors) == 1 and collectors[0][0] in ancestry(wild, cc, parents), "missing actual collect2 ancestry")
    actual, = [row for row in events if list(row[1]) == identities["cargo"] and row[4][1:] == command["argv"][2:]]
    need(actual[0] in ancestry(e2e, root, parents) and actual[0] in ancestry(gen, root, parents), "different Cargo root")
    candidates = [row for row in events if list(row[1]) == identities["rustc"] and "--crate-name" in row[4]
                  and row[4][row[4].index("--crate-name")+1] == "e2e"]
    need(len(candidates) == 1 and candidates[0][0] == e2e, "unexpected second test compiler")
    for row in events:
        if Path(row[3]).name in {"ld", "ld.bfd", "ld.lld", "ld.gold", "rust-lld", "wild", "collect2"} and "-o" in row[4]:
            chain = ancestry(row[0], root, parents)
            if e2e in chain:
                need(cc in chain and (row[0] == wild or row == collectors[0]), "additional unassigned native link")
    link_only = any(k.removeprefix("-Z").split("=", 1)[0] == "link-only" for k in roots[0][4])
    need(link_only == (program + ".rlink" in roots[0][4]), "ambiguous cached compile")
    return packed | {"rustc_path": "link-only" if link_only else "full", "pids": [e2e, gen, cc, wild]}


def calibrate(root, tools):
    n = 10_000_000
    out = root / "receipts/attribution/calibration"
    for mode in ["cal", "sham"]:
        for i, loops in enumerate([0, n, 0, n]):
            run_scope(out / f"{mode}-{i}", tools / "counter", mode, tools / "donors",
                      [tools / "nested", "root", tools / "donors", str(loops)])
    return check_calibration(out)


def check_calibration(out):
    predicted = {"e2e": 26, "generator": 6, "gcc": 24, "wild": 14, "whole": 34, "e2e_less_gcc": 2}
    accepted = {}
    for mode in ["cal", "sham"]:
        samples = [measured(out / f"{mode}-{i}", nested=True) for i in range(4)]
        totals = {}
        for key in samples[0]:
            delta = statistics.median(s[key] for s in samples[1::2]) - statistics.median(s[key] for s in samples[::2])
            expected = predicted[key] * 10_000_000
            need(abs(delta / expected - 1) < 0.02, f"{mode} {key} calibration {delta}/{expected}")
            totals[key] = [expected, delta]
        accepted[mode] = totals
    return accepted


def oracle(raw, names, root):
    lines = [json.loads(l) for l in raw.splitlines()]
    need(lines[-1] == {"reason": "build-finished", "success": True}, "missing Cargo terminal success")
    need(not any(r.get("reason") == "compiler-message" and r["message"]["level"] == "error" for r in lines),
         "compiler diagnostic on a successful command")
    rows = [r for r in lines if r.get("reason") == "compiler-artifact"]
    artifact, = [r for r in rows if r["target"]["kind"] == ["test"] and r["target"]["name"] == "e2e"
                 and r["target"]["src_path"] == str(root / "ruff/crates/ty_server/tests/e2e/main.rs")]
    path = Path(artifact["executable"])
    need(path.is_relative_to(root / "slot") and path.is_file(), "wrong active executable")
    inventory = {json.dumps([a["package_id"], a["target"]["name"], a["target"]["kind"], a["features"], a["profile"]["test"]],
                           separators=(",", ":")) for a in rows}
    need(set(names) == inventory, "changed logical graph")
    return path


SCHEDULE = ("sham", "e2e", "sham", "e2e", "sham")


def score(base, enrollment):
    vals = [measured(base / f"{i+1}-{mode}", enrollment) for i, mode in enumerate(SCHEDULE)]
    ratios = []
    ceilings = []
    for i in (1, 3):
        t = vals[i]
        adjacent = [vals[i-1]["whole"], vals[i+1]["whole"]]
        ratios.extend([abs(t["whole"] / k - 1) for k in adjacent])
        # Include residual link-only setup in the upper bound for removable compiler work.
        ceilings.append({"e2e_less_gcc": t["e2e_less_gcc"], "whole": t["whole"], "flanks": adjacent,
                         "max_removable_fraction": t["e2e_less_gcc"] / min(t["whole"], *adjacent),
                         "measured_unchanged_speed_ceiling": t["whole"] / (t["whole"] - t["e2e_less_gcc"])})
    return {"samples": vals, "flank_absolute_deviations": ratios,
            "measurement_admitted": statistics.median(ratios) < .03 and max(ratios) < .08,
            "ceilings": ceilings}
