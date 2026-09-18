#!/usr/bin/env python3
"""Measure saving real Ruff source through complete resident, fresh, and Cargo diagnostics."""

import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

from measure import (
    CASES,
    clock,
    command_for,
    compiler,
    distribution,
    machine,
    write_json,
)
from run_tests import PACKAGE, REVISION, archive_ruff
from source_diagnostics import (
    DiagnosticProjector,
    UnmappableDiagnostic,
    merge_diagnostics,
    normalize_diagnostics,
    parse_diagnostics,
)

FILES = (
    "src/lexer.rs",
    "src/string.rs",
    "src/parser/expression.rs",
    "src/parser/pattern.rs",
)
SUITES = ("main", "preservation", "fallback-preservation")


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise RuntimeError(f"source anchor did not occur exactly once: {before!r}")
    return source.replace(before, after)


def replace_expression(source, case, replacement):
    case = CASES[case]
    anchor = case["anchor"]
    return replace_once(source, anchor, anchor.replace(case["expression"], replacement))


def source_cases(sources, suite):
    lexer = sources["src/lexer.rs"]
    error = replace_expression(lexer, "unicode-identifier", "0u8")
    if suite == "preservation":
        string = sources["src/string.rs"]
        independent = replace_expression(string, "parse-octet", "0u8")
        expression = sources["src/parser/expression.rs"]
        expression_error = replace_expression(expression, "parse-atom", "0u8")
        return [
            ("existing-error", "establish", "src/string.rs", independent, 1),
            ("existing-error", "noop", "src/parser/expression.rs", expression, 1),
            (
                "independent-error",
                "error",
                "src/parser/expression.rs",
                expression_error,
                2,
            ),
            ("independent-error", "repair", "src/parser/expression.rs", expression, 1),
            ("existing-error", "repair", "src/string.rs", string, 0),
        ]
    clean = replace_expression(lexer, "unicode-identifier", "false")
    signature_anchor = "fn is_unicode_identifier_start(c: char) -> bool {"
    shifted = replace_once(
        error,
        signature_anchor,
        "// source benchmark: move the diagnostic\n" + signature_anchor,
    )
    signature = replace_once(
        lexer,
        signature_anchor,
        "fn is_unicode_identifier_start(c: char) -> i32 {",
    )
    string = sources["src/string.rs"]
    string_error = replace_expression(string, "parse-octet", "0u8")
    if suite == "fallback-preservation":
        return [
            ("unsupported-signature", "establish", "src/lexer.rs", signature, None),
            ("supported-with-pending", "error", "src/string.rs", string_error, None),
            ("supported-with-pending", "repair", "src/string.rs", string, None),
            ("unsupported-signature", "repair", "src/lexer.rs", lexer, 0),
            ("supported-after-repair", "error", "src/string.rs", string_error, 1),
            ("supported-after-repair", "repair", "src/string.rs", string, 0),
        ]
    if suite != "main":
        raise ValueError(f"unknown source suite {suite}")
    string_clean = replace_expression(string, "parse-octet", "'x'")
    octet_signature = "    fn parse_octet(&mut self, o: u8) -> char {"
    string_shifted = replace_once(
        string_error,
        octet_signature,
        "    // source benchmark: move the diagnostic\n" + octet_signature,
    )
    module_docs = "//! Parsing of string literals, bytes literals, and implicit string concatenation.\n"
    string_combined = replace_once(
        string_error,
        module_docs,
        module_docs + "\n// source benchmark: change outside the edited owner\n",
    )
    pattern = sources["src/parser/pattern.rs"]
    pattern_anchor = (
        "        identifier\n    }\n\n    /// Parses a parenthesized pattern"
    )
    pattern_error_anchor = pattern_anchor.replace("identifier", "0u8")
    pattern_error = replace_once(pattern, pattern_anchor, pattern_error_anchor)
    pattern_signature = (
        "    fn parse_match_pattern_target(&mut self) -> ast::Identifier {"
    )
    pattern_shifted = replace_once(
        pattern_error,
        pattern_signature,
        "    // source benchmark: move the diagnostic\n" + pattern_signature,
    )
    return [
        ("unchanged", "noop", "src/lexer.rs", lexer, 0),
        ("string-clean-body", "edit", "src/string.rs", string_clean, 0),
        ("string-clean-body", "repair", "src/string.rs", string, 0),
        ("string-type-error", "error", "src/string.rs", string_error, 1),
        ("string-shift-error", "insert", "src/string.rs", string_shifted, 1),
        ("string-shift-error", "remove", "src/string.rs", string_error, 1),
        ("string-type-error", "repair", "src/string.rs", string, 0),
        ("combined-semantic-and-trivia", "edit", "src/string.rs", string_combined, 1),
        ("combined-semantic-and-trivia", "repair", "src/string.rs", string, 0),
        ("pattern-type-error", "error", "src/parser/pattern.rs", pattern_error, 1),
        ("pattern-shift-error", "insert", "src/parser/pattern.rs", pattern_shifted, 1),
        ("pattern-shift-error", "remove", "src/parser/pattern.rs", pattern_error, 1),
        ("pattern-type-error", "repair", "src/parser/pattern.rs", pattern, 0),
        ("lexer-import-clean", "edit", "src/lexer.rs", clean, 0),
        ("lexer-import-clean", "repair", "src/lexer.rs", lexer, 0),
        ("lexer-import-error", "error", "src/lexer.rs", error, 1),
        ("lexer-shift-error", "insert", "src/lexer.rs", shifted, 1),
        ("lexer-shift-error", "remove", "src/lexer.rs", error, 1),
        ("lexer-import-error", "repair", "src/lexer.rs", lexer, 0),
        ("signature", "fallback", "src/lexer.rs", signature, None),
        ("signature", "repair", "src/lexer.rs", lexer, 0),
    ]


