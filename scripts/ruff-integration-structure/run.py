"""Single-host structural admission. Cargo, the 96-test harness and its reader run separately."""
import collections
import gzip
import json
import os
from pathlib import Path
import shutil
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "branch-return-pmu")]
import worker as historical
from bindings import OUT, ROOT, WORK, need, save, sha
import selection
import suite

b = historical.b
kit = historical.kit
native = historical.native
CARGO = ["cargo", "+ohm", "test", "-p", "ruff", "--test", "integration_test", "--no-run",
         "--locked", "--offline", "-j4", "--message-format=json"]
ARMS = ("Foff", "Fon")
BASE_TREES = ("8036cb549845a905ab83882f5b01766229e0e636", "d9fd6c8e4152d468a3a40d600ee1c6ebda13e5f2")
BRANCH = "charlie/qa-ruff-integration-structure-20261031"


def trace_boundary(where):
    with gzip.open(where / "exec.raw.gz", "rt") as trace:
        for pid, exe, argv in historical.processes.execs(trace):
            basename = Path(exe).name
            need(basename not in ("ruff", "integration_test") and not basename.startswith("integration_test-") and
                 not (Path(exe).is_relative_to(WORK) and basename.startswith("ruff-")),
                 ("Cargo executed the test or installed Ruff", pid, exe, argv))


def refuse_existing_work():
    b.fresh_outputs()
    need(all(not any((WORK / key).iterdir()) for key in ("target", "build")), "not an empty installation")


def receipt(arm, phase, branch, env, where, refs, last, clean, prefix, invoke=historical.invocation):
    where.mkdir()
    need(shutil.disk_usage(WORK).free > 3 * 2**30 and shutil.disk_usage(OUT).free > 5 * 2**30,
         "below native output and evidence space floor")
    if phase == "repair":
        historical.failed_session.before_repair(WORK, json.loads((where.parent / "invalid/working.json").read_bytes()),
                                               where / "failed-session-grace.json")
    historical.checked_source(phase, branch, where)
    rc = 101 if phase == "invalid" else 0
    streams, count, physical = invoke(where, env, "structural", rc, arm)
    need(count is None, "unexpected clock in structural admission")
    trace_boundary(where)
    rows, dirty = selection.roster(streams, kit.TREE)
    historical.publish(where / "roster.json.gz", dict(units=rows, dirty=dirty))
    modes = collections.Counter(row["mode"] for row in physical["rustcs"])
    record = dict(arm=arm, visit=phase, state=branch, code=rc, typed=len(rows), distinct_dirty=len(dirty),
                  full=modes["full"], link_only=modes["link-only"], wild=physical["wild"],
                  system_links=physical["other_linkers"])
    pending = historical.failed_session.observed(WORK)
    usage = historical.disk.allocated(WORK / "target", WORK / "build", where, failed_sessions=pending)
    record["allocated_bytes"] = usage["allocated"]
    if rc:
        save(where / "working.json", pending)
        need(any(r["crate"] == "ruff_python_parser" and r["mode"] == "full" for r in physical["rustcs"]),
             "invalid edit did not invoke real parser compiler")
        record["error"] = "E0308/ohm_branch_switch_invalid"
    else:
        empty = clean or phase == "cold-A"
        need(rows and (not empty or len(rows) == len(dirty)) and not pending, "nonempty cold or unfinished compiler")
        paths = selection.selected_paths(streams, kit.TREE, WORK)
        mapping = selection.join_native(physical, paths, empty, last, sha, arm.endswith("on"))
        filtered, providers = selection.reader_stream(streams, mapping, sha)
        save(where / "physical-owners.json", dict(owners=mapping, reader=providers))
        last.update(mapping)
        prod, files = native.observed(filtered, branch, kit.REVS[branch], env, ROOT, kit.TREE, WORK, where)
        files["harness"] = paths["harness"]
        images = {role: prod[role] for role in ("cli", "reader")}
        images["harness"] = native.elf(files["harness"])
        save(where / "harness-elf.json", images["harness"])
        # Keep original products even if a later behavioral assertion rejects the installation.
        if clean:
            for role, path in files.items():
                native.preserve(path, images[role], historical.BODIES, historical.BUNDLE)
        else:
            expected = refs[arm, branch]
            need(rows == expected["typed"] and expected["native_dir"] ==
                 historical.historical.stable_sdk.output_directory(streams, "tikv-jemalloc-sys"),
                 "typed graph or jemalloc provider differs from own clean")
            for role, path in files.items():
                native.same_file(path, images[role], expected["images"][role], historical.BODIES, where)
                if role in paths:
                    need(path.samefile(paths[role]), "tested a different Cargo artifact")
        oracle = suite.exercise(paths["harness"], paths["cli"], kit.TREE, env, where, prefix, historical.processes)
        need(not kit.git("status", "--porcelain"), "off-window tests modified checked-out Ruff")
        behavior = {k: v for k, v in prod.items() if k not in ("cli", "reader")}
        behavior["suite"] = oracle
        if clean:
            refs[arm, branch] = dict(typed=rows, images=images, behavior=behavior,
                native_dir=historical.historical.stable_sdk.output_directory(streams, "tikv-jemalloc-sys"))
        else:
            need(behavior == expected["behavior"], "same-branch behavioral result differs from own clean")
        record["products"] = {key: desc["whole"] for key, desc in images.items()}
        record["typed_layout"] = prod["typed"]
        record["suite_passed"] = 96
    save(where / "visit.json", record)
    print(arm, phase, record.get("suite_passed", record.get("error")), flush=True)
    return record


