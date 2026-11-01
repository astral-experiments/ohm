"""Run four independently trained treatments and one separate positive-kernel contact on a fresh admitted host."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import capture
import notify_calibration
import protocol
from capture import contact, ev, kernel, original, p, REG

BRANCH = "refs/heads/charlie/qa-ctfe-repair-notify-pmu-20261101"


def enrollment():
    e = os.environ
    ev.need(
        (
            e["GITHUB_REPOSITORY"],
            e["GITHUB_REF"],
            e["GITHUB_RUN_ATTEMPT"],
            e["REVIEWED_HEAD"],
            p.b.git(HERE, "rev-parse", "HEAD"),
        )
        == (p.b.REPO, BRANCH, "1", e["GITHUB_SHA"], e["GITHUB_SHA"]),
        "unregistered source or run",
    )
    ev.need(
        p.ROOT.resolve() == p.ROOT and (p.WORK / ".owned-by-packed-study").read_text() == str(p.ROOT),
        "unowned roots",
    )
    reg = json.loads((HERE / "contact-admission.json").read_bytes())
    # Without an exact successful official registration even SDK acquisition is closed.
    protocol.admit(reg, reg)
    return reg


def study(position, calibrator, observers, registry):
    ev.need(
        position in protocol.ARMS and shutil.disk_usage(p.OUT).free > 20 << 30,
        "unregistered position or insufficient capacity",
    )
    contact_proof = json.loads((p.OUT / "prerequisite.json").read_bytes())
    protocol.admit(contact_proof, registry)
    ev.need(
        "QA_EVIDENCE_B3SUM" not in os.environ
        and "GH_TOKEN" not in os.environ
        and "GITHUB_TOKEN" not in os.environ,
        "contaminated or credential-bearing measurement process",
    )
    os.environ["QA_EVIDENCE_B3SUM"] = "/usr/bin/b3sum"
    subprocess.run(
        [sys.executable, "-IB", p.HERE.parent / "branch-return-pmu/meter.py", calibrator, observers],
        check=True,
    )
    meter = json.loads((p.OUT / "meter-ready.json").read_bytes())
    os.sched_setaffinity(0, meter["affinity"])
    previous = (
        set(json.loads((HERE / "boot-exclusions.json").read_bytes()))
        | contact.OLD_BOOTS
        | {contact_proof["boot"]}
    )
    ev.need(
        len(meter["affinity"]) == 8
        and sorted(os.sched_getaffinity(0)) == meter["affinity"]
        and meter["boot"] not in previous
        and os.environ["RUNNER_NAME"] != contact_proof["runner"],
        "unqualified hardware host",
    )
    order = protocol.ARMS[position]
    separate = "E" if position == "01" else "O"
    boot = meter["boot"]
    p.save(
        p.OUT / "position.json",
        dict(
            run=int(os.environ["GITHUB_RUN_ID"]),
            head=os.environ["GITHUB_SHA"],
            runner=os.environ["RUNNER_NAME"],
            boot=boot,
            position=position,
            order=list(order),
            separate_native_role=separate,
            plan=protocol.digest(HERE / "PLAN.md"),
            contact=contact_proof,
            command=list(protocol.CARGO),
        ),
    )
    ev.need(list(protocol.CARGO) == p.original.CARGO, "different default Cargo command")
    rows = {r: json.loads((p.OUT / "sdk" / (r + ".json")).read_bytes())["files"] for r in ("E", "C")}
    start = p.OUT / "initial"
    start.mkdir()
    env = p.subjects.activate("Con", rows, start)
    ev.need(
        "LD_PRELOAD" not in env and not any(x.startswith("OHM_QA_PACK_") for x in env),
        "contaminated Cargo command",
    )
    tools = p.OUT / "tools"
    tools.mkdir()
    binary = tools / "table-notify"
    src = protocol.FROZEN / "notify.c"
    argv = [
        "/usr/bin/cc",
        "-std=gnu11",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        str(src),
        "-o",
        str(binary),
    ]
    subprocess.run(argv, check=True)
    p.save(
        tools / "tool.json",
        dict(
            argv=argv, source=ev.sha(src), elf=ev.sha(binary), compiler=ev.sha(Path(argv[0]).resolve())
        ),
    )
    observer_source = Path(os.environ["GITHUB_WORKSPACE"]) / "observer-source"
    group = kernel.qualify(
        observer_source,
        p.ROOT / "repair-kernel-tools",
        p.OUT / "kernel-fixtures",
        p.b.SDK / ev.WILD,
        boot,
    )
    reader = kernel.decoder(kernel.package(observer_source))
    p.save(
        p.OUT / "kernel-qualification.json",
        dict(
            source=kernel.HEAD,
            schema=3,
            boot=boot,
            observer=group["observer_sha256"],
            fixtures=ev.sha(p.OUT / "kernel-fixtures/group-v2/qualified.json"),
        ),
    )
    original.native_preflight(env, rows["C"])
    p.save(p.OUT / "notifier-counter-calibration.json", notify_calibration.exercise(p, ev, env))
    p.b.fresh_outputs()
    p.b.prepare_inputs(p.kit, env)
    subprocess.run([sys.executable, "-IB", p.HERE / "test_routes.py", p.kit.TREE], check=True)
    p.original.historical.calibration()
    refs = {}
    issues = []
    # Reverse reference order as well as scored order. Each of the three references has the same independent empty roots.
    for arm in ("Eon", "Con") if position == "01" else ("Con", "Eon"):
        p.history(arm, "clean", "reference", rows, refs, issues, None)
    p.cross_role(refs, issues)
    ev.need(not issues, "different executed load or contradictory independent empty")
    counted = {}
    placements = {}
    training = {}
    layouts = {}
    for role, structural in [(separate, True), *((v, False) for v in order)]:
        arm = "Eon" if role == "E" else "Con"
        d = p.OUT / (("structural-" if structural else "return-") + role)
        d.mkdir()
        cenv = p.subjects.activate(arm, rows, d)
        ev.need(cenv == env, "path or ordinary Cargo environment changed")
        p.b.fresh_outputs()
        p.routes.begin(p.kit.TREE, p.kit.REVS, p.kit.NAMES)
        visits = {}
        for phase in p.FULL[:-1]:
            visits[phase] = p.visit(
                arm, "ordinary", "return", phase, cenv, d / phase, refs, issues, None
            )
        clk, q = capture.physical(
            role, d / "repair", cenv, rows[arm[0]], refs, issues, reader, structural=structural
        )
        visits["repair"] = json.loads((d / "repair/visit.json").read_bytes())
        signatures = {
            phase: [v.get(k) for k in ("status", "graph", "dirty", "cli", "reader")]
            for phase, v in visits.items()
        }
        lay = {
            phase: contact.placement(original.contents(d / phase), p.WORK)
            for phase in p.FULL
            if phase != "invalid"
        }
        expected = contact.placement(
            original.contents(p.OUT / ("clean-reference-" + arm) / "clean-edited"), p.WORK
        )
        ev.need(
            lay["repair"] == lay["unchanged"] == expected
            and training.setdefault(arm, signatures) == signatures
            and layouts.setdefault(arm, lay) == lay,
            "different state history, native products or actual Cargo placement",
        )
        if not structural:
            counted[role] = clk
            placements[role] = q
    checks = {k: ev.comparison(placements[k], placements["B"], REG) for k in ("P", "O")}
    ev.need(
        capture.read_gz(p.OUT / "return-P/repair/physical-compilers.json.gz")
        == capture.read_gz(p.OUT / "return-B/repair/physical-compilers.json.gz"),
        "different compiler commands under interception",
    )
    checks["ordinary_parent_objects"] = capture.storage.parent_objects(
        placements["E"], placements["O"], REG
    )
    p.save(
        p.OUT / "completed.json",
        dict(
            complete=True,
            issues=issues,
            order=list(order),
            source="registered-four-role",
            comparisons=checks,
            contrasts=protocol.contrasts({arm: protocol.measured(counted[arm]) for arm in order}),
        ),
    )
    ev.need(not issues, "incomplete paired verdicts")


if __name__ == "__main__":
    try:
        r = enrollment()
        if sys.argv[1:2] == ["acquire"]:
            saved = protocol.certificate(Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]), r)
            p.save(p.OUT / "prerequisite.json", saved)
            p.subjects.acquire(Path(sys.argv[2]))
        else:
            study(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), r)
    except BaseException:
        if p.OUT.is_dir():
            (p.OUT / "failure.txt").write_text(traceback.format_exc())
        raise
