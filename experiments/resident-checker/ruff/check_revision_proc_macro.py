#!/usr/bin/env python3
"""Prove that a fresh compiler process isolates procedural macro globals per revision."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

MARKER = "revision isolation fixture: procedural macro already ran in this process"
MACRO = r"""
extern crate proc_macro;

use proc_macro::TokenStream;
use std::sync::atomic::{AtomicUsize, Ordering};

static INVOCATIONS: AtomicUsize = AtomicUsize::new(0);

#[proc_macro]
pub fn once(input: TokenStream) -> TokenStream {
    if INVOCATIONS.fetch_add(1, Ordering::SeqCst) == 0 {
        input
    } else {
        r#"compile_error!("revision isolation fixture: procedural macro already ran in this process")"#
            .parse()
            .unwrap()
    }
}
"""
CONSUMER = """
const REVISION: usize = revision_stateful::once!({revision});

#[test]
fn expansion_used_current_source() {{
    let expected = std::env::var("OHM_FIXTURE_REVISION").unwrap().parse::<usize>().unwrap();
    assert_eq!(REVISION, expected);
}}
"""


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def rust_environment(stage):
    environment = dict(os.environ, RUST_BACKTRACE="0", TERM="dumb")
    for key in ("OHM_ARBITRARY_COMPILER_CHILD", "OHM_ARBITRARY_REUSE_PROCESS"):
        environment.pop(key, None)
    for key in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
        prior = environment.get(key)
        environment[key] = str(stage / "lib") + (os.pathsep + prior if prior else "")
    return environment


def rustc(command, environment, directory, timeout):
    result = subprocess.run(
        command,
        cwd=directory,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    require(
        result.returncode == 0,
        f"command {command} exited {result.returncode}:\n{result.stdout}\n{result.stderr}",
    )
    return result


def read_lines(stream, queue):
    for line in stream:
        queue.put(line.rstrip("\n"))
    queue.put(None)


def receive(queue, process, kind, transcript, timeout):
    try:
        line = queue.get(timeout=timeout)
    except Empty:
        raise RuntimeError(f"timed out waiting for {kind}") from None
    require(line is not None, f"driver exited before {kind}: {process.poll()}")
    transcript.write(line + "\n")
    transcript.flush()
    actual, *fields = line.split("\t")
    require(actual == kind, f"expected {kind}, got {line!r}")
    return fields


def send(process, line):
    require(process.poll() is None, f"driver exited before {line!r}")
    process.stdin.write(line + "\n")
    process.stdin.flush()


def fingerprint(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def errors(text):
    result = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("level") == "error" and item.get("spans"):
            result.append(item["message"])
    return result


def run_route(args, route, library, environment):
    directory = args.output / route
    directory.mkdir()
    source = directory / "consumer.rs"
    binary = directory / ("consumer.exe" if os.name == "nt" else "consumer")
    error_path = directory / "compiler.stderr"
    command = [
        str(args.driver),
        "--sysroot",
        str(args.stage),
        "--edition=2024",
        "--error-format=json",
        "--crate-name=revision_macro_consumer",
        "--test",
        str(source),
        "--extern",
        f"revision_stateful={library}",
        "-o",
        str(binary),
    ]
    environment = dict(environment)
    reused = route == "same-process"
    if reused:
        environment["OHM_ARBITRARY_REUSE_PROCESS"] = "1"
    results = []
    with (
        error_path.open("wb") as stderr,
        (directory / "protocol.txt").open("w") as transcript,
    ):
        process = subprocess.Popen(
            command,
            cwd=directory,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            bufsize=1,
        )
        queue = Queue()
        thread = Thread(target=read_lines, args=(process.stdout, queue), daemon=True)
        thread.start()

        def next_line(kind):
            return receive(queue, process, kind, transcript, args.timeout)

        try:
            require(next_line("ready") == [str(process.pid)], "wrong startup PID")
            for revision in (1, 2):
                source.write_text(CONSUMER.format(revision=revision))
                old_hash = fingerprint(binary) if binary.is_file() else None
                offset = error_path.stat().st_size
                send(process, f"compile\t{revision}")
                fields = next_line("result")
                require(len(fields) == 4, f"unexpected result: {fields}")
                emitted, driver_pid, status, elapsed = map(int, fields)
                require(
                    (emitted, driver_pid) == (revision, process.pid) and elapsed > 0,
                    f"unexpected result: {fields}",
                )
                with error_path.open("rb") as reader:
                    reader.seek(offset)
                    raw = reader.read().decode()
                (directory / f"revision-{revision}.stderr").write_text(raw)
                lines = raw.splitlines()
                require(
                    lines[0] == f"resident-started\t{revision}"
                    and lines[-1] == f"resident-finished\t{revision}",
                    f"missing diagnostic markers: {raw}",
                )
                routes = [
                    line.split("\t")[2:]
                    for line in lines
                    if line.startswith(f"resident-route\t{revision}\t")
                ]
                require(
                    len(routes) == 1 and len(routes[0]) == 2 and routes[0][0] == route,
                    f"unexpected compiler route: {raw}",
                )
                compiler_pid = int(routes[0][1])
                messages = errors(raw)
                should_fail = reused and revision == 2
                require(
                    (status != 0) == should_fail,
                    f"unexpected exit for {route} revision {revision}: {raw}",
                )
                if should_fail:
                    require(messages == [MARKER], f"wrong compiler errors: {messages}")
                    require(
                        old_hash is not None and old_hash == fingerprint(binary),
                        "failing compilation replaced the previous test executable",
                    )
                else:
                    require(not messages, f"unexpected compiler errors: {messages}")
                    result = rustc(
                        [str(binary), "--exact", "expansion_used_current_source"],
                        dict(environment, OHM_FIXTURE_REVISION=str(revision)),
                        directory,
                        args.timeout,
                    )
                    require(
                        "1 passed; 0 failed" in result.stdout,
                        f"the new test binary did not pass: {result.stdout}",
                    )
                results.append(
                    {
                        "compiler_pid": compiler_pid,
                        "diagnostic": messages[0] if messages else None,
                        "status": status,
                        "test_executed": not should_fail,
                        "prior_executable_preserved": (
                            old_hash == fingerprint(binary)
                            if old_hash is not None
                            else None
                        ),
                    }
                )
            send(process, "quit")
            require(next_line("bye") == [str(process.pid)], "wrong shutdown PID")
            require(
                process.wait(timeout=args.timeout) == 0, "driver did not exit cleanly"
            )
            pids = [result.pop("compiler_pid") for result in results]
            require(
                (pids[0] == pids[1] == process.pid)
                if reused
                else (len(set(pids)) == 2 and process.pid not in pids),
                f"wrong actual compiler PIDs for {route}: {pids}; driver: {process.pid}",
            )
            return {
                "distinct_compiler_processes": len(set(pids)),
                "compiler_is_driver_process": reused,
                "revisions": results,
            }
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=args.timeout)
            thread.join(timeout=args.timeout)
            process.stdin.close()
            process.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("driver", "stage", "output"):
        parser.add_argument(
            f"--{name}", type=lambda value: Path(value).resolve(), required=True
        )
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    require(args.timeout > 0, "timeout must be positive")
    args.output.mkdir(parents=True)
    environment = rust_environment(args.stage)
    macro_source = args.output / "macro.rs"
    macro_source.write_text(MACRO)
    macro_command = [
        str(args.stage / "bin" / ("rustc.exe" if os.name == "nt" else "rustc")),
        "--sysroot",
        str(args.stage),
        "--edition=2024",
        "--crate-type=proc-macro",
        "--crate-name=revision_stateful",
        str(macro_source),
    ]
    filenames = rustc(
        [*macro_command, "--print=file-names"], environment, args.output, args.timeout
    ).stdout.splitlines()
    require(len(filenames) == 1, f"expected one procedural macro library: {filenames}")
    library = args.output / filenames[0]
    rustc([*macro_command, "-o", str(library)], environment, args.output, args.timeout)
    require(
        library.is_file(), f"rustc did not create procedural macro library {library}"
    )
    report = {
        "fixture": "stateful procedural macro succeeds only on first expansion in a process",
        "disk_incremental": False,
        "macro_library_changed_between_revisions": False,
        "default": run_route(args, "fresh-process", library, environment),
        "explicit_process_reuse": run_route(args, "same-process", library, environment),
    }
    output = json.dumps(report, indent=2) + "\n"
    (args.output / "summary.json").write_text(output)
    print(output, end="")


if __name__ == "__main__":
    main()
