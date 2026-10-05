#!/usr/bin/env python3
"""Matched Ohm compact-artifact workflow measurements on Linux."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import statistics
import subprocess
import threading
import time

MODES = ("baseline", "standard", "wrapper", "compact")
GIB = 1024**3
RECORDED_ENV = ("RUSTC", "RUSTDOC", "CARGO_ENCODED_RUSTFLAGS", "CARGO_INCREMENTAL",
                "CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR", "CARGO_HOME", "CARGO_BUILD_JOBS",
                "CARGO_PROFILE_DEV_DEBUG", "CARGO_PROFILE_DEV_BUILD_OVERRIDE_DEBUG",
                "CARGO_PROFILE_DEV_OPT_LEVEL", "CARGO_TERM_COLOR",
                "CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST", "CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST", "TMPDIR")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def command_output(argv, cwd=None):
    p = subprocess.run(argv, cwd=cwd, text=True, capture_output=True)
    return {"argv": list(map(str, argv)), "returncode": p.returncode,
            "stdout": p.stdout, "stderr": p.stderr}


def census(roots):
    inodes = {}
    result = {"allocated": 0, "logical": 0, "files": 0, "directories": 0, "categories": {}}
    for root in roots:
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not Path(directory, d).is_symlink()]
            for path in [Path(directory), *(Path(directory, name) for name in files)]:
                try:
                    st = path.lstat()
                except FileNotFoundError:
                    continue
                if path.is_symlink():
                    continue
                is_dir = path.is_dir()
                category = ("directories" if is_dir else
                            "compact-store" if "store" in path.parts else
                            "dep-graph" if path.name == "dep-graph.bin" else
                            "query-cache" if path.name == "query-cache.bin" else path.suffix or "other")
                key = (st.st_dev, st.st_ino)
                # An object hardlinked into the store belongs to the store even if its
                # incremental-cache alias happened to be visited first.
                if key not in inodes or category == "compact-store":
                    inodes[key] = (st.st_blocks * 512, st.st_size, is_dir, category)
    for allocated, logical, is_dir, category in inodes.values():
        result["allocated"] += allocated
        result["logical"] += logical
        result["directories" if is_dir else "files"] += 1
        row = result["categories"].setdefault(category, {"allocated": 0, "logical": 0, "entries": 0})
        row["allocated"] += allocated
        row["logical"] += logical
        row["entries"] += 1
    return result


def formats(roots, mode):
    magics = {b"!<arch>\n": "archive", b"RUSTZRL1": "wrapper", b"RCLIB001": "manifest", b"RCOBJ001": "object"}
    seen, counts, examples = set(), {}, {}
    for root in roots:
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not Path(directory, d).is_symlink()]
            for name in files:
                path = Path(directory, name)
                if path.is_symlink():
                    continue
                st = path.stat()
                key = (st.st_dev, st.st_ino)
                if key in seen:
                    continue
                seen.add(key)
                with path.open("rb") as f:
                    kind = magics.get(f.read(8))
                if kind:
                    counts[kind] = counts.get(kind, 0) + 1
                    examples.setdefault(kind, str(path))
    required = {"baseline": ("archive",), "standard": ("archive",),
                "wrapper": ("wrapper",), "compact": ("manifest", "object")}[mode]
    forbidden = ("wrapper", "manifest", "object") if mode in ("baseline", "standard") else (("manifest", "object") if mode == "wrapper" else ())
    return {"counts": counts, "examples": examples, "required": required, "forbidden": forbidden,
            "passed": bool(all(counts.get(kind, 0) for kind in required) and not any(counts.get(kind, 0) for kind in forbidden))}


def processes():
    result = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            data = (entry / "stat").read_text()
            end = data.rindex(")")
            fields = data[end + 2:].split()
            result[int(entry.name)] = {
                "ppid": int(fields[1]), "name": data[data.index("(") + 1:end],
                "ticks": int(fields[11]) + int(fields[12]),
                "rss": int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
                "uid": entry.stat().st_uid,
            }
        except (OSError, ValueError, IndexError):
            pass
    return result


class Monitor:
    def __init__(self, pid, roots, sample_disk, reserve):
        self.pid, self.roots, self.sample_disk = pid, roots, sample_disk
        self.reserve = reserve
        self.reserve_failed = False
        self.done = threading.Event()
        self.peak_rss = self.peak_disk = 0
        self.unrelated_compilers = {}
        self.outside_cpu_intervals = []
        self.samples = []
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        last_disk = 0
        previous = {}
        previous_time = time.monotonic()
        while not self.done.is_set():
            if shutil.disk_usage(self.roots[0]).free < self.reserve:
                self.reserve_failed = True
                try:
                    os.killpg(self.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                return
            ps = processes()
            owned = {self.pid}
            while True:
                new = {pid for pid, row in ps.items() if row["ppid"] in owned}
                if new <= owned:
                    break
                owned.update(new)
            rss = sum(ps[pid]["rss"] for pid in owned if pid in ps)
            self.peak_rss = max(rss, self.peak_rss)
            for pid, row in ps.items():
                if pid not in owned and row["name"] in {"rustc", "cargo", "clippy-driver", "wild", "cc1", "cc1plus", "ld.lld"}:
                    self.unrelated_compilers[str(pid)] = row["name"]
            now = time.monotonic()
            outside_ticks = sum(max(0, row["ticks"] - previous[pid]["ticks"])
                                for pid, row in ps.items() if pid in previous and pid not in owned
                                and pid != os.getpid() and row["uid"] == os.getuid())
            outside_cores = outside_ticks / os.sysconf("SC_CLK_TCK") / max(now - previous_time, 0.001)
            if previous and outside_cores > 0.5:
                self.outside_cpu_intervals.append({"time": time.time(), "cores": outside_cores})
            self.samples.append({"time": time.time(), "rss": rss, "processes": len(owned),
                                 "outside_user_cpu_cores": outside_cores})
            previous, previous_time = ps, now
            if self.sample_disk and time.monotonic() - last_disk >= 2:
                self.peak_disk = max(self.peak_disk, census(self.roots)["allocated"])
                last_disk = time.monotonic()
            self.done.wait(0.5)


def timed(argv, cwd, env, stem, roots, sample_disk, reserve):
    resources = stem.with_suffix(".time")
    log = stem.with_suffix(".log")
    start = time.perf_counter()
    with log.open("wb") as output:
        proc = subprocess.Popen(["/usr/bin/time", "-v", "-o", str(resources), *argv], cwd=cwd,
                                env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        monitor = Monitor(proc.pid, roots, sample_disk, reserve)
        monitor.thread.start()
        status = proc.wait()
        elapsed = time.perf_counter() - start
        monitor.done.set()
        monitor.thread.join()
    raw = resources.read_text() if resources.exists() else ""
    def metric(label, cast=float):
        match = re.search(r"^\s*" + re.escape(label) + r":\s*(\S+)", raw, re.M)
        return cast(match[1]) if match else None
    result = {"argv": argv, "cwd": str(cwd), "returncode": status, "wall_seconds": elapsed,
              "user_seconds": metric("User time (seconds)"), "system_seconds": metric("System time (seconds)"),
              "max_child_rss_bytes": (metric("Maximum resident set size (kbytes)", int) or 0) * 1024,
              "sampled_process_tree_peak_rss_bytes": monitor.peak_rss,
              "sampled_peak_allocated_bytes": monitor.peak_disk if sample_disk else None,
              "peak_disk_scope": "reachable files and directories; excludes deleted-open files; sampled lower bound",
              "instrumented_disk": sample_disk, "unrelated_compilers": monitor.unrelated_compilers,
              "outside_cpu_intervals": monitor.outside_cpu_intervals,
              "disk_reserve_failed": monitor.reserve_failed,
              "log": str(log), "resources": str(resources)}
    result["compiler_crates"] = re.findall(r"Running [^\n]*\brustc\b[^\n]*--crate-name ([^\s]+)", log.read_text(errors="replace"))
    stem.with_suffix(".monitor.json").write_text(json.dumps(monitor.samples))
    return result


class Fixture:
    def __init__(self, root, project):
        self.root, self.project = root, project
        self.main = root / ("crates/uv/src/bin/uv.rs" if project == "uv" else "crates/ruff/src/main.rs")
        self.lib = root / f"crates/{project}/src/lib.rs"
        self.original_main, self.original_lib = self.main.read_bytes(), self.lib.read_bytes()
        self.main_text = self.original_main.decode()
        assert self.main_text.count("fn main() -> ExitCode {") == 1
        assert "__ohm_compact_bench_value" not in self.original_lib.decode()

    def write(self, direct=0, library=0, inline=0):
        probe = ("fn main() -> ExitCode {\n"
                 '    if std::env::var_os("OHM_COMPACT_BENCH_ORACLE").is_some() {\n'
                 f'        println!("{{}}", {self.project}::__ohm_compact_bench_value() + {self.project}::__ohm_compact_bench_inline_value() + std::hint::black_box({direct}u32));\n'
                 '        return ExitCode::SUCCESS;\n    }')
        main = self.main_text.replace("fn main() -> ExitCode {", probe).encode()
        lib = self.original_lib + (f"\n#[inline(never)]\npub fn __ohm_compact_bench_value() -> u32 {{ std::hint::black_box({library}u32) }}\n"
                                   f"#[inline]\npub fn __ohm_compact_bench_inline_value() -> u32 {{ std::hint::black_box({inline}u32) }}\n").encode()
        for path, contents in ((self.main, main), (self.lib, lib)):
            if path.read_bytes() != contents:
                path.write_bytes(contents)

    def restore(self):
        self.main.write_bytes(self.original_main)
        self.lib.write_bytes(self.original_lib)


def runtime(binary, expected, destination):
    env = os.environ.copy()
    env["OHM_COMPACT_BENCH_ORACLE"] = "1"
    probe = subprocess.run([str(binary)], env=env, capture_output=True, text=True)
    version = command_output([str(binary), "--version"])
    help_result = command_output([str(binary), "--help"])
    result = {"expected_probe": expected, "probe_stdout": probe.stdout,
              "probe_stderr": probe.stderr, "probe_returncode": probe.returncode,
              "version": version, "help": help_result, "sha256": digest(binary)}
    result["passed"] = (probe.returncode == 0 and probe.stdout.strip() == str(expected)
                        and version["returncode"] == 0 and help_result["returncode"] == 0)
    destination.write_text(json.dumps(result, indent=2))
    return result


def owned_cleanup(path):
    marker = path / ".ohm-compact-benchmark"
    if not path.exists():
        return
    if path.is_symlink() or not marker.is_file() or marker.read_text() != "owned by benchmark.py\n":
        raise RuntimeError(f"refusing to delete unowned path {path}")
    shutil.rmtree(path)


def environment(args, mode, lane, project):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("CARGO_PROFILE_", "CARGO_UNSTABLE_OHM_", "WILD_", "RUSTC_COMPACT_")) or "RUSTFLAGS" in key:
            env.pop(key)
    for key in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
                "RUSTC", "RUSTDOC", "RUSTUP_TOOLCHAIN", "CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR",
                "OHM_COMPACT_BENCH_ORACLE"):
        env.pop(key, None)
    toolchain = args.baseline if mode == "baseline" else args.candidate
    # Let Ohm inject its authenticated bundled Wild flags. Explicit linker flags
    # intentionally disable immutable registry reuse and worktree seeding.
    flags = []
    if mode != "baseline":
        flags += ["-Zcompress-incremental=no", f"-Zartifact-compression-profile={args.compression_profile}"]
    if mode == "wrapper":
        flags += ["-Zcompress-artifacts=yes"]
    if mode == "compact":
        flags += [f"-Zcompact-artifact-store={lane / 'store'}"]
    env.update({"RUSTC": str(toolchain / "bin/rustc"), "RUSTDOC": str(toolchain / "bin/rustdoc"),
                "CARGO_ENCODED_RUSTFLAGS": "\x1f".join(flags), "CARGO_INCREMENTAL": "1",
                "CARGO_TARGET_DIR": str(lane / "target"), "CARGO_BUILD_BUILD_DIR": str(lane / "build"),
                "CARGO_HOME": str(args.cargo_home), "CARGO_BUILD_JOBS": str(args.jobs),
                "CARGO_PROFILE_DEV_DEBUG": "line-tables-only" if args.profile == "line" else "2",
                "CARGO_PROFILE_DEV_BUILD_OVERRIDE_DEBUG": "0", "CARGO_TERM_COLOR": "never",
                "CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST": "all", "CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST": "all",
                "TMPDIR": str(lane / "scratch")})
    if project == "ruff":
        env["CARGO_PROFILE_DEV_OPT_LEVEL"] = "1"
    return env, flags


def summarize(rows):
    result = []
    keys = sorted({(r["project"], r["mode"], r["phase"]) for r in rows if r.get("accepted")})
    for project, mode, phase in keys:
        samples = [r for r in rows if (r["project"], r["mode"], r["phase"]) == (project, mode, phase) and r.get("accepted")]
        result.append({"project": project, "mode": mode, "phase": phase, "n": len(samples),
                       "median_wall_seconds": statistics.median(r["wall_seconds"] for r in samples),
                       "median_cpu_seconds": statistics.median(r["user_seconds"] + r["system_seconds"] for r in samples),
                       "median_peak_child_rss_bytes": statistics.median(r["max_child_rss_bytes"] for r in samples),
                       "median_peak_tree_rss_bytes": statistics.median(r["sampled_process_tree_peak_rss_bytes"] for r in samples)})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "baseline", "candidate", "wild", "target-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--baseline-wild", type=Path)
    parser.add_argument("--cargo", default="/home/dev-user/.cargo/bin/cargo")
    parser.add_argument("--cargo-home", type=Path, default=Path("/tmp/codex-cargo-home"))
    parser.add_argument("--projects", nargs="+", choices=("uv", "ruff"), default=["uv", "ruff"])
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--profile", choices=("line", "full"), default="line")
    parser.add_argument("--compression-profile", choices=("fast", "balanced", "small", "legacy"), default="fast")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--edits", type=int, default=5)
    parser.add_argument("--min-free-gib", type=int, default=60)
    parser.add_argument("--sample-disk", action="store_true")
    parser.add_argument("--keep-targets", action="store_true")
    parser.add_argument("--online", action="store_true", help="Use only for dependency preparation, not accepted timing")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if min(args.jobs, args.rounds, args.edits) < 1:
        parser.error("jobs, rounds and edits must be positive")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("output must be new or empty; preserve earlier receipts")
    plan = []
    for project in args.projects:
        for round_index in range(args.rounds):
            order = args.modes if round_index % 2 == 0 else args.modes[::-1]
            for mode in order:
                lane = args.target_root / args.profile / project / f"round-{round_index}" / mode
                env, flags = environment(args, mode, lane, project)
                plan.append({"project": project, "round": round_index, "mode": mode, "lane": str(lane), "flags": flags,
                             "env": {k: env[k] for k in RECORDED_ENV if k in env}})
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return
    args.output.mkdir(parents=True, exist_ok=True)
    args.target_root.mkdir(parents=True, exist_ok=True)
    lock = (args.target_root / "benchmark.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    provenance = {"plan": plan, "uname": command_output(["uname", "-a"]),
                  "cpu": command_output(["lscpu"]), "df": command_output(["df", "-B1", str(args.target_root)]),
                  "script_sha256": digest(__file__), "cpu_affinity": sorted(os.sched_getaffinity(0)),
                  "settings": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                  "sources": {}, "toolchains": {}}
    for project in args.projects:
        root = args.sources / project
        provenance["sources"][project] = {"head": command_output(["git", "rev-parse", "HEAD"], root),
                                           "diff": command_output(["git", "diff", "--binary"], root)}
    for name, root in (("baseline", args.baseline), ("candidate", args.candidate)):
        bundled_wild = root / "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
        expected_wild = args.baseline_wild if name == "baseline" and args.baseline_wild else args.wild
        if not bundled_wild.is_file() or digest(bundled_wild) != digest(expected_wild):
            raise RuntimeError(f"install the measured Wild binary at {bundled_wild} before measuring")
        provenance["toolchains"][name] = {"version": command_output([str(root / "bin/rustc"), "-vV"]),
                                           "rustc_sha256": digest(root / "bin/rustc"),
                                           "bundled_wild_path": str(bundled_wild), "bundled_wild_sha256": digest(bundled_wild),
                                           "driver_sha256": {str(p): digest(p) for p in (root / "lib").glob("librustc_driver*.so")}}
    provenance["wild"] = {"version": command_output([str(args.wild), "--version"]), "sha256": digest(args.wild)}
    if args.baseline_wild:
        provenance["baseline_wild"] = {"version": command_output([str(args.baseline_wild), "--version"]),
                                      "sha256": digest(args.baseline_wild)}
    cargo_path = command_output(["rustup", "which", "--toolchain", "ohm", "cargo"])
    provenance["cargo"] = {"version": command_output([args.cargo, "+ohm", "-vV"]), "path": cargo_path}
    if cargo_path["returncode"] == 0:
        provenance["cargo"]["sha256"] = digest(cargo_path["stdout"].strip())
    (args.output / "provenance.json").write_text(json.dumps(provenance, indent=2))
    rows = []
    for cell in plan:
        project, mode = cell["project"], cell["mode"]
        lane, root = Path(cell["lane"]), args.sources / project
        if shutil.disk_usage(args.target_root).free < args.min_free_gib * GIB:
            raise RuntimeError("free space reserve reached")
        owned_cleanup(lane)
        lane.mkdir(parents=True)
        (lane / ".ohm-compact-benchmark").write_text("owned by benchmark.py\n")
        (lane / "scratch").mkdir()
        env, flags = environment(args, mode, lane, project)
        argv = [args.cargo, "+ohm", "build", "--locked", "-vv", "-p", project, "--bin", project, "-j", str(args.jobs)]
        if not args.online:
            argv.append("--offline")
        fixture = Fixture(root, project)
        directory = args.output / f"{project}-{mode}-{cell['round']}"
        directory.mkdir()
        binary = lane / "target/debug" / project
        try:
            fixture.write()
            sequence = [("clean", 0, 0, 0), ("noop", 0, 0, 0)]
            sequence += [("direct-edit", index, 0, 0) for index in range(1, args.edits + 1)]
            sequence += [("restore", 0, 0, 0)]
            sequence += [("library-edit", 0, index, 0) for index in range(1, args.edits + 1)]
            sequence += [("inline-edit", 0, args.edits, index) for index in range(1, args.edits + 1)]
            sequence += [("noop-final", 0, args.edits, args.edits)]
            for index, (phase, direct, library, inline) in enumerate(sequence):
                if shutil.disk_usage(args.target_root).free < args.min_free_gib * GIB:
                    raise RuntimeError("free space reserve reached")
                fixture.write(direct, library, inline)
                stem = directory / f"{index:02}-{phase}"
                row = timed(argv, root, env, stem, [lane], args.sample_disk, args.min_free_gib * GIB)
                row.update({"project": project, "mode": mode, "round": cell["round"], "phase": phase,
                            "direct_value": direct, "library_value": library, "inline_value": inline, "flags": flags,
                            "accepted": row["returncode"] == 0 and not row["unrelated_compilers"]
                            and len(row["outside_cpu_intervals"]) < 3 and not args.online and not args.sample_disk})
                if row["returncode"] == 0:
                    try:
                        row["oracle"] = runtime(binary, direct + library + inline, stem.with_suffix(".oracle.json"))
                    except Exception as error:
                        row["oracle"] = {"passed": False, "error": repr(error)}
                    row["accepted"] = row["accepted"] and row["oracle"]["passed"]
                    row["census"] = census([lane])
                    if phase == "clean":
                        row["formats"] = formats([lane], mode)
                        row["accepted"] = row["accepted"] and row["formats"]["passed"]
                rows.append(row)
                with (args.output / "samples.jsonl").open("a") as f:
                    f.write(json.dumps(row) + "\n")
                (args.output / "summary.json").write_text(json.dumps(summarize(rows), indent=2))
                print(json.dumps({k: row[k] for k in ("project", "mode", "round", "phase", "wall_seconds", "returncode", "accepted")}), flush=True)
                if row["returncode"]:
                    raise RuntimeError(f"build failed; see {row['log']}")
                if "formats" in row and not row["formats"]["passed"]:
                    raise RuntimeError(f"requested artifact format not found: {row['formats']}")
                if not row["oracle"]["passed"]:
                    raise RuntimeError(f"runtime oracle failed; see {stem.with_suffix('.oracle.json')}")
                if row["unrelated_compilers"]:
                    raise RuntimeError(f"unrelated compilers overlapped measurement: {row['unrelated_compilers']}")
                if len(row["outside_cpu_intervals"]) >= 3:
                    raise RuntimeError("outside user CPU exceeded half a core in at least three samples")
        finally:
            fixture.restore()
        if not args.keep_targets:
            owned_cleanup(lane)
    (args.output / "status.json").write_text(json.dumps({"status": "completed", "samples": len(rows), "completed_at": time.time()}))


if __name__ == "__main__":
    main()
