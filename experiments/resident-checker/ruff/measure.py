#!/usr/bin/env python3
"""Measure real Ruff parser edits in a resident compiler and fresh compiler processes."""

import argparse
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from run_edits import arguments, diagnostic, normalized
from run_tests import PACKAGE, REVISION, archive_ruff

CASES = {
    "unicode-identifier": {
        "file": "src/lexer.rs",
        "owner": "lexer::is_unicode_identifier_start",
        "anchor": "    is_xid_start(c)\n",
        "expression": "is_xid_start(c)",
    },
    "parse-octet": {
        "file": "src/string.rs",
        "owner": "string::StringParser::parse_octet",
        "anchor": "        char::from_u32(value).unwrap()\n",
        "expression": "char::from_u32(value).unwrap()",
    },
    "token-set": {
        "file": "src/parser/mod.rs",
        "owner": "parser::Parser::at_ts",
        "anchor": "        ts.contains(self.current_token_kind())\n",
        "expression": "ts.contains(self.current_token_kind())",
    },
    "parse-atom": {
        "file": "src/parser/expression.rs",
        "owner": "parser::Parser::parse_atom",
        "anchor": "\n        lhs.into()\n    }\n\n    /// Parses a postfix expression",
        "expression": "lhs.into()",
    },
}
DEFAULT_CASES = ("unicode-identifier", "parse-octet", "parse-atom")
METRICS = (
    "external_ns",
    "analysis_ns",
    "edit_ns",
    "internal_total_ns",
)


def clock():
    return time.perf_counter_ns()


def fail(message):
    raise RuntimeError(message)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n")
    temp.replace(path)


def machine():
    result = {
        "os": platform.system(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "logical_cpus": os.cpu_count(),
    }
    if result["os"] == "Darwin":
        cpu = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            check=False,
        )
        if cpu.returncode == 0:
            result["cpu"] = cpu.stdout.strip()
        profile = subprocess.run(
            ["system_profiler", "-json", "SPHardwareDataType"],
            capture_output=True,
            text=True,
            check=False,
        )
        if profile.returncode == 0:
            try:
                item = json.loads(profile.stdout)["SPHardwareDataType"][0]
                if cpu := item.get("chip_type"):
                    result["cpu"] = cpu
                if memory := item.get("physical_memory"):
                    result["memory"] = memory
            except (KeyError, IndexError, ValueError):
                pass
    elif result["os"] == "Linux" and (cpuinfo := Path("/proc/cpuinfo")).is_file():
        for line in cpuinfo.read_text().splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() in ("model name", "Hardware"):
                result["cpu"] = value.strip()
                break
    return result


def compiler(stage, source_revision):
    response = subprocess.run(
        [str(stage / "bin/rustc"), "-vV"], capture_output=True, text=True, check=True
    )
    fields = dict(
        line.split(": ", 1) for line in response.stdout.splitlines() if ": " in line
    )
    return {
        "source_revision": source_revision,
        "reported": {
            key: None if fields.get(key) in (None, "unknown") else fields[key]
            for key in ("release", "commit-hash", "commit-date", "host", "LLVM version")
        },
    }


def build(host, output):
    stage0, stage1 = host / "stage0", host / "stage1"
    deps = output / "driver-deps"
    deps.mkdir(exist_ok=True)
    stamp = host / "stage1-rustc" / host.name / "release/.librustc-stamp"
    for entry in stamp.read_bytes().split(b"\0"):
        if not entry:
            continue
        artifact = Path(os.fsdecode(entry[1:]))
        destination = deps / artifact.name
        if artifact.is_file() and not destination.exists():
            destination.symlink_to(artifact)
    binary = output / "timing-driver"
    source = Path(__file__).with_name("timing.rs")
    command = [
        str(stage0 / "bin/rustc"),
        "--edition=2024",
        str(source),
        "-L",
        f"all={deps}",
        "-C",
        "rpath=yes",
        "-L",
        f"native={stage1 / 'lib'}",
        "-C",
        f"link-arg=-Wl,-rpath,{stage1 / 'lib'}",
        "-o",
        str(binary),
    ]
    result = subprocess.run(
        command,
        env=dict(os.environ, RUSTC_BOOTSTRAP="1"),
        capture_output=True,
        text=True,
        check=False,
    )
    (output / "build.log").write_text(
        "$ " + " ".join(command) + "\n" + result.stdout + result.stderr
    )
    if result.returncode:
        fail(f"building the benchmark driver failed:\n{result.stderr}")
    return binary


