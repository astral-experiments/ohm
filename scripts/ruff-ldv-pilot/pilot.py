"""Two prospectively mirrored complete Cargo edit pairs per real Ruff workflow."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

from support import (HERE, calibrate, census, e2e, guards, instrument, native, need, physical, put, replay,
                     setup_tools, sha, study, visit)
import smoke


def registry(home):
    found = {}
    for path in (home / "registry/cache").glob("*/*.crate"):
        need(not path.is_symlink(), ("registry symlink", path))
        value = sha(path)
        need(value == found.setdefault(path.name, value), ("conflicting registry aliases", path))
    return found


def new_tree(source, repo, old):
    refs = Path(replay.git(source, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip())
    subprocess.run(["git", "init", "--quiet", repo], check=True)
    (repo / ".git/objects/info/alternates").write_text(str(refs / "objects") + "\n")
    replay.git(repo, "checkout", "--quiet", "--detach", old)


def unit_graph(cmd, env, repo, dest, suite):
    raw = subprocess.check_output([*cmd[:2], "-Zunstable-options", *cmd[2:], "--unit-graph"], env=env, cwd=repo)
    (dest / "graph.json").write_bytes(raw)
    graph = json.loads(raw)
    if suite == "e2e":
        expected, owners = e2e.graph_units(graph, repo, [])
        return expected, owners, sha(dest / "graph.json")
    units = graph["units"]
    need(graph["version"] == 1 and len(graph["roots"]) == 1, "wrong Cargo unit graph")
    root = units[graph["roots"][0]]
    need(root["target"]["name"] == "ruff_workspace" and root["profile"]["opt_level"] == "1", "wrong dev owner")
    expected = Counter()
    for u in units:
        need(u["mode"] in ("build", "run-custom-build") and not u["profile"].get("rustflags"), "extra flags or mode")
        if u["mode"] == "build":
            expected[e2e.artifact_key(u["pkg_id"], u["target"], u["features"], False)] += 1
    return expected, {"ruff_workspace": e2e.artifact_key(root["pkg_id"], root["target"], root["features"], False)}, sha(dest / "graph.json")


def executable_checks(test, repo, env, phase, folder, store):
    record = physical.keep(test, store, b"\x7fELF\x02\x01")
    def op(name, args, expected):
        result = subprocess.run([test, *args], env=env, cwd=repo, capture_output=True, timeout=120)
        (folder / (name + ".stdout")).write_bytes(result.stdout)
        (folder / (name + ".stderr")).write_bytes(result.stderr)
        put(folder / (name + ".json"), {"argv": [str(test), *args], "exit": result.returncode})
        need(result.returncode == expected, (phase, name, result.stderr[-1200:]))
        return result
    names = e2e.test_names(op("list", ["--list", "--format", "terse", "--color", "never"], 0).stdout.decode())
    need((e2e.ADDED in names) == (phase != "old"), ("stale catalog", phase))
    name = e2e.SIBLING if phase == "old" else e2e.ADDED
    negative = phase == "negative"
    result = op("named", ["--exact", name, "--test-threads", "1", "--nocapture", "--format", "pretty", "--color", "never"],
                101 if negative else 0)
    changed = e2e.executed(result.stdout.decode(), result.stderr.decode(), name, negative)
    need(sha(test) == record["sha256"], "harness output changed its ELF")
    return record, {"names_sha256": hashlib.sha256(("\n".join(names) + "\n").encode()).hexdigest(),
                    "count": len(names), "added": e2e.ADDED in names, "negative_left": changed}


def phase_checks(suite, rows, graph, work, repo, plain_env, phase, dest, extras, store, gold):
    from ownership import check_roots
    expected, owners, _ = graph
    bad = phase == "invalid"
    check_roots(rows, work)
    if suite == "e2e":
        dirty, keys, exe = e2e.products(rows, expected, owners, phase, work, repo)
        if not exe:
            return {"dirty": dirty, "inventory": keys, "error": "E0308"}
        record, verdict = executable_checks(exe, repo, plain_env, phase, dest, store)
        return {"dirty": dirty, "inventory": keys, "elf": record["sha256"], "bytes": record["stat"][2], "verdict": verdict}
    products = study.results(rows, not bad)
    keys = [e2e.artifact_key(p["package_id"], p["target"], p["features"], p["profile"]["test"]) for p in products]
    actual = Counter(keys)
    need(not (actual - expected) if bad else actual == expected, ("unregistered Cargo products", phase))
    dirty = sorted(k for k, p in zip(keys, products) if not p["fresh"])
    if bad:
        return {"dirty": dirty, "inventory": sorted(keys), "error": "E0308"}
    if phase in ("old", "clean-new"):
        need(Counter(dirty) == expected, ("nonempty cold build", phase))
    if phase == "new":
        need(owners["ruff_workspace"] in dirty, "edited package was skipped")
    revision = study.OLD if phase == "old" else study.NEW
    record = native.client(dest, rows, products, extras, work, plain_env, gold[revision], store)
    ar = study.artifact(products, study.OWNER)
    return {"dirty": dirty, "inventory": sorted(keys), "elf": record["sha256"], "bytes": record["stat"][2],
            "verdict": study.EXPECTED[revision], "owner_archive": {"sha256": sha(ar), "bytes": ar.stat().st_size}}


def main(source, suite, pair):
    schedule = json.loads((HERE / "schedule.json").read_bytes())
    assignment, = [s for s in schedule["slots"] if s["suite"] == suite and s["pair"] == pair]
    need(census.git(HERE, "rev-parse", "HEAD") == os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"], "wrong QA head")
    run, old_evidence, sdk = census.paths()
    old = study.OLD if suite == "option" else e2e.OLD
    new = study.NEW if suite == "option" else e2e.NEW
    need(census.git(source, "rev-parse", "HEAD") == new and not census.git(source, "status", "--porcelain=v1"), "unexpected frozen fixture")
    root = run / "ldv"
    root.mkdir()
    out = old_evidence / "ldv"
    out.mkdir()
    guards.admit(guards.resources(root, out), entry=True, bootstrap=True)
    physical_cores = {}
    for cpu in sorted(os.sched_getaffinity(0)):
        topology = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        key = tuple(int((topology / f).read_text()) for f in ("physical_package_id", "core_id"))
        physical_cores.setdefault(key, cpu)
    need(len(physical_cores) >= 4, "need four physical cores")
    cpus = list(physical_cores.values())[:4]
    os.sched_setaffinity(0, cpus)
    tools = root / "tools"
    identities = setup_tools(tools, sdk)
    calibrate(tools, out / "calibration")
    env = census.environment(run, sdk)
    Path(env["HOME"]).mkdir(exist_ok=True)
    smoke.run(root / "smoke", out / "smoke", tools, sdk, env)
    put(out / "enrolled.json", {"sdk": json.loads((old_evidence / "identity.json").read_bytes())["sdk"],
        "asset": census.common.SDK["asset"], "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "qa": os.environ["GITHUB_SHA"], "run": int(os.environ["GITHUB_RUN_ID"]), "schedule": sha(HERE / "schedule.json"),
        "physical_cores": cpus, "tools": identities, "assignment": assignment, "ruff": [old, new]})
    donor = root / "locked-inputs"
    donor.mkdir()
    subprocess.run(["cargo", "+ohm", "fetch", "--locked"], cwd=source, env={**env, "CARGO_HOME": str(donor)}, check=True)
    lock = tomllib.loads((source / "Cargo.lock").read_text())
    packages = {r["name"] + "-" + r["version"] + ".crate": r["checksum"] for r in lock["package"] if "checksum" in r}
    need(registry(donor) == packages, "locked registry archive closure")
    put(out / "registry.json", packages)
    gold = study.source_pair(source) if suite == "option" else None
    blobs = e2e.enroll(replay, source, packages) if suite == "e2e" else None
    cmd = study.CMD if suite == "option" else e2e.CARGO
    work = root / "work"
    work.mkdir()
    repo = root / "ruff"
    new_tree(source, repo, old)
    extras = root / "consumer"
    extras.mkdir()
    if suite == "option":
        (extras / "option-client.rs").write_bytes((HERE.parent / "ruff-workspace-option-edit/client.rs").read_bytes())
        (extras / "bad-option-client.rs").write_bytes(study.BAD_CLIENT)
    store = out / "native-bodies"
    store.mkdir()
    base = {**env, "CARGO_HOME": str(work / "cargo-home"), "CARGO_TARGET_DIR": str(work / "target"),
            "CARGO_BUILD_BUILD_DIR": str(work / "build")}
    records = {}
    common_graph = None
    def source_state(phase, write):
        if suite == "e2e":
            return e2e.source_state(replay, repo, blobs, phase, write=write)
        revision = study.OLD if phase == "old" else study.NEW
        fn = study.write_source if write else study.source_state
        return fn(repo, revision, phase == "invalid")
    for arm in ["plain", *assignment["order"]]:
        edit = ("old", "new", "unchanged") if arm == "plain" else ("old", "new", "unchanged", "invalid", "repair")
        cases = [("edit", edit)]
        if arm != "plain":
            cases.append(("clean", ("clean-new", "negative", "restored-new") if suite == "e2e" else ("clean-new",)))
        records[arm] = {}
        for history, phases in cases:
            case = out / (arm + "-" + history)
            case.mkdir()
            guards.admit(guards.resources(work, out), entry=True)
            source_state(phases[0], True)
            with replay.empty_roots(work, case):
                home = work / "cargo-home"
                (home / "registry").mkdir()
                for kind in ("index", "cache"):
                    subprocess.run(["cp", "-a", "--reflink=auto", donor / "registry" / kind,
                                    home / "registry" / kind], check=True)
                subprocess.run(["cargo", "+ohm", "fetch", "--locked", "--offline"], env=base, cwd=repo, check=True)
                need(registry(home) == packages, "private history has different registry bytes")
                graph_receipts = case / "graph-compilers"
                graph_receipts.mkdir()
                graph = unit_graph(cmd, instrument(base, tools, sdk, arm, graph_receipts), repo, case, suite)
                if common_graph is None:
                    common_graph = graph
                need(graph == common_graph, "different unmodified dev-profile graph")
                for phase in phases:
                    before = source_state(phase, True)
                    dest = case / phase
                    count, rusts, roster = visit(dest, work, repo, sdk, tools, arm, base, cmd,
                        expected=101 if phase == "invalid" else 0, score=arm != "plain" and history == "edit",
                        include_env=True)
                    need(before == source_state(phase, False), "source changed inside Cargo")
                    put(dest / "source.json", before)
                    rows = replay.cargo_rows((dest / "outer.stdout").read_bytes())
                    result = phase_checks(suite, rows, graph, work, repo, base, phase, dest, extras, store, gold)
                    tracked = [r for r in rusts if r["kind"] == "full" and r["name"] in graph[1]]
                    root_args = sorted((r["name"], r["argv"]) for r in tracked)
                    if phase == "new":
                        need({r["name"] for r in tracked} == set(graph[1]), ("did not compile edited roots", phase))
                        for r in tracked:
                            args = r["argv"]
                            options = {a if a != "-C" else "-C" + args[i + 1] for i, a in enumerate(args) if a.startswith("-C")}
                            need("-Copt-level=1" in options and "-Cdebuginfo=line-tables-only" in options
                                 and not any("-Zllvm-plugins" in a for a in args), ("wrong ordinary root profile", r["name"], options))
                        if arm == "guard":
                            need(sum(r["reason_totals"][0] for r in tracked) > 0, "no physical edited-owner guard skip")
                        if arm == "original":
                            need(sum(r["activation"] for r in tracked) > 0, "original callback did not run")
                    result.update({"instructions": count, "roster": roster, "root_argv": root_args,
                                   "owner_guard_hits": sum(r["reason_totals"][0] for r in tracked)})
                    put(dest / "result.json", result)
                    records[arm][phase] = result
                need(registry(home) == packages, "registry changed in a study history")
    # Finish all blind acquisitions first. Expose a paired effect only after the
    # independent raw native bytes, physical work and graph gates all pass.
    put(out / "acquired.json", records)
    for arm in assignment["order"]:
        for phase in ("old", "new", "unchanged"):
            actual, ref = records[arm][phase], records["plain"][phase]
            for key in ("dirty", "inventory", "roster", "root_argv", "elf", "verdict"):
                need(actual[key] == ref[key], ("changed ordinary workload or native output", arm, phase, key))
        for phase in ("new", "unchanged", "repair", "clean-new", *(("restored-new",) if suite == "e2e" else ())):
            ref = records[arm]["clean-new"]
            need(all(records[arm][phase][key] == ref[key] for key in ("elf", "verdict", "inventory")),
                 ("different independent complete output", arm, phase))
    for phase in records["original"]:
        a, b = records["original"][phase], records["guard"][phase]
        for key in ("dirty", "inventory", "roster", "root_argv"):
            need(a[key] == b[key], ("unmatched arms", phase, key))
        if "elf" in a:
            need(a["elf"] == b["elf"] and a["verdict"] == b["verdict"], ("different arm native outputs", phase))
    if suite == "e2e":
        for arm in records:
            need(records[arm]["new"]["verdict"]["count"] == records[arm]["old"]["verdict"]["count"] + 1, "wrong test delta")
    census.acquire.verify_sdk(sdk)
    need(all(sha(tools / name) == digest for name, digest in identities.items()) and registry(donor) == packages,
         "signed or measured contact inputs changed during the pilot")
    tol = {arm: {p: r["instructions"] for p, r in records[arm].items() if r["instructions"]} for arm in assignment["order"]}
    proof = {"qa": os.environ["GITHUB_SHA"], "assignment": assignment, "suite": suite, "physical": identities,
             "retired_user_instructions": tol, "original_over_guard_new": tol["original"]["new"] / tol["guard"]["new"],
             "native_hits_on_edit": records["guard"]["new"]["owner_guard_hits"], "acquired_sha256": sha(out / "acquired.json"),
             "verified_native_files": {a: records[a]["new"]["elf"] for a in records}}
    put(out / "verified.json", proof)
    print(json.dumps(proof), flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "install":
        source = Path(sys.argv[2]).resolve(strict=True)
        census.RUFF = study.NEW if sys.argv[3] == "option" else e2e.NEW
        need(census.git(source, "rev-parse", "HEAD") == census.RUFF, "wrong signed acquisition source")
        census.LOCK = sha(source / "Cargo.lock")
        census.install()
    else:
        main(Path(sys.argv[1]).resolve(), sys.argv[2], int(sys.argv[3]))
