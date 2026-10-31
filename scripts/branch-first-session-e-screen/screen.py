"""Compare both compiler policies with native sources and two independent ordinary histories."""

from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "branch-return-pmu")]
import subjects
import history
import same_branch
import peak
import tables
import worker
from extra_provider import exercise
from bindings import need, save, sha, ROOT, WORK, OUT

b, kit, native, full = worker.b, worker.kit, worker.native, worker.historical
SAME = (
    ("same-cold-A", "A"),
    ("same-edit", "A-edit"),
    ("same-repeat", "A-edit"),
    ("same-first-B", "B"),
)


def full_reference(arm, refs, env, base):
    for character in ("A", "B"):
        b.fresh_outputs()
        worker.receipt(arm, "cold-" + character, character, "clean", env, base / character, refs)
    # Advance the SAME historical branch, first from a fresh checkout at the genuine A.
    b.fresh_outputs()
    special_visit(arm, "same-empty-edit", "A-edit", "clean", env, base / "A-edit", refs)
    # Returning to B permits restoring only the inactive A ref to its original commit.
    history.command(kit.TREE, ["switch", "-q", kit.NAMES["B"]])
    history.reset_inactive(kit.TREE, kit.NAMES)


def special_visit(arm, phase, state, lane, env, d, refs):
    d.mkdir()
    need(
        shutil.disk_usage(WORK).free > 3 * 2**30 and shutil.disk_usage(OUT).free > 5 * 2**30,
        "private evidence/working capacity",
    )
    source = history.select(kit.TREE, kit.NAMES, state, phase, d)
    save(d / "source.json", source)
    observer = (
        peak.command(ROOT, WORK, d)
        if lane == "ordinary" and phase in {"same-cold-A", "same-edit", "same-first-B"}
        else nullcontext()
    )
    with observer:
        msgs, instructions, _ = worker.invocation(d, env, lane, 0, arm)
    need(not worker.failed_session.observed(WORK), "unfinished private session after valid Cargo")
    storage = worker.disk.allocated(WORK / "target", WORK / "build", d)
    need(
        min(storage["roots"].values()) > 0 and storage["all_inodes"] > 1000,
        "missing real target and build",
    )
    rows, dirty = full.roster(msgs)
    worker.publish(d / "roster.json.gz", {"members": rows, "dirty": dirty})
    names = {q["name"] for q in dirty}
    if phase in {"same-empty-edit", "same-cold-A"}:
        need(len(dirty) == 375 and not storage["packed_files"], "not a cold empty lib/CLI build")
    if phase == "same-edit":
        need({"ruff", "ruff_python_parser"} <= names, "historical source edit missed parser/CLI")
    if phase == "same-repeat":
        worker.settled_link.sole_bin(dirty)
    if phase == "same-first-B":
        need(
            {"ruff", "ruff_python_ast", "ruff_python_parser"} <= names,
            "different historical B switch topology",
        )
    branch = "B" if state == "B" else "A"
    products, paths = native.observed(msgs, branch, source["commit"], env, ROOT, kit.TREE, WORK, d)
    witness = same_branch.oracle(paths["cli"], kit.TREE, state == "A-edit")
    save(d / "28233.json", witness)
    jemalloc = full.stable_sdk.output_directory(msgs, "tikv-jemalloc-sys")
    graph = full.commit(rows)
    if lane == "clean":
        for name, path in paths.items():
            native.preserve(path, products[name], worker.BODIES, worker.BUNDLE)
        refs[arm, state] = {
            "products": products,
            "graph": graph,
            "typed": rows,
            "jemalloc": jemalloc,
            "witness": witness,
        }
    else:
        ref = refs[arm, state]
        need(
            rows == ref["typed"]
            and jemalloc == ref["jemalloc"]
            and worker.same_products(products, ref["products"])
            and (state != "A-edit" or witness == ref["witness"]),
            "same-branch visit diverged from independent empty",
        )
        for name, path in paths.items():
            native.same_file(path, products[name], ref["products"][name], worker.BODIES, d)
    row = {
        "arm": arm,
        "phase": phase,
        "branch": state,
        "source": source["commit"],
        "status": 0,
        "instructions": instructions,
        "allocated": storage["allocated"],
        "artifact_count": len(rows),
        "dirty": len(dirty),
        "dirty_digest": full.commit(dirty),
        "graph": graph,
        "cli": products["cli"]["whole"],
        "reader": products["reader"]["whole"],
        "native_output": jemalloc,
    }
    save(d / "visit.json", row)
    return row