def command_for(binary, capture, workspace, output, sysroot):
    output.mkdir(parents=True, exist_ok=True)
    original_root = Path(capture["cwd"])
    rust_args = arguments(capture, output, sysroot)
    original_input = str(original_root / PACKAGE / "src/lib.rs")
    rust_args = [
        str(workspace / PACKAGE / "src/lib.rs") if arg == original_input else arg
        for arg in rust_args
    ]
    env = dict(os.environ, RUSTC_BOOTSTRAP="1", **capture["env"])
    env.pop("CARGO_MAKEFLAGS", None)
    for key in ("CARGO_MANIFEST_DIR", "CARGO_MANIFEST_PATH"):
        if key in env:
            original = Path(env[key])
            if original.is_relative_to(original_root):
                env[key] = str(workspace / original.relative_to(original_root))
    return [str(binary), *rust_args], env


def source_edits(workspace, selected):
    result = {}
    for name in selected:
        case = CASES[name]
        path = workspace / PACKAGE / case["file"]
        original = path.read_bytes()
        anchor = case["anchor"].encode()
        expression = case["expression"].encode()
        if original.count(anchor) != 1 or anchor.count(expression) != 1:
            fail(f"{name}: source anchor was not unique in pinned Ruff")
        changed = original.replace(anchor, anchor.replace(expression, b"0u8"))
        result[name] = (path, original, changed)
    return result


def parse_line(line, expected):
    values = line.rstrip("\n").split("\t")
    if values[0] != expected:
        fail(f"expected driver response {expected!r}, got {line!r}")
    return values[1:]


def normalized_errors(lines):
    return [
        normalized(item, False)
        for line in lines
        if (item := diagnostic(line)) is not None
    ]


class Resident:
    def __init__(self, command, env, workspace, output):
        self.command = command
        self.env = dict(env, OHM_RUFF_TIMING_MODE="resident")
        self.workspace = workspace
        self.output = output
        self.proc = None

    def __enter__(self):
        stderr_path = self.output / "resident.stderr"
        self.stderr_writer = stderr_path.open("w")
        self.stderr_reader = stderr_path.open()
        start = clock()
        self.proc = subprocess.Popen(
            self.command,
            cwd=self.workspace,
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr_writer,
            text=True,
            bufsize=1,
        )
        try:
            assert self.proc.stdout is not None
            response = self.proc.stdout.readline()
            external = clock() - start
            pid, analysis = parse_line(response, "ready")
            self.pid = int(pid)
            self.startup = {"external_ns": external, "analysis_ns": int(analysis)}
            baseline_lines = self.read_diagnostics("baseline", "-")
            if normalized_errors(baseline_lines):
                fail("resident baseline emitted errors")
        except BaseException as error:
            self.__exit__(type(error), error, error.__traceback__)
            raise
        return self

    def read_diagnostics(self, operation, name):
        start = f"timing-start\t{operation}\t{name}\n"
        end = f"timing-end\t{operation}\t{name}\n"
        lines = []
        collecting = False
        deadline = time.monotonic() + 5
        while True:
            line = self.stderr_reader.readline()
            if not line:
                if time.monotonic() > deadline:
                    fail(
                        f"did not observe resident diagnostic delimiters {operation}/{name}"
                    )
                time.sleep(0.001)
                continue
            if line == start:
                collecting = True
            elif line == end and collecting:
                return lines
            elif collecting:
                lines.append(line)

    def request(self, operation, name):
        assert self.proc.stdin is not None and self.proc.stdout is not None
        start = clock()
        self.proc.stdin.write(f"{operation}\t{name}\n")
        self.proc.stdin.flush()
        response = self.proc.stdout.readline()
        external = clock() - start
        action, case, edit, analysis, total, errors, revision = parse_line(
            response, "result"
        )
        if (action, case) != (operation, name):
            fail(f"unexpected response to {operation}/{name}: {response}")
        diagnostics = normalized_errors(self.read_diagnostics(operation, name))
        return {
            "pid": self.pid,
            "external_ns": external,
            "edit_ns": int(edit),
            "analysis_ns": int(analysis),
            "internal_total_ns": int(total),
            "errors": int(errors),
            "revision": int(revision),
            "diagnostics": diagnostics,
        }

    def __exit__(self, exc_type, _exc, _traceback):
        try:
            if self.proc and self.proc.poll() is None:
                if exc_type is None:
                    assert self.proc.stdin is not None and self.proc.stdout is not None
                    self.proc.stdin.write("quit\n")
                    self.proc.stdin.flush()
                    parse_line(self.proc.stdout.readline(), "bye")
                    if self.proc.wait(timeout=15):
                        fail("resident driver returned nonzero after quit")
                else:
                    self.proc.terminate()
                    self.proc.wait(timeout=15)
        finally:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
                self.proc.wait()
            self.stderr_writer.close()
            self.stderr_reader.close()