def source_map(workspace):
    return {name: (workspace / PACKAGE / name).read_text() for name in FILES}


def build(host, output, *, source=None, binary_name="source-driver"):
    stage0, stage1 = host / "stage0", host / "stage1"
    deps = output / "driver-deps"
    deps.mkdir(exist_ok=True)
    stamp = host / "stage1-rustc" / host.name / "release/.librustc-stamp"
    for entry in stamp.read_bytes().split(b"\0"):
        if entry:
            artifact = Path(os.fsdecode(entry[1:]))
            destination = deps / artifact.name
            if artifact.is_file() and not destination.exists():
                destination.symlink_to(artifact)
    binary = output / binary_name
    command = [
        str(stage0 / "bin/rustc"),
        "--edition=2024",
        str(source or Path(__file__).with_name("source_timing.rs")),
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
        raise RuntimeError(f"building source driver failed:\n{result.stderr}")
    return binary


def protocol(line, kind):
    first, *values = line.rstrip("\n").split("\t")
    if first != kind:
        raise RuntimeError(f"expected {kind!r} response, got {line!r}")
    return values


def save(workspace, name, content):
    (workspace / PACKAGE / name).write_text(content)


def error_count(diagnostics):
    return sum(item["level"] == "error" for item in diagnostics)


def fresh(command, env, workspace, log, current_sources):
    result = subprocess.run(
        command,
        cwd=workspace,
        env=dict(env, OHM_RUFF_SOURCE_MODE="fresh"),
        capture_output=True,
        text=True,
        check=False,
    )
    responses = [
        line for line in result.stdout.splitlines() if line.startswith("fresh\t")
    ]
    if len(responses) != 1:
        log.write_text(result.stderr)
        raise RuntimeError(
            f"fresh compiler returned {result.returncode}, protocol {result.stdout!r}; see {log}"
        )
    pid, analysis, errors = protocol(responses[0], "fresh")
    diagnostics = normalize_diagnostics(
        parse_diagnostics(result.stderr.splitlines(), include_warnings=True),
        current_sources,
    )
    completed = clock()
    log.write_text(result.stderr)
    if result.returncode not in (0, int(int(errors) > 0)) or int(errors) != error_count(
        diagnostics
    ):
        raise RuntimeError(
            f"fresh exit {result.returncode}, compiler error count {errors}, parsed {len(diagnostics)}; see {log}"
        )
    return {
        "pid": int(pid),
        "analysis_ns": int(analysis),
        "returncode": result.returncode,
        "diagnostics": diagnostics,
        "completed_ns": completed,
    }


class ResidentSourceState:
    def __init__(self, sources):
        self.accepted = dict(sources)
        self.pending = set()

    def observe(self, name, source, route, reason):
        if route == "fallback":
            if source == self.accepted[name]:
                self.pending.discard(name)
            else:
                self.pending.add(name)
        else:
            self.accepted[name] = source
            self.pending.discard(name)
        if route != "fallback" and self.pending:
            return "fallback", "unresolved-source-fallback:" + ",".join(
                sorted(self.pending)
            )
        return route, reason


class Resident:
    def __init__(self, command, env, workspace, output, initial_sources):
        self.command, self.env, self.workspace = command, env, workspace
        self.output, self.initial_sources = output, initial_sources
        self.accepted_diagnostics = []
        self.sources = ResidentSourceState(initial_sources)
        self.proc = None

    def __enter__(self):
        self.writer = (self.output / "resident.stderr").open("w")
        self.reader = (self.output / "resident.stderr").open()
        started = clock()
        self.proc = subprocess.Popen(
            self.command,
            cwd=self.workspace,
            env=dict(self.env, OHM_RUFF_SOURCE_MODE="resident"),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.writer,
            text=True,
            bufsize=1,
        )
        try:
            pid, analysis = protocol(self.proc.stdout.readline(), "ready")
            self.pid = int(pid)
            self.accepted_diagnostics = normalize_diagnostics(
                parse_diagnostics(self.read("baseline"), include_warnings=True),
                self.initial_sources,
            )
            self.startup = {
                "external_ns": clock() - started,
                "analysis_ns": int(analysis),
                "diagnostics": self.accepted_diagnostics,
            }
        except BaseException as error:
            self.__exit__(type(error), error, error.__traceback__)
            raise
        return self

    def read(self, version):
        start, end = f"source-start\t{version}\n", f"source-end\t{version}\n"
        lines, collecting = [], False
        deadline = time.monotonic() + 15
        while True:
            line = self.reader.readline()
            if not line:
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        f"no stderr diagnostic markers for request {version!r}; inspect {self.output / 'resident.stderr'}"
                    )
                time.sleep(0.001)
            elif line == start:
                collecting = True
            elif line == end and collecting:
                return lines
            elif collecting:
                lines.append(line)

    def request(self, version, name, current_sources, fresh_command):
        self.proc.stdin.write(f"check\t{version}\t{self.workspace / PACKAGE / name}\n")
        self.proc.stdin.flush()
        response = self.proc.stdout.readline()
        (
            received,
            mode,
            reason,
            total,
            analysis,
            errors,
            revision,
            old_start,
            old_end,
            new_start,
            new_end,
            epoch,
            *owner,
        ) = protocol(response, "result")
        if received != str(version):
            raise RuntimeError(f"request version {version} received {response!r}")
        emitted = normalize_diagnostics(
            parse_diagnostics(self.read(version), include_warnings=True),
            self.initial_sources,
        )
        old_range = None if old_start == "-" else (int(old_start), int(old_end))
        new_range = None if new_start == "-" else (int(new_start), int(new_end))
        owner_range = (
            (int(owner[0]), int(owner[1])) if owner and owner[0] != "-" else old_range
        )
        route, reason = self.sources.observe(
            name, current_sources[name], mode, None if reason == "-" else reason
        )
        output = {
            "pid": self.pid,
            "route": route,
            "reason": reason,
            "native_route": mode,
            "internal_ns": int(total),
            "analysis_ns": int(analysis),
            "compiler_error_count": int(errors),
            "revision": int(revision),
            "original_range": old_range,
            "current_range": new_range,
            "owner_original_range": owner_range,
            "diagnostics_epoch": epoch,
        }
        if mode != "fallback":
            if epoch == "request":
                if owner_range is None:
                    raise RuntimeError(
                        f"native diagnostics with no edited range: {response}"
                    )
                self.accepted_diagnostics = merge_diagnostics(
                    self.accepted_diagnostics,
                    emitted,
                    name,
                    owner_range,
                )
            if route != "fallback":
                try:
                    diagnostics = DiagnosticProjector(
                        self.initial_sources, current_sources
                    ).project_diagnostics(self.accepted_diagnostics)
                except UnmappableDiagnostic as error:
                    output.update(
                        route="fallback", reason=f"diagnostic-projection: {error}"
                    )
        if output["route"] == "fallback":
            direct = fresh(
                *fresh_command,
                self.workspace,
                self.output / f"fallback-{version}.stderr",
                current_sources,
            )
            output["fallback_fresh_ns"] = direct["analysis_ns"]
            diagnostics = direct["diagnostics"]
            completed = direct["completed_ns"]
        else:
            completed = clock()
        output["diagnostics"] = diagnostics
        output["completed_ns"] = completed
        return output

    def __exit__(self, exc_type, _exc, _traceback):
        try:
            if self.proc and self.proc.poll() is None:
                if exc_type is None:
                    self.proc.stdin.write("quit\n")
                    self.proc.stdin.flush()
                    protocol(self.proc.stdout.readline(), "bye")
                    if self.proc.wait(timeout=15):
                        raise RuntimeError("resident compiler returned nonzero")
                else:
                    self.proc.terminate()
                    self.proc.wait(timeout=15)
        finally:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
                self.proc.wait()
            self.writer.close()
            self.reader.close()


