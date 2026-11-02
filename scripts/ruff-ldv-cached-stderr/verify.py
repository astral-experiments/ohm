"""Reopen the emitted Cargo bytes, actual exec receivers, counts and cached input files."""
from collections import Counter
import ast
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from files import digest, need


def read(p):
    return json.loads(p.read_bytes())


def lines(p):
    return p.read_text().splitlines()


def boot(folder):
    plan = read(HERE / "registration.json")
    entry, terminal = (read(folder / (p + ".json")) for p in ("entry", "complete"))
    slot = entry["slot"]
    need(sha_file(HERE / "registration.json") == entry["registration"] == terminal["registration"] and
         entry["training"] == plan["training"][str(slot)] and entry["cells"] == plan["cells"][str(slot)] and
         terminal["slot"] == slot and terminal["references"]["old"] != terminal["references"]["new"],
         "different enrollment or genuine edit")
    training = {}
    for mode in entry["training"]:
        src = folder / ("training-" + mode)
        diags = read(folder / ("diagnostics-" + mode + ".json"))
        stream = (src / "replay/outer.stderr").read_bytes()
        opens = lines(src / "replay/files.trace")
        detail = {}
        for name, row in diags.items():
            p = folder / ("bodies-" + mode) / row["sha"]
            data = p.read_bytes()
            need(digest(data) == row["sha"] and len(data) == row["bytes"] and row["stat"][6] == 1 and
                 row["opens"] == 1 and name.startswith(("target/","build/")) and ".." not in Path(name).parts and
                 Path(name).name.startswith("output-") and
                 any("O_RDONLY" in l and re.search(r"= [0-9]+<[^>]*" + re.escape("/" + name) + r">$", l) for l in opens),
                 ("unverified actual Cargo message cache file", mode, name))
            detail[name] = data
        need(all(stream.count(m) == sum(d.count(m) for d in detail.values())
                 for m in (b"OHM_LDV_GUARD",b"OHM_LDV_REASONS")) and stream.count(b"OHM_LDV_GUARD") > 0,
             "unaccounted output")
        training[mode] = {"sha":digest(stream), "bytes":len(stream), "activations":stream.count(b"OHM_LDV_GUARD"),
                          "reasons":stream.count(b"OHM_LDV_REASONS"),"files":len(detail)}
    cells = {}
    wanted = plan["command"]
    calibration=read(folder/"calibration/cargo-dispatch/accepted.json")
    need(calibration["plain"]==calibration["counted"],"proxy changed stdout or exec chain")
    actual, = [(p,a[0]) for p,a in calibration["plain"] if p.endswith("toolchains/ohm/bin/cargo")]
    for row, pair in zip(terminal["cells"], entry["cells"], strict=True):
        cache, mode = pair
        need([row["cached"],row["mode"]] == pair, "wrong realized permutation")
        loc = folder / row["path"]
        stdout, raw = (loc/"outer.stdout").read_bytes(), (loc/"outer.stderr").read_bytes()
        t = training[cache]
        need((raw.count(b"OHM_LDV_GUARD"),raw.count(b"OHM_LDV_REASONS")) == (t["activations"],t["reasons"]) and
             (digest(stdout),len(stdout),digest(raw),len(raw)) == (row["stdout_sha"],row["stdout_bytes"],row["stderr_sha"],row["stderr_bytes"]),
             "different measured replay")
        messages = [json.loads(l) for l in stdout.splitlines()]
        artifacts = [v for v in messages if v["reason"]=="compiler-artifact"]
        need(artifacts and all(v["fresh"] for v in artifacts) and messages[-1].get("success") is True,
             "physical Cargo did not report an all-fresh selection")
        native = read(loc/"kernel.json")
        need(native["tree"]["linkers"] == [] and not native["rustc"] and not list((loc/"native").glob("*.loaded")),
             "unexpected native work")
        pm = read(loc/"pmu.json")
        need(pm["instructions"] > 0 and pm["enabled"] == pm["running"] > 0 and pm["status"] == 0 and
             sha_file(loc/"pmu.json") == row["pmu"], "unqualified native instructions")
        executed = []
        for f in (loc/"trace").glob("exec.*"):
            for line in lines(f):
                if not line.startswith(("execve(","execveat(")) or not re.search(r" = 0$",line):
                    continue
                m = re.fullmatch(r'execve\(("(?:\\.|[^"\\])*"), (\[.*?\]), (.*)\)\s+= 0',line)
                need(m, "unknown successful kernel exec")
                exe, argv = (ast.literal_eval(m[i]) for i in (1,2))
                executed.append((int(f.suffix[1:]),exe,argv))
        commands = sorted([Path(exe).name for _,exe,_ in executed])
        need(commands == ["cargo","cargo","count"] and
             sum(pid == pm["pid"] and exe == actual[0] and a[0] == actual[1] and a[1:] == wanted[2:] for pid,exe,a in executed) == 1 and
             any(pid==pm["pid"] and a == wanted for pid,exe,a in executed), ("wrong executable, child or whole Cargo argv",commands))
        cells[(cache,mode)] = pm["instructions"]
    return {"slot":slot,"boot":entry["boot"],"run":entry["run"],"qa":entry["qa"],"order":entry["cells"],
            "training":training,"counts": [[c,m,cells[(c,m)]] for c,m in entry["cells"]],
            "source_native_consumers":terminal["references"], "complete_sha":sha_file(folder/"complete.json")}


def sha_file(path):
    return digest(path.read_bytes())


def analyze(a,b):
    need(a["slot"] == 1 and b["slot"] == 2 and a["boot"] != b["boot"] and a["qa"] == b["qa"] and a["run"] == b["run"],
         "not two independent enrolled boots")
    effects = []
    for v in (a,b):
        counts = {(c,m):n for c,m,n in v["counts"]}
        need(len(counts)==4, "incomplete factorial")
        for fixed in ("original","guard"):
            cost=counts["guard",fixed]-counts["original",fixed]
            mode=counts[fixed,"guard"]-counts[fixed,"original"]
            effects.append({"slot":v["slot"],"fixed_factor_value":fixed,"cache_extra":cost,"mode_extra":mode,
                            "cache_in_registered_range":4_544_000<=cost<=6_816_000,
                            "mode_within_registered_0_2_percent":abs(mode)*500 < counts[fixed,"original"]})
    return {"boots":[a,b],"effects":effects,"registered_sufficiency":all(
            e["cache_in_registered_range"] and e["mode_within_registered_0_2_percent"] for e in effects)}


if __name__ == "__main__":
    result = boot(Path(sys.argv[2])) if sys.argv[1]=="boot" else analyze(read(Path(sys.argv[2])), read(Path(sys.argv[3])))
    output = Path(sys.argv[-1])
    with output.open("x") as f:
        json.dump(result, f, sort_keys=True)
        f.write("\n")
