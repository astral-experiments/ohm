"""A fresh, wrapper-free contact admission and separately gated whole-Cargo measurement."""

from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import needed
import micro
import pilot
from support import calibrate, census, e2e, guards, need, put, replay, sha, study


def entry(source, suite):
    plan = pilot.source_plan(source, suite)
    manifest = HERE / "SHA256SUMS"
    need(manifest.is_file(), "absent wrapper-free registration")
    for row in manifest.read_text().splitlines():
        digest, path = row.split("  ", 1)
        target = HERE.parent.parent / path
        need(target.is_file() and sha(target) == digest, ("missing or different registered resource", path))
    return plan


def exact(left, right, *, context, flanks=False):
    keys = ["dirty", "inventory", "roster", "root_argv"] if not flanks else ["inventory"]
    keys += [key for key in ("elf", "verdict", "error") if key in left or key in right]
    for key in keys:
        need(left.get(key) == right.get(key), ("different ordinary native result", context, key))


def target_phase(contact, folder, work, repo, env, arm, which, suite, graph, cmd, extras, store, gold, score):
    count, rust, actual, roster, random_probes = needed.visit(
        contact, folder, work, repo, arm, env, cmd, expected=101 if which == "invalid" else 0,
        score=score, cold=which in ("old", "clean-new"))
    rows = replay.cargo_rows((folder / "outer.stdout").read_bytes())
    result = pilot.phase_checks(suite, rows, graph, work, repo, env, which, folder, extras, store, gold)
    owners = [r for r in rust if r["kind"] == "full" and r["name"] in graph[1]]
    if which == "new":
        need({r["name"] for r in owners} == set(graph[1]), "different genuine edited owners")
        for r in owners:
            args = r["argv"]
            cc = {a if a != "-C" else "-C" + args[i + 1] for i, a in enumerate(args) if a.startswith("-C")}
            need("-Copt-level=1" in cc and "-Cdebuginfo=line-tables-only" in cc and
                 not any("-Zllvm-plugins" in a for a in args) and
                 any("/build/debug/build/registries/v2-" in a for a in args), ("wrong true shared dev inputs", r["name"]))
        if arm == "original":
            need(sum(r["activation"] for r in owners) > 0, "native original did not reach LLVM")
        if arm == "guard":
            need(sum(r["reason_totals"][0] for r in owners) > 0, "native edited owners did not skip any LDV")
    if which == "unchanged":
        expected_native = {"rustc": [["link-only", "e2e", 1]], "linkers": [["signed-Wild", "e2e", 1]]} \
            if suite == "e2e" else {"rustc": [], "linkers": []}
        nonprobes = [row for row in actual["rustc"] if row[0] != "probe"]
        need(nonprobes == expected_native["rustc"] and actual["linkers"] == expected_native["linkers"],
             ("ordinary settled work changed", suite, actual))
    owner_commands = sorted([r["name"], r["argv"]] for r in rust
                            if r["kind"] in ("full", "link-only") and r["name"] in graph[1])
    result.update({"root_argv": owner_commands, "roster": roster,
                   "raw_roster": actual, "physical_autocfg": random_probes, "kernel_sha256": sha(folder / "kernel.json"),
                   "linker_argv_sha256": sha(folder / "linker-argv.json"), "count": count,
                   "guard_hits": sum(r["reason_totals"][0] for r in owners)})
    put(folder / "result.json", result)
    return result


