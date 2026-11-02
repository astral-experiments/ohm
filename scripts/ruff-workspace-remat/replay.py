"""Measure a real signed Cargo under two root-only LLVM pipelines on Ruff #28106."""

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit


QA = "f3f5ca9e62b41e2e1fb2bb79207c5d74bd881b5e"
ARM_FILE = Path(__file__).with_name("arms.json")
QA_LEDGER = Path(__file__).with_name("qa-sha256.json")
ARMS = json.loads(ARM_FILE.read_bytes())
if hashlib.sha256(ARM_FILE.read_bytes()).hexdigest() != "bfc3331eb56eebd635a73049bafefe7a6cd840b7cba7bc508bc2de617a8ed36c":
    raise ValueError("changed comparison profiles")


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def need(ok, what):
    if not ok:
        raise ValueError(what)


def read(path):
    return json.loads(path.read_bytes())


def put(path, obj):
    with path.open("x") as f:
        print(json.dumps(obj, sort_keys=True), file=f)


def git(repo, *args):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", repo, *args])


def verify_helpers(qa, ledger):
    for mod in list(sys.modules.values()):
        path = getattr(mod, "__file__", None)
        if path and Path(path).resolve().is_relative_to(qa / "scripts"):
            src = Path(path).resolve()
            need(ledger.get(str(src.relative_to(qa))) == sha(src), ("changed or unregistered helper", src))


def verified_clock(path, exit_code):
    row = read(path)
    need(row["code"] == exit_code and row["event_errno"] == 0 and row["instructions"] > 0
         and row["enabled"] == row["running"] > 0, ("invalid or multiplexed instruction counter", row))
    return row["instructions"]


def run(cmd, cwd, env, folder, work, out, exit_code=0, clock=None):
    from guards import run as guarded
    folder.mkdir()
    argv = [str(x) for x in cmd]
    if clock:
        argv = [str(clock), str(folder / "clock.json"), *argv]
    put(folder / "invocation.json", {"cwd": str(cwd), "argv": argv, "env": env})
    status = guarded(argv, cwd, env, folder, work, out)
    need(status == exit_code, (folder, status, (folder / "outer.stderr").read_bytes()[-2400:]))
    return verified_clock(folder / "clock.json", exit_code) if clock else None


@contextmanager
def empty_roots(work, out):
    ids = {}
    try:
        for name in ("build", "target", "cargo-home"):
            path = work / name
            path.mkdir()
            ids[path] = (path.stat().st_dev, path.stat().st_ino)
        put(out / "empty-roots.json", {str(path): value for path, value in ids.items() if not any(path.iterdir())})
        yield
    finally:
        for path, value in ids.items():
            need(not path.is_symlink() and (path.stat().st_dev, path.stat().st_ino) == value,
                 ("refusing changed private output root", path))
            shutil.rmtree(path)


def unit_graph(cli, repo, env, case, work, out, flags):
    import worker
    graph_cmd = [*cli[:2], "-Zunstable-options", *cli[2:], "--unit-graph"]
    run(graph_cmd, repo, env, case / "graph", work, out)
    graph = read(case / "graph/outer.stdout")
    expected = worker.graph_units(graph)
    root, = graph["roots"]
    profile = graph["units"][root]["profile"]
    need(profile["opt_level"] == "1" and profile.get("rustflags", []) == flags, ("Ruff root profile", profile))
    for index, unit in enumerate(graph["units"]):
        if index != root:
            need(not unit["profile"].get("rustflags"), ("treated dependency", unit))
    profile.pop("rustflags", None)
    return expected, graph


def cargo_rows(raw, graph=None):
    """Read Cargo JSON, accepting package-prefixed build-script output only in a verbose run."""
    script_prefixes = set()
    if graph is not None:
        for unit in graph["units"]:
            if unit["target"]["kind"] != ["custom-build"]:
                continue
            location, spec = unit["pkg_id"].rsplit("#", 1)
            name, sep, version = spec.partition("@")
            if not sep:
                name, version = unquote(urlsplit(location).path.rsplit("/", 1)[-1]), spec
            script_prefixes.add(f"[{name} {version}] ".encode())
    records = []
    for line in raw.splitlines():
        if line.startswith(b"["):
            prefix, sep, _ = line.partition(b"] ")
            if sep and prefix + sep in script_prefixes:
                continue
        record = json.loads(line)
        need(isinstance(record, dict) and isinstance(record.get("reason"), str), "invalid Cargo JSON message")
        records.append(record)
    return records