def fresh(command, env, workspace, log):
    env = dict(env, OHM_RUFF_TIMING_MODE="fresh")
    start = clock()
    result = subprocess.run(
        command,
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    external = clock() - start
    log.write_text(result.stderr)
    stdout = [line for line in result.stdout.splitlines() if line.startswith("fresh\t")]
    if len(stdout) != 1:
        fail(
            f"fresh driver exited {result.returncode}, had {len(stdout)} protocol "
            f"responses {result.stdout!r}; see {log}"
        )
    pid, analysis, errors = parse_line(stdout[0], "fresh")
    if result.returncode not in (0, int(int(errors) > 0)):
        fail(f"fresh driver exited {result.returncode}; see {log}")
    return {
        "pid": int(pid),
        "external_ns": external,
        "analysis_ns": int(analysis),
        "errors": int(errors),
        "diagnostics": normalized_errors(result.stderr.splitlines()),
    }


def validate(row):
    resident, fresh_result = row["resident"], row["fresh"]
    expected = 1 if row["operation"] == "apply" else 0
    for label, result in (("resident", resident), ("fresh", fresh_result)):
        if result["errors"] != expected or len(result["diagnostics"]) != expected:
            fail(f"{label} emitted unexpected diagnostics for {row}")
        if expected and result["diagnostics"][0]["code"] != "E0308":
            fail(f"{label} did not emit the expected E0308 for {row}")
    if resident["diagnostics"] != fresh_result["diagnostics"]:
        fail(f"fresh/resident code, message and primary start did not match for {row}")


def distribution(values, scale=1):
    values = sorted(value / scale for value in values)
    return {
        "count": len(values),
        "min": round(values[0], 3),
        "median": round(statistics.median(values), 3),
        "p95": round(values[math.ceil(0.95 * len(values)) - 1], 3),
        "max": round(values[-1], 3),
    }


def summarize_group(rows):
    result = {}
    for mode in ("resident", "fresh"):
        result[mode] = {
            metric.removesuffix("_ns") + "_ms": distribution(
                [row[mode][metric] for row in rows], scale=1_000_000
            )
            for metric in METRICS
            if metric in rows[0][mode]
        }
    resident_median = statistics.median(row["resident"]["external_ns"] for row in rows)
    fresh_median = statistics.median(row["fresh"]["external_ns"] for row in rows)
    result["external_speedup"] = {
        "fresh_median_over_resident_median": round(fresh_median / resident_median, 3),
        "paired_fresh_over_resident": distribution(
            [
                row["fresh"]["external_ns"] / row["resident"]["external_ns"]
                for row in rows
            ]
        ),
    }
    return result


def summary(raw):
    samples = raw["samples"]
    fresh_pids = {row["fresh"]["pid"] for row in samples}
    resident_pids = {row["resident"]["pid"] for row in samples}
    return {
        "schema": 1,
        "ruff_revision": REVISION,
        "compiler": raw["compiler"],
        "target": raw["target"],
        "environment": raw["environment"],
        "rounds": raw["rounds"],
        "warmup_rounds": raw["warmup_rounds"],
        "random_seed": raw["random_seed"],
        "case_execution_order": "cases and fresh/resident first mode randomized each round and revision; fixed seed",
        "percentile_method": "nearest rank",
        "compiler_graph": "enabled in both modes",
        "disk_incremental": False,
        "scopes": {
            "resident_external": "parent writes predefined mutation or restoration request to already-warm child stdin and waits for flushed diagnostic-complete response; includes IPC, HIR patch/restore, invalidation, full-crate analysis and diagnostic output",
            "fresh_external": "parent starts child to child exit; includes process startup and teardown, source parsing/expansion, full-crate analysis and diagnostic output; source file was written just before but outside this interval",
            "internal_analysis": "rustc analysis(()) call only; fresh does not include startup, source parsing/expansion or process teardown in this metric",
            "excluded_from_both": "Cargo startup, dependency work, file-watcher/source-save overhead, output metadata serialization, code generation, link and test execution",
            "source": "fresh reads edited text in a private Ruff Git archive; resident applies a supported direct-tail replacement in retained HIR, and does not accept arbitrary edited source text",
            "diagnostic_equality": "error count, code, message, and primary file/line/start-column in every pair; end columns and source text are not compared",
            "warmup": "one resident baseline plus the configured paired warmup rounds; fresh OS/disk caches stay warm and every timed fresh compiler is a new process",
        },
        "correctness": {
            "paired_revisions": len(samples),
            "edits_produced_one_matching_e0308": sum(
                row["operation"] == "apply" for row in samples
            ),
            "repairs_produced_no_errors": sum(
                row["operation"] == "restore" for row in samples
            ),
            "resident_processes": len(resident_pids),
            "fresh_process_ids": len(fresh_pids),
        },
        "resident_startup_ms": {
            key.removesuffix("_ns"): round(value / 1_000_000, 3)
            for key, value in raw["resident_startup"].items()
        },
        "all_revisions": summarize_group(samples),
        "by_operation": {
            operation: summarize_group(
                [row for row in samples if row["operation"] == operation]
            )
            for operation in ("apply", "restore")
        },
        "cases": {
            case: {
                "owner": CASES[case]["owner"],
                "file": CASES[case]["file"],
                "replacement": "0u8",
                "original_expression": CASES[case]["expression"],
                "operations": {
                    operation: summarize_group(
                        [
                            row
                            for row in samples
                            if row["case"] == case and row["operation"] == operation
                        ]
                    )
                    for operation in ("apply", "restore")
                },
            }
            for case in raw["cases"]
        },
    }


@contextmanager
def restored_sources(edits):
    try:
        yield
    finally:
        for path, original, _changed in edits.values():
            path.write_bytes(original)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", type=Path, required=True)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--repo", type=Path)
    parser.add_argument(
        "--compiler-revision",
        help="optional exact source revision used to build the patched compiler",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--compact", type=Path, help="also write the portable summary here"
    )
    parser.add_argument("--target", default="aarch64-apple-darwin")
    parser.add_argument("--case", action="append", choices=CASES)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--seed", type=int, default=82413)
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    if args.rounds < 1 or args.warmups < 0:
        parser.error("--rounds must be positive and --warmups must not be negative")
    if not args.build_only and (args.capture is None or args.repo is None):
        parser.error("--capture and --repo are required unless --build-only is used")
    selected = list(args.case or DEFAULT_CASES)
    if len(set(selected)) != len(selected):
        parser.error("do not repeat --case values")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    host = args.bootstrap.resolve() / args.target
    binary = build(host, output)
    if args.build_only:
        return

    capture = json.loads(args.capture.read_text())
    captured = capture["argv"]
    if (
        "--test" in captured
        or "--crate-name" not in captured
        or captured[captured.index("--crate-name") + 1] != "ruff_python_parser"
        or "--crate-type" not in captured
        or captured[captured.index("--crate-type") + 1] != "lib"
    ):
        parser.error("--capture must be the production Ruff parser library invocation")
    workspaces = {}
    commands = {}
    for mode in ("resident", "fresh"):
        workspace = output / "workspaces" / mode
        archive_ruff(args.repo.resolve(), workspace)
        workspaces[mode] = workspace
        commands[mode] = command_for(
            binary, capture, workspace, output / "artifacts" / mode, host / "stage1"
        )
    edits = source_edits(workspaces["fresh"], selected)
    write_json(
        output / "commands.json", {mode: value[0] for mode, value in commands.items()}
    )
    fresh_logs = output / "fresh-logs"
    fresh_logs.mkdir(exist_ok=True)
    randomizer = random.Random(args.seed)
    raw = {
        "target": args.target,
        "compiler": compiler(host / "stage1", args.compiler_revision),
        "environment": machine(),
        "rounds": args.rounds,
        "warmup_rounds": args.warmups,
        "random_seed": args.seed,
        "cases": selected,
        "warmups": [],
        "samples": [],
    }
    with (
        restored_sources(edits),
        Resident(*commands["resident"], workspaces["resident"], output) as resident,
    ):
        raw["resident_startup"] = resident.startup
        for sequence in range(args.warmups + args.rounds):
            warmup = sequence < args.warmups
            index = sequence + 1 if warmup else sequence - args.warmups + 1
            category = "warmup" if warmup else "sample"
            order = randomizer.sample(selected, len(selected))
            for name in order:
                path, original, changed = edits[name]
                for operation in ("apply", "restore"):
                    path.write_bytes(changed if operation == "apply" else original)
                    modes = randomizer.sample(("fresh", "resident"), 2)
                    row = {
                        "round": index,
                        "case": name,
                        "operation": operation,
                        "order": modes,
                    }
                    for mode in modes:
                        if mode == "resident":
                            row[mode] = resident.request(operation, name)
                        else:
                            row[mode] = fresh(
                                *commands["fresh"],
                                workspaces["fresh"],
                                fresh_logs
                                / f"{category}-{index:03}-{name}-{operation}.stderr",
                            )
                    validate(row)
                    raw["warmups" if warmup else "samples"].append(row)
            write_json(output / "raw.json", raw)
            print(
                f"finished {category} {index}: {', '.join(order)}",
                file=sys.stderr,
                flush=True,
            )

    result = summary(raw)
    write_json(output / "summary.json", result)
    if args.compact:
        write_json(args.compact, result)
    print(json.dumps(result["all_revisions"], indent=2))


if __name__ == "__main__":
    main()
