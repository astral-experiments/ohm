#!/usr/bin/env python3
"""Compare an isolated rustc dispatcher with fresh rustc on structural Ruff edits."""

import argparse
import json
import math
import os
import statistics
import subprocess
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

from measure import clock, compiler, distribution, machine, write_json
from measure_source import replace_once
from measure_test import (
    TEST,
    compiler_command,
    fingerprint,
    require,
    run_binary,
    write_logs,
)
from run_tests import (
    COUNT_KEYS,
    EXPECTED_COUNTS,
    PACKAGE,
    RESULT,
    REVISION,
    archive_ruff,
)
from source_diagnostics import normalize_diagnostics, parse_diagnostics

FILES = ("src/lib.rs", "src/string.rs", "src/ohm_revision_probe.rs")


def cases(workspace):
    root = workspace / PACKAGE
    lib = (root / FILES[0]).read_text()
    string = (root / FILES[1]).read_text()
    signature = replace_once(
        string,
        "fn parse_octet(&mut self, o: u8) -> char {\n        let mut radix_bytes = [o, 0, 0];",
        "fn parse_octet(&mut self, o: char) -> char {\n        let mut radix_bytes = [o as u8, 0, 0];",
    )
    signature = replace_once(
        signature, "self.parse_octet(o as u8)", "self.parse_octet(o)"
    )
    imported = replace_once(string, "use std::fmt;", "use std::fmt as revision_fmt;")
    imported = imported.replace("fmt::", "revision_fmt::")
    macro = replace_once(
        string,
        "char::from_u32(value).unwrap()",
        "revision_octet_char!(value)",
    )
    macro = replace_once(
        macro,
        "use std::fmt;",
        "use std::fmt;\nmacro_rules! revision_octet_char { ($value:expr) => { char::from_u32($value).unwrap() }; }",
    )
    broken_macro = replace_once(
        macro,
        "($value:expr) => { char::from_u32($value).unwrap() }",
        "($value:expr) => {{ let _ = $value; 'x' }}",
    )
    module_lib = replace_once(
        lib, "mod string;", "mod string;\nmod ohm_revision_probe;"
    )
    module_string = replace_once(
        string,
        "char::from_u32(value).unwrap()",
        "crate::ohm_revision_probe::octet(value)",
    )
    module = (
        "pub(crate) fn octet(value: u32) -> char { char::from_u32(value).unwrap() }\n"
    )

    def snapshot(lib_source=lib, string_source=string, module_source=None):
        return dict(zip(FILES, (lib_source, string_source, module_source), strict=True))

    return [
        (
            "initial-syntax-error",
            "compile_error",
            snapshot(string_source=string + "\nfn ohm_broken( {\n"),
        ),
        ("syntax-repair", "pass", snapshot()),
        ("signature-and-caller", "pass", snapshot(string_source=signature)),
        ("signature-repair", "pass", snapshot()),
        ("import-and-all-references", "pass", snapshot(string_source=imported)),
        ("import-repair", "pass", snapshot()),
        ("macro-definition-and-call", "pass", snapshot(string_source=macro)),
        ("macro-behavior-fails-test", "fail", snapshot(string_source=broken_macro)),
        ("macro-behavior-repair", "pass", snapshot(string_source=macro)),
        ("macro-removal", "pass", snapshot()),
        ("create-and-use-module", "pass", snapshot(module_lib, module_string, module)),
        (
            "delete-still-referenced-module",
            "compile_error",
            snapshot(module_lib, module_string),
        ),
        ("recreate-module", "pass", snapshot(module_lib, module_string, module)),
        ("remove-module-and-references", "pass", snapshot()),
    ]


def save(workspace, sources):
    for name, content in sources.items():
        path = workspace / PACKAGE / name
        if content is None:
            path.unlink(missing_ok=True)
        elif not path.exists() or path.read_text() != content:
            path.write_text(content)


