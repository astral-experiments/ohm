"""Count just the registered full Ruff repair while changing one private packed-table create."""

import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "ctfe-crossover-pilot")]
import evidence as ev
import pilot as p

REG = json.loads((HERE / "owners.json").read_bytes())
ORDERS = {"01": ["P", "B"], "02": ["B", "P"]}
BRANCH = "refs/heads/charlie/qa-ctfe-repair-encode-20261101"
PREVIOUS = {r["boot"] for r in REG["originals"]} | {
    "4f4d4a31-68c1-447b-9909-8f4c951d6d82",
    "c9fb2eab-3d98-4154-b864-cfac6df82005",
}
GRAPH = "f5909e1cbd4832369f783bdbd733e54562bcce15e44592b8ec15793e9996c660"


def enrolled():
    e = os.environ
    ev.need(
        (e["GITHUB_REPOSITORY"], e["GITHUB_REF"], e["GITHUB_RUN_ATTEMPT"], p.b.git(HERE, "rev-parse", "HEAD"))
        == (p.b.REPO, BRANCH, "1", e["GITHUB_SHA"])
        and e["REVIEWED_HEAD"] == e["GITHUB_SHA"],
        "incorrect diagnostic enrollment",
    )
    ev.need(
        p.ROOT.resolve() == p.ROOT and (p.WORK / ".owned-by-packed-study").read_text() == str(p.ROOT),
        "unowned private roots",
    )


def repair(mode, root, sdk, env, where, refs, issues):
    where.mkdir()
    ev.need(
        shutil.disk_usage(p.WORK).free > 2 << 30 and shutil.disk_usage(p.OUT).free > 5 << 30,
        "insufficient capacity for native repair",
    )
    old = json.loads((where.parent / "invalid/failed.json").read_bytes())
    p.original.failed_session.before_repair(p.WORK, old, where / "grace.json")
    p.routes.advance(p.kit.TREE, p.kit.NAMES, "repair", "return")
    source = p.routes.snapshot(p.kit.TREE, p.kit.REVS, p.kit.TREES, p.kit.NAMES, "repair", "return")
    p.save(where / "source.json", source)
    selected = REG["selected"]
    owners = selected + REG["other"]
    before = ev.sessions(p.WORK, owners)
    p.publish(where / "before.json.gz", before)
    paths = [before["owners"][o] for o in selected]
    hooks = ev.hooks(root, sdk)
    control = Path(hooks["OHM_QA_PACK_CONTROL"])
    ev.need(not (env.keys() & hooks.keys()) and not control.exists(), "gate already active")
    control.mkdir()
    (control / "config").write_text(ev.config(mode, paths))
    try:
        messages, n, other = p.original.invocation(where, env | hooks, "measured", 0, "Con")
    finally:
        control.rename(where / "calls")
    c = where / "calls"
    clock = json.loads((where / "clock.json").read_bytes())
    ev.need(clock["running"] == clock["enabled"] and other is None, "repair counter did not have full duty")
    ev.need(not p.original.failed_session.observed(p.WORK), "working session survived successful repair")
    after = ev.sessions(p.WORK, owners)
    p.publish(where / "after.json.gz", after)
    images, events = ev.physical(c, sdk, paths)
    lib = Path(hooks["LD_PRELOAD"])
    ev.mapped_observer(c, images, lib, ev.ident(lib))
    wild = ev.roster(images, events, REG, p.original.CARGO, before["owners"])
    result = ev.certify(before, after, images, events, selected, mode == "B", all_owners=owners)
    p.publish(where / "placements.json.gz", result)
    rows, dirty = p.original.historical.roster(messages)
    p.publish(where / "roster.json.gz", dict(members=rows, dirty=dirty))
    ev.need(
        sorted([r["name"], r["kind"][0]] for r in dirty) == REG["physical_units"]
        and rows == refs["Con", "clean-edited"][0],
        "typed graph or dirty set changed",
    )
    storage = p.original.disk.allocated(p.WORK / "target", p.WORK / "build", where, failed_sessions=())
    products, files = p.original.native.observed(
        messages, "B", p.kit.REVS["B"], env, root, p.kit.TREE, p.WORK, where
    )
    p.product_check(files, products, refs["Con", "clean-edited"][1], where, issues)
    output = Path(wild)
    ev.need(
        output.is_absolute()
        and output.is_relative_to(p.WORK)
        and not output.is_symlink()
        and output.samefile(files["cli"])
        and products["cli"]["whole"] == ev.sha(output),
        "wrong output for actual stock Wild",
    )
    p.save(
        where / "link.json",
        {
            "wild_output": wild,
            "file": ev.ident(output),
            "cargo": str(files["cli"]),
            "returned": ev.ident(files["cli"]),
        },
    )
    p.save(
        where / "visit.json",
        dict(
            phase="repair",
            status=0,
            observer="pmu",
            instructions=n,
            allocated=storage["allocated"],
            graph=p.original.historical.commit(rows),
            dirty=p.original.historical.commit(dirty),
            cli=products["cli"]["whole"],
            reader=products["reader"]["whole"],
        ),
    )
    return result, n, ev.compiler_commands(images)


