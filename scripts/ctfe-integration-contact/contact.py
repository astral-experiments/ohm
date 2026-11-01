"""Collect two ordinary hardware-counted Ruff integration histories with separately observed references."""

import gzip
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as q
import instructions as policy


def read(path):
    return json.loads(path.read_bytes())


def fresh(h, env):
    s = q.semantics()
    paths = s.roots(env, h.ROOT)
    s.physical_roots(paths, empty=False)
    h.b.fresh_outputs()
    q.need(
        all(not any((h.WORK / part).iterdir()) for part in ("target", "build")), "nonempty Cargo state"
    )
    h.routes.begin(h.kit.TREE, h.kit.REVS, h.kit.NAMES)
    return s.physical_roots(paths, empty=True)


def trial(h, s, suite, observer, arm, phase, env, top, refs, owners, prefix, fresh_state, reference):
    w = top / phase
    w.mkdir()
    if fresh_state is not None:
        h.save(w / "fresh.json", fresh_state)
    if phase == "repair":
        h.original.failed_session.before_repair(
            h.WORK, read(top / "invalid/failed.json"), w / "grace.json"
        )
    h.routes.advance(h.kit.TREE, h.kit.NAMES, phase, "return")

    def snapshot():
        return h.routes.snapshot(h.kit.TREE, h.kit.REVS, h.kit.TREES, h.kit.NAMES, phase, "return")

    state = snapshot()
    h.save(w / "source.json", state)
    if phase == "unchanged":
        q.need(state == read(top / "comment/source.json"), "checkout changed between repeat and comment")
    rc = 101 if phase == "invalid" else 0
    counted = phase in q.HISTORY
    if counted:
        observer.source(w, arm, env, "before")
        events, count, physical = h.original.invocation(w, env, "measured", rc, arm)
        observer.source(w, arm, env, "after")
        clock = read(w / "clock.json")
        q.need(physical is None and count == policy.timed(clock, phase), "uncertified counter")
    else:
        events, count, physical = observer.invocation(w, env, rc, arm)
        q.need(count is None, "counter active during clean reference")
        seen = observer.packages().reader.read(w / "kernel.tsv.gz", expected_code=rc, expected_schema=3)
        q.install_boundary(seen["execs"])
    pending = h.original.failed_session.observed(h.WORK)
    ledger = h.original.disk.allocated(h.WORK / "target", h.WORK / "build", w, failed_sessions=pending)
    q.need(
        ledger["all_inodes"] > 1000 and min(ledger["roots"].values()) > 0,
        "incomplete allocated-inode ledger",
    )
    typed, dirty = s.roster(events, h.kit.TREE)
    h.publish(w / "roster.json.gz", {"units": typed, "dirty": dirty})
    policy.rosters_admit(reference, arm, phase, typed, dirty)
    rec = dict(
        phase=phase,
        arm=arm,
        status=rc,
        allocated=ledger["allocated"],
        typed=len(typed),
        dirty=len(dirty),
        physical=None if counted else q.identities(physical),
        wild_outputs=None if counted else q.link_outputs(physical),
    )
    if counted:
        rec["clock"] = clock
    if rc:
        h.save(w / "failed.json", pending)
    else:
        cold = phase in q.EMPTY or phase == "Y-B"
        q.need(
            len(typed) == 390
            and not pending
            and (not cold or (len(dirty) == 390 and ledger["packed_files"] == 0)),
            "wrong typed installation, pending session or false cold",
        )
        paths = s.selected_paths(events, h.kit.TREE, h.WORK)
        if counted:
            ref = q.reference(phase)
            mapping = policy.reference_owners(refs[arm, ref]["owners"])
            rec["external_owner_witness"] = ref
        else:
            mapping = s.join_native(physical, paths, cold, owners, h.sha, True)
        filtered, providers = s.reader_stream(events, mapping, h.sha)
        # Collect the physical operand and Cargo's promoted executable independently for warm links too.
        identities = {}
        for role in ("cli", "harness"):
            actual = paths[role]
            targets = [actual, *(Path(r["path"]) for r in mapping[role]["linked_by"])]
            identities[role] = {
                str(p): [p.stat().st_dev, p.stat().st_ino, p.stat().st_size, h.sha(p)] for p in targets
            }
            for link in mapping[role]["linked_by"]:
                (owner,) = [
                    ld
                    for ld in physical["wild_processes"]
                    if ld["pid"] == link["pid"] and ld["output"] == link["path"]
                ]
                (rust,) = [r for r in physical["rustcs"] if r["event"] == owner["rustc_event"]]
                q.need(
                    rust["crate"] == ("ruff" if role == "cli" else "integration_test"),
                    "link owned by different crate",
                )
        h.save(
            w / "selected.json",
            dict(
                paths={n: str(p) for n, p in paths.items()},
                owners=mapping,
                reader=providers,
                operands=q.operand_files(mapping, providers, h.sha),
                terminal_files=identities,
            ),
        )
        owners.update(mapping)
        branch = state["branch"]
        native = h.original.native
        prod, files = native.observed(
            filtered, branch, h.kit.REVS[branch], env, h.ROOT, h.kit.TREE, h.WORK, w
        )
        files["harness"] = paths["harness"]
        images = {k: prod[k] for k in ("cli", "reader")}
        images["harness"] = native.elf(paths["harness"])
        h.save(w / "harness-elf.json", images["harness"])
        expected = q.reference(phase)
        if phase in q.EMPTY:
            for role, p in files.items():
                native.preserve(p, images[role], h.original.BODIES, h.original.BUNDLE)
        else:
            prior = refs[arm, expected]
            q.need(
                typed == prior["typed"], "same branch typed roster differs from own independent clean"
            )
            for role, p in files.items():
                native.same_file(p, images[role], prior["images"][role], h.original.BODIES, w)
        oracle = suite.exercise(
            paths["harness"], paths["cli"], h.kit.TREE, env, w, prefix, h.original.processes
        )
        behavior = {k: v for k, v in prod.items() if k not in ("cli", "reader")} | {"suite": oracle}
        native_dir = h.original.historical.stable_sdk.output_directory(events, "tikv-jemalloc-sys")
        if phase in q.EMPTY:
            refs[arm, phase] = dict(
                typed=typed, images=images, behavior=behavior, native_dir=native_dir, owners=mapping
            )
        else:
            q.need(
                (behavior, native_dir) == (prior["behavior"], prior["native_dir"]),
                "behavior or native generator path changed",
            )
        rec["products"] = {k: v["whole"] for k, v in images.items()}
        rec["suite_count"] = 96
    q.need(snapshot() == state, "off-window validations changed source")
    h.save(w / "visit.json", rec)
    print(arm, phase, rec.get("suite_count", "expected E0308"), flush=True)
    return rec


