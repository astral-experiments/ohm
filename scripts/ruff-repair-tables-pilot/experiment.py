"""One source-qualified matched GNU hardware screen. A failed early budget terminates the schedule."""

import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import guards, namespace, protocol as P, source_binding as reg, visits, stage_control

w = visits.w
b = w.b
need = P.need


def records():
    result = {r: json.loads((b.OUT / "sdk" / (r + ".json")).read_bytes()) for r in ("E", "R")}
    need(
        [(r, d["source"]) for r, d in result.items()] == [("E", reg.P), ("R", reg.R)],
        "wrong parent/child physical source",
    )
    proof = json.loads((b.OUT / "sdk/R-source-qualified.json").read_bytes())
    need(
        proof["members"] == 81
        and proof["old"] == reg.P
        and proof["new"] == reg.R
        and len(proof["run_make"]) == 7
        and len(proof["units"]["rustc_incremental"]) == 11
        and proof["qa"] == os.environ["GITHUB_SHA"],
        "missing actual candidate source or native suite",
    )
    return {r: x["files"] for r, x in result.items()}


def active(arm, subjects, where):
    where.mkdir()
    cert = b.OUT / "sdk" / ("authoritative-E.json" if arm[0] == "E" else "R-source-qualified.json")
    env = b.activate(arm, subjects, where, permitted=P.ROLES, source_manifest=reg.sha(cert))
    env["TMPDIR"] = str(b.ROOT / "private-tmp")
    return env


def empty(arm, subjects, observed, refs):
    base = b.OUT / "empty" / arm
    env = active(arm, subjects, base)
    if arm.endswith("on"):
        stage_control.run(b.ROOT / ("tiny-staged-" + arm), env, base / "staged-tiny")
    for phase in ("clean-A", "clean-B", "clean-private-B", "clean-check-B"):
        b.fresh_outputs()
        visits.visit(phase, arm, env, base / phase, "plain", {}, observed, refs, reference=True)
    typed = visits.check_metadata.cross(refs["Eon", "B", "check"], refs[arm, "B", "check"])
    b.save(base / "cross-checked.json", typed)
    need(
        arm == "Roff" or typed["complete_byte_and_listing_equality"],
        "cross-compiler clean metadata differs; per-provider typed results and full original bodies retained for independent diagnosis",
    )
    for a, c in ((("A", "clean"), ("B", "clean")), (("B", "clean"), ("B", "private"))):
        left, right = (refs[arm, *k]["products"] for k in (a, c))
        need(left["cli"]["whole"] != right["cli"]["whole"], "edit did not produce a distinct runnable Ruff")
    for branch, kind in (("A", "clean"), ("B", "clean"), ("B", "private")):
        parent = refs["Eon", branch, kind]
        cur = refs[arm, branch, kind]
        need(
            parent["typed"] == cur["typed"]
            and w.same_products(parent["products"], cur["products"])
            and parent["up035"] == cur["up035"],
            "cross-role behavioral or source divergence",
        )
        for n in ("cli", "reader"):
            for k in ("executable", "loads"):
                need(
                    parent["products"][n][k] == cur["products"][n][k],
                    ("different native instruction bytes", arm, branch, kind, n, k),
                )


def history(arm, lane, phases, subjects, observed, refs):
    base = b.OUT / lane / arm
    env = active(arm, subjects, base)
    b.fresh_outputs()
    frontend = json.loads((base / "arm.json").read_bytes())["versions"]["rustc"].splitlines()[0]
    need(frontend.startswith("rustc "), "missing rustc version")
    state = {"physical_tables": lane == "observed", "version": frontend.removeprefix("rustc ")}
    group = {}
    for phase in phases:
        if lane == "observed":
            if phase in ("repair", "private-UP035-B"):
                method = "peak" if observed is not None else "plain"
            elif phase == "cold-A":
                method = "plain"  # Historical cold topology exists; no third full ptrace run.
            else:
                method = "trace"
        else:
            method = "measured"
        result = visits.visit(phase, arm, env, base / phase, method, state, observed, refs)
        group[phase] = result
        print("verified", arm, lane, phase, flush=True)
    b.save(base / "complete.json", group)
    return group


