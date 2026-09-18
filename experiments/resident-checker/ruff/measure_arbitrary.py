#!/usr/bin/env python3
"""Compare arbitrary edits in one rustc-driver process with fresh, incremental rustc."""

import argparse
import hashlib
import json
import os
import re
import statistics
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

from measure import machine, write_json

SUMMARY = re.compile(
    r"test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
    r"(\d+) measured; (\d+) filtered out; finished in .*"
)
TEST = re.compile(r"^test (\S+) \.\.\. (ok|FAILED|ignored)$", re.MULTILINE)
PANIC_THREAD_ID = re.compile(r"(thread '[^'\n]+' \()\d+(\) panicked at )")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def now():
    return time.perf_counter_ns()


def error_diagnostics(text):
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("reason") == "compiler-message":
            item = item["message"]
        if item.get("level") != "error" or not item.get("spans"):
            continue
        yield item


def source_diagnostics(text):
    diagnostics = []
    for item in error_diagnostics(text):
        code = item.get("code") or {}
        diagnostics.append({"code": code.get("code"), "message": item["message"]})
    return diagnostics


def diagnostic_locations(text):
    return [
        [
            {
                "file": Path(span["file_name"]).name,
                "line_start": span["line_start"],
                "line_end": span["line_end"],
                "column_start": span["column_start"],
                "column_end": span["column_end"],
            }
            for span in item["spans"]
            if span.get("is_primary")
        ]
        for item in error_diagnostics(text)
    ]


def rust_environment(stage):
    environment = dict(os.environ, RUST_BACKTRACE="0", TERM="dumb")
    for key in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
        prior = environment.get(key)
        environment[key] = str(stage / "lib") + (os.pathsep + prior if prior else "")
    return environment


def _read_lines(pipe, queue):
    for line in pipe:
        queue.put(line.rstrip("\n"))
    queue.put(None)