def run(position, calibrator, observers):
    ev.need(position in ORDERS and shutil.disk_usage(p.OUT).free > 20 << 30, "insufficient worker capacity")
    subprocess.run(
        [sys.executable, "-IB", p.HERE.parent / "branch-return-pmu/meter.py", calibrator, observers], check=True
    )
    meter = json.loads((p.OUT / "meter-ready.json").read_bytes())
    os.sched_setaffinity(0, meter["affinity"])
    ev.need(
        len(meter["affinity"]) == 8
        and sorted(os.sched_getaffinity(0)) == meter["affinity"]
        and meter["boot"] not in PREVIOUS,
        "wrong boot or affinity",
    )
    tools = p.OUT / "tools"
    tools.mkdir()
    src = HERE / "pack_gate.c"
    lib = tools / "pack-gate.so"
    argv = [
        "/usr/bin/cc",
        "-std=gnu11",
        "-O2",
        "-fPIC",
        "-shared",
        "-Wall",
        "-Wextra",
        "-Werror",
        str(src),
        "-ldl",
        "-o",
        str(lib),
    ]
    ev.need("QA_EVIDENCE_B3SUM" not in os.environ, "unexpected observer hash utility")
    os.environ["QA_EVIDENCE_B3SUM"] = "/usr/bin/b3sum"
    subprocess.run(argv, check=True)
    subprocess.run([sys.executable, "-IB", HERE / "test_gate.py", "--library", lib], check=True)
    p.save(
        tools / "tool.json",
        dict(
            source=p.sha(src),
            elf=p.sha(lib),
            file=ev.ident(lib),
            b3sum=p.sha(Path("/usr/bin/b3sum")),
            compiler=p.sha(Path(argv[0]).resolve()),
            argv=argv,
        ),
    )
    p.save(
        p.OUT / "position.json",
        dict(
            position=position,
            order=ORDERS[position],
            boot=meter["boot"],
            run=os.environ["GITHUB_RUN_ID"],
            head=os.environ["GITHUB_SHA"],
            plan=p.sha(HERE / "PLAN.md"),
            registration=p.sha(HERE / "owners.json"),
            command=p.original.CARGO,
        ),
    )
    rows = {r: json.loads((p.OUT / "sdk" / (r + ".json")).read_bytes())["files"] for r in ("E", "C")}
    start = p.OUT / "initial"
    start.mkdir()
    e = p.subjects.activate("Con", rows, start)
    p.b.fresh_outputs()
    p.b.prepare_inputs(p.kit, e)
    subprocess.run([sys.executable, "-IB", p.HERE / "test_routes.py", p.kit.TREE], check=True)
    p.original.historical.calibration()
    refs = {}
    issues = []
    p.history("Con", "clean", "reference", rows, refs, issues, None)
    ev.need(
        refs["Con", "clean-A"][1]["cli"]["whole"] != refs["Con", "clean-B"][1]["cli"]["whole"],
        "real A/B ELF remained unchanged",
    )
    summaries = {}
    counts = {}
    commands = {}
    for mode in ORDERS[position]:
        where = p.OUT / ("return-" + mode)
        where.mkdir()
        env = p.subjects.activate("Con", rows, where)
        ev.need(env == e, "different Cargo context")
        p.b.fresh_outputs()
        p.routes.begin(p.kit.TREE, p.kit.REVS, p.kit.NAMES)
        for phase in p.FULL[:-1]:
            p.visit("Con", "ordinary", "return", phase, env, where / phase, refs, issues, None)
        summaries[mode], counts[mode], commands[mode] = repair(
            mode, p.ROOT, p.b.SDK, env, where / "repair", refs, issues
        )
    ev.need(commands["P"] == commands["B"], "physical Rust compiler argv changed")
    checked = ev.comparison(summaries["P"], summaries["B"], REG)
    p.save(
        p.OUT / "diagnostic.json",
        dict(
            instructions=counts, pass_minus_blocked=counts["P"] - counts["B"], placement=checked, issues=issues
        ),
    )
    ev.need(not issues, "native products differ from own empty reference")


if __name__ == "__main__":
    try:
        enrolled()
        if sys.argv[1] == "acquire":
            p.subjects.acquire(Path(sys.argv[2]))
        else:
            run(sys.argv[1], *map(Path, sys.argv[2:]))
    except BaseException:
        if p.OUT.is_dir():
            (p.OUT / "failure.txt").write_text(traceback.format_exc())
        raise