def revision_command(executable, capture, workspace, directory, stage):
    command, env, binary = compiler_command(
        executable, capture, workspace, directory, stage
    )
    clean = []
    iterator = iter(command)
    for argument in iterator:
        if argument == "-C":
            option = next(iterator)
            if option.split("=", 1)[0] not in ("debuginfo", "split-debuginfo"):
                clean.extend((argument, option))
        elif argument == "-Zohm-resident-query-graph" or argument.startswith(
            ("-Cdebuginfo=", "-Csplit-debuginfo=")
        ):
            continue
        else:
            clean.append(argument)
    clean.extend(
        (
            "-C",
            f"incremental={directory / 'incremental'}",
            "-C",
            "debuginfo=line-tables-only",
            "-C",
            "split-debuginfo=off",
        )
    )
    return clean, env, binary


class Worker:
    def __init__(self, command, environment, workspace, path, reuse):
        self.path = path
        self.route = "same-process" if reuse else "fresh-process"
        self.stderr = path.open("wb")
        self.process = subprocess.Popen(
            command,
            cwd=workspace,
            env={**environment, "OHM_ARBITRARY_REUSE_PROCESS": "1" if reuse else "0"},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            text=True,
            bufsize=1,
        )
        self.pid = self.process.pid
        self.responses = Queue()

        def read_lines():
            for line in self.process.stdout:
                self.responses.put(line)
            self.responses.put(None)

        Thread(target=read_lines, daemon=True).start()
        ready = self.line().split("\t")
        require(
            ready == ["ready", str(self.pid)],
            f"unexpected revision worker greeting {ready}",
        )

    def line(self):
        try:
            line = self.responses.get(timeout=120)
        except Empty:
            raise RuntimeError(
                f"revision worker timed out; inspect {self.path}"
            ) from None
        require(line, f"revision worker exited; inspect {self.path}")
        return line.rstrip("\n")

    def send(self, text):
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()

    def compile(self, version):
        offset = self.path.stat().st_size
        self.send(f"compile\t{version}")
        fields = self.line().split("\t")
        require(
            len(fields) == 5 and fields[:3] == ["result", str(version), str(self.pid)],
            f"unexpected compilation: {fields}",
        )
        with self.path.open("rb") as handle:
            handle.seek(offset)
            diagnostics = handle.read().decode()
        require(
            f"resident-finished\t{version}" in diagnostics,
            f"no completed diagnostic barrier for {version}",
        )
        routes = [
            line.split("\t")
            for line in diagnostics.splitlines()
            if line.startswith(f"resident-route\t{version}\t")
        ]
        require(
            len(routes) == 1 and len(routes[0]) == 4 and routes[0][2] == self.route,
            f"unexpected process route for {version}: {routes}",
        )
        compiler_pid = int(routes[0][3])
        require(
            (compiler_pid == self.pid) == (self.route == "same-process"),
            f"wrong process identity for {version}: {routes}",
        )
        return int(fields[3]), diagnostics, compiler_pid

    def close(self):
        if self.process.poll() is None:
            self.send("quit")
            require(
                self.line().split("\t") == ["bye", str(self.pid)],
                "unexpected quit response",
            )
            require(self.process.wait(timeout=20) == 0, "worker exited unsuccessfully")
        self.stderr.close()


