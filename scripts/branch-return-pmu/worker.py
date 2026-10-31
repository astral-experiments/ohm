"""Two independent four-arm branch histories. Only the literal ordinary Cargo command is metered."""

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bindings as b
from bindings import need, save, sha, OUT, ROOT, WORK

sys.path[:0] = [str(b.HIST / "full-cli"), str(b.HIST), str(b.HIST / "harness")]
import full_cli as historical
import disk
import failed_session
import native
import study as kit
from omission import publish
from meter import clock
import processes
import kernel_contact
import kernel_events
import link_diagnostic
import settled_link

PHASES = (
    ("cold-A", "A"),
    ("first-B", "B"),
    ("return-A", "A"),
    ("return-B", "B"),
    ("unchanged-B", "B"),
    ("invalid", "B"),
    ("repair", "B"),
)
CARGO = historical.CARGO
BODIES = ROOT / "clean-reference-bodies"
BUNDLE = OUT / "native-bodies"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_source(phase, branch, where):
    historical.visited_source(phase, branch, where)
    exact = kit.git("rev-parse", "HEAD")
    tree = kit.git("rev-parse", "HEAD^{tree}")
    status = kit.git("status", "--porcelain")
    parser = "crates/ruff_python_parser/src/lib.rs"
    need(
        exact == kit.REVS[branch]
        and tree == kit.TREES[branch]
        and (status == "M " + parser if phase == "invalid" else not status),
        ("source history", phase, status),
    )
    save(
        where / "source.json",
        dict(
            commit=exact,
            tree=tree,
            branch=kit.git("symbolic-ref", "HEAD"),
            status=status,
            parser_sha256=sha(kit.TREE / parser),
            registry_lock=sha(kit.TREE / "Cargo.lock"),
        ),
    )


def invocation(where, env, lane, rc, arm):
    if lane == "measured":
        prefix = [str(OUT / "observers/plain"), str(where / "clock.json")]
    elif lane == "structural":
        prefix = kernel_events.wrap(where, arm, env)
    else:
        prefix = []
    command = prefix + CARGO
    try:
        result = subprocess.run(
            command, cwd=kit.TREE, env=env, input=b"", capture_output=True, timeout=2400
        )
    except subprocess.TimeoutExpired as error:
        if lane == "structural":
            kernel_events.timeout(where, error)
        raise
    for key, raw in [("stdout", result.stdout), ("stderr", result.stderr)]:
        with (where / ("cargo." + key + ".gz")).open("xb") as f:
            f.write(gzip.compress(raw, compresslevel=2, mtime=0))
    publish(
        where / "cargo.json.gz",
        dict(
            argv=CARGO,
            observer_argv=command if prefix else None,
            cwd=str(kit.TREE),
            env=env,
            expected=rc,
            exit=result.returncode,
            stdin_sha256=digest(b""),
            stdout_sha256=digest(result.stdout),
            stderr_sha256=digest(result.stderr),
        ),
    )
    if lane == "structural" and result.returncode != rc:
        kernel_events.preserve(where)
    need(
        result.returncode == rc,
        ("ordinary Cargo exit", where, rc, result.returncode, result.stderr[-800:]),
    )
    n = clock(where / "clock.json", rc)["instructions"] if lane == "measured" else None
    phys = None
    if lane == "structural":
        try:
            phys = kernel_events.inventory(where, arm, rc, env)
            need(phys["cargos"][0]["argv"][1:] == CARGO[2:], "actual Cargo command")
            publish(where / "native-execs.json.gz", phys)
        finally:
            kernel_events.preserve(where)
    messages = [json.loads(k) for k in result.stdout.splitlines()]
    need(
        messages[-1] == {"reason": "build-finished", "success": rc == 0},
        "actual Cargo JSON completion",
    )
    errors = [
        m
        for m in messages
        if m["reason"] == "compiler-message" and m["message"]["level"] == "error"
    ]
    if rc:
        tagged = [m for m in errors if m["message"].get("code")]
        need(
            tagged
            and all(
                m["target"]["name"] == "ruff_python_parser"
                and m["message"]["code"]["code"] == "E0308"
                and any(
                    "ohm_branch_switch_invalid" in t["text"]
                    for s in m["message"]["spans"]
                    for t in s["text"]
                )
                for m in tagged
            ),
            "wrong compiler diagnostic or package",
        )
        publish(where / "diagnostics.json.gz", errors)
    else:
        need(not errors, "successful command replayed an error diagnostic")
    return messages, n, phys