def verify_argv(lines, flags, compiler=None):
    from study import OWNER
    selected = [l for l in lines.splitlines() if "Running " in l and "--crate-name " + OWNER + " " in l]
    need(len(selected) == 1 and "-C opt-level=1" in selected[0], ("missing actual signed owner argv", selected))
    leaves = {flag for arm in ARMS.values() for flag in arm}
    for line in lines.splitlines():
        if "Running " in line and "--crate-name " in line:
            args = shlex.split(line.split("Running \x60",1)[1].removesuffix("\x60"))
            need([s for s in args if s in leaves] == (flags if line == selected[0] else []), ("wrong codegen flags", line))
            if compiler is not None:
                position = args.index("--crate-name")
                need(position > 0 and Path(args[position - 1]).samefile(compiler), ("wrong compiler", args[:position]))
    return selected[0]


def runtime(here, work, env, phase, batch, clock, gold):
    """Measure client startup and a populated metadata/read/format loop independently."""
    import study as p
    output = phase / "runtime"
    output.mkdir()
    src = here / "measure-client.rs"
    binary = here / "measure-client"
    binary.unlink(missing_ok=True)
    cmd = read(phase / "client/compile.json")["argv"]
    need(cmd[:2] == ["rustc", "+ohm"] and Path(cmd[2]) == here / "option-client.rs"
         and cmd[-2:] == ["-o", str(here / "option-client")], ("consumer compiler", cmd))
    cmd[2] = str(src)
    cmd[-1] = str(binary)
    cmd.extend(["-Copt-level=1"])
    run(cmd, here, env, output / "compile", work, batch)
    rows = []
    # Pass option names at run time. The signed driver is identical in both arms.
    keys = (p.KEY, p.SIBLING, p.MISSING)
    for i, n in enumerate((0, 128, 1024, 1024, 128, 0)):
        q = output / str(i)
        count = run([binary, str(n), *keys], here, env, q, work, batch, clock=clock)
        digest = 14695981039346656037
        for _ in range(n):
            for key in keys:
                for byte in gold.get(key, b"\xff"):
                    digest = ((digest ^ byte) * 1099511628211) & ((1 << 64) - 1)
        need((q / "outer.stdout").read_text() == f"{digest:016x}\n" and not (q / "outer.stderr").stat().st_size,
             ("wrong measured runtime result", q))
        rows.append([n, count, f"{digest:016x}"])
    return {"counts": rows, "bytes": binary.stat().st_size, "sha256": sha(binary)}