def run_unit_tests(binary, workspace, output, selected):
    if selected:
        return run_binary(binary, workspace, output)
    result = subprocess.run(
        [str(binary)],
        cwd=workspace / PACKAGE,
        env={**os.environ, "INSTA_UPDATE": "no", "CARGO_TERM_COLOR": "never"},
        capture_output=True,
        text=True,
        check=False,
    )
    completed = clock()
    write_logs(output, result.stdout, result.stderr)
    combined = result.stdout + result.stderr
    summaries = list(RESULT.finditer(combined))
    require(len(summaries) == 1, f"full libtest summary missing at {output}")
    counts = dict(zip(COUNT_KEYS, map(int, summaries[0].groups()), strict=True))
    require(
        counts["passed"] + counts["failed"] == EXPECTED_COUNTS["unit"]
        and not any(counts[key] for key in ("ignored", "measured", "filtered")),
        f"full unit suite incomplete: {counts} at {output}",
    )
    require(
        result.returncode == (101 if counts["failed"] else 0),
        f"unexpected full suite exit {result.returncode} at {output}",
    )
    if counts["failed"]:
        require(
            f"{TEST} ... FAILED" in combined or f"{TEST} --- FAILED" in combined,
            f"expected octet behavior failure missing at {output}",
        )
    return {
        "result": "fail" if counts["failed"] else "pass",
        "completed_ns": completed,
        "counts": counts,
    }


def execute(
    mode,
    workspace,
    snapshot,
    expected,
    version,
    output,
    binary,
    invoke,
    selected,
    memory=None,
):
    previous = fingerprint(binary)
    started = clock()
    save(workspace, snapshot)
    if memory is not None:
        memory_started = clock()
        memory_observation = memory.refresh()
        memory_elapsed = clock() - memory_started
    else:
        memory_observation, memory_elapsed = None, None
    status, log, compiler_pid = invoke(version)
    if status == 0:
        test = run_unit_tests(binary, workspace, output, selected)
        outcome = test["result"]
        ended = test["completed_ns"]
    else:
        test, outcome, ended = None, "compile_error", clock()
    require(
        outcome == expected,
        f"{mode} revision {version} got {outcome}, expected {expected}; {output}",
    )
    if status:
        require(
            fingerprint(binary) == previous,
            f"{mode} error replaced old executable at {version}",
        )
    output.with_suffix(".compiler").write_text(log)
    diagnostics = normalize_diagnostics(
        parse_diagnostics(log),
        {key: value for key, value in snapshot.items() if value is not None},
    )
    require(
        not status or diagnostics,
        f"{mode} compile failure missing source diagnostics at {version}",
    )
    return {
        "elapsed_ns": ended - started,
        "outcome": outcome,
        "diagnostics": diagnostics,
        "test_ran": status == 0,
        "test_counts": test["counts"] if test else None,
        "old_executable_preserved": status != 0 and previous is not None,
        "compiler_pid": compiler_pid,
        **(
            {
                "incremental_memory": memory_observation,
                "incremental_memory_refresh_ns": memory_elapsed,
            }
            if memory is not None
            else {}
        ),
        "flat_dep_graph": [
            line.removeprefix("ohm-flat-dep-graph\t")
            for line in log.splitlines()
            if line.startswith("ohm-flat-dep-graph\t")
        ],
    }


def case_evidence(rows):
    counts = dict.fromkeys(("pass", "fail", "compile_error"), 0)
    cases = {}
    for row in rows:
        counts[row["expected"]] += 1
        result = row["modes"]["worker"]
        evidence = {
            "test_counts": result["test_counts"],
            "source_error_codes": [
                item["code"]["code"] if item.get("code") else None
                for item in result["diagnostics"]
                if item["level"] == "error"
            ],
        }
        previous = cases.setdefault(row["case"], evidence)
        require(
            previous == evidence,
            f"inconsistent test counts or error codes for {row['case']}",
        )
    return counts, cases


def memory_evidence(rows):
    keys = (
        "retention",
        "file_count",
        "locked_files",
        "locked_bytes",
        "locked_page_bytes",
        "prefaulted_bytes",
        "mapped_page_bytes",
        "new_prefaulted_bytes",
        "new_files",
        "reused_files",
        "released_files",
        "skipped_bytes",
        "skipped_page_bytes",
    )
    result = []
    for row in rows:
        entry = row["modes"]["worker"]["incremental_memory"]
        result.append(
            {
                "case": row["case"],
                **{key: entry[key] for key in keys},
                "error_count": len(entry["errors"]),
                "file_names": sorted(
                    {
                        Path(path).name
                        for item in entry["files"]
                        for path in item["paths"]
                    }
                ),
            }
        )
    return result


