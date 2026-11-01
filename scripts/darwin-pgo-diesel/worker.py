"""Capture the failed live collector, freeze its instrumented native SDK, then replay."""

import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from escrow import GIB, facts, free_guard, keep_graphs, pack, safe_for_clone
from identity import (
    CARGO,
    ERROR,
    HEALTHY_A,
    HERE,
    HOST,
    PATCHED_B,
    PERF,
    PERF_DIESEL,
    Q,
    RUST,
    diagnosis,
    extra,
    host_sources,
    need,
    sha,
    text,
    trace,
    write,
)
from supervise import finished


def load(p):
    return json.loads(p.read_bytes())


def check_paths(cwd, inc, args, tmp):
    need(
        cwd.is_dir()
        and cwd.resolve().parent == tmp.resolve()
        and inc.resolve() == cwd.resolve() / "incremental-state"
        and not inc.is_symlink(),
        "timing directory points outside the original Darwin TMPDIR",
    )
    out = Path(extra(args, "--out-dir"))
    need(out.is_dir() and out.resolve().is_relative_to(cwd.resolve()), "compiler output outside captured root")
    for offset, a in enumerate(args):
        if a == "--extern":
            _, _, p = args[offset + 1].partition("=")
            provider = Path(p)
            need(
                provider.is_file() and provider.resolve().is_relative_to(cwd.resolve()),
                "external rlib not in captured workspace",
            )
        if a == "-L":
            _, _, p = args[offset + 1].partition("=")
            provider = Path(p)
            need(
                provider.is_dir() and provider.resolve().is_relative_to(cwd.resolve()),
                "dependency search points outside workspace",
            )


def first(w, r):
    """Never launch a diagnostic compiler before this receipt/its upload."""
    log = (r / "original-opt-dist.log").read_text(errors="replace")
    training = trace(log)
    stage = Path(training["stage"])
    need(stage == w / "source/rust/build" / HOST / "stage2", "recorded SDK outside owned checkout")
    write(r / "native-training.json", training)
    status = load(r / "primary.json")
    if status["stopped_after_completed_rustc_profiles"]:
        finished(log)
        profile = Path(training["build"]) / "opt-artifacts/rustc-pgo.profdata"
        need(profile.is_file() and profile.stat().st_size > 0, "missing actual merged training profile")
        write(
            r / "before-replay.json",
            {
                "outcome": "original 9-benchmark training completed",
                "merged_profile": {"size": profile.stat().st_size, "sha256": sha(profile)},
                "failed_timing_root": False,
            },
        )
    else:
        need(status["code"] != 0, "nonfailure without the unmodified training checkpoint")
        rec = diagnosis(log, training, exact=False)
        cwd = Path(rec["cwd"])
        tmp = Path(training["base_env"]["TMPDIR"])
        need(
            cwd.is_dir()
            and cwd.resolve().parent == tmp.resolve()
            and Path(rec["inc"]).resolve() == cwd.resolve() / "incremental-state",
            "reported failed cwd outside private collector TMPDIR",
        )
        # Preserve the complete workspace even if the raw-graph identity gate refuses.
        try:
            rows = keep_graphs(cwd, r / "original-graphs")
        finally:
            snap = pack(cwd, r / "original-workspace.tar.gz")
        for row in rows:
            file = cwd / row["path"]
            need(
                sha(file) == row["sha256"] and file.stat().st_ino == row["ino"], "original graph no longer matches"
            )
        write(r / "workspace-custody.json", {"cwd": str(cwd), "archive": snap, "graphs": rows})
        need(
            any(
                Path(row["path"]).name == "dep-graph.bin" and not Path(row["path"]).parent.name.endswith("-working")
                for row in rows
            ),
            "no finalized original Diesel graph",
        )
        diagnosis(log, training, exact=True)
        check_paths(cwd, Path(rec["inc"]), rec["argv"], tmp)
        need(
            sha(cwd / Q) == PATCHED_B
            and (cwd / "eprintln").is_file()
            and ERROR in (cwd / "eprintln").read_text(errors="replace"),
            "physical failed input is a different source or error",
        )
        write(
            r / "before-replay.json",
            {
                "outcome": "original Diesel Opt/IncrPatched decoder ICE",
                "original": rec,
                "original_workspace": snap,
                "graphs": rows,
                "eprintln_sha256": sha(cwd / "eprintln"),
                "failed_timing_root": True,
            },
        )