def main(args):
    qa, src, original, scratch, out = (v.resolve() for v in
                                      (args.qa, args.source, args.original, args.scratch, args.results))
    need(original.name == "ohm-branch-object-qa", original)
    os.environ["RUNNER_TEMP"] = str(original.parent)
    need(sha(QA_LEDGER) == "f06a602f6520bd74935fd4e09e523cef18ff9b7810bb20c9818a25a5f8751969", "changed pinned QA ledger")
    ledger = read(QA_LEDGER)
    for file, expected in ledger.items():
        need(sha(qa/file) == expected, ("changed frozen QA input", file))
    sys.path[:0] = [str(qa / "scripts/ruff-workspace-option-edit"), str(qa / "scripts/ruff-repair-tables-pilot")]
    import guards
    import worker as w
    p = w.p
    verify_helpers(qa, ledger)
    need(not out.exists() and not scratch.exists()
         and not any(a.is_relative_to(b) for a, b in ((out, scratch), (scratch, out), (out, original),
                                                         (scratch, original), (scratch, src), (out, src), (scratch, qa), (out, qa))),
         "use separate new scratch and results directories outside all reference trees")
    gold = p.source_pair(src)
    logs = original / "logs"
    need(read(logs/"accepted.json")["new_compiler_treatments"] == 0
         and read(logs/"enrollment.json")["boot"] == Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
         "original receiver result must belong to this boot")
    cpus = read(logs/"cpus.json")
    need(len(cpus)==4 and len({tuple(key) for key,_ in cpus})==4, "original four physical cores")
    for (pkg, core), cpu in cpus:
        topo = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        need(cpu in os.sched_getaffinity(0) and [pkg,core]==[int((topo/k).read_text()) for k in ("physical_package_id","core_id")], "CPU custody")
    os.sched_setaffinity(0, [cpu for _,cpu in cpus])
    extra = w.acquire.verify_sdk(w.SDK)
    need(w.ROOT == original and extra == read(logs / "sdk.json"), "signed SDK")
    need(read(logs / "environment.json") == w.ENV, "reference env does not describe this host")
    def registry(home):
        registry = home / "registry/cache"
        actual = {}
        for crate in registry.glob("*/*.crate"):
            need(not crate.is_symlink() and crate.name not in actual, ("foreign registry file",crate))
            actual[crate.name] = sha(crate)
        return actual
    expected_registry = read(logs/"registry.json")
    original_cargo = Path(w.ENV["CARGO_HOME"])
    need(registry(original_cargo) == expected_registry, "original cargo registry custody")
    sdk_ledger = hashlib.sha256(json.dumps(extra, sort_keys=True).encode()).hexdigest()
    clock = logs / "counter-programs/plain"
    # Reuse the exact original worker-built and calibrated executable, and assert functioning PMU again below.
    need(clock.is_file() and any(sha(q) == sha(clock) for q in (original / "counter-kit").rglob("plain")),
         "counter is not identical to original executable")
    guards.admit(guards.resources(scratch.parent, out.parent), entry=True, bootstrap=True)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import e2e
    if args.suite == "e2e":
        need(args.e2e_source is not None, "missing test fixture checkout")
        return e2e.run(sys.modules[__name__], args, w, registry, expected_registry, original_cargo, clock)
    manifest = e2e.compiler_manifest(sys.modules[__name__], args.e2e_rustcs)
    scratch.mkdir()
    out.mkdir()
    here = scratch / "helper"
    work = scratch / "work"
    here.mkdir()
    work.mkdir()
    repo = scratch / "ruff"
    # Private object alternate (local read-only source object access), independent worktree and ref store.
    upstream = Path(git(src, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip())
    subprocess.run(["git", "init", "-q", repo], check=True)
    (repo / ".git/objects/info/alternates").write_text(str(upstream / "objects") + "\n")
    git(repo, "checkout", "--quiet", "--detach", p.OLD)
    p.source_state(repo, p.OLD, False)
    for target, payload in (("option-client.rs", (w.HERE / "client.rs").read_bytes()), ("bad-option-client.rs", p.BAD_CLIENT),
                            ("measure-client.rs", Path(__file__).with_name("measure-client.rs").read_bytes())):
        (here / target).write_bytes(payload)
    bodies = out / "client-bodies"
    bodies.mkdir()
    base_env = {**w.ENV, "CARGO_HOME": str(work / "cargo-home"), "CARGO_TARGET_DIR": str(work / "target"),
                "CARGO_BUILD_BUILD_DIR": str(work / "build")}
    conf = scratch / "profile.toml"
    for prog, commit in (("cargo", w.c.SDK["cargo"]), ("rustc", w.c.SDK["rust"])):
        actual = subprocess.check_output(["rustup", "which", "--toolchain", "ohm", prog], env=w.ENV, text=True).strip()
        version = subprocess.check_output([prog, "+ohm", "-vV"], env=w.ENV, text=True)
        need(Path(actual).samefile(w.SDK / "bin" / prog) and commit in version and "ohm-1.99.0-22" in version, prog)
    put(out / "identity.json", {"qa": QA, "old": p.OLD, "new": p.NEW, "counter": sha(clock),
        "sdk_ledger": sdk_ledger, "source_common_dir": str(upstream), "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "driver": sha(Path(__file__)), "profiles": sha(ARM_FILE), "reader": sha(here / "measure-client.rs"), "order": args.order,
        "study_mode": "matched-rustc" if manifest else "signed-profile-control"})
    norm_graph = None
    observations = []
    # Each arm has an independently empty OLD history and a second independently empty clean NEW reference.
    for ix, arm in enumerate(args.order.split(",")):
        env, flags, compiler, identity = e2e.compiler_arm(sys.modules[__name__], w, manifest, arm, base_env)
        put(out / f"compiler-{arm}.json", identity)
        cli = p.CMD
        client_env = env
        if compiler is None:
            conf.write_text("[profile.dev.package.ruff_workspace]\nrustflags = " + json.dumps(flags) + "\n")
            cli = [*p.CMD[:2], "-Zprofile-rustflags", "--config", str(conf), *p.CMD[2:]]
        else:
            # Run the registered downstream rustc commands against the same compiler and sysroot as Cargo.
            home = scratch / ("consumer-rustup-" + arm)
            (home / "toolchains").mkdir(parents=True)
            (home / "toolchains/ohm").symlink_to(compiler.parent.parent, target_is_directory=True)
            client_env = {**env, "RUSTUP_HOME": str(home), "RUSTUP_AUTO_INSTALL": "0"}
            selected = subprocess.check_output(["rustup", "which", "--toolchain", "ohm", "rustc"], text=True, env=client_env)
            need(Path(selected.strip()).samefile(compiler), "downstream compiler differs from Cargo")
        for history, phases in (("edit", ("old", "new", "unchanged", "invalid", "repair")),
                                ("clean", ("clean-new",))):
            case = out / f"{ix}-{arm}-{history}"
            case.mkdir()
            with empty_roots(work, case):
                # Each independent history starts without Cargo freshness, trust, inventory or compiler state.
                # Only the original index and authenticated crate archives are copied to the same private path.
                home = work / "cargo-home"
                (home/"registry").mkdir()
                for kind in ("index", "cache"):
                    run(["cp", "-a", "--reflink=auto", original_cargo/"registry"/kind, home/"registry"/kind],
                        here, env, case/("prepare-"+kind), work, out)
                for fname in ("config","config.toml"):
                    if (original_cargo/fname).exists():
                        shutil.copy2(original_cargo/fname, home/fname)
                run(["cargo","+ohm","fetch","--locked","--offline"],repo,env,case/"offline-fetch",work,out)
                need(registry(home)==expected_registry, "changed registry input at history start")
                expected, graph = unit_graph(cli, repo, env, case, work, out, flags)
                if norm_graph is None:
                    norm_graph = graph
                need(norm_graph == graph, "unit graph changed beyond owner flags")
                for phase in phases:
                    rev, bad = (p.OLD if phase == "old" else p.NEW), phase == "invalid"
                    before = p.write_source(repo, rev, bad)
                    dest = case / phase
                    # Only the separately empty reference is verbose. It cannot skip compiling the root.
                    cmd = [*cli, "-vv"] if phase == "clean-new" else cli
                    count = run(cmd, repo, env, dest, work, out, 101 if bad else 0,
                                clock=None if phase == "clean-new" else clock)
                    need(before == p.source_state(repo, rev, bad), "source changed while Cargo ran")
                    put(dest / "source.json", before)
                    rows = cargo_rows((dest / "outer.stdout").read_bytes(), graph if phase == "clean-new" else None)
                    products = p.results(rows, not bad)
                    w.ownership.check_roots(rows, work)
                    if not bad:
                        actual = Counter(w.graph_key(r["package_id"], r["target"], r["features"]) for r in products)
                        need(actual == expected, "incomplete or unexpected Cargo artifact inventory")
                        dirty = sorted(r["target"]["name"] for r in products if not r["fresh"])
                        if phase in ("old", "clean-new"):
                            need(all(not r["fresh"] for r in products), "false clean reference")
                        if phase == "new":
                            need(p.OWNER in dirty, ("changed source did not rebuild its owner", dirty))
                        if phase == "clean-new":
                            put(dest / "actual-argv.json", verify_argv((dest / "outer.stderr").read_text(), flags, compiler))
                        native = w.native.client(dest, rows, products, here, work, client_env, gold[rev], bodies)
                        ar = p.artifact(products, p.OWNER)
                        dyn = runtime(here, work, client_env, dest, out, clock, gold[rev]) if phase in ("new","clean-new") else None
                        results = {"cargo": count, "unfresh": dirty, "consumer": native, "archive_bytes": ar.stat().st_size,
                                   "archive_sha256": sha(ar), "runtime": dyn, "output_sha256": p.EXPECTED[rev]}
                    else:
                        results = {"cargo": count, "error": "E0308"}
                    observations.append({"arm": arm, "history": history, "phase": phase, **results})
                    put(dest / "qualified.json", results)
                need(registry(home)==expected_registry, "changed registry inputs during history")
        need(e2e.compiler_arm(sys.modules[__name__], w, manifest, arm, base_env)[3] == identity, "changed compiler")
    need(w.acquire.verify_sdk(w.SDK) == extra and registry(original_cargo)==expected_registry, "changed SDK or registry")
    put(out / "observations.json", observations)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("qa", "source", "original", "scratch", "results"):
        parser.add_argument("--" + name, type=Path, required=True)
    orders = [f"{a},{b}" for a in ARMS for b in ARMS if a != b and "normal" in (a,b)]
    parser.add_argument("--order", required=True, choices=orders)
    parser.add_argument("--suite", choices=["build", "e2e"], default="build")
    parser.add_argument("--e2e-source", type=Path)
    parser.add_argument("--matched-rustcs", type=Path, dest="e2e_rustcs")
    main(parser.parse_args())