def machine_admission(subjects, observed):
    need(
        (b.WORK / ".owned-by-packed-study").read_text() == str(b.ROOT)
        and b.ROOT.resolve() == b.ROOT
        and not b.ROOT.is_symlink(),
        "unowned native history roots",
    )
    ready = json.loads((b.OUT / "meter-ready.json").read_bytes())
    os.sched_setaffinity(0, ready["affinity"])
    prior = json.loads((HERE / "inputs/previous.json").read_bytes())
    need(
        prior["head"] == reg.HISTORICAL
        and len(prior["old_excluded_boots"]) == len(set(prior["old_excluded_boots"])) == 78
        and len(prior["sessions"]) == 12
        and all(q["boot"] in prior["old_excluded_boots"] for q in prior["sessions"].values())
        and ready["boot"] == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        and ready["boot"] not in prior["old_excluded_boots"]
        and sorted(os.sched_getaffinity(0)) == ready["affinity"]
        and len(ready["affinity"]) == 8,
        "prior machine or incorrect hardware scope",
    )
    entry = guards.resources(b.WORK, b.OUT)
    guards.admit(entry, entry=True)
    b.save(
        b.OUT / "enrollment.json",
        dict(
            run=int(os.environ["GITHUB_RUN_ID"]),
            head=os.environ["GITHUB_SHA"],
            job=os.environ["GITHUB_JOB"],
            runner=os.environ["RUNNER_NAME"],
            attempt=1,
            meter=ready,
            previous=reg.sha(HERE / "inputs/previous.json"),
            source=reg.sha(b.OUT / "sdk/R-source-qualified.json"),
            fixture=reg.sha(
                b.OUT
                / (
                    "peak-qualification/refused.json"
                    if observed is None
                    else "peak-qualification/calibration/report.json"
                )
            ),
            resource=entry,
            order=list(P.ROLES),
            observed_order=list(P.PEAK_ROLES),
            privileged_namespace_creation=observed,
            plan=reg.sha(HERE / "PLAN.md"),
            command=P.COMMAND,
        ),
    )
    for n in ("empty", "measured", "single-checkout", "observed"):
        (b.OUT / n).mkdir()
    env = active("Eon", subjects, b.OUT / "initial")
    b.fresh_outputs()
    b.prepare_inputs(w.kit, env)
    w.historical.calibration()
    return entry


def matched(command_rows):
    visible = {}
    for arm, phases in command_rows.items():
        for name, row in phases.items():
            signature = (
                row["source"],
                row.get("graph"),
                row.get("dirty"),
                row.get("dirty_digest"),
                row.get("up035"),
            )
            if name in visible:
                need(
                    visible[name] == signature,
                    ("different ordinary source, typed graph or result", arm, name),
                )
            else:
                visible[name] = signature


def projected(phases, key):
    return {arm: {p: v[key] for p, v in row.items()} for arm, row in phases.items()}


def fixed_inputs(subjects):
    for role, wanted in subjects.items():
        physical = b.PARK / role if (b.PARK / role).exists() else b.SDK
        need(b.inventory(physical) == wanted, ("physical SDK changed", role))
    gr = {p.name: b.sha(p) for p in (b.HOME / ".cargo/registry/cache").glob("*/*.crate")}
    need(
        gr == json.loads((b.OUT / "ruff-inputs.json").read_bytes())["archives"],
        "original 505 archives changed",
    )