def decode(w, r):
    """Examine stored originals; native replays remain independent of this decoder."""
    import hashlib
    import struct
    from eager_header import scan
    from graph_forensics import original, read

    custody = load(r / "before-replay.json")
    if not custody["failed_timing_root"]:
        return
    graphs = {
        row["sha256"]
        for row in custody["graphs"]
        if Path(row["path"]).name == "dep-graph.bin" and not Path(row["path"]).parent.name.endswith("-working")
    }
    need(graphs, "no finalized graph in accepted original")
    for digest in sorted(graphs):
        path = r / "original-graphs" / digest
        need(sha(path) == digest, "saved graph changed before offline decoding")
        result = {"sha256": digest, "bytes": path.stat().st_size}
        try:
            with original(path) as data:
                need(hashlib.sha256(data).hexdigest() == digest, "mapped graph changed")
                result["eager_headers"] = scan(data)
                result["complete_structure"] = read(data)
        except (ValueError, AssertionError, IndexError, struct.error) as error:
            result["decoder_refusal"] = type(error).__name__ + ": " + str(error)
        write(r / ("original-graph-decode." + digest + ".json"), result)


def collector_source(w, r, t):
    upstream = w / "source/rust/src/tools/rustc-perf"
    staged = Path(t["cwd"])
    need(text(["git", "-C", upstream, "rev-parse", "HEAD"]) == PERF, "wrong active rustc-perf checkout")
    pins = load(HERE / "collector-members.json")
    for name, digest in pins.items():
        need(sha(upstream / name) == digest == sha(staged / name), "collector/template bytes differ: " + name)
    result = {
        "source": PERF,
        "source_members": pins,
        "collector": sha(staged / "target/debug/collector"),
        "rustc_fake": sha(staged / "target/debug/rustc-fake"),
        "bootstrap_config": sha(Path(t["base_env"]["RUST_BOOTSTRAP_CONFIG"])),
    }
    write(r / "rustc-perf-identity.json", result)
    return result


def command(directory, argv, cwd, env, timeout):
    directory.mkdir()
    write(directory / "argv.json", {"argv": list(map(str, argv)), "cwd": str(cwd)})
    free_guard(directory)
    deadline = time.monotonic() + timeout
    refused = None
    with (directory / "stdout").open("wb") as out, (directory / "stderr").open("wb") as err:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
        try:
            while child.poll() is None:
                free_guard(directory)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("diagnostic command deadline exceeded")
                try:
                    child.wait(timeout=min(2, remaining))
                except subprocess.TimeoutExpired:
                    continue
        except (OSError, ValueError, TimeoutError) as error:
            refused = str(error)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
    write(directory / "exit.json", {"code": child.returncode, "refusal": refused})
    need(refused is None, refused)
    return child.returncode