def paired_timing_statistics(rows):
    measured = [row for row in rows if row["round"] > 0]
    require(measured, "paired timing needs at least one measured revision")

    def group(selected):
        elapsed = {
            mode: [row["modes"][mode]["elapsed_ns"] for row in selected]
            for mode in ("worker", "fresh")
        }
        require(
            all(time > 0 for times in elapsed.values() for time in times),
            "paired timings must be positive",
        )
        pairs = list(zip(elapsed["worker"], elapsed["fresh"], strict=True))
        ratios = sorted(control / candidate for candidate, control in pairs)
        median_ratio = round(statistics.median(ratios), 4)
        return {
            "revisions": len(selected),
            "save_to_result_ms": {
                mode: distribution(times, 1e6) for mode, times in elapsed.items()
            },
            "ratio_of_medians_fresh_over_worker": round(
                statistics.median(elapsed["fresh"])
                / statistics.median(elapsed["worker"]),
                4,
            ),
            "median_of_paired_ratios_fresh_over_worker": median_ratio,
            "paired_ratio_fresh_over_worker": {
                "min": round(ratios[0], 4),
                "median": median_ratio,
                "p95": round(ratios[math.ceil(0.95 * len(ratios)) - 1], 4),
                "max": round(ratios[-1], 4),
            },
            "worker_wins": sum(candidate < control for candidate, control in pairs),
            "fresh_wins": sum(control < candidate for candidate, control in pairs),
            "ties": sum(control == candidate for candidate, control in pairs),
        }

    return {
        "ratio_definition": "fresh control divided by worker candidate; values above 1 favor the candidate. Ratios pair the same source revision before aggregation; a ratio of pooled medians can disagree with the matched comparisons.",
        "all": group(measured),
        "successful_compilations": group(successful)
        if (
            successful := [
                row for row in measured if row["expected"] != "compile_error"
            ]
        )
        else None,
        "by_outcome": {
            outcome: group(selected)
            for outcome in ("pass", "fail", "compile_error")
            if (selected := [row for row in measured if row["expected"] == outcome])
        },
        "by_round": {
            str(number): group([row for row in measured if row["round"] == number])
            for number in sorted({row["round"] for row in measured})
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("driver", "stage", "capture", "repo", "output"):
        parser.add_argument(
            f"--{name}", type=lambda item: Path(item).resolve(), required=True
        )
    parser.add_argument("--compiler-revision", required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument(
        "--selected-test",
        action="store_true",
        help="run only the exact octet test instead of all parser unit tests",
    )
    parser.add_argument(
        "--reuse-compiler-process",
        action="store_true",
        help="research-only: proc macro dylibs and mutable global state can persist; ordinary Ruff runs must leave this disabled",
    )
    parser.add_argument(
        "--pin-incremental-pages",
        action="store_true",
        help="keep the worker's serialized stock incremental files mapped and prefaulted in this process",
    )
    parser.add_argument(
        "--require-locked-pages",
        action="store_true",
        help="require the optional page experiment to successfully lock selected pages",
    )
    parser.add_argument("--memory-limit-mib", type=int, default=256)
    parser.add_argument(
        "--flat-dep-graph",
        action="store_true",
        help="opt the worker alone into the compiler's experimental mapped dependency graph sidecar",
    )
    args = parser.parse_args()
    require(args.rounds > 0 and args.warmups >= 0, "invalid round count")
    require(
        args.memory_limit_mib > 0
        and (not args.require_locked_pages or args.pin_incremental_pages),
        "invalid incremental memory options",
    )
    require(
        not (args.pin_incremental_pages and args.flat_dep_graph),
        "measure one candidate at a time",
    )
    args.output.mkdir(parents=True, exist_ok=False)
    capture = json.loads(args.capture.read_text())
    workspaces = {
        name: args.output / name / "workspace" for name in ("worker", "fresh")
    }
    commands = {}
    for mode, workspace in workspaces.items():
        archive_ruff(args.repo, workspace)
        executable = args.driver if mode == "worker" else args.stage / "bin/rustc"
        commands[mode] = revision_command(
            executable, capture, workspace, workspace.parent / "target", args.stage
        )
        if args.flat_dep_graph:
            commands[mode][1].pop("RUSTC_OHM_FLAT_DEP_GRAPH", None)
            commands[mode][1].pop("RUSTC_OHM_FLAT_DEP_GRAPH_TRACE", None)
            if mode == "worker":
                commands[mode][1].update(
                    RUSTC_OHM_FLAT_DEP_GRAPH="1", RUSTC_OHM_FLAT_DEP_GRAPH_TRACE="1"
                )
    corpus = cases(workspaces["worker"])
    worker = Worker(
        *commands["worker"][:2],
        workspaces["worker"],
        args.output / "worker.stderr",
        args.reuse_compiler_process,
    )
    if args.pin_incremental_pages:
        from incremental_memory import IncrementalMemory

        memory = IncrementalMemory(
            workspaces["worker"].parent / "target" / "incremental",
            args.memory_limit_mib * 1024 * 1024,
            require_lock=args.require_locked_pages,
        )
    else:
        memory = None
    rows, version = [], 0
    try:
        for index in range(args.warmups + args.rounds):
            for name, expected, snapshot in corpus:
                version += 1
                row = {
                    "case": name,
                    "expected": expected,
                    "round": index - args.warmups + 1,
                    "modes": {},
                }
                for mode in (
                    ("worker", "fresh") if index % 2 == 0 else ("fresh", "worker")
                ):
                    command, env, binary = commands[mode]

                    def fresh(
                        _version, command=command, workspace=workspaces[mode], env=env
                    ):
                        process = subprocess.Popen(
                            command,
                            cwd=workspace,
                            env=env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                        )
                        _stdout, stderr = process.communicate()
                        return process.returncode, stderr, process.pid

                    result = execute(
                        mode,
                        workspaces[mode],
                        snapshot,
                        expected,
                        version,
                        args.output / f"{version:03}-{mode}",
                        binary,
                        worker.compile if mode == "worker" else fresh,
                        args.selected_test,
                        memory if mode == "worker" else None,
                    )
                    row["modes"][mode] = result
                require(
                    row["modes"]["worker"]["diagnostics"]
                    == row["modes"]["fresh"]["diagnostics"],
                    f"worker and fresh diagnostics differ at {name} ({version}); inspect {args.output}",
                )
                require(
                    row["modes"]["worker"]["test_counts"]
                    == row["modes"]["fresh"]["test_counts"],
                    f"worker and fresh libtest counts differ at {name} ({version})",
                )
                rows.append(row)
                print(f"{version} {name} {expected}", flush=True)
    finally:
        worker.close()
        if memory is not None:
            memory.close()
    measured = [row for row in rows if row["round"] > 0]
    process_counts = {
        mode: len({row["modes"][mode]["compiler_pid"] for row in measured})
        for mode in workspaces
    }
    require(
        process_counts["worker"]
        == (1 if args.reuse_compiler_process else len(measured))
        and process_counts["fresh"] == len(measured),
        f"unexpected compiler process counts: {process_counts}",
    )
    if args.flat_dep_graph:
        candidate_events = [row["modes"]["worker"]["flat_dep_graph"] for row in rows]
        control_events = [row["modes"]["fresh"]["flat_dep_graph"] for row in rows]
        require(
            any("loaded" in events for events in candidate_events)
            and any("written" in events for events in candidate_events)
            and not any(control_events),
            "experimental sidecar was not both written and loaded, or contaminated the fresh control",
        )

    def times(selected):
        return {
            mode: distribution(
                [row["modes"][mode]["elapsed_ns"] for row in selected], 1e6
            )
            for mode in workspaces
        }

    outcome_counts, evidence = case_evidence(measured)
    summary = {
        "schema": 1,
        "ruff_revision": REVISION,
        "compiler": compiler(args.stage, args.compiler_revision),
        "machine": machine(),
        "rounds": args.rounds,
        "warmups": args.warmups,
        "test": TEST
        if args.selected_test
        else "all 245 ruff_python_parser unit tests; macro regression must fail the octet test",
        "target_debuginfo": "line-tables-only; split off",
        "method": "One dispatcher PID, fresh normal rustc session for every edit, and ordinary disk incremental state; the default starts a fresh compiler subprocess per edit for procedural-macro isolation. The independent comparator starts the same rustc anew per edit with separate disk incremental state. Timers include save, compilation and test execution on successful compilations. This is not warm Cargo or semantic-query reuse in memory.",
        "compiler_process_policy": "research-only shared process; no procedural-macro isolation"
        if args.reuse_compiler_process
        else "fresh isolated compiler process for every revision",
        **(
            {
                "incremental_page_prefault": {
                    "limit_bytes": args.memory_limit_mib * 1024 * 1024,
                    "require_locked_pages": args.require_locked_pages,
                    "refresh_ms": distribution(
                        [
                            row["modes"]["worker"]["incremental_memory_refresh_ns"]
                            for row in measured
                        ],
                        1e6,
                    ),
                    "source": "The parent maps only the last finalized incremental generation. On APFS rustc normally clones that generation into a working directory with new file identities; this control does not establish that it pins the exact vnode subsequently opened by rustc.",
                    "observations": memory_evidence(measured),
                }
            }
            if memory is not None
            else {}
        ),
        **(
            {
                "experimental_flat_dep_graph": {
                    "worker_events": [
                        row["modes"]["worker"]["flat_dep_graph"] for row in measured
                    ],
                    "fresh_events": [
                        row["modes"]["fresh"]["flat_dep_graph"] for row in measured
                    ],
                    "worker_revision_counts": {
                        event: sum(
                            event in row["modes"]["worker"]["flat_dep_graph"]
                            for row in measured
                        )
                        for event in ("loaded", "written", "fallback", "write-failed")
                    },
                }
            }
            if args.flat_dep_graph
            else {}
        ),
        "validation": {
            "measured_revisions": len(measured),
            "same_dispatcher_pid": True,
            "worker_compiler_processes": process_counts["worker"],
            "fresh_comparator_processes": process_counts["fresh"],
            "all_expected_outcomes_match": True,
            "test_counts_match": True,
            "outcome_counts": outcome_counts,
            "exact_normalized_source_diagnostics_match": True,
            "no_test_after_compile_error": all(
                not item["test_ran"]
                for row in measured
                if row["expected"] == "compile_error"
                for item in row["modes"].values()
            ),
            "existing_binary_preserved_after_module_error": all(
                item["old_executable_preserved"]
                for row in measured
                if row["case"] == "delete-still-referenced-module"
                for item in row["modes"].values()
            ),
        },
        "save_to_result_ms": times(measured),
        "ratio_of_medians_fresh_over_worker": round(
            statistics.median(row["modes"]["fresh"]["elapsed_ns"] for row in measured)
            / statistics.median(
                row["modes"]["worker"]["elapsed_ns"] for row in measured
            ),
            3,
        ),
        "paired_timing": paired_timing_statistics(rows),
        "by_case_ms": {
            name: {
                "outcome": expected,
                **evidence[name],
                **times([row for row in measured if row["case"] == name]),
            }
            for name, expected, _ in corpus
        },
    }
    write_json(args.output / "raw.json", rows)
    write_json(args.output / "summary.json", summary)


if __name__ == "__main__":
    main()