def run(source, suite, stage, pair):
    plan = entry(source, suite)
    need(stage in ("admit", "score") and pair in (1, 2) and (stage != "admit" or pair == 1), "unregistered assignment")
    track = json.loads((HERE / "schedule.json").read_bytes())
    assign, = [s for s in track["slots"] if (s["suite"], s["pair"]) == (suite, pair)]
    need(census.git(HERE, "rev-parse", "HEAD") == os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"], "wrong QA commit")
    run_dir, existing, sdk = census.paths()
    root, out = run_dir / "ldv-needed", existing / "ldv"
    root.mkdir()
    out.mkdir()
    if stage == "score":
        witness = Path(os.environ["RUNNER_TEMP"]) / "verified-ldv-native-gate.json"
        prior = json.loads(witness.read_bytes())
        need(prior["qa"] == os.environ["GITHUB_SHA"] and str(prior["run"]) == os.environ["ADMISSION_RUN"]
             and set(prior["native"]) == {"option", "e2e"} and
             all(len(v["acquired"]) == len(v["physical"]) == 64 for v in prior["native"].values()),
             "two independently verified native admissions are required")
        put(out / "previous-admission.json", prior)
    guards.admit(guards.resources(root, out), entry=True, bootstrap=True)
    cpus = {}
    for cpu in sorted(os.sched_getaffinity(0)):
        topo = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        cpus.setdefault(tuple(int((topo / name).read_text()) for name in ("physical_package_id", "core_id")), cpu)
    need(len(cpus) >= 4, "host has fewer than four physical cores")
    chosen = list(cpus.values())[:4]
    os.sched_setaffinity(0, chosen)
    tools = root / "tools"
    tools.mkdir()
    contact = needed.Contact(sdk, tools, out)
    small = HERE.parent / "ruff-workspace-link-census/wild-diagnostic"
    for name, source_file, options in (("count", "count.c", []), ("toy", "calibrate.c", ["-pthread"])):
        subprocess.run(["/usr/bin/cc", "-O2", "-Wall", small / source_file, *options, "-o", tools / name], check=True)
    calibrate(tools, out / "calibration")
    env = census.environment(run_dir, sdk)
    Path(env["HOME"]).mkdir(exist_ok=True)
    put(out / "enrolled.json", {"qa": os.environ["GITHUB_SHA"], "run": int(os.environ["GITHUB_RUN_ID"]),
        "stage": stage, "slot": assign, "schedule": sha(HERE / "schedule.json"), "plan": plan, "cpus": chosen,
        "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(), "contact": sha(out / "physical-contact.json"),
        "counter": sha(tools / "count")})
    donor = root / "locked-inputs"
    donor.mkdir()
    subprocess.run(["cargo", "+ohm", "fetch", "--locked"], cwd=source, env={**env, "CARGO_HOME": str(donor)}, check=True)
    packages = {r["name"] + "-" + r["version"] + ".crate": r["checksum"]
                for r in tomllib.loads((source / "Cargo.lock").read_text())["package"] if "checksum" in r}
    need(pilot.registry(donor) == packages and packages["autocfg-1.5.0.crate"] == track["allowed_autocfg"],
         "different real registry inputs")
    put(out / "registry.json", packages)
    micro.run(contact, env, donor, packages["autocfg-1.5.0.crate"], root / "smoke", out / "smoke")
    git_old, git_new, cmd = plan["old"], plan["new"], plan["command"]
    gold = study.source_pair(source) if suite == "option" else None
    blobs = e2e.enroll(replay, source, packages) if suite == "e2e" else None
    work, repo, extras, store = root / "work", root / "ruff", root / "consumer", out / "native-bodies"
    for p in (work, extras, store):
        p.mkdir()
    pilot.new_tree(source, repo, git_old)
    if suite == "option":
        shutil.copyfile(HERE.parent / "ruff-workspace-option-edit/client.rs", extras / "option-client.rs")
        (extras / "bad-option-client.rs").write_bytes(study.BAD_CLIENT)
    base = {**env, "CARGO_HOME": str(work / "cargo-home"), "CARGO_TARGET_DIR": str(work / "target"),
            "CARGO_BUILD_BUILD_DIR": str(work / "build")}

    def source_state(phase, write):
        if suite == "e2e":
            return e2e.source_state(replay, repo, blobs, phase, write=write)
        fn = study.write_source if write else study.source_state
        return fn(repo, git_old if phase == "old" else git_new, phase == "invalid")

    records = {}
    (out / "checkpoints").mkdir()
    graph = None
    for label in ["plain-A", "plain-B", *assign["order"]]:
        arm = "plain" if label.startswith("plain-") else label
        contact.select(arm)
        records[label] = {}
        cases = [("edit", ("old", "new", "unchanged"))] if arm == "plain" else [
            ("edit", ("old", "new", "unchanged", "invalid", "repair")),
            ("clean", ("clean-new", "negative", "restored-new") if suite == "e2e" else ("clean-new",))]
        for kind, phases in cases:
            case = out / f"{label}-{kind}"
            case.mkdir()
            guards.admit(guards.resources(work, out), entry=True)
            source_state(phases[0], True)
            with replay.empty_roots(work, case):
                home = work / "cargo-home"
                (home / "registry").mkdir()
                for sub in ("index", "cache"):
                    subprocess.run(["cp", "-a", "--reflink=auto", donor / "registry" / sub, home / "registry" / sub], check=True)
                subprocess.run(["cargo", "+ohm", "fetch", "--locked", "--offline"], env=base, cwd=repo, check=True)
                need(pilot.registry(home) == packages, "different private registry")
                cur = pilot.unit_graph(cmd, base, repo, case, suite)
                if graph is None:
                    graph = cur
                need(cur == graph, "different real dev graph")
                for phase in phases:
                    before = source_state(phase, True)
                    dest = case / phase
                    scored = stage == "score" and arm != "plain" and kind == "edit" and phase in ("new", "unchanged")
                    result = target_phase(contact, dest, work, repo, base, arm, phase, suite, graph, cmd,
                                          extras, store, gold, scored)
                    need(before == source_state(phase, False), "source changed inside real Cargo")
                    put(dest / "source.json", before)
                    records[label][phase] = result
                    put(out / "checkpoints" / f"{label}-{phase}.json", result)
                    # Stop before another observation on genuine uncontrolled variation.
                    if label != "plain-A" and phase in records["plain-A"]:
                        exact(records["plain-A"][phase], result, context=[label, phase])
        if arm != "plain":
            for returned in ("new", "unchanged", "repair", *(("restored-new",) if suite == "e2e" else ())):
                exact(records[label]["clean-new"], records[label][returned], context=[label, returned], flanks=True)
    for phase, original in records["original"].items():
        exact(original, records["guard"][phase], context=["diagnostic arms", phase])
    if suite == "e2e":
        for arm in records.values():
            need(arm["new"]["verdict"]["count"] == arm["old"]["verdict"]["count"] + 1, "different test count")
    contact.finish()
    need(pilot.registry(donor) == packages, "original registry donor changed")
    put(out / "acquired.json", records)
    summary = {"stage": stage, "suite": suite, "assignment": assign, "qa": os.environ["GITHUB_SHA"],
               "source": [git_old, git_new], "run": int(os.environ["GITHUB_RUN_ID"]),
               "acquired": sha(out / "acquired.json"), "physical": sha(out / "physical-contact.json"),
               "guarded_owner_skips": records["guard"]["new"]["guard_hits"],
               "qualified_native": {a: {p: {"elf": r.get("elf"), "kernel": r["kernel_sha256"]}
                                       for p, r in row.items()} for a, row in records.items()}}
    if stage == "score":
        summary["whole_tree_user_instructions"] = {k: {p: records[k][p]["count"] for p in ("new", "unchanged")}
                                                  for k in ("original", "guard")}
        summary["original_over_guard_new"] = records["original"]["new"]["count"] / records["guard"]["new"]["count"]
    put(out / "verified.json", summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    if sys.argv[1] in ("verify-entry", "install"):
        plan = entry(Path(sys.argv[2]).resolve(strict=True), sys.argv[3])
        if sys.argv[1] == "install":
            census.install()
        else:
            print(json.dumps(plan))
    else:
        try:
            run(Path(sys.argv[1]).resolve(strict=True), sys.argv[2], sys.argv[3], int(sys.argv[4]))
        except Exception as exc:
            _, where, _ = census.paths()
            if (where / "ldv").is_dir():
                put(where / "ldv/failure.json", {"type": type(exc).__name__, "reason": str(exc)[-1800:]})
            raise
