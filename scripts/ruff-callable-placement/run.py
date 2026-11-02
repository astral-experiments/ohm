"""Run one held-out ordinary test build on the same two physically verified source compilers."""

from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import native
from verify_source import verify
from callable_decision import decide


def git(repo, *args):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", repo, *args])


def head(repo, revision="HEAD"):
    return git(repo, "rev-parse", revision).strip().decode()


def enroll(reader, fixture):
    plan = json.loads((HERE / "registration.json").read_bytes())
    binding = json.loads((HERE / "reader.json").read_bytes())
    assert __debug__ and os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
    assert os.environ["GITHUB_REF"] == "refs/heads/charlie/qa-ruff-db-link-cause-20261102"
    assert os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch" and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
    assert head(HERE) == os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"]
    assert head(reader) == binding["revision"]
    assert native.sha(HERE / "registration.json") == binding["initial_registration_sha256"]
    verify(fixture, plan)
    assert head(fixture) == plan["source"]["new"]
    placement = reader / "scripts/ruff-source-placement"
    assert native.sha(placement / "receiver.py") == binding["receiver_sha256"]
    sys.path.insert(0, str(placement))
    import common
    import receiver
    spec = importlib.util.spec_from_file_location("callable_placement_worker", placement / "worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    reg = common.source_binding()
    assert [reg["roles"][k]["revision"] for k in ("P", "C")] == [plan["compiler_parent"], plan["compiler_candidate"]]
    inherited = json.loads((placement / "protocol.json").read_bytes())["inherited_trees"]
    assert all(head(reader, "HEAD:scripts/" + path) == tree for path, tree in inherited.items())
    assert native.sha(placement / "candidate.bundle") == reg["bundle"]["sha256"]
    common.capsule.HERE, common.capsule.REG = placement, reg
    return plan, binding, reg, receiver, worker


def unit_graph(cmd, env, repo, folder):
    data = subprocess.check_output([*cmd[:2], "-Zunstable-options", *cmd[2:], "--unit-graph"], env=env, cwd=repo)
    (folder / "unit-graph.json").write_bytes(data)
    graph = json.loads(data)
    units = graph["units"]
    root, = graph["roots"]
    assert graph["version"] == 1 and units[root]["target"]["name"] == "e2e"
    producer = [u for u in units if u["target"]["name"] == "ty_python_semantic" and u["mode"] == "build"]
    assert producer and all(u["profile"]["opt_level"] == "1" for u in producer)
    assert all(not u["profile"].get("rustflags") for u in units)
    return hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()


def one_role(kit, worker, root, out, repo, donor, plan, role):
    work, store = root / "work", out / "native-witnesses"
    kit.select(role)
    env = {**kit.base, "CARGO_HOME": str(work/"cargo-home"), "CARGO_TARGET_DIR": str(work/"target"),
           "CARGO_BUILD_BUILD_DIR": str(work/"build")}
    worker.runtime.clean(env)
    src = plan["source"]
    typed, test_src = repo/src["path"], repo/"crates/ty_server/tests/e2e/signature_help.rs"
    source_bytes = {v: git(repo, "show", f"{src[v]}:{src['path']}") for v in ("old", "new")}
    test_bytes = test_src.read_bytes()
    needle = b"    let workspace_root = SystemPath::new(\"src\");"
    assert test_bytes.count(needle) == 1
    negative_test = test_bytes.replace(needle, b'    assert!(std::hint::black_box(false), "OHM_28277_RUNTIME_CHANGED");\n' + needle)
    cmd = plan["build_argv"]
    check_cmd = ["cargo", "+ohm", "check", "-p", "ty_server", "--test", "e2e", "--locked", "--offline", "-j4"]
    observations, retained = {}, set()
    graph = None
    for history, phases in (("edit", ("empty_old", "edit", "unchanged", "invalid", "repair")),
                            ("clean", ("empty_new", "return_old", "score_new", "negative", "restored"))):
        folder = out / f"{role}-{history}"
        folder.mkdir()
        with worker.replay.empty_roots(work, folder):
            home = work / "cargo-home"
            (home / "registry").mkdir()
            for part in ("index", "cache"):
                subprocess.run(["cp", "-a", "--reflink=auto", donor/"registry"/part, home/"registry"/part], check=True)
            subprocess.run(["cargo", "+ohm", "fetch", "--locked", "--offline"], cwd=repo, env=env, check=True)
            fresh_graph = unit_graph(cmd, env, repo, folder)
            assert graph is None or graph == fresh_graph
            graph = fresh_graph
            for label in phases:
                if label == "score_new" and role == "C" and not retained:
                    # Still visit this exact source to prime the independent runtime negative control.
                    print("No admitted C2 object on the registered edit", flush=True)
                version = "old" if label in ("empty_old", "return_old") else "new"
                if head(repo) != src[version]:
                    git(repo, "checkout", "--quiet", "--detach", src[version])
                file_bytes = source_bytes[version]
                if label == "invalid":
                    file_bytes += b'\ncompile_error!("OHM_28277_INVALID_SOURCE");\n'
                if typed.read_bytes() != file_bytes:
                    typed.write_bytes(file_bytes)
                behavior = negative_test if label == "negative" else test_bytes
                if test_src.read_bytes() != behavior:
                    test_src.write_bytes(behavior)
                assert head(repo, "HEAD^{tree}") == src[version+"_tree"]
                phase = folder / label
                cold = label in ("empty_old", "empty_new")
                score = label == "score_new"
                observed = label in ("edit", "return_old")
                # The warm counter covers Cargo and its descendants. The syscall and
                # debugger observations that qualify the mechanism run on separate visits.
                with ExitStack() as stack:
                    if not score:
                        if cold or observed:
                            stack.enter_context(worker.placement_peak.observe(worker.guards, phase, kit,
                                owners={"ty_python_semantic", "ty_server", "e2e"}))
                        if observed:
                            stack.enter_context(worker.tracking.add_file_calls(worker.guards, phase))
                    rusts, actual, roster, _, pmu, _ = worker.runtime.visit(
                        kit, phase, work, repo, env, check_cmd if label == "invalid" else cmd,
                        101 if label == "invalid" else 0, score=score, cold=cold, observe=observed)
                assert typed.read_bytes() == file_bytes and test_src.read_bytes() == behavior
                result = {"graph": graph, "commit": head(repo), "source": native.sha(typed), "calls": actual,
                          "kernel": native.sha(phase/"kernel.json"), "pmu_file": pmu}
                if observed:
                    selection = worker.tracking.read(phase, kit.sdk)
                    native.emit(phase/"selection.json", selection)
                    admitted = {Path(row["destination"]).name for row in selection["renames"]}
                    if role == "P":
                        assert not admitted
                    if label == "edit":
                        retained.update(admitted)
                    result["admitted"] = sorted(admitted)
                if cold or label == "edit":
                    disk = worker.storage.census(work, phase, out/"workproduct-indices")
                    native.emit(phase/"storage.json", disk)
                    result["placement_bytes"] = disk["optional_tail_bytes"]
                    if role == "P":
                        assert result["placement_bytes"] == 0
                    native.emit(phase/"objects.json", native.archive_objects(phase, rusts, retained, store))
                if label == "invalid":
                    assert b"OHM_28277_INVALID_SOURCE" in (phase/"outer.stderr").read_bytes()
                else:
                    binary = native.root_program(phase, repo, work)
                    result["verdict"] = native.verdict(binary, repo, env, phase, plan["named_test"], label == "negative")
                    if cold or label in ("edit", "return_old"):
                        result["sites"] = native.debug_sites(binary, src["path"], plan["source_sites"],
                                                          int(version == "new"), env, phase)
                observations[label] = result
                native.emit(phase/"case.json", result)
                print(role, label, actual, "admitted", len(result.get("admitted", [])), flush=True)
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == b""
    return observations


def run(reader, repo):
    plan, binding, reg, receiver, worker = enroll(reader, repo)
    scratch = Path(os.environ["RUNNER_TEMP"]) / "ohm-callable-placement"
    scratch.mkdir()
    out, root = scratch/"evidence", scratch/"trial"
    out.mkdir(); root.mkdir()
    block = int(os.environ.get("PAIR_BLOCK", "0"))
    order, expected = ["P", "C"], []
    if block:
        import replication
        order, expected = replication.qualify(receiver.api, scratch, block)
    for folder in (out/"workproduct-indices", out/"native-witnesses", root/"work"):
        folder.mkdir()
    inputs = scratch/"sdks"
    receiver.install(inputs, registration=reg)
    cpus, kit = worker.setup(root, out, inputs)
    for name in ("source-qualification.json", "docs-qualification.json"):
        shutil.copyfile(inputs / name, out / name)
    native.emit(out/"entry.json", {"reader": binding, "run": os.environ["GITHUB_RUN_ID"], "qa": head(HERE),
        "cpu": cpus, "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(), "source": reg["roles"],
        "plan": native.sha(HERE/"registration.json"), "order": order, "block": block})
    donor = root/"registry-donor"
    donor.mkdir()
    subprocess.run(["cargo", "+ohm", "fetch", "--locked"], cwd=repo, env={**kit.base, "CARGO_HOME":str(donor)}, check=True)
    locked = {p["name"]+"-"+p["version"]+".crate":p["checksum"] for p in tomllib.loads((repo/"Cargo.lock").read_text())["package"] if "checksum" in p}
    assert worker.pilot.registry(donor) == locked
    native.emit(out/"registry.json", locked)
    reports = {role: one_role(kit, worker, root, out, repo, donor, plan, role) for role in order}
    kit.finish()
    native.emit(out/"histories.json", reports)
    decision = decide(out, reports)
    native.emit(out/"decision.json", decision)
    if block:
        replication.finish(out, reports, decision, block, order, expected)


if __name__ == "__main__":
    if len(sys.argv) != 3 or not __debug__:
        raise SystemExit("usage: run.py PINNED_READER RUFF_CHECKOUT")
    run(*(Path(p).resolve(strict=True) for p in sys.argv[1:]))