def local_host(h, calibrator, observers):
    h.b.prepare_checkout(calibrator, h.b.CAL, "scripts/gnu-renderer-pfc-hardware")
    h.b.prepare_checkout(observers, h.b.OBS, "scripts/gnu-example-ceiling")
    kit = calibrator / "scripts/gnu-renderer-pfc-hardware"
    subprocess.run(["sha256sum", "--strict", "--check", "--status", "SHA256SUMS"], cwd=kit, check=True)
    boot = runpy.run_path(str(kit / "calibration.py"))["host"](observers, h.OUT)
    host = dict(
        boot=boot,
        affinity=sorted(os.sched_getaffinity(0)),
        machine=os.uname().machine,
        release=os.uname().release,
    )
    h.reg.host(host)
    q.excluded_boot(boot)
    return host


def main(argv):
    q.check_source(os.environ["REVIEWED_HEAD"])
    ctfe, select, suite = q.packages()
    import pilot as h

    q.need(
        Path(h.__file__).resolve() == ctfe / "scripts/ctfe-crossover-pilot/pilot.py",
        "wrong runtime helper",
    )
    q.need(
        os.environ["GITHUB_REPOSITORY"] == h.b.REPO
        and os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
        and os.environ["GITHUB_REF"] == "refs/heads/" + policy.BRANCH
        and os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"]
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and h.ROOT.resolve() == h.ROOT
        and (h.WORK / ".owned-by-packed-study").read_text() == str(h.ROOT),
        "wrong registration or private roots",
    )
    if argv[0] == "acquire" and len(argv) == 2:
        h.subjects.acquire(Path(argv[1]))
        return
    q.need(
        argv[0] == "run" and len(argv) == 3 and not (h.OUT / "meter-ready.json").exists(),
        "unknown mode or active counters",
    )
    pos = os.environ["POSITION"]
    order = policy.ORDER[pos]
    host = local_host(h, *map(Path, argv[1:]))
    policy.fresh_boot(host["boot"])
    h.save(
        h.OUT / "position.json",
        dict(
            mode="counter-pilot",
            position=pos,
            runner=os.environ["RUNNER_NAME"],
            order=order,
            run=int(os.environ["GITHUB_RUN_ID"]),
            head=os.environ["GITHUB_SHA"],
            command=q.COMMAND,
            host=host,
            boot=host["boot"],
            hardware_gate=h.reg.hardware_gate(),
            plan=h.sha(q.HERE / "PLAN.md"),
        ),
    )
    shutil.copyfile(q.HERE / "PLAN.md", h.OUT / "PLAN.md")
    rows = {k: read(h.OUT / "sdk" / (k + ".json"))["files"] for k in ("E", "C")}
    initial = h.OUT / "initial"
    initial.mkdir()
    env = h.subjects.activate("Eon", rows, initial)
    trace = h.component("trace")
    trace.prepare("contact", host)
    capture = trace.packages().capture
    q.need(
        capture.CARGO == h.original.CARGO == q.BUILD and h.reg.OBSERVER == q.KERNEL,
        "unexpected base adapter",
    )
    capture.CARGO = q.COMMAND.copy()
    h.original.CARGO = q.COMMAND.copy()
    calibration = runpy.run_path(str(Path(argv[1]) / "scripts/gnu-renderer-pfc-hardware/calibration.py"))
    binary = calibration["setup"](Path(argv[2]), h.ROOT, h.OUT)
    q.need(
        binary == h.OUT / "observers/plain" and len(os.sched_getaffinity(0)) == 8,
        "wrong counter/affinity",
    )
    h.save(
        h.OUT / "meter-ready.json",
        dict(
            boot=host["boot"],
            affinity=host["affinity"],
            observer=h.b.OBS,
            calibrator=h.b.CAL,
            plain=str(binary),
        ),
    )
    h.b.fresh_outputs()
    h.b.prepare_inputs(h.kit, env)
    reference = policy.raw_contact(
        Path(os.environ["INTEGRATION_ORIGINAL"]),
        Path(os.environ["CONTACT_BASE"]),
        h.kit.TREE,
        Path(os.environ["CTFE_EXECS_SOURCE"]),
    )
    h.save(h.OUT / "prior-native-contact.json", reference)
    h.original.historical.calibration()
    suite.inventory((Path(suite.__file__).with_name("expected-tests.txt")).read_bytes())
    prefix = suite.permission_prefix(initial)
    import semantic

    refs, records, separate = {}, {}, {}
    for arm in order:
        top = h.OUT / arm
        top.mkdir()
        env = h.subjects.activate(arm, rows, top)
        trace.catalog(arm, rows, top, env)
        visits, owners = {}, {}
        for phase in q.PHASES:
            new = None
            if phase in q.EMPTY or phase == "Y-B":
                new = fresh(h, env)
                owners = {}
            visits[phase] = trial(
                h, select, suite, trace, arm, phase, env, top, refs, owners, prefix, new, reference
            )
        q.need(
            all(
                visits["X-A"]["products"][r] != visits["X-B"]["products"][r]
                for r in ("cli", "harness", "reader")
            ),
            "historical native products did not change",
        )
        separate[arm] = semantic.run(h, select, suite, trace, arm, env, top, owners, fresh)
        for phase in ("semantic-edit", "semantic-empty"):
            actual = json.loads(gzip.decompress((top / phase / "roster.json.gz").read_bytes()))
            policy.rosters_admit(reference, arm, phase, actual["units"], actual["dirty"])
        h.b.verify_physical(h.b.SDK, rows[arm[0]])
        records[arm] = visits
    for phase in q.EMPTY:
        e, c = (refs[arm, phase] for arm in q.ARMS)
        q.need(
            e["typed"] == c["typed"] and e["behavior"] == c["behavior"],
            "different compiler cross-role behavior",
        )
        for role in ("cli", "harness", "reader"):
            q.need(
                all(e["images"][role][key] == c["images"][role][key] for key in ("loads", "executable")),
                ("different cross-role executable bytes", phase, role),
            )
    h.save(
        h.OUT / "complete.json",
        dict(
            qualified=True,
            scored=14,
            schema=3,
            phases=list(q.PHASES),
            visits=records,
            semantic=separate,
            observed=policy.outcomes(records),
            prerequisite=policy.REGISTERED,
        ),
    )


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except BaseException:
        if "RUNNER_TEMP" in os.environ:
            out = Path(os.environ["RUNNER_TEMP"]) / "ohm-branch-object-qa/logs"
            if out.is_dir():
                (out / "failure.txt").write_text(traceback.format_exc())
        raise