def run(physical, observers):
    reg.official_job()
    subjects = records()
    (b.ROOT / "private-tmp").mkdir()
    sp.run([sys.executable, "-IB", b.HERE / "meter.py", physical, observers], check=True)
    q = b.OUT / "peak-qualification"
    q.mkdir()
    # Small proof comes first; calibrations have no access to the active Cargo or Ruff roots.
    probe_env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C"}
    isolated = namespace.qualify(q, probe_env)
    machine_admission(subjects, isolated)
    refs = {}
    measured = {}
    shape = {}
    for arm in P.ROLES[:2]:
        empty(arm, subjects, isolated, refs)
        measured[arm] = history(arm, "measured", P.MAIN, subjects, isolated, refs) | history(
            arm, "single-checkout", P.ORDINARY, subjects, isolated, refs
        )
    matched(measured)
    thresholds = P.early(projected(measured, "instructions"))
    stop = any(not d["passed"] for d in thresholds.values())
    b.save(b.OUT / "early.json", {"conditions": thresholds, "stops_Roff": stop, "scored_only_whole": True})
    # Both scope-limited physical histories still run, even for a CPU rejection. No default/other host is opened on a red.
    for arm in P.PEAK_ROLES:
        shape[arm] = history(arm, "observed", P.PEAK, subjects, isolated, refs)
        for n in set(P.PEAK) & set(P.MAIN):
            a, c = shape[arm][n], measured[arm][n]
            for fld in ("rc", "source", "graph", "dirty_digest", "cli", "reader", "up035", "output_roles"):
                need(a.get(fld) == c.get(fld), ("observed and ordinary native outcome differ", arm, n, fld))
    matched(shape)
    for name in (
        "return-A",
        "return-B",
        "unchanged-B",
        "invalid",
        "invalid-repeat",
        "private-restore-B",
        "stage-repair",
        "verify-repair",
        "post-repair-A",
        "post-repair-B",
        "verify-private-B",
    ):
        old, new = (shape[a][name]["native_execs"] for a in P.PEAK_ROLES)
        need(
            old["full"] == new["full"]
            and old["link_only"] == new["link_only"]
            and len(old["wild"]) == len(new["wild"]),
            ("real release native stages diverged", name),
        )
    peaks = {a: {p: d[p].get("peak") for p in ("repair", "private-UP035-B")} for a, d in shape.items()}
    if stop:
        result = {
            "decision": "reject",
            "reason": "prespecified whole-instruction ceiling exceeded",
            "failed": [n for n, v in thresholds.items() if not v["passed"]],
            "Roff_run": False,
            "conditions": thresholds,
        }
    else:
        arm = "Roff"
        empty(arm, subjects, isolated, refs)
        measured[arm] = history(arm, "measured", P.MAIN, subjects, isolated, refs)
        default = b.OUT / "default-stage"
        env = active(arm, subjects, default)
        # The completed main history leaves the repaired, restored B at the same paths.
        # Obtain the default's own warm metadata without altering either measured interval.
        for phase in ("stage-check", "stage-build"):
            visits.visit(phase, arm, env, default / phase, "plain", {}, isolated, refs)
        measured[arm].update(history(arm, "single-checkout", P.ORDINARY, subjects, isolated, refs))
        matched(measured)
        result = P.final(projected(measured, "instructions"), projected(measured, "allocated"), peaks)
        result.update(decision="screen-pass" if result["passed"] else "reject", Roff_run=True)
    fixed_inputs(subjects)
    result.update(
        measured_roles=list(measured),
        observed_roles=list(shape),
        separate_observation=True,
        sampled_observations=peaks,
        qualification=reg.sha(b.OUT / "sdk/R-source-qualified.json"),
        early=reg.sha(b.OUT / "early.json"),
    )
    b.save(b.OUT / "complete.json", result)
    print(json.dumps({k: result[k] for k in ("decision", "Roff_run")}), flush=True)


if __name__ == "__main__":
    try:
        run(*[Path(p).resolve() for p in sys.argv[1:]])
    except BaseException:
        if b.OUT.exists():
            (b.OUT / "refusal.txt").write_text(traceback.format_exc())
        raise
