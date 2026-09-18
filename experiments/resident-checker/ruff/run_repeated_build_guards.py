#!/usr/bin/env python3
"""Exercise multiple test builds and rejected source revisions in one compiler."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

from run_test_build_guards import MAIN, OTHER, read_lines, require, scalar

LINKER_FAILURE = "ohm fixture: injected linker failure"
LINKER_SOURCE = """fn behavior() -> bool {
    true
}

#[test]
fn test_behavior() {
    assert!(behavior());
}
"""


def fingerprint(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


class Worker:
    def __init__(self, process, timeout, transcript):
        self.process = process
        self.timeout = timeout
        self.transcript = transcript
        self.lines = []
        self.queue = Queue()
        self.reader = Thread(
            target=read_lines, args=(process.stdout, self.queue), daemon=True
        )
        self.reader.start()

    def receive(self, kind=None):
        try:
            line = self.queue.get(timeout=self.timeout)
        except Empty:
            raise RuntimeError(f"timed out waiting for {kind!r}") from None
        require(line is not None, f"compiler closed stdout before {kind!r}")
        self.lines.append(line)
        first, *fields = line.split("\t")
        if kind is not None:
            require(first == kind, f"expected {kind!r}, got {line!r}")
        return first, fields

    def send(self, line):
        require(
            self.process.poll() is None, "resident compiler exited between requests"
        )
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        self.reader.join(timeout=self.timeout)
        self.process.stdin.close()
        self.process.stdout.close()
        self.transcript.write_text("\n".join(self.lines) + "\n")


def run(args):
    args.output.mkdir(parents=True)
    sources = {name: args.output / name for name in ("lib.rs", "other.rs")}
    sources["lib.rs"].write_text(MAIN)
    sources["other.rs"].write_text(OTHER)
    artifact = args.output / ("test.exe" if os.name == "nt" else "test")
    environment = dict(
        os.environ,
        OHM_RUFF_SOURCE_MODE="resident-repeat-build",
        RUSTC_BOOTSTRAP="1",
    )
    if args.no_cache:
        environment.pop("OHM_RUFF_CODEGEN_CACHE", None)
    else:
        environment["OHM_RUFF_CODEGEN_CACHE"] = str(args.output / "codegen-cache")
    command = [
        str(args.driver),
        "--edition=2024",
        "--sysroot",
        str(args.stage),
        "-Zohm-resident-query-graph",
        "--error-format=json",
        "--test",
        "--crate-name",
        "resident_repeated_test_guard",
        "-Ccodegen-units=4",
        str(sources["lib.rs"]),
        "-o",
        str(artifact),
    ]
    observations = []

    with (args.output / "compiler.stderr").open("w") as stderr:
        process = subprocess.Popen(
            command,
            cwd=args.output,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
        )
        worker = Worker(process, args.timeout, args.output / "protocol.txt")
        receive, send = worker.receive, worker.send

        def write(name, text):
            sources[name].write_text(text)

        def check(version, name, text, mode, errors=None):
            write(name, text)
            send(f"check\t{version}\t{sources[name]}")
            _, result = receive("result")
            require(result[0] == str(version), f"wrong checked version: {result}")
            require(result[1] == mode, f"wrong checked mode: {result}")
            if errors is not None:
                require(int(result[5]) == errors, f"wrong error count: {result}")

        def build(name, version, *, rejected=None, test_exit=None):
            original = fingerprint(artifact) if artifact.is_file() else None
            send(f"build\t{version}")
            _, reply = receive("build")
            require(reply[0] == str(version), f"wrong build version: {reply}")
            if rejected is not None:
                require(
                    reply[1:] == ["rejected", rejected], f"wrong rejection: {reply}"
                )
                require(original is not None, "no earlier executable to guard")
                require(
                    fingerprint(artifact) == original, "rejection replaced executable"
                )
                observations.append(
                    {
                        "name": name,
                        "rejected": rejected,
                        "test_ran": False,
                        "stale_artifact_preserved": True,
                    }
                )
                return

            require(reply[1:] == ["ready", "-"], f"build was not ready: {reply}")
            _, analysis = receive("build-analysis")
            require(
                analysis[0] == str(version), f"wrong build-analysis version: {analysis}"
            )
            units = []
            while True:
                event, fields = receive()
                require(
                    fields[0] == str(version), f"wrong build event version: {fields}"
                )
                if event == "build-finished":
                    require(fields[2] == "ok", f"build failed: {fields}")
                    break
                require(
                    event == "build-codegen-unit", f"unexpected build event: {event}"
                )
                require(
                    fields[2] in ("compiled", "reused"), f"unknown CGU mode: {fields}"
                )
                require(fields[3], f"missing CGU fingerprint: {fields}")
                units.append({"name": fields[1], "mode": fields[2], "hash": fields[3]})

            if not args.no_cache:
                require(units, "cache-enabled successful build returned no CGUs")
            result = subprocess.run(
                [str(artifact), "--exact", "test_behavior"],
                capture_output=True,
                text=True,
                check=False,
            )
            require(
                result.returncode == test_exit,
                f"wrong test exit {result.returncode}: {result.stdout}",
            )
            observations.append(
                {
                    "name": name,
                    "test_ran": True,
                    "test_exit": result.returncode,
                    "units": units,
                }
            )

        try:
            _, ready = receive("ready")
            pid = int(ready[0])
            require(
                pid == process.pid, f"ready worker PID {pid} != child {process.pid}"
            )

            build("baseline", 0, test_exit=0)
            build("unchanged-same-version", 0, test_exit=0)
            build("wrong-version", 1, rejected="source-version-is-not-current")
            check(1, "lib.rs", scalar(MAIN, "false"), "resident", 0)
            build("behavior-edit", 1, test_exit=101)
            check(2, "lib.rs", MAIN, "resident", 0)
            build("behavior-repair", 2, test_exit=0)
            check(3, "lib.rs", scalar(MAIN, "0u8"), "resident", 1)
            build("type-error", 3, rejected="accepted-source-has-errors")
            check(4, "other.rs", scalar(OTHER, "false"), "resident")
            build("error-survives-other-edit", 4, rejected="accepted-source-has-errors")
            check(5, "other.rs", OTHER, "resident")
            build(
                "error-survives-other-repair", 5, rejected="accepted-source-has-errors"
            )
            check(6, "lib.rs", MAIN, "resident", 0)
            build("type-error-repair", 6, test_exit=0)
            write("other.rs", scalar(OTHER, "false"))
            build(
                "unchecked-edit",
                6,
                rejected="source-on-disk-does-not-match-accepted-revision",
            )
            write("other.rs", OTHER)
            build("unchecked-edit-restored", 6, test_exit=0)
            unsupported = OTHER.replace("unrelated() -> bool", "unrelated() -> char")
            check(7, "other.rs", unsupported, "fallback")
            build(
                "unsupported-edit",
                7,
                rejected="source-revision-requires-fresh-compiler",
            )
            check(8, "other.rs", OTHER, "noop", 0)
            build("unsupported-edit-restored", 8, test_exit=0)
            check(9, "lib.rs", scalar(MAIN, "false"), "resident", 0)
            check(10, "lib.rs", scalar(MAIN, "false"), "noop", 0)
            build("behavior-after-duplicate-check", 10, test_exit=101)
            check(11, "lib.rs", MAIN, "resident", 0)
            build("final-repair", 11, test_exit=0)
            send("quit")
            receive("bye")
            require(
                process.wait(timeout=args.timeout) == 0, "worker did not exit cleanly"
            )
        finally:
            worker.close()

    if not args.no_cache:
        first, unchanged = observations[:2]
        require(
            all(unit["mode"] == "compiled" for unit in first["units"]),
            "first build reused unknown objects",
        )
        require(
            all(unit["mode"] == "reused" for unit in unchanged["units"]),
            "unchanged build recompiled an object",
        )
        first_hashes = {unit["name"]: unit["hash"] for unit in first["units"]}
        unchanged_hashes = {unit["name"]: unit["hash"] for unit in unchanged["units"]}
        require(
            first_hashes == unchanged_hashes,
            "unchanged build returned different object hashes",
        )
        previous = first_hashes
        for observation in observations[1:]:
            if "units" not in observation:
                continue
            current = {unit["name"]: unit["hash"] for unit in observation["units"]}
            for unit in observation["units"]:
                if unit["mode"] == "reused":
                    require(
                        previous.get(unit["name"]) == unit["hash"],
                        "reused object has a different fingerprint",
                    )
            if observation["name"] in (
                "behavior-edit",
                "behavior-repair",
                "behavior-after-duplicate-check",
                "final-repair",
            ):
                require(
                    any(unit["mode"] == "compiled" for unit in observation["units"]),
                    "a behavior-changing build reused all objects",
                )
                require(
                    any(unit["mode"] == "reused" for unit in observation["units"]),
                    "a behavior-changing build rebuilt all objects",
                )
                require(
                    any(previous.get(name) != value for name, value in current.items()),
                    "a behavior-changing build produced no different object",
                )
            previous = current
    return {
        "schema_version": 2,
        "passed": len(observations),
        "same_pid_until_quit": True,
        "pid": pid,
        "cache_enabled": not args.no_cache,
        "requests": observations,
    }


def linker_failure_probe(args):
    if os.name != "posix":
        return {"status": "skipped", "reason": "requires a POSIX linker wrapper"}
    linker = args.linker or shutil.which("cc")
    if not linker:
        return {"status": "skipped", "reason": "no host C compiler found for linking"}
    linker = Path(linker).resolve()
    require(
        linker.is_file() and os.access(linker, os.X_OK),
        "specified linker is not executable",
    )

    directory = args.output / "linker-failure"
    directory.mkdir()
    source = directory / "lib.rs"
    source.write_text(LINKER_SOURCE)
    artifact = directory / "test"
    marker = directory / "induce-failure"
    wrapper = directory / "linker"
    wrapper.write_text(
        '#!/bin/sh\nif test -f "$OHM_GUARD_LINKER_FAILURE"; then\n'
        f"  printf '%s\\n' '{LINKER_FAILURE}' >&2\n"
        '  exit 71\nfi\nexec "$OHM_GUARD_REAL_LINKER" "$@"\n'
    )
    wrapper.chmod(0o755)
    environment = dict(
        os.environ,
        OHM_RUFF_SOURCE_MODE="resident-repeat-build",
        RUSTC_BOOTSTRAP="1",
        OHM_GUARD_REAL_LINKER=str(linker),
        OHM_GUARD_LINKER_FAILURE=str(marker),
    )
    if args.no_cache:
        environment.pop("OHM_RUFF_CODEGEN_CACHE", None)
    else:
        environment["OHM_RUFF_CODEGEN_CACHE"] = str(directory / "codegen-cache")
    command = [
        str(args.driver),
        "--edition=2024",
        "--sysroot",
        str(args.stage),
        "-Zohm-resident-query-graph",
        "--error-format=json",
        "--test",
        "--crate-name",
        "resident_repeated_linker_guard",
        str(source),
        "-o",
        str(artifact),
        f"-Clinker={wrapper}",
    ]
    diagnostics = directory / "compiler.stderr"
    with diagnostics.open("w") as stderr:
        process = subprocess.Popen(
            command,
            cwd=directory,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
        )
        worker = Worker(process, args.timeout, directory / "protocol.txt")

        def build(version):
            worker.send(f"build\t{version}")
            _, reply = worker.receive("build")
            require(
                reply == [str(version), "ready", "-"],
                f"linker build not ready: {reply}",
            )
            _, analysis = worker.receive("build-analysis")
            require(
                analysis[0] == str(version), f"wrong linker build analysis: {analysis}"
            )
            while True:
                event, fields = worker.receive()
                require(
                    fields[0] == str(version), f"wrong linker build version: {fields}"
                )
                if event == "build-finished":
                    return fields[2]
                require(
                    event == "build-codegen-unit",
                    f"unexpected linker build event: {event}",
                )

        try:
            _, ready = worker.receive("ready")
            pid = int(ready[0])
            require(
                pid == process.pid, "linker fixture worker reported a different PID"
            )
            require(build(0) == "ok", "initial linker fixture build failed")
            test = subprocess.run(
                [str(artifact), "--exact", "test_behavior"],
                capture_output=True,
                text=True,
                timeout=args.timeout,
                check=False,
            )
            require(
                test.returncode == 0,
                f"initial linker fixture test failed: {test.stdout}",
            )
            original = fingerprint(artifact)

            marker.touch()
            require(build(0) == "failed", "injected linker failure was not reported")
            require(
                fingerprint(artifact) == original,
                "linker failure replaced the earlier executable",
            )
            marker.unlink()

            source.write_text(scalar(LINKER_SOURCE, "false"))
            worker.send(f"check\t1\t{source}")
            _, checked = worker.receive("result")
            require(
                checked[:3] == ["1", "fallback", "previous-codegen-failed"],
                f"poisoned worker handled a later edit: {checked}",
            )
            worker.send("build\t1")
            _, rejected = worker.receive("build")
            require(
                rejected == ["1", "rejected", "previous-codegen-failed"],
                f"poisoned worker accepted a later build: {rejected}",
            )
            require(
                fingerprint(artifact) == original,
                "poisoned worker replaced the earlier executable",
            )
            worker.send("quit")
            worker.receive("bye")
            require(
                process.wait(timeout=args.timeout) == 0, "linker worker failed to quit"
            )
        finally:
            worker.close()

    logs = diagnostics.read_text()
    require(LINKER_FAILURE in logs, "rustc did not emit the injected linker diagnostic")
    return {
        "status": "passed",
        "same_pid_until_quit": True,
        "pid": pid,
        "baseline": {"build": "ok", "test_ran": True, "test_exit": test.returncode},
        "injected_failure": {
            "build": "failed",
            "diagnostic_confirmed": True,
            "test_ran": False,
            "stale_artifact_preserved": True,
        },
        "later_edit": {"mode": "fallback", "reason": "previous-codegen-failed"},
        "later_build": {
            "mode": "rejected",
            "reason": "previous-codegen-failed",
            "test_ran": False,
            "stale_artifact_preserved": True,
        },
        "worker_exit": 0,
    }


def portable(result):
    probe = dict(result["linker_failure_probe"])
    probe.pop("pid", None)
    if "same_pid_until_quit" in probe:
        probe["single_compiler_process_until_quit"] = probe.pop("same_pid_until_quit")
    return {
        "schema_version": result["schema_version"],
        "passed": result["passed"],
        "single_compiler_process_until_quit": result["same_pid_until_quit"],
        "resident_codegen_cache_enabled": result["cache_enabled"],
        "method": "One native rustc process built and linked a real two-module Rust test fixture. Every accepted build ran the emitted exact test; rejected builds never ran it and the prior executable SHA-256 stayed identical. When the resident cache is enabled, the compiler reports a stable fingerprint of regular object bytes and optional associated object files; behavior changes must rebuild and reuse different units, change an object fingerprint, and keep reused fingerprints equal to the preceding successful build. The separate linker-failure fixture uses one additional compiler process and a host C compiler wrapper to fail the next link deliberately.",
        "requests": result["requests"],
        "linker_failure_probe": probe,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--linker", type=Path, help="host C compiler to delegate to (defaults to cc)"
    )
    args = parser.parse_args()
    args.driver = args.driver.resolve()
    args.stage = args.stage.resolve()
    args.output = args.output.resolve()
    result = run(args)
    result["linker_failure_probe"] = linker_failure_probe(args)
    (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.output / "publish-summary.json").write_text(
        json.dumps(portable(result), indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "requests": len(result["requests"]),
                "same_pid_until_quit": True,
                "linker_failure_probe": result["linker_failure_probe"]["status"],
            }
        )
    )


if __name__ == "__main__":
    main()