def cargo(stage, target, workspace, output, current_sources, offline):
    env = dict(
        os.environ,
        CARGO_TARGET_DIR=str(target),
        CARGO_BUILD_BUILD_DIR=str(target / "build"),
        CARGO_INCREMENTAL="1",
        CARGO_TERM_COLOR="never",
        RUSTC=str(stage / "bin/rustc"),
    )
    for option in (
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
    ):
        env.pop(option, None)
    command = [
        "cargo",
        "+ohm",
        "check",
        "--locked",
        "-p",
        "ruff_python_parser",
        "--lib",
        "--message-format=json",
    ]
    if offline:
        command.append("--offline")
    result = subprocess.run(
        command, cwd=workspace, env=env, capture_output=True, text=True, check=False
    )
    diagnostics = normalize_diagnostics(
        parse_diagnostics(result.stdout.splitlines(), include_warnings=True),
        current_sources,
    )
    completed = clock()
    output.with_suffix(".stdout").write_text(result.stdout)
    output.with_suffix(".stderr").write_text(result.stderr)
    if result.returncode != (101 if error_count(diagnostics) else 0):
        raise RuntimeError(
            f"Cargo returned {result.returncode} with {len(diagnostics)} diagnostics; see {output}.stderr"
        )
    parser_artifacts = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if (
            item.get("reason") == "compiler-artifact"
            and item.get("target", {}).get("name") == "ruff_python_parser"
        ):
            parser_artifacts.append(item["fresh"])
    return {
        "returncode": result.returncode,
        "diagnostics": diagnostics,
        "parser_artifact_fresh": parser_artifacts,
        "completed_ns": completed,
    }