def same_products(got, want):
    return {k: v for k, v in got.items() if k not in ("cli", "reader")} == {
        k: v for k, v in want.items() if k not in ("cli", "reader")
    }


def receipt(arm, phase, branch, lane, env, where, refs):
    where.mkdir()
    need(
        shutil.disk_usage(WORK).free > 3 * 2**30 and shutil.disk_usage(OUT).free > 5 * 2**30,
        "owned native work/receipt free-space guard",
    )
    if phase == "repair":
        failed_session.before_repair(
            WORK,
            json.loads((where.parent / "invalid/working.json").read_bytes()),
            where / "failed-session-grace.json",
        )
    checked_source(phase, branch, where)
    rc = 101 if phase == "invalid" else 0
    messages, insn, physical = invocation(where, env, lane, rc, arm)
    working = failed_session.observed(WORK)
    if phase == "invalid":
        save(where / "working.json", working)
    storage = disk.allocated(WORK / "target", WORK / "build", where, failed_sessions=working)
    need(
        min(storage["roots"].values()) > 0 and storage["all_inodes"] > 1000, "incomplete allocation"
    )
    result = dict(
        arm=arm,
        phase=phase,
        branch=branch,
        source=kit.REVS[branch],
        instructions=insn,
        allocated=storage["allocated"],
        status=rc,
    )
    if rc:
        need(lane != "clean", "invalid in clean reference")
        save(where / "visit.json", result)
        return result
    need(not working, ("unfinished session after valid command", phase, sorted(working)))
    if physical:
        processes.sessions(where, physical, WORK)
    if lane == "structural" and arm.endswith("on") and phase in ("first-B", "return-B"):
        from storage_witness import collect

        collect(WORK, where)
    rows, dirty = historical.roster(messages)
    publish(where / "roster.json.gz", dict(members=rows, dirty=dirty))
    is_cold = lane == "clean" or phase == "cold-A"
    need(not is_cold or (len(dirty) == 375 and storage["packed_files"] == 0), "true empty root")
    if phase in ("first-B", "return-A", "return-B"):
        names = {r["name"] for r in dirty}
        need(
            {"ruff", "ruff_python_ast", "ruff_python_parser"} <= names
            and len(dirty) == 20
            and historical.commit(dirty) == settled_link.SWITCH_DIRTY,
            ("historical source did not affect its real graph", names),
        )
        need(
            (storage["packed_files"] > 0) == (arm == "Kon"), "incorrect older branch object format"
        )
        if physical:
            need(
                any(r["crate"] == "ruff" for r in physical["rustcs"]) and physical["wild"] >= 1,
                "missing real Ruff compilation or link",
            )
    if phase == "unchanged-B":
        settled_link.sole_bin(dirty)
        need((storage["packed_files"] > 0) == (arm == "Kon"), "incorrect settled object retention")
    products, files = native.observed(
        messages, branch, kit.REVS[branch], env, ROOT, kit.TREE, WORK, where
    )
    native_output = historical.stable_sdk.output_directory(messages, "tikv-jemalloc-sys")
    graph = historical.commit(rows)
    if lane == "clean":
        for name, path in files.items():
            native.preserve(path, products[name], BODIES, BUNDLE)
        refs[(arm, branch)] = {
            "products": products,
            "graph": graph,
            "typed": rows,
            "jemalloc": native_output,
        }
    else:
        original = refs[arm, branch]
        need(
            rows == original["typed"]
            and native_output == original["jemalloc"]
            and same_products(products, original["products"]),
            "wrong clean graph, namespace or native verdict",
        )
        for name, path in files.items():
            native.same_file(path, products[name], original["products"][name], BODIES, where)
    if lane == "structural" and phase in ("cold-A", "return-B", "unchanged-B"):
        settled_link.collect(where, phase, physical, messages, files["cli"])
        if phase == "unchanged-B":
            settled_link.watched_after(where, kit.TREE)
    result.update(
        artifact_count=len(rows),
        dirty=len(dirty),
        dirty_digest=historical.commit(dirty),
        graph=graph,
        cli=products["cli"]["whole"],
        reader=products["reader"]["whole"],
        native_output=native_output,
    )
    save(where / "visit.json", result)
    return result


