"""Two independent boots, complete authentic cached diagnostics, same settled tree for all four cells."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import files
sys.path.insert(0, str(HERE.parent / "ruff-ldv-needed"))
import needed
import micro
import pilot
from support import calibrate, census, guards, need, put, replay, sha, study

MODES = ("original", "guard")


def snapshot(result, phase, gold):
    data = (result / "outer.stderr").read_bytes()
    return {"stderr_bytes": len(data), "stderr_sha": files.digest(data), "activations": data.count(b"OHM_LDV_GUARD"),
            "reasons": data.count(b"OHM_LDV_REASONS"), "stdout_sha": sha(result / "outer.stdout"),
            "stdout_bytes": (result / "outer.stdout").stat().st_size, "phase": phase, "consumer_sha": gold["elf"]}


def count_graph(path):
    return sorted(json.dumps(row, sort_keys=True, separators=(",", ":"))
                  for row in replay.cargo_rows(path.read_bytes()))


def run(source, slot):
    plan = json.loads((HERE / "registration.json").read_bytes())
    prior = plan["prior"]
    need(slot in (1, 2) and os.environ["GITHUB_RUN_ATTEMPT"] == "1" and
        census.git(HERE, "rev-parse", "HEAD") == os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"],
        "incorrect separately registered checkout")
    for prefix, oid in plan["original_trees"].items():
        need(census.git(HERE, "rev-parse", "HEAD:scripts/" + prefix) == oid, ("changed common QA code", prefix))
    state = pilot.source_plan(source, "option")
    cmd = state["command"]
    need([state["old"], state["new"]] == plan["revisions"] and cmd == plan["command"], "wrong ordinary Ruff history")
    run_dir, evidence, sdk = census.paths()
    root = run_dir / "no-codegen"
    root.mkdir()
    out = evidence / "no-codegen"
    out.mkdir()
    guards.admit(guards.resources(root, out), entry=True, bootstrap=True)
    topology = {}
    for cpu in sorted(os.sched_getaffinity(0)):
        p = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        topology.setdefault(tuple(int((p / n).read_text()) for n in ("physical_package_id", "core_id")), cpu)
    cpus = list(topology.values())[:4]
    need(len(cpus) == 4, "four actual cores required")
    os.sched_setaffinity(0, cpus)
    tools = root / "tools"
    tools.mkdir()
    contact = needed.Contact(sdk, tools, out)
    small = HERE.parent / "ruff-workspace-link-census/wild-diagnostic"
    for name, filename, args in (("count", "count.c", []), ("toy", "calibrate.c", ["-pthread"])):
        subprocess.run(["/usr/bin/cc", "-O2", "-Wall", small / filename, *args, "-o", tools / name], check=True)
    calibrate(tools, out / "calibration")
    env = census.environment(run_dir, sdk)
    Path(env["HOME"]).mkdir(exist_ok=True)
    micro.proxy_calibration(contact, env, root, out / "calibration/cargo-dispatch")
    donor = root / "registry-donor"
    donor.mkdir()
    subprocess.run(["cargo", "+ohm", "fetch", "--locked"], env={**env, "CARGO_HOME": str(donor)},
                   cwd=source, check=True)
    packs = {p["name"] + "-" + p["version"] + ".crate": p["checksum"]
             for p in tomllib.loads((source / "Cargo.lock").read_text())["package"] if "checksum" in p}
    need(pilot.registry(donor) == packs and packs["autocfg-1.5.0.crate"] == plan["autocfg"], "different locked input")
    put(out / "registry.json", packs)
    work, repo, extras, store = (root / "work", root / "ruff", root / "consumer", out / "native-bodies")
    for p in (work, extras, store):
        p.mkdir()
    pilot.new_tree(source, repo, study.OLD)
    shutil.copyfile(HERE.parent / "ruff-workspace-option-edit/client.rs", extras / "option-client.rs")
    (extras / "bad-option-client.rs").write_bytes(study.BAD_CLIENT)
    base = {**env, "CARGO_HOME": str(work / "cargo-home"), "CARGO_TARGET_DIR": str(work / "target"),
            "CARGO_BUILD_BUILD_DIR": str(work / "build")}
    gold = study.source_pair(source)
    graph = None
    references = {}
    archive = {}
    cells = []
    order = plan["cells"][str(slot)]
    training = plan["training"][str(slot)]
    put(out / "entry.json", {"qa": os.environ["GITHUB_SHA"], "prior": prior, "run": os.environ["GITHUB_RUN_ID"],
        "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(), "cpus": cpus, "slot": slot,
        "training": training, "cells": order, "registration": sha(HERE / "registration.json")})
    for ix, mode in enumerate(training):
        contact.select(mode)
        home = work / "cargo-home"
        case = out / ("training-" + mode)
        case.mkdir()
        study.write_source(repo, study.OLD, False)
        with replay.empty_roots(work, case):
            (home / "registry").mkdir()
            for sub in ("cache", "index"):
                subprocess.run(["cp", "-a", "--reflink=auto", donor / "registry" / sub, home / "registry" / sub], check=True)
            subprocess.run(["cargo", "+ohm", "fetch", "--locked", "--offline"], env=base, cwd=repo, check=True)
            need(pilot.registry(home) == packs, "private package bytes changed")
            current = pilot.unit_graph(cmd, base, repo, case, "option")
            need(graph is None or graph == current, "different ordinary development graph")
            graph = current
            for phase, version in (("old", study.OLD), ("new", study.NEW)):
                loc = case / phase
                study.write_source(repo, version, False)
                if phase == "old":
                    loc.mkdir()
                    (loc / "native").mkdir()
                    code = guards.run(cmd, repo, contact.env(base, mode, loc / "native"), loc, work, out, timeout=3000)
                    need(code == 0, "cold training failed")
                else:
                    _, _, physical, _, _ = needed.visit(contact, loc, work, repo, mode, base, cmd)
                    need(physical == {"rustc": [["full", "ruff_workspace", 1]], "linkers": []}, ("edit changed", physical))
                rows = replay.cargo_rows((loc / "outer.stdout").read_bytes())
                observed = pilot.phase_checks("option", rows, graph, work, repo, base, phase, loc, extras, store, gold)
                need(observed["elf"] == references.setdefault(phase, observed["elf"]), "different native consumer")
                put(loc / "checked.json", observed)
            census_dir = case / "replay"
            census_dir.mkdir()
            (census_dir / "native").mkdir()
            trace = census_dir / "files.trace"
            ordinary = ["/usr/bin/strace", "-f", "-qq", "-y", "-s", "8192", "-e", "trace=execve,execveat,openat,openat2",
                        "-o", str(trace), "--", *cmd]
            code = guards.run(ordinary, repo, contact.env(base, mode, census_dir / "native"),
                              census_dir, work, out, timeout=600)
            need(code == 0 and not list((census_dir / "native").iterdir()), "unsettled cache capture")
            check = pilot.phase_checks("option", replay.cargo_rows((census_dir / "outer.stdout").read_bytes()),
                    graph, work, repo, base, "unchanged", census_dir, extras, store, gold)
            need(check["dirty"] == [] and check["elf"] == references["new"], "cache-training oracle")
            archive[mode] = files.capture(trace, work, out / ("bodies-" + mode), (census_dir / "outer.stderr").read_bytes(), mode)
            put(out / ("diagnostics-" + mode + ".json"), archive[mode])
            if ix == 0:
                continue
            stable = archive[mode]
            need({k: v["nonprobe"] for k,v in stable.items()} == {k: v["nonprobe"] for k,v in archive[training[0]].items()},
                 "different file set or different bytes outside diagnostic text")
            # The private target from this single final genuine edit remains live
            # with identical non-message inputs across all four counted cells.
            baseline_stdout = count_graph(census_dir / "outer.stdout")
            active = mode
            try:
                for number, (cached, propagated) in enumerate(order):
                    loc = out / f"cell-{number}-{cached}-{propagated}"
                    files.switch(work, archive[cached], out / ("bodies-" + cached), stable, archive[active])
                    active = cached
                    contact.select(propagated)
                    _, rusts, actual, _, _ = needed.visit(contact, loc, work, repo, propagated, base, cmd, score=True)
                    need(not rusts and actual == {"rustc": [], "linkers": []}, ("genuine non-zero native work", actual))
                    rows = replay.cargo_rows((loc / "outer.stdout").read_bytes())
                    verdict = pilot.phase_checks("option", rows, graph, work, repo, base, "unchanged", loc, extras, store, gold)
                    need(not verdict["dirty"] and verdict["elf"] == references["new"] and
                         count_graph(loc / "outer.stdout") == baseline_stdout, "changed complete ordinary outcome")
                    row = snapshot(loc, cached, verdict)
                    expected = (out / ("training-" + cached) / "replay/outer.stderr").read_bytes()
                    need((row["activations"], row["reasons"]) == (expected.count(b"OHM_LDV_GUARD"), expected.count(b"OHM_LDV_REASONS")),
                         "actual replay did not follow the substituted genuine cached files")
                    cells.append({**row, "cached": cached, "mode": propagated, "path": loc.name, "pmu": sha(loc / "pmu.json")})
            finally:
                files.switch(work, stable, out / ("bodies-" + mode), stable, archive[active])
    contact.finish()
    put(out / "complete.json", {"cells": cells, "references": references, "slot": slot,
                                "registration": sha(HERE / "registration.json")})


if __name__ == "__main__":
    if sys.argv[1:] == ["install"]:
        need(census.git(HERE, "rev-parse", "HEAD") == os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"],
             "different installer source")
        census.install()
    else:
        run(Path(sys.argv[1]).resolve(strict=True), int(sys.argv[2]))