def timing(rows):
    result = {}
    if not rows:
        return result
    for mode in ("resident", "fresh", "cargo"):
        values = [row[mode]["external_ns"] for row in rows if mode in row]
        if values:
            result[mode] = distribution(values, 1e6)
    if "cargo" in result:
        result["ratio_of_medians_cargo_over_resident"] = round(
            statistics.median(row["cargo"]["external_ns"] for row in rows)
            / statistics.median(row["resident"]["external_ns"] for row in rows),
            3,
        )
    return result


def summary(raw):
    samples = raw["samples"]
    supported = [row for row in samples if row["resident"]["route"] == "resident"]
    fallbacks = [row for row in samples if row["resident"]["route"] == "fallback"]
    noops = [row for row in samples if row["resident"]["route"] == "noop"]
    comparable = timing(supported)

    def all_matching(suite, case, operation, predicate):
        matching = [
            row["resident"]
            for row in samples
            if (row["suite"], row["case"], row["operation"]) == (suite, case, operation)
        ]
        return bool(matching) and all(predicate(item) for item in matching)

    def error_in(result, file):
        return any(
            diagnostic["level"] == "error"
            and any(
                span["is_primary"] and span["file_name"] == file
                for span in diagnostic["spans"]
            )
            for diagnostic in result["diagnostics"]
        )

    def pending_fresh(result, string_error):
        return (
            result["route"] == "fallback"
            and (result["reason"] or "").startswith("unresolved-source-fallback:")
            and error_in(result, "src/lexer.rs")
            and error_in(result, "src/string.rs") == string_error
        )

    return {
        "schema": 1,
        "ruff_revision": REVISION,
        "compiler": raw["compiler"],
        "environment": raw["environment"],
        "rounds": raw["rounds"],
        "warmup_rounds": raw["warmup_rounds"],
        "random_seed": raw["random_seed"],
        "suites": raw["suites"],
        "measurement": "timer begins before opening and writing a real Rust source file and ends after diagnostics are parsed, projected and available; routes run sequentially on matching independent disposable archives; resident receives only a path and increasing version",
        "fresh_oracle": "same patched compiler starts a new process and parses actual edited files for every transition; every source-bearing rustc error and warning must match in full, including all spans, children, source lines and rendered output; no-span compiler footers, metadata and build chatter are excluded",
        "cargo": "ordinary warm cargo +ohm check --locked -p ruff_python_parser --lib --message-format=json; disk incremental enabled and resident graph disabled",
        "percentile": "nearest rank",
        "validation": {
            "transitions": len(samples),
            "supported": len(supported),
            "fallback": len(fallbacks),
            "fallback_percent": round(100 * len(fallbacks) / len(samples), 2),
            "noop": len(noops),
            "matched_complete_fresh_diagnostics": all(
                row["resident_equals_fresh"] for row in samples
            ),
            "matched_complete_cargo_diagnostics": all(
                row.get("cargo_equals_fresh", True) for row in samples
            )
            if raw["cargo_enabled"]
            else None,
            "startup_diagnostics_match_fresh": all(
                item["resident_equals_fresh"] for item in raw["startups"].values()
            ),
            "independent_error": all(
                all_matching(
                    "preservation",
                    case,
                    operation,
                    lambda result, count=count: (
                        result["route"] == "resident"
                        and error_count(result["diagnostics"]) == count
                    ),
                )
                for case, operation, count in (
                    ("existing-error", "establish", 1),
                    ("independent-error", "error", 2),
                    ("independent-error", "repair", 1),
                    ("existing-error", "repair", 0),
                )
            ),
            "rendered_source_and_range_ends_compared": True,
            "native_clean_edit_and_warning": all_matching(
                "main",
                "string-clean-body",
                "edit",
                lambda result: (
                    result["route"] == "resident"
                    and error_count(result["diagnostics"]) == 0
                    and any(
                        item["level"] == "warning" for item in result["diagnostics"]
                    )
                ),
            ),
            "native_error_repair": all(
                all_matching(
                    "main",
                    "string-type-error",
                    operation,
                    lambda result, count=count: (
                        result["route"] == "resident"
                        and error_count(result["diagnostics"]) == count
                    ),
                )
                for operation, count in (("error", 1), ("repair", 0))
            ),
            "line_shifts_refresh_diagnostics_without_a_fresh_compiler": all(
                all_matching(
                    "main",
                    "pattern-shift-error",
                    operation,
                    lambda result: (
                        result["route"] == "noop"
                        and error_count(result["diagnostics"]) == 1
                    ),
                )
                for operation in ("insert", "remove")
            ),
            "import_warning_falls_back": all_matching(
                "main",
                "lexer-import-clean",
                "edit",
                lambda result: (
                    result["route"] == "fallback"
                    and error_count(result["diagnostics"]) == 0
                    and any(
                        item["level"] == "warning" for item in result["diagnostics"]
                    )
                ),
            ),
            "signature_falls_back": all_matching(
                "main",
                "signature",
                "fallback",
                lambda result: (
                    result["route"] == "fallback" and error_in(result, "src/lexer.rs")
                ),
            ),
            "combined_semantic_and_trivia_falls_back": all_matching(
                "main",
                "combined-semantic-and-trivia",
                "edit",
                lambda result: (
                    result["route"] == "fallback" and error_in(result, "src/string.rs")
                ),
            )
            and all_matching(
                "main",
                "combined-semantic-and-trivia",
                "repair",
                lambda result: error_count(result["diagnostics"]) == 0,
            ),
            "unresolved_fallback_keeps_using_fresh": all_matching(
                "fallback-preservation",
                "unsupported-signature",
                "establish",
                lambda result: (
                    result["route"] == "fallback" and error_in(result, "src/lexer.rs")
                ),
            )
            and all_matching(
                "fallback-preservation",
                "supported-with-pending",
                "error",
                lambda result: pending_fresh(result, True),
            )
            and all_matching(
                "fallback-preservation",
                "supported-with-pending",
                "repair",
                lambda result: pending_fresh(result, False),
            )
            and all_matching(
                "fallback-preservation",
                "unsupported-signature",
                "repair",
                lambda result: error_count(result["diagnostics"]) == 0,
            )
            and all_matching(
                "fallback-preservation",
                "supported-after-repair",
                "error",
                lambda result: (
                    result["route"] == "resident"
                    and error_in(result, "src/string.rs")
                    and not error_in(result, "src/lexer.rs")
                ),
            )
            and all_matching(
                "fallback-preservation",
                "supported-after-repair",
                "repair",
                lambda result: (
                    result["route"] == "resident"
                    and error_count(result["diagnostics"]) == 0
                ),
            ),
        },
        "targets": {
            "resident_median_under_100_ms": comparable.get("resident", {}).get(
                "median", float("inf")
            )
            < 100,
            "resident_p95_under_200_ms": comparable.get("resident", {}).get(
                "p95", float("inf")
            )
            < 200,
            "cargo_median_at_least_twice_resident": comparable.get(
                "ratio_of_medians_cargo_over_resident", 0
            )
            >= 2
            if raw["cargo_enabled"]
            else None,
        },
        "by_route_ms": {
            "resident": comparable,
            "fallback": timing(fallbacks),
            "noop": timing(noops),
        },
        "by_case_ms": {
            f"{suite}/{case}/{operation}": timing(
                [
                    row
                    for row in samples
                    if (row["suite"], row["case"], row["operation"])
                    == (suite, case, operation)
                ]
            )
            for suite, case, operation in sorted(
                {(row["suite"], row["case"], row["operation"]) for row in samples}
            )
        },
        "startup_ms": {
            suite: {"resident": round(item["resident"]["external_ns"] / 1e6, 3)}
            for suite, item in raw["startups"].items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("bootstrap", "capture", "repo", "output", "cargo-target"):
        parser.add_argument(
            f"--{option}", type=Path, required=option in ("bootstrap", "output")
        )
    parser.add_argument("--target", default="aarch64-apple-darwin")
    parser.add_argument("--compiler-revision")
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--seed", type=int, default=194121)
    parser.add_argument("--suite", choices=SUITES, action="append")
    parser.add_argument("--compact", type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--skip-cargo", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.rounds < 1 or args.warmups < 0:
        parser.error("--rounds must be positive and --warmups must not be negative")
    if not args.build_only and (
        not args.capture
        or not args.repo
        or (not args.skip_cargo and not args.cargo_target)
    ):
        parser.error(
            "--capture, --repo and (unless --skip-cargo) --cargo-target are required"
        )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    host = args.bootstrap.resolve() / args.target
    binary = args.binary.resolve() if args.binary else build(host, output)
    if args.build_only:
        return
    capture = json.loads(args.capture.read_text())
    if "--test" in capture["argv"] or "ruff_python_parser" not in capture["argv"]:
        parser.error("--capture must be a production Ruff parser library invocation")
    suites = args.suite or list(SUITES)
    randomizer = random.Random(args.seed)
    raw = {
        "compiler": compiler(host / "stage1", args.compiler_revision),
        "environment": machine(),
        "rounds": args.rounds,
        "warmup_rounds": args.warmups,
        "random_seed": args.seed,
        "suites": suites,
        "cargo_enabled": not args.skip_cargo,
        "startups": {},
        "warmups": [],
        "samples": [],
    }
    for suite in suites:
        suite_output = output / suite
        (suite_output / "logs").mkdir(parents=True, exist_ok=True)
        workspaces, commands, initial_maps = {}, {}, {}
        for mode in ("resident", "fresh", "cargo"):
            if mode == "cargo" and args.skip_cargo:
                continue
            workspace = suite_output / "workspaces" / mode
            archive_ruff(args.repo.resolve(), workspace)
            workspaces[mode] = workspace
            initial_maps[mode] = source_map(workspace)
            if mode != "cargo":
                command, environment = command_for(
                    binary,
                    capture,
                    workspace,
                    suite_output / "artifacts" / mode,
                    host / "stage1",
                )
                command.remove("--cap-lints=allow")
                commands[mode] = command, environment
        initial = initial_maps["resident"]
        if not all(sources == initial for sources in initial_maps.values()):
            raise RuntimeError("initial checkouts are not identical")
        cases = source_cases(initial, suite)
        try:
            with Resident(
                *commands["resident"], workspaces["resident"], suite_output, initial
            ) as resident:
                startup = {
                    "resident": resident.startup,
                    "fresh": fresh(
                        *commands["fresh"],
                        workspaces["fresh"],
                        suite_output / "logs" / "initial.fresh.stderr",
                        initial,
                    ),
                }
                startup["resident_equals_fresh"] = (
                    startup["resident"]["diagnostics"]
                    == startup["fresh"]["diagnostics"]
                )
                if not startup["resident_equals_fresh"]:
                    raise RuntimeError(f"{suite}: resident baseline differs from fresh")
                if not args.skip_cargo:
                    startup["cargo"] = cargo(
                        host / "stage1",
                        args.cargo_target.resolve(),
                        workspaces["cargo"],
                        suite_output / "logs" / "initial.cargo",
                        initial,
                        args.offline,
                    )
                    if (
                        startup["cargo"]["diagnostics"]
                        != startup["fresh"]["diagnostics"]
                    ):
                        write_json(suite_output / "startup-mismatch.json", startup)
                        raise RuntimeError(
                            f"{suite}: Cargo baseline differs from fresh, see {suite_output / 'startup-mismatch.json'}"
                        )
                raw["startups"][suite] = startup
                version = 0
                current = dict(initial)
                for round_number in range(args.warmups + args.rounds):
                    category = "warmup" if round_number < args.warmups else "sample"
                    for case, operation, name, content, expected in cases:
                        version += 1
                        current[name] = content
                        row = {
                            "suite": suite,
                            "round": round_number,
                            "version": version,
                            "case": case,
                            "operation": operation,
                            "file": name,
                            "expected_error_count": expected,
                        }
                        routes = list(workspaces)
                        randomizer.shuffle(routes)
                        row["route_order"] = routes
                        stem = (
                            suite_output
                            / "logs"
                            / f"{category}-{round_number:03}-{case}-{operation}"
                        )
                        for mode in routes:
                            started = clock()
                            save(workspaces[mode], name, content)
                            if mode == "resident":
                                result = resident.request(
                                    version, name, current, commands["resident"]
                                )
                            elif mode == "fresh":
                                result = fresh(
                                    *commands["fresh"],
                                    workspaces[mode],
                                    stem.with_name(stem.name + ".fresh.stderr"),
                                    current,
                                )
                            else:
                                result = cargo(
                                    host / "stage1",
                                    args.cargo_target.resolve(),
                                    workspaces[mode],
                                    stem.with_name(stem.name + ".cargo"),
                                    current,
                                    args.offline,
                                )
                            completed = result.pop("completed_ns")
                            row[mode] = {**result, "external_ns": completed - started}
                        row["resident_equals_fresh"] = (
                            row["resident"]["diagnostics"]
                            == row["fresh"]["diagnostics"]
                        )
                        if "cargo" in row:
                            row["cargo_equals_fresh"] = (
                                row["cargo"]["diagnostics"]
                                == row["fresh"]["diagnostics"]
                            )
                        if (
                            expected is not None
                            and error_count(row["fresh"]["diagnostics"]) != expected
                        ):
                            row["unexpected_error_count"] = True
                        raw["warmups" if category == "warmup" else "samples"].append(
                            row
                        )
                        if (
                            not row["resident_equals_fresh"]
                            or not row.get("cargo_equals_fresh", True)
                            or row.get("unexpected_error_count")
                        ):
                            write_json(output / "raw.json", raw)
                            raise RuntimeError(
                                f"{suite} {case}/{operation}: complete diagnostics differ or wrong count; see {output / 'raw.json'}"
                            )
                    write_json(output / "raw.json", raw)
                    print(
                        f"finished {suite} {category} {round_number}",
                        file=sys.stderr,
                        flush=True,
                    )
        finally:
            for mode, workspace in workspaces.items():
                for name, content in initial_maps[mode].items():
                    save(workspace, name, content)
    result = summary(raw)
    write_json(output / "summary.json", result)
    if args.compact:
        write_json(args.compact.resolve(), result)
    print(json.dumps(result["by_route_ms"], indent=2))
    required = ["matched_complete_fresh_diagnostics", "startup_diagnostics_match_fresh"]
    if not args.skip_cargo:
        required.append("matched_complete_cargo_diagnostics")
    if "main" in suites:
        required.extend(
            (
                "native_clean_edit_and_warning",
                "native_error_repair",
                "line_shifts_refresh_diagnostics_without_a_fresh_compiler",
                "import_warning_falls_back",
                "signature_falls_back",
                "combined_semantic_and_trivia_falls_back",
            )
        )
    if "preservation" in suites:
        required.append("independent_error")
    if "fallback-preservation" in suites:
        required.append("unresolved_fallback_keeps_using_fresh")
    failures = [name for name in required if not result["validation"][name]]
    if failures:
        raise RuntimeError(
            f"benchmark controls did not hold: {', '.join(failures)}; see {output / 'summary.json'}"
        )


if __name__ == "__main__":
    main()