def install(arm, lane, registry, refs, where):
    where.mkdir()
    env = b.activate(arm, registry, where)
    if lane == "structural":
        kernel_events.catalog(arm, registry, where)
    b.fresh_outputs()
    results = {}
    if lane == "clean":
        for branch in ("A", "B"):
            b.fresh_outputs()
            results[branch] = receipt(
                arm, "cold-" + branch, branch, lane, env, where / branch, refs
            )
    else:
        for phase, branch in PHASES:
            results[phase] = receipt(arm, phase, branch, lane, env, where / phase, refs)
            print(lane, arm, phase, "qualified output", flush=True)
        need(
            results["return-A"]["cli"] != results["return-B"]["cli"],
            "different Git source yielded same Ruff executable",
        )
    save(where / "visits.json", results)
    return results


def across_clean(refs):
    for branch in ("A", "B"):
        base = refs["Foff", branch]
        a = base["products"]
        for arm in b.ORDERS["01"]:
            q = refs[arm, branch]
            y = q["products"]
            need(
                base["typed"] == q["typed"] and same_products(a, y),
                "different typed graph or CLI/reader behavior",
            )
            for file in ("cli", "reader"):
                need(
                    a[file]["executable"] == y[file]["executable"]
                    and a[file]["loads"] == y[file]["loads"],
                    ("executable sections/load bytes differ", arm, branch, file),
                )


def finish(registry, orders, records):
    unexpected = []
    for arm in orders:
        for phase, _ in PHASES:
            a = records["structural", arm][phase]
            c = records["measured", arm][phase]
            for k in (
                "status",
                "source",
                "graph",
                "dirty",
                "dirty_digest",
                "cli",
                "reader",
                "native_output",
            ):
                need(a.get(k) == c.get(k), ("structural and ordinary lane disagree", arm, phase, k))
            if phase == "unchanged-B":
                where = OUT / "structural" / arm / phase
                proof = settled_link.read(where / "settled-origin.json")
                native = historical.load(where / "native-execs.json.gz")
                settled_link.sole_bin(historical.load(where / "roster.json.gz")["dirty"])
                need(
                    proof["link"] == settled_link.link(native, proof["cold"]),
                    ("missing authenticated settled native link", arm),
                )
    for phase, _ in PHASES:
        rows = {records["measured", arm][phase].get("dirty_digest") for arm in orders}
        if len(rows) != 1:
            unexpected.append(dict(phase=phase, reason="matched arms have different dirty units"))
        if phase in ("return-A", "return-B", "unchanged-B"):
            rosters = {}
            for arm in orders:
                reported = historical.load(
                    OUT / "structural" / arm / phase / "native-execs.json.gz"
                )
                rosters[arm] = [
                    sorted((r["crate"], r["mode"]) for r in reported["rustcs"]),
                    reported["wild"],
                ]
            if any(v != rosters[orders[0]] for v in rosters.values()):
                unexpected.append(
                    dict(
                        phase=phase,
                        reason="matched arms have different physical Rust/link rosters",
                        rosters=rosters,
                    )
                )
    save(
        OUT / "admission.json",
        dict(unexpected=unexpected, positions=orders, source=b.spec(), files=len(registry["F"])),
    )
    need(not unexpected, ("unexplained strict-Cargo graph; counts unqualified", unexpected))
    save(
        OUT / "complete.json",
        {
            "host_complete": True,
            "arms": orders,
            "phases": [p for p, _ in PHASES],
            "raw_counts_unscaled": True,
            "requires_independent_cross_host_replay": True,
        },
    )


