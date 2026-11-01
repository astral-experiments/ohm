"""Acquire one of six independently enrolled full Ruff D/Q histories."""

import os
import runpy
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "ctfe-crossover-pilot"
sys.path[:0] = [str(HERE), str(BASE)]
import endpoints
import git_layout
import packed_donor
import packed_sdk as sdk
import packed_watches
import pilot as h
import qualification
import packed_confirmation as six

BRANCH = six.BRANCH
HISTORIES = (
    ("clean", "reference", h.REFS),
    ("structural", "return", h.FULL),
    ("structural", "dirty", h.PREFIX),
    ("measured", "return", h.FULL),
)


def activate(arm, rows, top):
    return h.b.activate(
        arm, rows, top, permitted=sdk.ARMS, source_manifest=sdk.manifests()[arm[0]]
    )


def bind_host(calibrator, observers):
    h.b.prepare_checkout(calibrator, h.b.CAL, "scripts/gnu-renderer-pfc-hardware")
    h.b.prepare_checkout(observers, h.b.OBS, "scripts/gnu-example-ceiling")
    kit = calibrator / "scripts/gnu-renderer-pfc-hardware"
    subprocess.run(
        ["sha256sum", "--strict", "--check", "--status", "SHA256SUMS"],
        cwd=kit,
        check=True,
    )
    api = runpy.run_path(str(kit / "calibration.py"))
    boot = api["host"](observers, h.OUT)
    host = dict(
        boot=boot,
        affinity=sorted(os.sched_getaffinity(0)),
        machine=os.uname().machine,
        release=os.uname().release,
    )
    h.reg.host(host)
    six.fresh(host["boot"], os.environ["RUNNER_NAME"])
    return api, host


def job():
    h.need(
        os.environ.get("GITHUB_REPOSITORY") == h.b.REPO
        and os.environ.get("GITHUB_REF") == "refs/heads/" + BRANCH
        and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.environ.get("GITHUB_RUN_ATTEMPT") == "1"
        and h.b.git(HERE, "rev-parse", "HEAD")
        == os.environ["GITHUB_SHA"]
        == os.environ["REVIEWED_HEAD"]
        and h.ROOT.resolve() == h.ROOT
        and (h.WORK / ".owned-by-packed-study").read_text() == str(h.ROOT),
        "unowned host, attempt, reviewed head or namespace",
    )


def main(argv):
    job()
    slot = os.environ["CONFIRMATION_POSITION"]
    order = six.order(slot)
    if len(argv) == 3 and argv[0] == "acquire":
        sdk.acquire(Path(argv[1]), Path(argv[2]), h.subjects, h.b)
        return
    h.need(
        len(argv) == 3
        and argv[0] == "confirmation"
        and shutil.disk_usage(h.OUT).free > 20 * 2**30
        and not (h.OUT / "meter-ready.json").exists(),
        "unregistered action, active counter or insufficient disk",
    )
    calibrator, observers = map(Path, argv[1:])
    api, host = bind_host(calibrator, observers)
    sdk_rows = sdk.verify_pair(
        {k: sdk.read(h.OUT / "sdk" / (k + ".json")) for k in sdk.SOURCES}
    )
    rows = {k: v["files"] for k, v in sdk_rows.items()}
    position = dict(
        mode=six.MODE,
        position=slot,
        order=list(order),
        **six.ENROLLMENT,
        host=host,
        boot=host["boot"],
        runner=os.environ["RUNNER_NAME"],
        run=int(os.environ["GITHUB_RUN_ID"]),
        head=os.environ["GITHUB_SHA"],
        command=h.original.CARGO,
        plan=six.PLAN,
        registered_plan=h.sha(HERE / "inputs/registered-plan.md"),
        hardware_gate=h.reg.hardware_gate(),
        prerequisites=qualification.prereqs(),
        packed_source=[sdk.SOURCE_RUN, sdk.SOURCE_JOB, sdk.compact(sdk.enrolled())],
    )
    h.save(h.OUT / "position.json", position)
    shutil.copyfile(HERE / "inputs/six-plan.md", h.OUT / "PLAN.md")
    initial = h.OUT / "initial"
    initial.mkdir()
    env = activate(order[0], rows, initial)
    tracer = h.component("trace")
    # Dependency for this distinct application, using the original positive observer's own schema.
    tracer.packages().subjects = sdk
    tracer.prepare("contact", host)
    plain = api["setup"](observers, h.ROOT, h.OUT)
    h.need(
        plain == h.OUT / "observers/plain"
        and sorted(os.sched_getaffinity(0)) == host["affinity"],
        "counter admission/CPU changed",
    )
    h.save(
        h.OUT / "meter-ready.json",
        dict(
            boot=host["boot"],
            affinity=host["affinity"],
            observer=h.b.OBS,
            calibrator=h.b.CAL,
            plain=str(plain),
        ),
    )
    h.b.fresh_outputs()
    h.b.prepare_inputs(h.kit, env)
    # This inherited private clone exercises the loose baseline before the real public ref transport.
    subprocess.run(
        [sys.executable, "-IB", BASE / "test_routes.py", h.kit.TREE], check=True
    )
    h.save(h.OUT / "git-layout.json", git_layout.install(h.kit.TREE))
    h.original.historical.calibration()
    refs, issues, rosters = {}, [], {}
    from types import SimpleNamespace

    hooks = SimpleNamespace(
        git_layout=git_layout,
        activate=activate,
        capture=packed_donor.capture,
        script_output=packed_watches.script_output,
    )
    histories = []
    for lane, line, phases in HISTORIES:
        for arm in order:
            start = time.monotonic_ns()
            records = h.history(
                arm, lane, line, rows, refs, issues, tracer, phases, packed=hooks
            )
            stop = time.monotonic_ns()
            histories.append(
                dict(lane=lane, line=line, arm=arm, start_ns=start, stop_ns=stop)
            )
            rosters[lane, line, arm] = records
        if lane == "clean":
            h.cross_role(refs, issues, order)
    for arm in order:
        for phase in h.FULL:
            s = rosters["structural", "return", arm][phase]
            m = rosters["measured", "return", arm][phase]
            h.need(
                all(
                    m.get(k) == s.get(k)
                    for k in ("status", "graph", "dirty", "cli", "reader")
                ),
                ("traced and ordinary histories disagree", arm, phase),
            )
    h.save(h.OUT / "native-issues.json", issues)
    h.need(not issues, "original same-role whole ELFs / cross-role loads refused")
    summaries = {}
    for arm in order:
        clocks = {
            p: sdk.read(h.OUT / f"measured-return-{arm}" / p / "clock.json")
            for p in h.FULL
        }
        summaries[arm] = endpoints.count(clocks)
        h.need(
            all(
                summaries[arm]["phases"][p]["instructions"]
                == rosters["measured", "return", arm][p]["instructions"]
                for p in h.FULL
            ),
            "disjoint ordinary return measurement",
        )
    six.history_order(slot, histories, summaries)
    h.save(h.OUT / "history-intervals.json", histories)
    terminal = dict(
        qualified=True,
        position=position,
        visits=sum(len(v) for v in rosters.values()),
        metered=2 * len(h.FULL),
        source=[sdk.D, sdk.Q],
        measured=summaries,
        primary={
            a: rosters["measured", "return", a]["X-B"]["instructions"] for a in order
        },
        all_seven={
            a: sum(r["instructions"] for r in rosters["measured", "return", a].values())
            for a in order
        },
    )
    h.save(h.OUT / "complete.json", terminal)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except BaseException:
        if h.OUT.is_dir():
            (h.OUT / "failure.txt").write_text(traceback.format_exc())
        raise
