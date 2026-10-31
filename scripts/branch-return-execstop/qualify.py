"""One plain empty reference and one independent kernel-observed Koff cold Ruff build."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
PILOT = HERE.parent / "branch-return-pmu"
if sys.argv[1:] == ["--preflight"]:
    os.environ.setdefault("RUNNER_TEMP", "/unused-cold-exec-qualification")
sys.path[:0] = [str(HERE), str(PILOT), str(HERE / "kernel")]
import images
from history import digest
import bindings as b
from bindings import need
import worker as old
import read_events

ARM = "Koff"
NEW_BRANCH = "charlie/qa-branch-return-execstop-20261031"
HISTORICAL = "f3b1c0113bc9b4b197ed3789a1480876c7575442"


def inputs():
    need(Path(read_events.__file__).resolve() == HERE / "kernel/read_events.py" and
         Path(old.__file__).resolve() == PILOT / "worker.py", "wrong isolated Python module resolution")
    need(old.ROOT == old.kit.ROOT == old.historical.ROOT == b.ROOT and old.kit.TREE == b.ROOT / "ruff" and
         old.WORK == old.kit.WORK == old.historical.WORK == b.WORK and old.OUT == old.kit.OUT == old.historical.OUT == b.OUT and
         old.BODIES == b.ROOT / "clean-reference-bodies" and old.BUNDLE == b.OUT / "native-bodies",
         "wrong historical acquisition, native reference or evidence location")
    for tag, path in (("8036cb549845a905ab83882f5b01766229e0e636", "scripts/branch-return-pmu"),
                      ("d9fd6c8e4152d468a3a40d600ee1c6ebda13e5f2", "scripts/ohm-packed-ruff")):
        need(b.git(HERE, "rev-parse", "HEAD:" + path) == tag, ("historical source tree changed", path))
    library = json.loads((PILOT / "historical-sources.json").read_bytes())
    need(all(b.sha(HERE.parents[1] / path) == value for path, value in library["files"].items()),
         "historical reader source changed")
    need(b.sha(HERE / "cold.json") == "d6f11fd5aba2558229813cedf8778f97ae3f9a6b4a264a7631aca661aedd9790",
         "original cold topology")
    return json.loads((HERE / "cold.json").read_bytes())


def tools(registry):
    paths = {"cargo": b.SDK / "bin/cargo", "rustc": b.SDK / "bin/rustc", "wild": b.SDK / b.WILD,
             "proxy": b.PROXIES / "rustup", "sysld": Path("/usr/bin/ld")}
    result = {role: {"path": str(p), "resolved": str(p.resolve(strict=True)),
                     "identity": [b.sha(p), *b.numbers(p)]} for role, p in paths.items()}
    for role in ("cargo", "rustc", "wild"):
        need(result[role]["identity"] == registry["K"][str(paths[role].relative_to(b.SDK))], ("changed SDK tool", role))
    return result


def observed(env, where, observer):
    ledger = where / "kernel.tsv"
    command = [str(observer), str(ledger), "--", *old.CARGO]
    with (where / "cargo.stdout").open("xb") as so, (where / "cargo.stderr").open("xb") as se:
        result = subprocess.run(command, cwd=old.kit.TREE, env=env, stdin=subprocess.DEVNULL,
                                stdout=so, stderr=se, timeout=9000)
    outputs = {}
    for key in ("stdout", "stderr"):
        raw = where / ("cargo." + key)
        outputs[key] = b.sha(raw)
        old.processes.compact(raw, where / ("cargo." + key + ".gz"))
    old.publish(where / "cargo.json.gz", {"argv": old.CARGO, "observer_argv": command,
                "cwd": str(old.kit.TREE), "env": env, "expected": 0, "exit": result.returncode,
                "stdin_sha256": hashlib.sha256(b"").hexdigest(),
                "stdout_sha256": outputs["stdout"], "stderr_sha256": outputs["stderr"]})
    need(result.returncode == 0, ("cold observed Cargo or observer failed", result.returncode))
    messages = [json.loads(l) for l in gzip.decompress((where / "cargo.stdout.gz").read_bytes()).splitlines()]
    need(messages[-1] == {"reason": "build-finished", "success": True}
         and all(m["message"]["level"] != "error" for m in messages if m["reason"] == "compiler-message"),
         "Cargo did not return a successful clean build with clean diagnostics")
    return messages


def compare(where, native, messages, env, ref, expected):
    rows, dirty = old.historical.roster(messages)
    old.publish(where / "roster.json.gz", {"members": rows, "dirty": dirty})
    need(len(rows) == 375 and rows == dirty == ref["typed"] and digest(rows) == expected["typed"],
         "cold Cargo graph or dirty roster differs from independent empty")
    need(len(native["cargos"]) == 1 and native["cargos"][0]["argv"][1:] == old.CARGO[2:], "wrong physical Cargo CLI")
    need(not old.failed_session.observed(b.WORK), "open working session after completed build")
    disk = old.disk.allocated(b.WORK / "target", b.WORK / "build", where)
    need(min(disk["roots"].values()) > 0 and disk["all_inodes"] > 1000 and disk["packed_files"] == 0,
         "incorrect off/cold output allocation")
    old.processes.sessions(where, native, b.WORK)
    found, files = old.native.observed(messages, "A", old.kit.REVS["A"], env, b.ROOT, old.kit.TREE, b.WORK, where)
    namespace = old.historical.stable_sdk.output_directory(messages, "tikv-jemalloc-sys")
    need(namespace == ref["jemalloc"] and old.same_products(found, ref["products"]),
         "changed typed reader, CLI verdict, or Cargo context")
    for name, path in files.items():
        old.native.same_file(path, found[name], ref["products"][name], old.BODIES, where)
    old.settled_link.collect(where, "cold-A", native, messages, files["cli"])
    linked, = [r for r in native["wild_processes"] if Path(r["output"]).name == "ruff"]
    bin_path = Path(linked["output"])
    need(linked["rustc_crate"] == "ruff" and bin_path.samefile(files["cli"])
         and bin_path == bin_path.resolve(strict=True) and files["cli"] == b.WORK / "target/debug/ruff",
         "registered Wild output does not own the actual Cargo CLI")
    visit = {"arm": ARM, "phase": "cold-A", "branch": "A", "source": old.kit.REVS["A"], "instructions": None,
             "allocated": disk["allocated"], "status": 0, "artifact_count": len(rows), "dirty": len(dirty),
             "dirty_digest": digest(dirty), "graph": digest(rows), "cli": found["cli"]["whole"],
             "reader": found["reader"]["whole"], "native_output": namespace}
    clean = json.loads((b.OUT / "clean/cold-A/visit.json").read_bytes())
    need(dict(visit, allocated=None) == dict(clean, allocated=None), "native visit differs from the full independent reference")
    b.save(where / "visit.json", visit)
    return {"typed": len(rows), "typed_sha256": digest(rows), "full_rustcs": len(native["rustcs"]),
            "wild_links": native["wild"], "system_links": len(native["other_linkers"]),
            "native": {k: found[k]["whole"] for k in files}, "cli_link": linked["event"],
            "cli_linked_file": str(bin_path), "cli_returned_file": str(files["cli"]),
            "cli_file_identity": b.numbers(files["cli"]), "namespace": namespace, "allocated": disk["allocated"]}


def main(source, observer, fixture_result):
    expected = inputs()
    need(os.environ["GITHUB_REPOSITORY"] == b.REPO and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
         and os.environ["GITHUB_REF"] == "refs/heads/" + NEW_BRANCH
         and os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"] == b.git(HERE, "rev-parse", "HEAD"),
         "unexpected qualification run")
    need(b.ROOT.resolve() == b.ROOT and (b.WORK / ".owned-by-packed-study").read_text() == str(b.ROOT)
         and shutil.disk_usage(b.OUT).free >= 32 * 2**30, "task-owned volume and reserve")
    fixture = json.loads(fixture_result.read_bytes())
    need(fixture["qualified"] is True and fixture["observer_sha256"] == b.sha(observer), "native fixtures must use this observer")
    available = sorted(os.sched_getaffinity(0))
    need(len(available) >= 8, "fewer than eight available CPUs")
    os.sched_setaffinity(0, available[:8])
    need(sorted(os.sched_getaffinity(0)) == available[:8], "different historical child affinity")
    b.save(b.OUT / "enrollment.json", {"run": int(os.environ["GITHUB_RUN_ID"]), "attempt": 1, "head": os.environ["GITHUB_SHA"],
            "runner": os.environ.get("RUNNER_NAME"), "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "original_head": HISTORICAL, "source": b.spec(), "arm": ARM, "command": old.CARGO, "counter": None,
            "available_cpus": available, "process_cpus": available[:8]})
    reg = b.acquire(source)
    initial = b.OUT / "initial"
    initial.mkdir()
    env = b.activate(ARM, reg, initial)
    b.fresh_outputs()
    b.prepare_inputs(old.kit, env)
    old.historical.calibration()

    refs = {}
    clean = b.OUT / "clean"
    clean.mkdir()
    env = b.activate(ARM, reg, clean)
    b.fresh_outputs()
    old.receipt(ARM, "cold-A", "A", "clean", env, clean / "cold-A", refs)
    need(refs[ARM, "A"]["graph"] == expected["typed"], "wrong independent empty graph")

    base = b.OUT / "observed"
    base.mkdir()
    same_env = b.activate(ARM, reg, base)
    need(same_env == env, "different observable environment")
    b.fresh_outputs()
    where = base / "cold-A"
    where.mkdir()
    old.checked_source("cold-A", "A", where)
    need((where / "source.json").read_bytes() == (clean / "cold-A/source.json").read_bytes(), "different Ruff reference source")
    catalog = tools(reg)
    b.save(base / "catalog.json", catalog)
    try:
        messages = observed(env, where, observer)
        ledger = where / "kernel.tsv"
        closed = read_events.read(ledger, expected_code=0)
        lifecycle = {k: len(v) if isinstance(v, list) else v for k, v in closed.items()}
        b.save(where / "lifecycle.json", lifecycle)
        native = images.inventory(ledger, closed, catalog, expected, old.processes.other_link)
        old.publish(where / "native-execs.json.gz", native)
        need(native["successful_exec_count"] == expected["successful_execs"],
             ("different cold successful executable count", native["successful_exec_count"], expected["successful_execs"]))
        result = compare(where, native, messages, env, refs[ARM, "A"], expected)
        result.update({"ledger_sha256": b.sha(ledger), "observer_sha256": b.sha(observer), "host_complete": True})
    finally:
        if (where / "kernel.tsv").exists():
            old.processes.compact(where / "kernel.tsv", where / "kernel.tsv.gz")
    need(tools(reg) == catalog, "selected executable identity changed")
    for role in reg:
        b.verify_physical(b.SDK if role == "K" else b.PARK / role, reg[role])
    need({p.name: b.sha(p) for p in (b.HOME / ".cargo/registry/cache").glob("*/*.crate")} ==
         json.loads((b.OUT / "ruff-inputs.json").read_bytes())["archives"], "changed locked dependencies")
    b.save(b.OUT / "complete.json", result)


if __name__ == "__main__":
    if sys.argv[1:] == ["--preflight"]:
        frozen = inputs()
        print(json.dumps({"reader": read_events.__file__, "pilot": old.__file__, "tree": str(old.kit.TREE),
                          "body_dir": str(old.BODIES), "artifact_dir": str(old.BUNDLE), "source": b.spec()["manifest"],
                          "expected_typed": frozen["typed"], "expected_successful_execs": frozen["successful_execs"]}))
        sys.exit(0)
    try:
        main(*map(Path, sys.argv[1:]))
    except BaseException:
        (b.OUT / "refusal.txt").write_text(traceback.format_exc())
        raise