def runtime(w, r):
    t = load(r / "native-training.json")
    load(r / "before-replay.json")
    host_sources(w)
    collector_source(w, r, t)
    stage = Path(t["stage"])
    src = w / "source/rust"
    cargo = Path(extra(t["argv"], "--cargo"))
    (driver,) = (stage / "lib").glob("librustc_driver-*.dylib")
    tools = {
        "rustc": stage / "bin/rustc",
        "driver": driver,
        "cargo": cargo,
    }
    detail = {}
    for name, p in tools.items():
        stat = p.stat()
        detail[name] = {
            "path": str(p),
            "realpath": str(p.resolve()),
            "size": stat.st_size,
            "sha256": sha(p),
            "dev": stat.st_dev,
            "ino": stat.st_ino,
            "mtime_ns": stat.st_mtime_ns,
        }
    sections = text(["xcrun", "otool", "-l", tools["driver"]])
    need(
        "sectname __llvm_prf_cnts" in sections and "sectname __llvm_prf_data" in sections,
        "stage2 driver lacks native PGO coverage sections",
    )
    (r / "driver-otool.txt").write_text(sections + "\n")
    tools_env = t["base_env"] | {"LLVM_PROFILE_FILE": str(r / "identity-%m_%p.profraw")}
    vv = subprocess.check_output([tools["rustc"], "-vV"], text=True, env=tools_env)
    need("commit-hash: " + RUST in vv and "host: " + HOST in vv, "instrumented rustc version mismatch")
    cv = subprocess.check_output([cargo, "-vV"], text=True, env=tools_env)
    need("commit-hash: " + CARGO in cv, "instrumented Cargo version mismatch")
    raw = list(r.glob("identity-*.profraw"))
    need(raw and all(p.stat().st_size > 0 for p in raw), "no profiles from the actual instrumented tools")
    profdata = Path(t["build"]) / HOST / "ci-llvm/bin/llvm-profdata"
    output = subprocess.check_output(
        [str(profdata), "show", str(max(raw, key=lambda p: p.stat().st_size))], text=True
    )
    (r / "identity-llvm-profdata.txt").write_text(output)
    need("Total functions:" in output, "profile is unreadable")
    write(
        r / "tool-identity.json",
        {
            "tools": detail,
            "vv": vv,
            "cargo_vv": cv,
            "readable_profile_files": {p.name: [p.stat().st_size, sha(p)] for p in raw},
        },
    )
    # These one-off identity counters are not part of the original PGO output.
    for p in raw:
        p.unlink()
    free_guard(r, 6 * GIB)
    sys.path.insert(0, str(w / "transport/scripts/rc22-native"))
    import sdk

    dest = Path(os.environ["RUNNER_TEMP"]) / "diesel-instrumented-runtime"
    need(not dest.exists(), "instrumented runtime destination already present")
    sdk.freeze(stage, dest, src, HOST)
    shutil.copy2(cargo, dest / "bin/cargo")
    for name, path in [
        ("rustc", dest / "bin/rustc"),
        ("driver", dest / "lib" / tools["driver"].name),
        ("cargo", dest / "bin/cargo"),
    ]:
        need(sha(path) == detail[name]["sha256"], "frozen tool differs: " + name)
    # Verify the relocated runtime can launch and use its own target std without the build checkout.
    probe = Path(os.environ["RUNNER_TEMP"]) / "diesel-transportability"
    probe.mkdir()
    portable_env = t["base_env"] | {"LLVM_PROFILE_FILE": str(probe / "portable_%m_%p.profraw")}
    new_rustc = dest / "bin/rustc"
    new_cargo = dest / "bin/cargo"
    need(
        subprocess.check_output([new_rustc, "-vV"], env=portable_env, text=True) == vv
        and subprocess.check_output([new_cargo, "-vV"], env=portable_env, text=True) == cv,
        "relocated compiler/Cargo do not identify as their originals",
    )
    root = Path(subprocess.check_output([new_rustc, "--print", "sysroot"], env=portable_env, text=True).strip())
    std = Path(
        subprocess.check_output([new_rustc, "--print", "target-libdir"], env=portable_env, text=True).strip()
    )
    need(
        root.samefile(dest) and std.resolve().is_relative_to(dest.resolve()) and any(std.glob("libstd-*.rlib")),
        "relocated compiler is reading another SDK",
    )
    source = probe / "portable.rs"
    source.write_text("pub fn proof() -> usize { std::mem::size_of::<usize>() }\n")
    product = probe / "libportable.rmeta"
    code = command(
        r / "runtime-smoke",
        [new_rustc, "--crate-name", "portable", "--crate-type", "lib", "--emit=metadata", source, "-o", product],
        probe,
        portable_env,
        120,
    )
    need(
        code == 0 and product.is_file() and product.stat().st_size > 0,
        "relocated instrumented compiler cannot produce metadata",
    )
    runtime_archive = pack(dest, r / "instrumented-sdk.tar.gz", cap=3 * GIB)
    write(
        r / "runtime.json",
        runtime_archive
        | {
            "observed_sysroot": str(root),
            "target_libdir": str(std),
            "portable_source_sha256": sha(source),
            "portable_rmeta_sha256": sha(product),
        },
    )


