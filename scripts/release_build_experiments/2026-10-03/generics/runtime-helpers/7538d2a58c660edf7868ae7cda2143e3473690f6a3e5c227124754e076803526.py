#!/usr/bin/env python3
"""Measure isolated cold/small-edit Ohm release builds for shared generics.

Each invocation produces one JSON record, raw Cargo/time output, and immutable
copies of both executables. It never deletes a previous target or result.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def capture(args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def system_snapshot():
    return {
        "time": time.time(),
        "loadavg": os.getloadavg(),
        "cpu": Path("/proc/stat").read_text().splitlines()[0],
        "memory": Path("/proc/meminfo").read_text(),
        "processes": capture(["ps", "-eo", "pid,ppid,pcpu,pmem,comm", "--sort=-pcpu"]),
    }


def process_ticks():
    processes = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            raw = (entry / "stat").read_text()
            name, _, rest = raw.rpartition(")")
            fields = rest.split()
            processes[int(entry.name)] = {"parent": int(fields[1]), "name": name.partition("(")[2], "ticks": int(fields[11]) + int(fields[12]), "started": fields[19]}
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    own = {os.getpid()}
    while True:
        children = {pid for pid, data in processes.items() if data["parent"] in own}
        if children.issubset(own):
            break
        own.update(children)
    return {"time": time.monotonic(), "cpu": [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]], "outside": {pid: data for pid, data in processes.items() if pid not in own}}


def monitor_delta(before, after):
    elapsed = after["time"] - before["time"]
    hz = os.sysconf("SC_CLK_TCK")
    outside = []
    for pid, data in after["outside"].items():
        prior = before["outside"].get(pid)
        if prior and prior["started"] == data["started"]:
            used = (data["ticks"] - prior["ticks"]) / hz
            if used > 0.01 or data["name"] in {"rustc", "cargo", "cc", "cc1", "clang", "ld", "ld.lld", "mold", "ninja"}:
                outside.append({"pid": pid, "name": data["name"], "cpu_seconds": used})
    deltas = [last - first for first, last in zip(before["cpu"], after["cpu"])]
    total = sum(deltas)
    return {"time": time.time(), "seconds": elapsed, "idle_fraction": deltas[3] / total, "iowait_fraction": deltas[4] / total, "steal_fraction": deltas[7] / total, "outside_cpu_cores": sum(p["cpu_seconds"] for p in outside) / elapsed, "outside": outside}


def host_limits():
    cgroup = Path("/proc/self/cgroup").read_text()
    paths = {Path("/sys/fs/cgroup")}
    for line in cgroup.splitlines():
        if line.startswith("0::"):
            current = Path("/sys/fs/cgroup") / line[3:].lstrip("/")
            while current != Path("/sys/fs"):
                paths.add(current)
                current = current.parent
    limits = {}
    for path in paths:
        for name in ("cpu.max", "cpuset.cpus.effective", "memory.max"):
            file = path / name
            if file.exists():
                limits[str(file)] = file.read_text().strip()
    return {"lscpu": capture(["lscpu"]), "affinity": sorted(os.sched_getaffinity(0)), "self_cgroup": cgroup, "limits": limits}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--name", choices=["uv", "ruff"], required=True)
    parser.add_argument("--toolchain", default="ohm")
    parser.add_argument("--lto", choices=["fat", "thin"], required=True)
    parser.add_argument("--share", choices=["default", "yes"], required=True)
    parser.add_argument("--sample", type=int, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cargo-home", type=Path, required=True)
    parser.add_argument("--discard-builds", action="store_true")
    parser.add_argument("--library-edit", action="store_true")
    args = parser.parse_args()
    args.repo = args.repo.resolve()
    identifier = f"{args.name}-{args.lto}-{args.share}-{args.sample}"
    destination = args.root.resolve() / identifier
    if shutil.disk_usage(args.root.resolve().parent).free < 30 * 1024**3:
        raise SystemExit("Refusing to start with less than 30 GiB free")
    destination.mkdir(parents=True, exist_ok=False)
    target = destination / "target"
    build = destination / "build"
    env = os.environ.copy()
    for key in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "CARGO_BUILD_JOBS", "CARGO_BUILD_RUSTFLAGS", "CARGO_INCREMENTAL", "CARGO_BUILD_INCREMENTAL", *[key for key in env if key.startswith("CARGO_PROFILE_RELEASE_")]):
        env.pop(key, None)
    env.update({
        "CARGO_HOME": str(args.cargo_home.resolve()),
        "CARGO_TARGET_DIR": str(target),
        "CARGO_BUILD_BUILD_DIR": str(build),
        "CARGO_PROFILE_RELEASE_LTO": args.lto,
        "CARGO_TERM_COLOR": "never",
    })
    if args.share == "yes":
        env["CARGO_ENCODED_RUSTFLAGS"] = "-Zshare-generics=yes"
    command = ["cargo", f"+{args.toolchain}", "build", "--locked", "--offline", "--release", "-p", args.name, "--bin", args.name, "--timings"]
    result = {
        "id": identifier,
        "repo": str(args.repo),
        "source_sha": capture(["git", "rev-parse", "HEAD"], args.repo),
        "source_status": capture(["git", "status", "--short"], args.repo),
        "command": command,
        "environment": {key: env[key] for key in ("CARGO_HOME", "CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR", "CARGO_PROFILE_RELEASE_LTO", "CARGO_TERM_COLOR", "CARGO_ENCODED_RUSTFLAGS", "CARGO_INCREMENTAL", "CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST", "CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST", "RUSTUP_TOOLCHAIN", "CC", "CXX") if key in env},
        "rustc": capture(["rustc", f"+{args.toolchain}", "-vV"]),
        "cargo": capture(["cargo", f"+{args.toolchain}", "-vV"]),
        "logical_cpus": os.cpu_count(),
        "host_limits": host_limits(),
        "uname": capture(["uname", "-a"]),
        "runner_sha256": digest(__file__),
        "samples": [],
    }
    for executable in ("cargo", "rustc"):
        path = capture(["rustup", "which", "--toolchain", args.toolchain, executable])
        result[executable + "_path"] = path
        result[executable + "_sha256"] = digest(path)
    if result["source_status"]:
        raise SystemExit("Refusing a dirty benchmark source checkout")
    def save():
        temporary = destination / "result.json.tmp"
        temporary.write_text(json.dumps(result, indent=2) + "\n")
        temporary.replace(destination / "result.json")
    def run(kind):
        record = {"kind": kind, "before": system_snapshot()}
        before_cpu = [int(value) for value in record["before"]["cpu"].split()[1:9]]
        time.sleep(3)
        idle_cpu = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
        deltas = [after - before for before, after in zip(before_cpu, idle_cpu)]
        record["idle_fraction_before"] = deltas[3] / sum(deltas)
        record["iowait_fraction_before"] = deltas[4] / sum(deltas)
        if record["idle_fraction_before"] < 0.95:
            result["samples"].append(record)
            save()
            raise SystemExit("Refusing a sample with less than 95% CPU idle before build")
        save()
        started = time.monotonic()
        monitor = []
        prior = process_ticks()
        with (destination / f"{kind}.log").open("w") as log, (destination / f"{kind}-monitor.jsonl").open("w") as monitoring:
            proc = subprocess.Popen(["/usr/bin/time", "-v", *command], cwd=args.repo, env=env, stdout=log, stderr=subprocess.STDOUT)
            while True:
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                current = process_ticks()
                observation = monitor_delta(prior, current)
                monitor.append(observation)
                monitoring.write(json.dumps(observation) + "\n")
                monitoring.flush()
                prior = current
                if proc.returncode is not None:
                    break
        record.update({"elapsed": time.monotonic() - started, "returncode": proc.returncode, "after": system_snapshot()})
        record["monitor"] = {"max_outside_cpu_cores": max(item["outside_cpu_cores"] for item in monitor), "foreign_compiler_observations": [item for item in monitor if any(p["name"] in {"rustc", "cargo", "cc", "cc1", "clang", "ld", "ld.lld", "mold", "ninja"} for p in item["outside"])], "outside_cpu_over_one_core_seconds": sum(item["seconds"] for item in monitor if item["outside_cpu_cores"] > 1), "mean_steal_fraction": sum(item["steal_fraction"] * item["seconds"] for item in monitor) / sum(item["seconds"] for item in monitor)}
        record["lock_wait_detected"] = "Blocking waiting for file lock" in (destination / f"{kind}.log").read_text()
        if proc.returncode == 0:
            executable = target / "release" / args.name
            copy = destination / f"{args.name}-{kind}"
            shutil.copy2(executable, copy)
            record.update({"binary_size": copy.stat().st_size, "binary_sha256": digest(copy), "binary": str(copy)})
            record["version"] = capture([str(copy), "--version"])
        result["samples"].append(record)
        save()
        if proc.returncode:
            raise SystemExit(proc.returncode)
    run("cold")
    source = args.repo / ("crates/uv/src/bin/uv.rs" if args.name == "uv" else "crates/ruff/src/main.rs")
    original = source.read_bytes()
    needle = b"fn main() -> ExitCode {"
    assert original.count(needle) == 1
    modified = original.replace(needle, needle + b'\n    std::hint::black_box("ohm release generic sharing probe");')
    result["edit"] = {"path": str(source.relative_to(args.repo)), "before_sha256": hashlib.sha256(original).hexdigest(), "after_sha256": hashlib.sha256(modified).hexdigest(), "description": "Add black_box of a constant string at the binary entry point; original output preserved."}
    source.write_bytes(modified)
    try:
        run("edit")
        if args.library_edit:
            if args.name == "uv":
                library = args.repo / "crates/uv-normalize/src/package_name.rs"
                old, new = b'f.write_str("a string")', b'f.write_str("a package name string")'
            else:
                library = args.repo / "crates/ruff_text_size/src/serde_impls.rs"
                old, new = b'"invalid range: {start:?}..{end:?}"', b'"invalid text range: {start:?}..{end:?}"'
            original_library = library.read_bytes()
            assert original_library.count(old) == 1
            modified_library = original_library.replace(old, new)
            result["library_edit"] = {"path": str(library.relative_to(args.repo)), "before_sha256": hashlib.sha256(original_library).hexdigest(), "after_sha256": hashlib.sha256(modified_library).hexdigest(), "description": "Change an error message in a generic Serde deserializer in a shared library, on top of the entrypoint edit."}
            library.write_bytes(modified_library)
            try:
                run("library-edit")
            finally:
                library.write_bytes(original_library)
    finally:
        source.write_bytes(original)
    if args.discard_builds:
        timings = target / "cargo-timings"
        if timings.exists():
            shutil.copytree(timings, destination / "cargo-timings")
        result["discarded_build_directories"] = []
        for owned in (target, build):
            if owned.exists():
                assert owned.resolve().parent == destination and not owned.is_symlink()
                result["discarded_build_directories"].append({"path": str(owned), "disk_bytes": capture(["du", "-sb", str(owned)]).split()[0]})
                shutil.rmtree(owned)
        save()
    print(json.dumps({"path": str(destination), "samples": [{key: item.get(key) for key in ("kind", "elapsed", "binary_size")} for item in result["samples"]]}), flush=True)


if __name__ == "__main__":
    main()