class Worker:
    def __init__(self, command, cwd, environment, logs, timeout=60):
        self.timeout = timeout
        self.logs = logs
        logs.mkdir(parents=True, exist_ok=True)
        self.stderr_path = logs / "compiler.stderr"
        self.stderr = self.stderr_path.open("wb")
        self.transcript = (logs / "protocol.txt").open("w")
        self.process = None
        self.thread = None
        self.queue = Queue()
        started = now()
        try:
            self.process = subprocess.Popen(
                command,
                cwd=cwd,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.stderr,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            self.thread = Thread(
                target=_read_lines, args=(self.process.stdout, self.queue), daemon=True
            )
            self.thread.start()
            ready = self.receive("ready")
            require(
                ready == [str(self.process.pid)],
                f"driver startup PID differs from spawned PID: {ready}",
            )
            self.pid = self.process.pid
            self.startup_ns = now() - started
        except BaseException:
            self.close()
            raise

    def receive(self, kind):
        try:
            line = self.queue.get(timeout=self.timeout)
        except Empty:
            raise RuntimeError(
                f"timed out waiting for {kind}; see {self.stderr_path}"
            ) from None
        require(line is not None, f"driver closed stdout; see {self.stderr_path}")
        self.transcript.write(line + "\n")
        self.transcript.flush()
        received, *arguments = line.split("\t")
        require(received == kind, f"expected {kind}, got {line!r}")
        return arguments

    def send(self, request):
        require(self.process.poll() is None, "driver died between requests")
        self.process.stdin.write(request + "\n")
        self.process.stdin.flush()

    def compile(self, version):
        offset = self.stderr_path.stat().st_size
        started = now()
        self.send(f"compile\t{version}")
        response = self.receive("result")
        ended = now()
        require(len(response) == 4, f"malformed compile response: {response}")
        emitted_version, pid, status, internal = map(int, response)
        require(emitted_version == version, f"wrong compile version: {response}")
        require(pid == self.pid, f"compiler changed PID: {response}")
        require(self.process.poll() is None, f"driver exited after revision {version}")
        with self.stderr_path.open("rb") as reader:
            reader.seek(offset)
            raw = reader.read().decode("utf-8")
        require(
            raw.splitlines()[-1:] == [f"resident-finished\t{version}"],
            f"compiler diagnostics lack their completion marker: {response}: {raw}",
        )
        routes = [
            line.split("\t")[2:]
            for line in raw.splitlines()
            if line.startswith(f"resident-route\t{version}\t")
        ]
        require(
            len(routes) == 1 and len(routes[0]) == 2, f"missing compiler route: {raw}"
        )
        route, compiler_pid = routes[0]
        (self.logs / f"compiler-{version:04}.stderr").write_text(raw)
        return {
            "status": status,
            "internal_ns": internal,
            "external_ns": ended - started,
            "diagnostics": source_diagnostics(raw),
            "diagnostic_locations": diagnostic_locations(raw),
            "pid": pid,
            "route": route,
            "compiler_pid": int(compiler_pid),
        }

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            if self.thread is not None:
                self.thread.join(timeout=self.timeout)
            for pipe in (self.process.stdin, self.process.stdout):
                if pipe is not None:
                    pipe.close()
        self.stderr.close()
        self.transcript.close()

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        try:
            if exception_type is None:
                self.send("quit")
                require(self.receive("bye") == [str(self.pid)], "wrong shutdown PID")
                require(
                    self.process.wait(timeout=self.timeout) == 0,
                    "compiler did not exit cleanly",
                )
        finally:
            self.close()


def fresh_compile(command, cwd, environment, logs, version, timeout=60):
    logs.mkdir(parents=True, exist_ok=True)
    started = now()
    with subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
        ended = now()
        (logs / f"compiler-{version:04}.stdout").write_text(stdout)
        (logs / f"compiler-{version:04}.stderr").write_text(stderr)
        return {
            "status": process.returncode,
            "internal_ns": None,
            "external_ns": ended - started,
            "diagnostics": source_diagnostics(stderr),
            "diagnostic_locations": diagnostic_locations(stderr),
            "pid": process.pid,
        }


def source_files(
    *, mode="base", macro=6, imported="calculate", extra=None, missing=False
):
    signature = mode in {"signature", "type-error"}
    if mode == "malformed":
        body = "let broken = ; input * 2"
    elif mode == "multi":
        body = "adjust(input) * 2"
    elif mode == "type-error":
        body = 'let answer: i32 = "wrong"; answer + offset'
    elif signature:
        body = "adjust(input) * 2 + offset"
    else:
        body = "adjust(input) * 2"
    parameters = "input: i32, offset: i32" if signature else "input: i32"
    adjust = "input + 1" if mode == "multi" else "input"
    alternative = (
        "pub fn alternative(input: i32, offset: i32) -> i32 { calculate(input, offset) + 1 }"
        if signature
        else "pub fn alternative(input: i32) -> i32 { calculate(input) + 1 }"
    )
    model = f"""pub fn calculate({parameters}) -> i32 {{ {body} }}
fn adjust(input: i32) -> i32 {{ {adjust} }}
pub fn sentinel() -> i32 {{ adjust(4) }}
{alternative}
"""
    arguments = "2, 2" if signature else "3"
    modules = ("mod extra;\n" if extra is not None else "") + (
        "mod missing;\n" if missing else ""
    )
    extra_test = (
        "    #[test]\n    fn extra_module() { assert_eq!(super::extra::contribution(), 10); }\n"
        if extra is not None
        else ""
    )
    lib = f"""#![allow(dead_code)]
mod model;
{modules}use model::{imported} as compute;
macro_rules! expected {{ () => {{ {macro} }}; }}
#[cfg(test)]
mod tests {{
    #[test]
    fn behavior() {{ assert_eq!(super::compute({arguments}), expected!()); }}
    #[test]
    fn helper() {{ assert_eq!(super::model::sentinel(), 4); }}
{extra_test}}}
"""
    files = {"lib.rs": lib, "model.rs": model}
    if extra is not None:
        files["extra.rs"] = f"pub fn contribution() -> i32 {{ {extra} }}\n"
    return files


@dataclass(frozen=True)
class Case:
    name: str
    files: dict
    failed_tests: tuple = ()
    diagnostic: tuple | None = None

    @property
    def tests(self):
        if self.diagnostic:
            return {}
        names = {"tests::behavior", "tests::helper"}
        if "extra.rs" in self.files:
            names.add("tests::extra_module")
        return {
            name: "FAILED" if name in self.failed_tests else "ok"
            for name in sorted(names)
        }


PARSE_ERROR = (None, "expected expression, found `;`")
TYPE_ERROR = ("E0308", "mismatched types")
MISSING_ERROR = ("E0583", "file not found for module `missing`")
CASES = (
    Case("initial-malformed", source_files(mode="malformed"), diagnostic=PARSE_ERROR),
    Case("initial-repair", source_files()),
    Case(
        "multiple-function-bodies",
        source_files(mode="multi"),
        failed_tests=("tests::behavior", "tests::helper"),
    ),
    Case("multiple-function-repair", source_files()),
    Case("signature-and-callers", source_files(mode="signature")),
    Case(
        "macro-definition",
        source_files(mode="signature", macro=7),
        failed_tests=("tests::behavior",),
    ),
    Case("macro-repair", source_files(mode="signature")),
    Case(
        "import-resolution",
        source_files(mode="signature", imported="alternative"),
        failed_tests=("tests::behavior",),
    ),
    Case("import-repair", source_files(mode="signature")),
    Case("module-added", source_files(mode="signature", extra=10)),
    Case(
        "module-behavior",
        source_files(mode="signature", extra=11),
        failed_tests=("tests::extra_module",),
    ),
    Case("module-removed", source_files(mode="signature")),
    Case("type-error", source_files(mode="type-error"), diagnostic=TYPE_ERROR),
    Case("type-error-repair", source_files(mode="signature")),
    Case(
        "malformed-after-build", source_files(mode="malformed"), diagnostic=PARSE_ERROR
    ),
    Case("malformed-repair", source_files(mode="signature")),
    Case(
        "missing-module",
        source_files(mode="signature", missing=True),
        diagnostic=MISSING_ERROR,
    ),
    Case("missing-module-repair", source_files(mode="signature")),
)


def write_sources(directory, files):
    for path in directory.glob("*.rs"):
        if path.name not in files:
            path.unlink()
    for name, content in files.items():
        path = directory / name
        if not path.exists() or path.read_text() != content:
            path.write_text(content)


def fingerprint(path):
    if not path.is_file():
        return None
    with path.open("rb") as artifact:
        return hashlib.file_digest(artifact, "sha256").hexdigest()


def test_output(stdout, stderr):
    text = stdout + stderr
    summaries = list(SUMMARY.finditer(text))
    require(len(summaries) == 1, f"expected exactly one libtest summary: {text}")
    matches = list(TEST.finditer(text))
    tests = {match[1]: match[2] for match in matches}
    require(len(tests) == len(matches), f"duplicate tests in libtest output: {text}")
    return {
        "tests": tests,
        "counts": list(map(int, summaries[0].groups())),
        "normalized_output": PANIC_THREAD_ID.sub(
            r"\g<1><thread id removed>\g<2>",
            SUMMARY.sub("test result: <timing removed>", text),
        ).strip(),
    }


def run_test(binary, cwd, environment, logs, version, timeout):
    started = now()
    result = subprocess.run(
        [str(binary), "--test-threads=1", "--color", "never"],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    ended = now()
    (logs / f"tests-{version:04}.stdout").write_text(result.stdout)
    (logs / f"tests-{version:04}.stderr").write_text(result.stderr)
    return {
        "status": result.returncode,
        "external_ns": ended - started,
        **test_output(result.stdout, result.stderr),
    }


def run_revision(compile_case, case, binary, cwd, environment, logs, version, timeout):
    old_binary = fingerprint(binary)
    result = compile_case(version)
    require(
        result["status"] in (0, 1), f"rustc unexpectedly exited: {case.name}: {result}"
    )
    result["test"] = None
    result["stale_artifact_preserved"] = None
    if case.diagnostic:
        require(
            result["status"] == 1, f"{case.name}: compile error succeeded: {result}"
        )
        expected_code, fragment = case.diagnostic
        require(
            any(
                diagnostic["code"] == expected_code
                and fragment in diagnostic["message"]
                for diagnostic in result["diagnostics"]
            ),
            f"{case.name}: expected diagnostic {case.diagnostic}: {result}",
        )
        after = fingerprint(binary)
        require(
            old_binary == after, f"{case.name}: rejected edit changed the old binary"
        )
        result["stale_artifact_preserved"] = old_binary is not None
        return result
    require(result["status"] == 0, f"{case.name}: compilation failed: {result}")
    require(not result["diagnostics"], f"{case.name}: unexpected diagnostic: {result}")
    require(binary.is_file(), f"{case.name}: compilation emitted no test executable")
    result["test"] = test = run_test(binary, cwd, environment, logs, version, timeout)
    require(test["tests"] == case.tests, f"{case.name}: incorrect tests: {test}")
    require(
        test["status"] == (101 if case.failed_tests else 0),
        f"{case.name}: wrong test exit status: {test}",
    )
    require(
        test["counts"]
        == [len(case.tests) - len(case.failed_tests), len(case.failed_tests), 0, 0, 0],
        f"{case.name}: wrong libtest summary: {test}",
    )
    return result


def compare(case, first, second):
    require(
        first["status"] == second["status"], f"{case.name}: compiler statuses differ"
    )
    require(
        first["diagnostics"] == second["diagnostics"],
        f"{case.name}: diagnostics differ: {first['diagnostics']} versus {second['diagnostics']}",
    )
    require(
        first["diagnostic_locations"] == second["diagnostic_locations"],
        f"{case.name}: source diagnostic locations differ: {first['diagnostic_locations']} versus {second['diagnostic_locations']}",
    )
    require(
        (first["test"] is None) == (second["test"] is None),
        f"{case.name}: only one mode ran tests",
    )
    if first["test"] is not None:
        for field in ("status", "tests", "counts", "normalized_output"):
            require(
                first["test"][field] == second["test"][field],
                f"{case.name}: test {field} differs: {first['test'][field]} versus {second['test'][field]}",
            )


def compiler_command(executable, stage, source, binary, incremental, debuginfo):
    incremental.mkdir(parents=True, exist_ok=True)
    binary.parent.mkdir(parents=True, exist_ok=True)
    return [
        str(executable),
        "--edition=2024",
        "--crate-name",
        "arbitrary_edit_fixture",
        "--test",
        "--error-format=json",
        "--sysroot",
        str(stage),
        "-Copt-level=0",
        "-Ccodegen-units=8",
        f"-Cdebuginfo={debuginfo}",
        "-Csplit-debuginfo=off",
        f"-Cincremental={incremental}",
        str(source),
        "-o",
        str(binary),
    ]


def median(items):
    return int(statistics.median(items)) if items else None


def compact(rows, cases):
    summary = []
    for case in cases:
        case_rows = [row for row in rows if row["case"] == case.name]
        modes = {}
        for mode in ("persistent-driver", "fresh-rustc"):
            results = [row[mode] for row in case_rows]
            first = results[0]
            modes[mode] = {
                "compile_status": first["status"],
                "diagnostics": first["diagnostics"],
                "diagnostic_locations": first["diagnostic_locations"],
                "tests_executed": first["test"] is not None,
                "test_statuses": first["test"]["tests"] if first["test"] else {},
                "existing_stale_artifacts_not_run": sum(
                    result["stale_artifact_preserved"] is True for result in results
                ),
                "compile_external_median_ns": median(
                    [result["external_ns"] for result in results]
                ),
                "compile_internal_median_ns": median(
                    [
                        result["internal_ns"]
                        for result in results
                        if result["internal_ns"] is not None
                    ]
                ),
                "test_external_median_ns": median(
                    [
                        result["test"]["external_ns"]
                        for result in results
                        if result["test"]
                    ]
                ),
            }
        summary.append({"case": case.name, "modes": modes})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--rustc", type=Path, required=True)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--compiler-revision")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--debuginfo", default="line-tables-only")
    args = parser.parse_args()
    require(
        args.rounds > 0 and args.warmups >= 0 and args.timeout > 0,
        "invalid rounds, warmups or timeout",
    )
    stage = (
        args.stage
        or Path(
            subprocess.check_output(
                [str(args.rustc.resolve()), "--print", "sysroot"], text=True
            ).strip()
        )
    ).resolve()
    driver, rustc, output = (
        args.driver.resolve(),
        args.rustc.resolve(),
        args.output.resolve(),
    )
    output.mkdir(parents=True, exist_ok=True)
    work = output / "work"
    require(not work.exists(), f"refusing to reuse benchmark files: {work}")
    source = work / "source"
    source.mkdir(parents=True)
    environment = rust_environment(stage)
    environment["OHM_ARBITRARY_REUSE_PROCESS"] = "1"
    modes = ("persistent-driver", "fresh-rustc")
    binaries = {
        mode: work / mode / ("fixture.exe" if os.name == "nt" else "fixture")
        for mode in modes
    }
    commands = {
        mode: compiler_command(
            executable,
            stage,
            source / "lib.rs",
            binaries[mode],
            work / mode / "incremental",
            args.debuginfo,
        )
        for mode, executable in zip(modes, (driver, rustc), strict=True)
    }
    logs = {mode: output / "logs" / mode for mode in modes}
    for directory in logs.values():
        directory.mkdir(parents=True)
    rows, fresh_pids, driver_pids = [], set(), set()
    stale_guarded = {mode: 0 for mode in modes}
    with Worker(
        commands[modes[0]], source, environment, logs[modes[0]], args.timeout
    ) as worker:
        for round_number in range(-args.warmups, args.rounds):
            for index, case in enumerate(CASES):
                version = (round_number + args.warmups) * len(CASES) + index + 1
                write_sources(source, case.files)
                order = modes if (version % 2) else tuple(reversed(modes))
                row = {"round": round_number, "case": case.name}
                for mode in order:

                    def compile_case(version, mode=mode):
                        if mode == modes[0]:
                            return worker.compile(version)
                        return fresh_compile(
                            commands[mode],
                            source,
                            environment,
                            logs[mode],
                            version,
                            args.timeout,
                        )

                    result = run_revision(
                        compile_case,
                        case,
                        binaries[mode],
                        source,
                        environment,
                        logs[mode],
                        version,
                        args.timeout,
                    )
                    row[mode] = result
                    if mode == modes[0]:
                        require(
                            result["route"] == "same-process"
                            and result["compiler_pid"] == worker.pid,
                            f"fixture did not compile in the coordinator process: {result}",
                        )
                    if result["stale_artifact_preserved"]:
                        stale_guarded[mode] += 1
                    (driver_pids if mode == modes[0] else fresh_pids).add(result["pid"])
                compare(case, row[modes[0]], row[modes[1]])
                if round_number >= 0:
                    rows.append(row)
        require(
            driver_pids == {worker.pid},
            f"more than one persistent driver PID: {driver_pids}",
        )
        require(
            len(fresh_pids) > 1, "fresh comparator did not use independent processes"
        )
        require(
            all(stale_guarded.values()),
            "neither mode tested preservation of an old executable",
        )
        report = {
            "benchmark": "arbitrary-edits-persistent-driver-vs-fresh-rustc",
            "machine": machine(),
            "compiler": subprocess.check_output(
                [str(rustc), "-vV"], env=environment, text=True
            )
            .strip()
            .splitlines(),
            "compiler_source_revision": args.compiler_revision,
            "profile": {
                "debug_info": args.debuginfo,
                "split_debug_info": "off",
                "opt_level": 0,
                "codegen_units": 8,
                "separate_persistent_disk_incremental_directories": True,
            },
            "rounds": args.rounds,
            "warmup_rounds": args.warmups,
            "matched_revisions": len(rows),
            "single_driver_pid": len(driver_pids) == 1,
            "single_compiler_pid": True,
            "compiler_route": "same-process",
            "fixture_has_no_procedural_macros": True,
            "fresh_compiler_processes_including_warmups": len(fresh_pids),
            "driver_startup_ns": worker.startup_ns,
            "stale_artifacts_not_run_including_warmups": stale_guarded,
            "medians": {
                mode: {
                    "compile_external_ns": median(
                        [row[mode]["external_ns"] for row in rows]
                    ),
                    "successful_compile_external_ns": median(
                        [
                            row[mode]["external_ns"]
                            for row in rows
                            if row[mode]["status"] == 0
                        ]
                    ),
                    "compile_error_external_ns": median(
                        [
                            row[mode]["external_ns"]
                            for row in rows
                            if row[mode]["status"] != 0
                        ]
                    ),
                    "test_external_ns": median(
                        [
                            row[mode]["test"]["external_ns"]
                            for row in rows
                            if row[mode]["test"]
                        ]
                    ),
                }
                for mode in modes
            },
            "cases": compact(rows, CASES),
        }
    write_json(output / "summary.json", report)
    print(
        json.dumps(
            {
                "matched_revisions": report["matched_revisions"],
                "single_driver_pid": report["single_driver_pid"],
                "medians": report["medians"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