def check_clone(src, dest):
    """Recreate within-tree hard links if cp split them, then check the entire clone."""
    original, _ = facts(src)
    copied, _ = facts(dest)
    need(original.keys() == copied.keys(), "clone path set differs")
    sources = {(r["dev"], r["ino"]) for r in original.values() if r["type"] == "file"}
    first = {}
    observed = {}
    for path, expected in original.items():
        got = copied[path]
        need(
            all(expected.get(k) == got.get(k) for k in ("type", "mode", "size", "sha256", "target")),
            "byte, type or mode mismatch in clone: " + path,
        )
        if expected["type"] != "file":
            continue
        owned = (expected["dev"], expected["ino"])
        new = (got["dev"], got["ino"])
        need(new not in sources, "clone aliases the parked original: " + path)
        need(observed.setdefault(new, owned) == owned, "originally different files already share one clone inode")
        if owned in first:
            representative = dest / first[owned]
            if not (dest / path).samefile(representative):
                (dest / path).unlink()
                os.link(representative, dest / path)
        else:
            first[owned] = path
    for path, expected in original.items():
        if expected["type"] == "file":
            owned = (expected["dev"], expected["ino"])
            need(
                (dest / path).samefile(dest / first[owned]),
                "not all same-generation alias relationships were restored",
            )


def direct(w, r):
    """The command is literal; the full transient Cargo child environment is not claimed."""
    original = load(r / "before-replay.json")
    if not original["failed_timing_root"]:
        return
    t = load(r / "native-training.json")
    rec = original["original"]
    cwd = Path(rec["cwd"])
    safe_for_clone(cwd)
    known = load(r / "tool-identity.json")["tools"]
    rust = Path(rec["argv"][0])
    need(
        sha(rust) == known["rustc"]["sha256"] and sha(Path(known["driver"]["path"])) == known["driver"]["sha256"],
        "real compiler changed before direct replay",
    )
    for row in original["graphs"]:
        need(sha(cwd / row["path"]) == row["sha256"], "original changed after capture")
    parked = cwd.with_name(cwd.name + "-captured-before-replay")
    need(not parked.exists(), "timing-directory custody collision")
    cwd.rename(parked)
    try:
        for name, warm, state in [
            ("warm-B", True, "B"),
            ("warm-A", True, "A"),
            ("empty-A", False, "A"),
            ("empty-B", False, "B"),
        ]:
            free_guard(r, 1 * GIB)
            subprocess.run(["/bin/cp", "-cRp", parked, cwd], check=True)
            try:
                check_clone(parked, cwd)
                inc = cwd / "incremental-state"
                if not warm:
                    shutil.rmtree(inc)
                if state == "A":
                    replacement = (cwd / Q).with_name("mod.rs.replay-restore")
                    need(not replacement.exists(), "source replacement path collides")
                    shutil.copy2(Path(t["cwd"]) / PERF_DIESEL / Q, replacement)
                    replacement.replace(cwd / Q)
                need(sha(cwd / Q) == (HEALTHY_A if state == "A" else PATCHED_B), "replay source changed")
                out = Path(extra(rec["argv"], "--out-dir")).resolve()
                need(out.is_relative_to(cwd.resolve()), "output escaped clone")
                for p in out.glob("libdiesel-*"):
                    if p.suffix in (".rmeta", ".rlib"):
                        p.unlink()
                dest = r / ("direct-" + name)
                scratch = Path(os.environ["RUNNER_TEMP"]) / ("diesel-direct-profile-" + name)
                scratch.mkdir()
                env = (
                    t["base_env"]
                    | t["env"]
                    | rec["explicit_env"]
                    | {
                        "LLVM_PROFILE_FILE": str(scratch / "default_%m_%p.profraw"),
                        "CARGO_MANIFEST_DIR": str(cwd),
                        "CARGO_PKG_NAME": "diesel",
                        "CARGO_PKG_VERSION": "2.2.10",
                        "CARGO_CRATE_NAME": "diesel",
                    }
                )
                write(r / ("direct-" + name + "-environment.json"), env)
                code = command(dest, rec["argv"], cwd, env, 240)
                diag = (dest / "stderr").read_text(errors="replace")
                outputs = {
                    p.name: [p.stat().st_size, sha(p)]
                    for p in out.glob("libdiesel-*")
                    if p.suffix in (".rmeta", ".rlib")
                }
                write(
                    dest / "result.json",
                    {
                        "exit": code,
                        "source": state,
                        "old_graph": warm,
                        "exact_decoder_ice": ERROR in diag and "SerializedDepGraph>::decode" in diag,
                        "outputs": outputs,
                    },
                )
            finally:
                if cwd.exists():
                    shutil.rmtree(cwd)
    finally:
        need(not cwd.exists(), "cannot restore captured directory while a clone exists")
        parked.rename(cwd)
    for row in original["graphs"]:
        need(sha(cwd / row["path"]) == row["sha256"], "original graph changed during off-clock replay")
    for n in ["empty-A", "empty-B"]:
        q = load(r / ("direct-" + n) / "result.json")
        need(
            q["exit"] == 0 and {Path(k).suffix for k in q["outputs"]} == {".rmeta", ".rlib"},
            "fresh direct control did not typecheck and emit the complete library",
        )


