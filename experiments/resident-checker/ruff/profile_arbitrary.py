#!/usr/bin/env python3
"""Profile real arbitrary Ruff edits through ordinary isolated incremental rustc."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from arbitrary_ruff import cases, revision_command, run_unit_tests, save
from measure import clock, compiler, distribution, machine, write_json
from measure_test import fingerprint, require
from run_tests import REVISION, archive_ruff
from source_diagnostics import normalize_diagnostics, parse_diagnostics

EVENTS = "generic-activity,incr-cache-load"
DEFAULT_CASES = (
    "unchanged",
    "initial-syntax-error",
    "syntax-repair",
    "signature-and-caller",
    "signature-repair",
    "import-and-all-references",
    "import-repair",
    "macro-definition-and-call",
    "macro-behavior-fails-test",
    "macro-behavior-repair",
    "macro-removal",
    "create-and-use-module",
    "delete-still-referenced-module",
    "recreate-module",
    "remove-module-and-references",
)
ACTIVITIES = {
    "incremental": {
        "prepare_session": "incr_comp_prepare_session_directory",
        "prepare_and_load_graph": "incr_comp_prepare_load_dep_graph",
        "load_graph": "incr_comp_load_dep_graph",
        "decode_graph_reverse_index": "incr_comp_load_dep_graph_reverse_index",
        "open_query_result_cache": "incr_comp_load_query_result_cache",
        "promote_query_cache": "incr_comp_query_cache_promotion",
        "serialize_query_cache": "incr_comp_serialize_result_cache",
        "persist_query_cache": "incr_comp_persist_result_cache",
        "serialize_graph": "serialize_dep_graph",
        "persist_graph": "incr_comp_persist_dep_graph",
        "finalize_session": "incr_comp_finalize_session_directory",
    },
    "frontend": {
        "parse_root": "parse_crate",
        "macro_expansion_including_module_parsing": "macro_expand_crate",
        "procedural_macro_calls": "expand_proc_macro",
        "derive_macro_outer": "expand_derive_proc_macro_outer",
        "resolve_names": "resolve_crate",
        "type_check": "type_check_crate",
        "coherence": "coherence_checking",
        "borrow_check": "MIR_borrow_checking",
        "lints": "lint_checking",
    },
    "backend": {
        "write_metadata": "write_crate_metadata",
        "monomorphization": "monomorphization_collector",
        "find_codegen_unit_reuse": "find_cgu_reuse",
        "codegen_main_thread": "codegen_crate",
        "finish_codegen_main_thread": "finish_ongoing_codegen",
        "llvm_backend": "LLVM_passes",
        "link_including_overhead": "link",
        "run_linker": "run_linker",
    },
}
HIGHLIGHTS = {
    "incremental": (
        "load_graph",
        "decode_graph_reverse_index",
        "open_query_result_cache",
        "lazy_query_decode_self_time",
        "persist_query_cache",
        "serialize_graph",
    ),
    "frontend": (
        "macro_expansion_including_module_parsing",
        "procedural_macro_calls",
        "resolve_names",
        "type_check",
        "borrow_check",
    ),
    "backend": (
        "codegen_main_thread",
        "llvm_backend",
        "link_including_overhead",
        "run_linker",
    ),
}
INVOCATION_COUNTS = {
    "procedural_macro_calls": "expand_proc_macro",
    "derive_macro_outer": "expand_derive_proc_macro_outer",
}


def duration(value):
    return value["secs"] * 1_000_000_000 + value["nanos"]


def read_profile(report):
    items = report["query_data"]
    lookup = {item["label"]: item for item in items}
    require(len(items) == len(lookup), "self-profile summary repeats event labels")
    activities = {}
    for group, names in ACTIVITIES.items():
        activities[group] = {
            name: duration(item["time"])
            for name, label in names.items()
            if (item := lookup.get(label)) is not None
        }
    lazy = {
        item["label"]: value
        for item in items
        if (value := duration(item["incremental_load_time"])) > 0
    }
    activities["incremental"]["lazy_query_decode_self_time"] = sum(lazy.values())
    activities["frontend"]["external_crate_metadata_decode_self_time"] = sum(
        duration(item["self_time"])
        for item in items
        if item["label"].startswith("metadata_decode_entry_")
    )
    counts = {
        name: lookup[label]["invocation_count"] if label in lookup else 0
        for name, label in INVOCATION_COUNTS.items()
    }
    return activities, lazy, counts


def read_report(directory, summarize):
    traces = list(directory.glob("*.mm_profdata"))
    require(len(traces) == 1, f"expected one rustc self-profile at {directory}")
    path = traces[0].with_suffix("")
    result = subprocess.run(
        [str(summarize), "summarize", "--json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    require(result.returncode == 0, f"measureme summarize failed: {result.stderr}")
    return read_profile(json.loads(path.with_suffix(".json").read_text()))


def invoke(command, environment, workspace, directory, profile):
    command = list(command)
    if profile:
        command.extend(
            (f"-Zself-profile={directory}", f"-Zself-profile-events={EVENTS}")
        )
    started = clock()
    result = subprocess.run(
        command,
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = clock() - started
    (directory / "compiler.stdout").write_text(result.stdout)
    (directory / "compiler.stderr").write_text(result.stderr)
    return result, elapsed


def prepare(command, environment, workspace, directory):
    directory.mkdir(parents=True)
    result, _ = invoke(command, environment, workspace, directory, False)
    require(result.returncode == 0, f"initial incremental build failed: {directory}")


def execute(
    args, command, environment, workspace, binary, directory, snapshot, expected
):
    directory.mkdir(parents=True)
    previous = fingerprint(binary)
    started = clock()
    save(workspace, snapshot)
    result, compile_ns = invoke(command, environment, workspace, directory, True)
    compile_done = clock()
    if result.returncode == 0:
        test = run_unit_tests(binary, workspace, directory / "test", args.selected_test)
        outcome, counts = test["result"], test["counts"]
        test_ns = test["completed_ns"] - compile_done
        elapsed = test["completed_ns"] - started
    else:
        outcome, counts, test_ns, elapsed = (
            "compile_error",
            None,
            None,
            compile_done - started,
        )
        require(
            previous == fingerprint(binary),
            f"compile error replaced executable: {directory}",
        )
    require(
        outcome == expected,
        f"unexpected result {outcome}, expected {expected}: {directory}",
    )
    diagnostics = normalize_diagnostics(
        parse_diagnostics(result.stderr),
        {key: value for key, value in snapshot.items() if value is not None},
    )
    require(
        outcome != "compile_error" or diagnostics, f"no source diagnostic: {directory}"
    )
    profile, queries, invocations = read_report(directory, args.summarize)
    if outcome != "compile_error":
        for group, name in (
            ("incremental", "load_graph"),
            ("incremental", "open_query_result_cache"),
            ("frontend", "macro_expansion_including_module_parsing"),
            ("frontend", "type_check"),
            ("backend", "codegen_main_thread"),
            ("backend", "run_linker"),
        ):
            require(
                name in profile[group],
                f"missing {group}.{name} from profile: {directory}",
            )
    return {
        "outcome": outcome,
        "test_counts": counts,
        "error_codes": [
            item["code"]["code"] if item.get("code") else None
            for item in diagnostics
            if item["level"] == "error"
        ],
        "external_ns": {
            "compile": compile_ns,
            "test": test_ns,
            "save_to_result": elapsed,
        },
        "activity_ns": profile,
        "activity_counts": invocations,
        "lazy_query_decode_ns": queries,
    }


def measurements(values, possible):
    values = [value for value in values if value is not None]
    return {
        "observed": len(values),
        "missing": possible - len(values),
        "ms": distribution(values, 1e6) if values else None,
    }


def count_distribution(values):
    return {
        key: int(value) if isinstance(value, float) and value.is_integer() else value
        for key, value in distribution(values).items()
    }


def summarize_rows(rows):
    require(rows, "cannot summarize no profile rows")
    total = len(rows)
    activities = {}
    for group, labels in ACTIVITIES.items():
        names = list(labels)
        if group == "incremental":
            names.append("lazy_query_decode_self_time")
        if group == "frontend":
            names.append("external_crate_metadata_decode_self_time")
        activities[group] = {
            name: measurements(
                [row["activity_ns"][group].get(name) for row in rows], total
            )
            for name in names
        }
    queries = sorted(
        {name for row in rows for name in row["lazy_query_decode_ns"]},
        key=lambda name: sum(row["lazy_query_decode_ns"].get(name, 0) for row in rows),
        reverse=True,
    )
    return {
        "revisions": total,
        "external": {
            name: measurements([row["external_ns"][name] for row in rows], total)
            for name in ("compile", "test", "save_to_result")
        },
        "activities": activities,
        "activity_counts": {
            name: count_distribution([row["activity_counts"][name] for row in rows])
            for name in INVOCATION_COUNTS
        },
        "lazy_query_decode_types": len(queries),
        "largest_lazy_query_decodes": {
            name: measurements(
                [row["lazy_query_decode_ns"].get(name, 0) for row in rows], total
            )
            for name in queries[:10]
        },
    }


def compact_metric(metric):
    result = metric["ms"] or {"count": 0}
    return {**result, **({"missing": metric["missing"]} if metric["missing"] else {})}


def compact_summary(summary):
    def group(item):
        return {
            "revisions": item["revisions"],
            "external_ms": {
                name: compact_metric(metric)
                for name, metric in item["external"].items()
            },
            "activities_ms": {
                group: {
                    name: compact_metric(metric) for name, metric in metrics.items()
                }
                for group, metrics in item["activities"].items()
            },
            "activity_counts": item["activity_counts"],
            "lazy_query_decode_types": item["lazy_query_decode_types"],
            "largest_lazy_query_decodes_ms": {
                name: compact_metric(metric)
                for name, metric in item["largest_lazy_query_decodes"].items()
            },
        }

    def case(item):
        return {
            "outcome": item["outcome"],
            "test_counts": item["test_counts"],
            "error_codes": item["error_codes"],
            "external_ms": {
                name: compact_metric(metric)
                for name, metric in item["external"].items()
            },
            "activity_counts": item["activity_counts"],
            "activity_medians_ms": {
                phase: {
                    name: metric["ms"]["median"]
                    for name in names
                    if (metric := item["activities"][phase][name])["ms"] is not None
                }
                for phase, names in HIGHLIGHTS.items()
            },
        }

    return {
        **{
            name: summary[name]
            for name in (
                "schema",
                "ruff_revision",
                "compiler",
                "machine",
                "rounds",
                "warmups",
                "tests",
                "method",
                "validation",
            )
        },
        "all": group(summary["all"]),
        "by_outcome": {
            name: group(item) for name, item in summary["by_outcome"].items()
        },
        "by_case": {name: case(item) for name, item in summary["by_case"].items()},
    }


def group_rows(measured, names):
    return {
        "all": summarize_rows(measured),
        "by_outcome": {
            outcome: summarize_rows(selected)
            for outcome in ("pass", "fail", "compile_error")
            if (selected := [row for row in measured if row["outcome"] == outcome])
        },
        "by_case": {
            name: {
                "outcome": selected[0]["outcome"],
                "test_counts": selected[0]["test_counts"],
                "error_codes": selected[0]["error_codes"],
                **summarize_rows(selected),
            }
            for name in names
            if (selected := [row for row in measured if row["case"] == name])
        },
    }


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("stage", "capture", "repo", "output"):
        parser.add_argument(
            f"--{name}", type=lambda value: Path(value).resolve(), required=True
        )
    parser.add_argument(
        "--summarize",
        type=lambda value: Path(value).resolve(),
        help="rust-lang/measureme's summarize 12.0.3; default: search PATH",
    )
    parser.add_argument("--compiler-revision", required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument(
        "--cases", nargs="+", choices=DEFAULT_CASES, default=DEFAULT_CASES
    )
    parser.add_argument(
        "--selected-test",
        action="store_true",
        help="only for smoke tests; default: all 245 parser unit tests",
    )
    args = parser.parse_args()
    if args.summarize is None:
        if located := shutil.which("summarize"):
            args.summarize = Path(located)
        else:
            parser.error(
                "install rust-lang/measureme's summarize 12.0.3 and pass --summarize"
            )
    require(args.rounds > 0 and args.warmups >= 0, "invalid round count")
    require(
        len(set(args.cases)) == len(args.cases), "repeated case names are not supported"
    )
    return args


def main():
    args = arguments()
    args.output.mkdir(parents=True, exist_ok=False)
    workspace = args.output / "workspace"
    archive_ruff(args.repo, workspace)
    corpus = {
        name: (expected, snapshot) for name, expected, snapshot in cases(workspace)
    }
    corpus["unchanged"] = corpus["syntax-repair"]
    capture = json.loads(args.capture.read_text())
    command, environment, binary = revision_command(
        args.stage / "bin/rustc", capture, workspace, args.output / "target", args.stage
    )
    prepare(command, environment, workspace, args.output / "initial")
    rows = []
    for round_number in range(1 - args.warmups, args.rounds + 1):
        for index, name in enumerate(args.cases):
            expected, snapshot = corpus[name]
            directory = args.output / f"round-{round_number}" / f"{index:02}-{name}"
            result = execute(
                args,
                command,
                environment,
                workspace,
                binary,
                directory,
                snapshot,
                expected,
            )
            result.update({"round": round_number, "case": name})
            rows.append(result)
            print(f"{round_number} {name} {result['outcome']}", flush=True)
        if round_number != args.rounds and snapshot != corpus["unchanged"][1]:
            save(workspace, corpus["unchanged"][1])
            prepare(
                command,
                environment,
                workspace,
                args.output / f"reset-after-{round_number}",
            )
    measured = [row for row in rows if row["round"] > 0]
    successful = [row for row in measured if row["outcome"] != "compile_error"]
    if successful:
        require(
            any(
                row["activity_ns"]["incremental"].get("decode_graph_reverse_index", 0)
                for row in successful
            ),
            "no dependency-graph reverse index was decoded",
        )
        require(
            any(
                row["activity_ns"]["incremental"]["lazy_query_decode_self_time"]
                for row in successful
            ),
            "no cached query answers were decoded",
        )
    summary = {
        "schema": 1,
        "ruff_revision": REVISION,
        "compiler": compiler(args.stage, args.compiler_revision),
        "machine": machine(),
        "rounds": args.rounds,
        "warmups": args.warmups,
        "tests": "exact octet test"
        if args.selected_test
        else "all 245 parser unit tests",
        "method": {
            "process_policy": "fresh isolated rustc per revision; independent persistent on-disk incremental state; a successful unprofiled baseline compile before all rounds and between rounds when a custom case sequence does not restore baseline",
            "profile": f"-Zself-profile-events={EVENTS}; decoded by rust-lang/measureme summarize 12.0.3; no -Ztime-passes",
            "time": "external compile, test and save-to-result are wall-clock durations, independent of the internal compiler clock; profiling overhead is included, so use a separate unprofiled benchmark for absolute speed",
            "activities": "measureme cumulative inclusive durations per rustc label, except the two explicitly marked self_time; phases are diagnostic, can overlap or nest, can aggregate across invocations or threads, and must not be summed as a compiler wall-time breakdown; lazy query loads sum per-query exclusive decode times across threads",
            "proc_macros": "procedural_macro_calls times and counts actual procedural macro executions; derive_macro_outer is a surrounding activity and is not added to it; absent invocation events count as zero",
            "lazy_query_names": "rustc may report some cached-query labels as <unknown> with this limited event set; their decode time is included in the total and their identity is not inferred",
            "absence": "compiler errors may omit downstream activities; missing values are excluded from medians; a zero lazy-query decode means the profile observed none",
            "debuginfo": "line-tables-only; split off",
        },
        "validation": {
            "every_outcome_matched": True,
            "tests_never_ran_after_compile_error": all(
                row["test_counts"] is None
                for row in measured
                if row["outcome"] == "compile_error"
            ),
            "outcomes": {
                name: sum(row["outcome"] == name for row in measured)
                for name in ("pass", "fail", "compile_error")
            },
        },
        **group_rows(measured, args.cases),
    }
    write_json(args.output / "raw.json", rows)
    write_json(args.output / "detailed-summary.json", summary)
    write_json(args.output / "summary.json", compact_summary(summary))


if __name__ == "__main__":
    main()