def install(arm, lane, rows, refs, base, variant):
    base.mkdir()
    env = subjects.activate(arm, rows, base)
    b.fresh_outputs()
    if lane == "clean":
        full_reference(arm, refs, env, base)
        return
    records = {}
    previous = None
    phases = worker.PHASES if variant == "main" else SAME
    for phase, branch in phases:
        d = base / phase
        if variant == "main":
            watcher = (
                peak.command if lane == "ordinary" and phase in {"cold-A", "first-B"} else None
            )
            record = worker.receipt(arm, phase, branch, lane, env, d, refs, sample=watcher)
        else:
            record = special_visit(arm, phase, branch, lane, env, d, refs)
        records[phase] = record
        if lane == "ordinary" and phase in {
            "cold-A",
            "first-B",
            "same-cold-A",
            "same-edit",
            "same-repeat",
            "same-first-B",
        }:
            observed = tables.scan(WORK, d, cold=phase in {"cold-A", "same-cold-A"}, arm=arm)
            if previous is not None:
                save(d / "table-transitions.json", tables.relate(previous, observed, phase))
            previous = observed
        print(arm, lane, variant, phase, "validated", flush=True)
    if variant == "same":
        history.reset_inactive(kit.TREE, kit.NAMES)
    else:
        need(
            records["return-A"]["cli"] != records["return-B"]["cli"],
            "different genuine source returned one program",
        )
    save(base / "visits.json", records)
    return records


def compare_clean(refs, order):
    for state in ("A", "B", "A-edit"):
        base = refs[order[0], state]
        for arm in order[1:]:
            r = refs[arm, state]
            need(
                r["graph"] == base["graph"]
                and r["typed"] == base["typed"]
                and worker.same_products(r["products"], base["products"]),
                "cross-arm clean verdict",
            )
            if state == "A-edit":
                need(r["witness"] == base["witness"], "different parser verdict on A'")
            for binary in ("cli", "reader"):
                for field in ("executable", "loads"):
                    need(
                        r["products"][binary][field] == base["products"][binary][field],
                        ("different loadable output", state, arm, binary, field),
                    )


def compare_ordinary(records, order):
    for study, phases in (("main", worker.PHASES), ("same", SAME)):
        for phase, _ in phases:
            originals = []
            for arm in order:
                a, m = (records[lane, arm, study][phase] for lane in ("ordinary", "measured"))
                guard = lambda row: {
                    k: v for k, v in row.items() if k not in {"allocated", "instructions"}
                }
                need(
                    guard(a) == guard(m) and a["instructions"] is None and m["instructions"] > 0,
                    ("ordinary/metered disagreement", arm, study, phase),
                )
                originals.append(a)
            for key in ("source", "status", "graph", "dirty_digest"):
                need(
                    all(r.get(key) == originals[0].get(key) for r in originals),
                    ("different arm results", study, phase, key),
                )


