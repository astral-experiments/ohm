"""Measure the enrolled compiler source on the held-out Ruff #27924 TOML parser edit."""

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit


QA = "f3f5ca9e62b41e2e1fb2bb79207c5d74bd881b5e"
ARM_FILE = Path(__file__).with_name("arms.json")
QA_LEDGER = Path(__file__).with_name("qa-sha256.json")
ARMS = json.loads(ARM_FILE.read_bytes())
if hashlib.sha256(ARM_FILE.read_bytes()).hexdigest() != "3ea3708565878bfc3dde928215952e6ebce886df489954ccb9590e100650a2fa":
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


def verify_argv(lines, flags, compiler, wrapper):
    from study import OWNER
    selected = [l for l in lines.splitlines() if "Running " in l and "--crate-name " + OWNER + " " in l]
    need(len(selected) == 1 and "-C opt-level=1" in selected[0], ("missing actual signed owner argv", selected))
    leaves = {flag for arm in ARMS.values() for flag in arm}
    for line in lines.splitlines():
        if "Running " in line and "--crate-name " in line:
            args = shlex.split(line.split("Running \x60",1)[1].removesuffix("\x60"))
            need([s for s in args if s in leaves] == (flags if line == selected[0] else []), ("wrong codegen flags", line))
            prefix = args[:args.index("--crate-name")]
            start = next((i for i, a in enumerate(prefix) if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", a)), None)
            need(start is not None and len(prefix) >= start + 2, ("missing compiler launcher", prefix))
            for actual, expected in zip(prefix[start:start + 2], (wrapper, compiler), strict=True):
                path = Path(actual)
                need(path.is_absolute() and path.is_file() and path.samefile(expected), ("wrong compiler launcher", actual, str(expected)))
    return selected[0]


def main(args):
    qa, src, original, scratch, out = (v.resolve() for v in
                                      (args.qa, args.source, args.original, args.scratch, args.results))
    need(original.name == "ohm-branch-object-qa", original)
    os.environ["RUNNER_TEMP"] = str(original.parent)
    need(sha(QA_LEDGER) == "08d8de7e0f13f5669dcdfd893dd96762211c5905acc8f6302f8184330e58959d", "changed pinned QA ledger")
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
    p.source_pair(src)
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
    import source_pass
    import toml_holdout as fixture
    from reader import members
    need(Path(sys.modules["reader"].__file__).resolve()==w.setup.CGU/"reader.py", "wrong archive member reader")
    verify_helpers(qa, ledger)
    this=sys.modules[__name__]
    src=args.toml_source.resolve(strict=True)
    need(all(not a.is_relative_to(b) and not b.is_relative_to(a) for a in (scratch,out) for b in (src,)),"overlapping holdout source")
    blobs=fixture.enroll(this,src,expected_registry)
    manifest = source_pass.validate(args.source_pass)
    need(Path(manifest["signed_rustc"]).samefile(w.SDK / "bin/rustc"), "wrong enrolled compiler")
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
    git(repo, "checkout", "--quiet", "--detach", fixture.OLD)
    fixture.source_state(this,repo,blobs,fixture.OLD,False,p.INVALID)
    shutil.copyfile(Path(__file__).with_name("toml-reader.rs"),here/"toml-reader.rs")
    bodies = out / "client-bodies"
    bodies.mkdir()
    archives = out / "archive-bodies"
    archives.mkdir()
    base_env = {**w.ENV, "CARGO_HOME": str(work / "cargo-home"), "CARGO_TARGET_DIR": str(work / "target"),
                "CARGO_BUILD_BUILD_DIR": str(work / "build")}
    for prog, commit in (("cargo", w.c.SDK["cargo"]), ("rustc", w.c.SDK["rust"])):
        actual = subprocess.check_output(["rustup", "which", "--toolchain", "ohm", prog], env=w.ENV, text=True).strip()
        version = subprocess.check_output([prog, "+ohm", "-vV"], env=w.ENV, text=True)
        need(Path(actual).samefile(w.SDK / "bin" / prog) and commit in version and "ohm-1.99.0-22" in version, prog)
    put(out / "identity.json", {"qa": QA, "old": fixture.OLD, "new": fixture.NEW, "counter": sha(clock), "lock":fixture.LOCK,
        "sdk_ledger": sdk_ledger, "source_common_dir": str(upstream), "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "driver": sha(Path(__file__)), "profiles": sha(ARM_FILE), "reader": sha(here/"toml-reader.rs"), "order": args.order,
        "study_mode": "signed-source-pass-toml", "fixture":sha(Path(fixture.__file__))})
    norm_graph = None
    observations = []
    # Each arm has an independently empty OLD history and a second independently empty clean NEW reference.
    for ix, arm in enumerate(args.order.split(",")):
        env, flags, compiler, identity = source_pass.select(manifest, arm, base_env)
        put(out / f"compiler-{arm}.json", identity)
        cli = p.CMD
        # The linked clients also use the original, physically attested signed SDK.
        home = scratch / ("consumer-rustup-" + arm)
        (home / "toolchains").mkdir(parents=True)
        (home / "toolchains/ohm").symlink_to(compiler.parent.parent, target_is_directory=True)
        client_env = {**env, "RUSTUP_HOME": str(home), "RUSTUP_AUTO_INSTALL": "0"}
        selected = subprocess.check_output(["rustup", "which", "--toolchain", "ohm", "rustc"], text=True, env=client_env)
        need(Path(selected.strip()).samefile(compiler), "downstream compiler differs from Cargo")
        for history, phases in (("edit", ("old", "new", "unchanged", "invalid", "repair")),
                                ("clean", ("clean-new","inspect-old","inspect-new"))):
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
                    inspected = phase in ("inspect-old","inspect-new")
                    env = source_pass.select(manifest, arm, base_env, inspected)[0]
                    native_before = source_pass.snapshot(env)
                    rev, bad = (fixture.OLD if phase in ("old","inspect-old") else fixture.NEW), phase == "invalid"
                    before=fixture.source_state(this,repo,blobs,rev,bad,p.INVALID,write=True)
                    dest = case / phase
                    # Only the separately empty reference is verbose. It cannot skip compiling the root.
                    cmd = [*cli, "-vv"] if phase == "clean-new" else cli
                    count = run(cmd, repo, env, dest, work, out, 101 if bad else 0,
                                clock=clock if history=="edit" else None)
                    native_evidence = source_pass.collect(env, native_before, arm, inspected)
                    put(dest/"native.json", native_evidence)
                    need(before==fixture.source_state(this,repo,blobs,rev,bad,p.INVALID),"source changed while Cargo ran")
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
                            put(dest / "actual-argv.json", verify_argv((dest / "outer.stderr").read_text(), flags, compiler, env["RUSTC_WRAPPER"]))
                        native=fixture.client(this,w,dest,rows,products,graph,here,work,client_env,rev,bodies)
                        ar = p.artifact(products, p.OWNER)
                        need(ar.is_file() and not ar.is_symlink() and 0<ar.stat().st_size<=512<<20,"unexpected library")
                        objects,metadata=members(ar.read_bytes(),p.OWNER)
                        results={"cargo":count,"unfresh":dirty,"consumer":native,"archive_bytes":ar.stat().st_size,
                                 "archive_sha256":sha(ar),"objects":objects,"metadata":metadata}
                        if phase in ("new", "clean-new"):
                            saved = w.physical.keep(ar, archives, b"!<arch>\n")
                            need(saved["sha256"] == results["archive_sha256"], "library changed during preservation")
                            results["original_archive"] = saved
                    else:
                        results = {"cargo": count, "error": "E0308"}
                    results["native"] = native_evidence
                    observations.append({"arm": arm, "history": history, "phase": phase, **results})
                    put(dest / "qualified.json", results)
                need(registry(home)==expected_registry, "changed registry inputs during history")
        need(source_pass.select(manifest, arm, base_env)[3] == identity, "changed compiler")
    need(w.acquire.verify_sdk(w.SDK) == extra and registry(original_cargo)==expected_registry, "changed SDK or registry")
    put(out / "observations.json", observations)
    put(out/"source-proof.json",source_pass.qualify(observations,("ruff_workspace",),require_skips=False))
    put(out/"accepted.json",fixture.qualify(this,observations,out))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("qa", "source", "original", "scratch", "results"):
        parser.add_argument("--" + name, type=Path, required=True)
    orders = ("signed,stock,strict", "strict,stock,signed")
    parser.add_argument("--order", required=True, choices=orders)
    parser.add_argument("--toml-source", type=Path, required=True)
    parser.add_argument("--source-pass", type=Path, required=True)
    main(parser.parse_args())