def main(source):
    head = os.environ["GITHUB_SHA"]
    need(os.environ["GITHUB_REPOSITORY"] == b.REPO and os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH and
         os.environ["GITHUB_RUN_ATTEMPT"] == "1" and os.environ["REVIEWED_HEAD"] == head == b.git(HERE, "rev-parse", "HEAD"),
         "unexpected branch, run or attempt")
    need(tuple(b.git(HERE, "rev-parse", "HEAD:scripts/branch-return-pmu", "HEAD:scripts/ohm-packed-ruff").splitlines()) == BASE_TREES,
         "historical native oracle trees changed")
    need(ROOT.resolve() == ROOT and (WORK / ".owned-by-packed-study").read_text() == str(ROOT) and
         shutil.disk_usage(OUT).free >= 32 * 2**30 and shutil.disk_usage(WORK).free >= 14 * 2**30,
         "owned runner capacity")
    need(historical.CARGO == ["cargo", "+ohm", "build", "-p", "ruff", "--bin", "ruff", "--locked", "--offline",
                              "-j4", "--message-format=json"], "inherited invocation contract changed")
    # Only this new Python process selects the integration command. Reuse the checked raw recorder;
    # it also checks the real installed Cargo argv and the parser's typed E0308.
    historical.CARGO = CARGO
    for folder in ("clean", "history", "initial"):
        (OUT / folder).mkdir()
    shutil.copy2(HERE / "PLAN.md", OUT / "PLAN.md")
    shutil.copy2(b.RUNTIME, OUT / "source-kit.json")
    suite.inventory((HERE / "expected-tests.txt").read_bytes())
    prefix = suite.permission_prefix(OUT / "initial")
    save(OUT / "enrollment.json", dict(head=head, parent="1d446332e82ca0188f63c3fddc9689f1f131fd42",
         run=int(os.environ["GITHUB_RUN_ID"]), attempt=1, plan=sha(HERE / "PLAN.md"), argv=CARGO, arms=ARMS,
         f=b.HEADS["F"], cargo=b.CARGO, wild=b.WILD_ELF, phase_order=historical.PHASES,
         boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(), suite_prefix=prefix))
    registry = b.acquire(source)
    env = b.activate(ARMS[0], registry, OUT / "initial")
    refuse_existing_work()
    b.prepare_inputs(kit, env)
    historical.historical.calibration()
    refs, records = {}, []
    for arm in ARMS:
        root = OUT / "clean" / arm
        root.mkdir()
        env = b.activate(arm, registry, root)
        for branch in ("A", "B"):
            refuse_existing_work()
            receipt(arm, "cold-" + branch, branch, env, root / branch, refs, {}, True, prefix)
    for branch in ("A", "B"):
        off, on = (refs[arm, branch] for arm in ARMS)
        need(off["typed"] == on["typed"] and off["behavior"] == on["behavior"], "cross-arm clean graph or verdict")
        for name in off["images"]:
            need(all(off["images"][name][k] == on["images"][name][k] for k in ("loads", "executable")),
                 ("cross-arm code bytes differ", branch, name))
    for arm in ARMS:
        root = OUT / "history" / arm
        root.mkdir()
        env = b.activate(arm, registry, root)
        refuse_existing_work()
        last, history = {}, []
        for phase, branch in historical.PHASES:
            history.append(receipt(arm, phase, branch, env, root / phase, refs, last, False, prefix))
        need(history[2]["products"]["cli"] != history[3]["products"]["cli"] and
             history[2]["products"]["reader"] != history[3]["products"]["reader"], "different source did not affect outputs")
        records += history
    b.verify_physical(b.SDK, registry["F"])
    save(OUT / "complete.json", dict(qualified=True, head=head, arms=ARMS, clocks=0, histories=records))


if __name__ == "__main__":
    if sys.argv[1:] == ["--print-command"]:
        print(json.dumps(CARGO))
        sys.exit(0)
    try:
        main(Path(sys.argv[1]).resolve())
    except BaseException:
        (OUT / "rejected.txt").write_text(traceback.format_exc())
        raise