def main(pos, source, calibration, observer, provider):
    order = subjects.ORDERS[pos]
    head = os.environ["GITHUB_SHA"]
    need(
        os.environ["GITHUB_REPOSITORY"] == b.REPO
        and os.environ["GITHUB_REF"] == "refs/heads/" + subjects.REF
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and head == os.environ["REVIEWED_HEAD"] == b.git(HERE, "rev-parse", "HEAD"),
        "unregistered workflow or QA checkout",
    )
    e = subjects.enrollment()
    need(
        ROOT.resolve() == ROOT
        and (WORK / ".owned-by-packed-study").read_text() == str(ROOT)
        and shutil.disk_usage(OUT).free >= 32 * 2**30,
        "insufficient capacity/ownership",
    )
    for name in ("clean", "ordinary", "measured", "providers", "initial"):
        (OUT / name).mkdir()
    for name in (
        "PLAN.md",
        "inputs/e-source.json",
        "inputs/source-replay.json",
        "inputs/cold-units.json",
        "inputs/ruff-28233.json",
        "inputs/ruff-28233.patch",
        "inputs/excluded-boots.json",
    ):
        shutil.copy2(HERE / name, OUT / Path(name).name)
    oracle = json.loads(
        (subjects.HERE.parent / "branch-return-pmu/historical-sources.json").read_bytes()
    )
    need(
        all(sha(HERE.parents[1] / p) == h for p, h in oracle["files"].items()),
        "different historical semantic oracle",
    )
    worker.link_diagnostic.acquire()
    subprocess.run(
        [
            sys.executable,
            "-IB",
            subjects.HERE.parent / "branch-return-pmu/meter.py",
            calibration,
            observer,
        ],
        check=True,
    )
    ready = json.loads((OUT / "meter-ready.json").read_bytes())
    os.sched_setaffinity(0, ready["affinity"])
    need(
        sorted(os.sched_getaffinity(0)) == ready["affinity"]
        and ready["boot"] not in json.loads((HERE / "inputs/excluded-boots.json").read_bytes()),
        "overlapping boot or collector CPU scope",
    )
    save(
        OUT / "enrollment.json",
        {
            "position": pos,
            "order": order,
            "head": head,
            "run": int(os.environ["GITHUB_RUN_ID"]),
            "attempt": 1,
            "boot": ready["boot"],
            "runner": os.environ["RUNNER_NAME"],
            "K": b.spec(),
            "E": e,
            "command": worker.CARGO,
            "plan": sha(HERE / "PLAN.md"),
        },
    )
    rows = subjects.acquire(source)
    env = subjects.activate(order[0], rows, OUT / "initial")
    b.fresh_outputs()
    b.prepare_inputs(kit, env)
    full.calibration()
    peak.calibrate(ROOT, WORK, OUT / "peak-capability.json")
    patch = (HERE / "inputs/ruff-28233.patch").read_bytes()
    clone_rows = history.construct(kit.TREE, patch)
    save(
        OUT / "same-branch-source.json",
        {
            "parent": history.A,
            "commit": clone_rows[0],
            "tree": clone_rows[1],
            "public_commit": same_branch.EDIT,
            "public_parent": same_branch.PARENT,
            "patch": same_branch.CHANGE_SHA,
        },
    )
    refs = {}
    for arm in order:
        install(arm, "clean", rows, refs, OUT / "clean" / arm, "main")
    compare_clean(refs, order)
    exercise(rows, provider, order, activate=subjects.activate)
    records = {}
    for lane in ("ordinary", "measured"):
        for arm in order:
            (OUT / lane / arm).mkdir()
            for study in ("main", "same"):
                records[lane, arm, study] = install(
                    arm, lane, rows, refs, OUT / lane / arm / study, study
                )
    compare_ordinary(records, order)
    seed = {p.name: sha(p) for p in (b.HOME / ".cargo/registry/cache").glob("*/*.crate")}
    need(
        len(seed) == 505
        and seed == json.loads((OUT / "ruff-inputs.json").read_bytes())["archives"],
        "changed Ruff registry",
    )
    for role, expected in rows.items():
        p = b.PARK / role
        need(
            b.inventory(p if p.exists() else b.SDK) == expected,
            ("changed terminal physical SDK", role),
        )
    save(
        OUT / "sdk/terminal.json",
        {"both_complete_byte_and_inode_inventories_unchanged": True, "registry": full.commit(seed)},
    )
    save(
        OUT / "complete.json",
        {
            "order": order,
            "main": [p for p, _ in worker.PHASES],
            "same": [p for p, _ in SAME],
            "host_complete": True,
            "scheduled_counts_unscaled": True,
            "needs_official_pair_replay": True,
        },
    )


if __name__ == "__main__":
    try:
        main(sys.argv[1], *map(Path, sys.argv[2:]))
    except BaseException:
        if OUT.is_dir():
            (OUT / "failure.txt").write_text(traceback.format_exc())
        raise