def main(pos, source, calibrator, observer, provider_repo, kernel_repo):
    need(pos in b.ORDERS and sha(HERE / "PLAN.md") == b.PLAN, "wrong enrollment")
    oracle = json.loads((HERE / "historical-sources.json").read_bytes())
    need(
        oracle["git"] == "99dd1ed50dc39354707148ed77ec2ec5d8235978"
        and all(sha(HERE.parents[1] / name) == digest for name, digest in oracle["files"].items()),
        "foreign historical CLI/runtime reader source",
    )
    orders = b.ORDERS[pos]
    need(
        os.environ["GITHUB_REF"] == "refs/heads/" + b.BRANCH
        and os.environ["GITHUB_REPOSITORY"] == b.REPO
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1",
        "wrong official run identity",
    )
    need(
        b.git(HERE, "rev-parse", "HEAD") == os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"],
        "different QA commit",
    )
    need(
        ROOT.resolve() == ROOT
        and (WORK / ".owned-by-packed-study").read_text() == str(ROOT)
        and shutil.disk_usage(OUT).free >= 32 * 2**30,
        "fresh runner capacity",
    )
    for name in ("clean", "structural", "measured", "providers"):
        (OUT / name).mkdir()
    shutil.copy2(HERE / "PLAN.md", OUT / "PLAN.md")
    shutil.copy2(b.RUNTIME, OUT / "source-kit.json")
    link_diagnostic.acquire()
    subprocess.run([sys.executable, "-IB", HERE / "meter.py", calibrator, observer], check=True)
    ready = json.loads((OUT / "meter-ready.json").read_bytes())
    native_qualification = kernel_contact.prepare(kernel_repo, ready["boot"])
    os.sched_setaffinity(0, ready["affinity"])
    need(sorted(os.sched_getaffinity(0)) == ready["affinity"], "ordinary worker affinity")
    save(
        OUT / "enrollment.json",
        dict(
            position=pos,
            order=orders,
            run=int(os.environ["GITHUB_RUN_ID"]),
            head=os.environ["GITHUB_SHA"],
            attempt=1,
            boot=ready["boot"],
            kernel_contact=native_qualification,
            runner=os.environ.get("RUNNER_NAME"),
            job=os.environ["GITHUB_JOB"],
            source=b.spec(),
            plan=b.PLAN,
            command=CARGO,
        ),
    )
    registry = b.acquire(source)
    start = OUT / "initial"
    start.mkdir()
    env = b.activate(orders[0], registry, start)
    b.fresh_outputs()
    b.prepare_inputs(kit, env)
    historical.calibration()
    refs = {}
    records = {}
    for arm in orders:
        install(arm, "clean", registry, refs, OUT / "clean" / arm)
    across_clean(refs)
    # The separately fetched historical Unicode package is absent from A and B. Its own
    # registry is private to this control and cannot alter the primary 505-archive seed.
    from extra_provider import exercise

    exercise(registry, provider_repo, orders)
    for lane in ("structural", "measured"):
        for arm in orders:
            records[lane, arm] = install(arm, lane, registry, refs, OUT / lane / arm)
    final_seed = {p.name: sha(p) for p in (b.HOME / ".cargo/registry/cache").glob("*/*.crate")}
    need(
        final_seed == json.loads((OUT / "ruff-inputs.json").read_bytes())["archives"],
        "primary locked registry changed across histories",
    )
    for role, want in registry.items():
        physical = b.PARK / role if (b.PARK / role).exists() else b.SDK
        need(b.inventory(physical) == want, ("full SDK changed over the campaign", role))
    save(
        OUT / "sdk" / "terminal.json",
        dict(
            both_complete_byte_and_inode_inventories_unchanged=True,
            registry=historical.commit(final_seed),
        ),
    )
    finish(registry, orders, records)


if __name__ == "__main__":
    try:
        main(sys.argv[1], *map(Path, sys.argv[2:]))
    except BaseException:
        if OUT.exists():
            (OUT / "failure.txt").write_text(traceback.format_exc())
        raise