def focused(w, r):
    t = load(r / "native-training.json")
    known = load(r / "tool-identity.json")["tools"]
    for name in known:
        row = known[name]
        need(
            sha(row["path"]) == row["sha256"] and Path(row["path"]).stat().st_ino == row["ino"],
            "fresh collector would use a changed " + name,
        )
    argv = t["argv"].copy()
    for flag, value in [("--profiles", "Opt"), ("--exact-match", "diesel-2.2.10"), ("--jobs", "1")]:
        argv[argv.index(flag) + 1] = value
    job = Path(os.environ["RUNNER_TEMP"]) / "diesel-focused-profile"
    job.mkdir()
    tmp = job / "tmp"
    tmp.mkdir()
    env = t["base_env"] | t["env"] | {"TMPDIR": str(tmp), "LLVM_PROFILE_FILE": str(job / "default_%m_%p.profraw")}
    write(r / "focused-environment.json", env)
    code = command(r / "focused-collector", argv, Path(t["cwd"]), env, 25 * 60)
    f = r / "focused-collector"
    log = (f / "stdout").read_text(errors="replace") + "\n" + (f / "stderr").read_text(errors="replace")
    need(
        "Running diesel-2.2.10: Opt + [Full, IncrFull, IncrUnchanged, IncrPatched]" in log or code != 0,
        "focused collector did not execute Opt",
    )
    if code and ERROR in log:
        d = diagnosis(log, t)
        cwd = Path(d["cwd"])
        check_paths(cwd, Path(d["inc"]), d["argv"], tmp)
        rows = keep_graphs(cwd, f / "graphs")
        snap = pack(cwd, f / "workspace.tar.gz")
        write(f / "matching-ice.json", {"original": d, "graphs": rows, "archive": snap})
    logs = list(job.glob("*.profraw"))
    write(
        f / "result.json",
        {"code": code, "fresh_actual_collector": True, "matching_ice": ERROR in log, "profraw_files": len(logs)},
    )
    need(code == 0 or (f / "matching-ice.json").exists(), "focused job encountered a different failure")


if __name__ == "__main__":
    w = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    r = w / "source/reports/diesel-pgo"
    need(platform.system() == "Darwin" and platform.machine() == "arm64", "requires native Apple Silicon")
    {
        "source": lambda: host_sources(w),
        "first": lambda: first(w, r),
        "decode": lambda: decode(w, r),
        "runtime": lambda: runtime(w, r),
        "direct": lambda: direct(w, r),
        "focused": lambda: focused(w, r),
    }[sys.argv[1]]()
