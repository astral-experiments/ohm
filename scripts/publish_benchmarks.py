#!/usr/bin/env python3
"""Publish benchmark measurements and refresh the tables from the checked-in reports."""

import argparse
import copy
import json
import math
from pathlib import Path
import re
import statistics
import subprocess

import workflow_results

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "scripts/benchmark_results"
KINDS = ("workflow", "sessions", "historical", "ablation", "disk")
TY_WORKTREE_REPORT = "ty-worktree.json"
TY_SCENARIO = "scripts/session_replays/ty-29327.json"
DEVELOPER_WORKFLOW_REPORT = "developer-workflows.json"
DISK_HEADLINE = r"disk usage (?:decreases by around \d+%(?: in completed ten-worktree comparisons)?|comparisons are incomplete)"


def load(path):
    return json.loads(path.read_text())


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def compact(report):
    """Keep the measurements and audit summaries used to interpret a run."""
    result = copy.deepcopy(report)
    provenance = result["provenance"] = {
        key: value
        for key, value in result.get("provenance", {}).items()
        if key in {
            "runner_sha256",
            "wrapper",
            "toolchains",
            "helpers",
            "python",
            "system_cpu",
            "raw_results_sha256",
            "fixtures",
            "exporter_sha256",
            "cargo_home_configuration",
            "native_tools",
        }
    }
    cpu = provenance.get("system_cpu", {})
    cpu.pop("commands", None)
    cpu.pop("trace_jsonl", None)
    cpu.pop("preflight_attempts", None)
    for segment in cpu.get("segments", []):
        segment.pop("trace_jsonl", None)
        preflight = segment.get("preflight", {})
        if "samples" in preflight:
            preflight["sample_count"] = len(preflight.pop("samples"))
    for attempt in cpu.get("excluded_attempts", []):
        attempt.pop("trace_jsonl", None)
    for key in ("raw_evidence", "evidence", "full_report"):
        result.pop(key, None)
    return result


def latest_reports():
    return {kind: load(RESULTS / f"{kind}.json") for kind in KINDS}


SESSION_LABELS = {"ruff": "Ruff session", "uv": "uv session", "codex": "Codex session"}


def validate_session_coverage(report):
    excluded = report.get("excluded_projects", {})
    if not isinstance(excluded, dict) or not excluded.keys() <= SESSION_LABELS.keys() or not all(
        isinstance(reason, str) and reason.strip() for reason in excluded.values()
    ):
        raise ValueError("Invalid session exclusions")
    if report["repetitions"] < 1:
        raise ValueError("A session comparison needs at least one repetition")
    complete = SESSION_LABELS.keys() - excluded.keys()
    for key in ("commands", "timed_command_seconds", "timed_session_seconds"):
        if set(report[key]) != complete:
            raise ValueError(f"Session coverage differs for {key}")
    for project in complete:
        for key in ("timed_command_seconds", "timed_session_seconds"):
            lanes = report[key][project]
            if set(lanes) != {"stock", "ohm"} or any(
                len(values) != report["repetitions"]
                or not all(math.isfinite(v) and v > 0 for v in values)
                for values in lanes.values()
            ):
                raise ValueError(f"Incomplete session comparison for {project}")


def validate_partial_disk(disk, release):
    """Validate the terminal inventory and the pairs selected for publication."""

    def require(condition):
        if not condition:
            raise ValueError("Incomplete or inconsistent partial disk report")

    try:
        validation = disk["validation"]
        terminal = disk["campaign"]["fork_continuation"]
        require(disk["release"] == terminal["release"] == release)
        require(
            terminal["state"] == "finished_with_failed_original_cohort"
            and math.isfinite(terminal["finished_at"])
        )
        require(
            validation["full_campaign_passed"] is False
            and validation[
                "paired_sources_explicit_settings_commands_and_test_counts_match"
            ]
            is True
        )
        rows = disk["cohort_inventory"]
        inventory = {row["cell"]: row for row in rows}
        expected = {
            f"{p}-{label}-{mode}"
            for p in ("ruff", "uv")
            for label in ("stock", "ohm")
            for mode in ("single", "forks")
        }
        require(len(rows) == 8 and set(inventory) == expected)
        require(
            all(
                r["state"] in {"audited_complete", "failed"}
                and r["accepted"] is (r["state"] == "audited_complete")
                for r in rows
            )
        )
        accepted = {cell for cell, row in inventory.items() if row["accepted"]}
        require(accepted < expected and validation["timing_comparisons"] is False)
        require({r["cell"] for r in disk["cohorts"]} == accepted)
        eligible, missing = set(), {}
        for project in ("ruff", "uv"):
            for mode in ("single", "forks"):
                pair = {f"{project}-{label}-{mode}" for label in ("stock", "ohm")}
                if pair <= accepted:
                    eligible.update(
                        (project, mode, n)
                        for n in ([1] if mode == "single" else [2, 10])
                    )
                else:
                    missing[project, mode] = pair - accepted
        observed = set()
        for item in disk["readme_comparisons"]:
            row = item["comparison"]
            key = row["project"], row["cohort"], row["worktrees"]
            require(
                key in eligible
                and key not in observed
                and item["project"] == row["project"]
            )
            require(row["valid_pair"] is True and row["mismatched_fields"] == [])
            if row["worktrees"] != 2:
                require(
                    all(
                        row[label + "_retained_bytes"]
                        == inventory[f"{row['project']}-{label}-{row['cohort']}"][
                            "retained_bytes"
                        ]
                        for label in ("stock", "ohm")
                    )
                )
            observed.add(key)
        require(observed == eligible)
        omitted = disk["omitted_comparisons"]
        require(
            len(omitted) == len(missing)
            and {(r["project"], r["cohort"]) for r in omitted} == set(missing)
        )
        require(
            all(
                set(r["missing_audited_cohorts"]) == missing[r["project"], r["cohort"]]
                and r["ratio"] is None
                for r in omitted
            )
        )
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Missing partial disk report identities") from error


CODEX_TEST_COUNT_COMPARISON = (
    "Unique successful nextest selections; raw tests_started includes "
    "verified captured retry banners and remains unchanged."
)


def replay_test_counts(report, kind, project, command):
    started = command["tests_started"]
    method = report["methodology"].get("test_count_comparison_by_project", {}).get(project)
    if not (
        kind == "sessions"
        and project == "codex"
        and command["category"] == "test"
        and method == CODEX_TEST_COUNT_COMPARISON
    ):
        if "selected_tests_completed" in command:
            raise ValueError("Unexpected selected test counts")
        return started

    # Retry output can contain extra libtest banners for the same selected tests.
    selected = command.get("selected_tests_completed")
    if not isinstance(selected, dict) or set(selected) != {"stock", "ohm"} or set(started) != set(selected):
        raise ValueError("Missing selected test counts")
    for lane, counts in selected.items():
        banners = started[lane]
        if (
            not isinstance(counts, list)
            or not isinstance(banners, list)
            or len(counts) != report["repetitions"]
            or len(banners) != len(counts)
            or any(type(n) is not int or type(b) is not int or not 0 < n <= b for n, b in zip(counts, banners))
        ):
            raise ValueError("Invalid selected test counts")
    return selected


def validate(reports):
    release = reports["sessions"]["ohm_release"]
    if not re.fullmatch(r"ohm-\d+\.\d+\.\d+-[1-9]\d*", release):
        raise ValueError("Invalid Ohm release identity")
    validate_session_coverage(reports["sessions"])
    rust = reports["sessions"]["rust_version"]
    if not release.startswith(f"ohm-{rust}-"):
        raise ValueError("Ohm and stock Rust versions differ")
    for kind in KINDS[:-1]:
        report = reports[kind]
        if (report["ohm_release"], report["rust_version"]) != (release, rust):
            raise ValueError(f"{kind}: mismatched toolchain identity")
        if "failure" in report:
            failure = report["failure"]
            if (
                kind not in {"historical", "ablation"}
                or set(report) - {"rust_version", "ohm_release", "failure", "host", "provenance"}
                or not isinstance(failure, dict)
                or failure.get("project") != {"historical": "ruff", "ablation": "uv"}[kind]
                or not isinstance(failure.get("reason"), str)
                or not failure["reason"].strip()
                or not re.fullmatch(r"[0-9a-f]{64}", failure.get("log_sha256", ""))
            ):
                raise ValueError(f"{kind}: invalid failed replay report")
            continue
        methodology = report["methodology"]
        if not methodology["all_commands_succeeded"]:
            raise ValueError(f"{kind}: unsuccessful measurements")
        if methodology["external_compilations_observed"] != 0:
            raise ValueError(f"{kind}: contaminated measurements")
        if kind != "workflow":
            if not methodology["matching_test_counts_within_pairs"]:
                raise ValueError(f"{kind}: mismatched test counts")
            for project, commands in report["commands"].items():
                for command in commands:
                    counts = list(replay_test_counts(report, kind, project, command).values())
                    if any(value != counts[0] for value in counts):
                        raise ValueError(f"{kind}: mismatched command test counts")
                for lane, totals in report["timed_command_seconds"][project].items():
                    if len(totals) != report["repetitions"]:
                        raise ValueError(f"{kind}: missing repetitions")
                    for repetition, total in enumerate(totals):
                        values = [c["wall_seconds"][lane][repetition] for c in commands]
                        if not all(math.isfinite(v) and v > 0 for v in values):
                            raise ValueError(f"{kind}: invalid command duration")
                        if not math.isclose(sum(values), total):
                            raise ValueError(f"{kind}: inconsistent command total")
    workflow = reports["workflow"]
    if (
        workflow["valid_samples"] != workflow["planned_samples"]
        or workflow["unmeasured_cells"]
    ):
        raise ValueError("Workflow measurements are incomplete")
    if len(workflow["samples"]) != workflow["valid_samples"]:
        raise ValueError("Workflow sample count differs")
    for row in workflow["comparisons"]:
        stock, ohm = row["stock_seconds"], row["ohm_seconds"]
        if not all(
            math.isfinite(v) and v > 0 for v in (stock, ohm)
        ) or not math.isclose(stock / ohm, row["speedup"]):
            raise ValueError("Invalid workflow comparison")
    disk = reports["disk"]
    status = disk["validation"]["status"]
    if status not in {"pass", "partial"} or set(disk["toolchains"]) != {
        release,
        rust if status == "partial" else "stock-" + rust,
    }:
        raise ValueError("Disk audit or toolchain identity differs")
    if status == "partial":
        validate_partial_disk(disk, release)
    for item in disk["readme_comparisons"]:
        row = item["comparison"]
        stock, ohm = row["stock_retained_bytes"], row["ohm_retained_bytes"]
        if not all(math.isfinite(v) and v > 0 for v in (stock, ohm)) or not all(
            math.isclose(expected, row[key])
            for key, expected in {
                "percent_less_disk": 100 * (stock - ohm) / stock,
                "bytes_saved": stock - ohm,
                "stock_gib": stock / 2**30,
                "ohm_gib": ohm / 2**30,
            }.items()
        ):
            raise ValueError("Invalid disk comparison")
    return release, rust


def table(headers, rows):
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(row) + " |" for row in rows),
        ]
    )


def render_tables(reports, ty_worktree, ty_scenario):
    release, rust = validate(reports)
    version = release.removeprefix("ohm-")
    if ty_worktree["rust"] != rust or not re.fullmatch(
        rf"ohm-{re.escape(rust)}-[1-9]\d*", ty_worktree["ohm"]
    ):
        raise ValueError("ty study and table toolchain identities differ")
    sessions = reports["sessions"]
    mean = statistics.fmean
    projects = tuple(p for p in SESSION_LABELS if p in sessions["commands"])
    incomplete = bool(sessions.get("excluded_projects"))

    def ty_total(group, lane):
        total = ty_worktree[group][lane]["total"]
        samples = total["samples"]
        if not samples or not all(math.isfinite(v) and v > 0 for v in samples):
            raise ValueError("Invalid ty study samples")
        median = statistics.median(samples)
        if not math.isclose(median, total["median"]):
            raise ValueError("ty study median differs from samples")
        return median

    def seconds(pair):
        stock, ohm = pair
        saved = f"{100 * (stock - ohm) / stock:.2f}%".replace("-", "−") if stock else "—"
        return [f"{stock:,.2f} s", f"{ohm:,.2f} s", saved]

    lanes = ("stock", "ohm")
    ty_commands = [step for step in ty_scenario["steps"] if step["kind"] == "command"]
    ty_steps = ty_worktree["session_steps"]
    if len(ty_commands) != len(ty_steps):
        raise ValueError("ty command count differs from the fixture")
    ty_categories = {
        key: [0.0, 0.0]
        for key in ("check", "test", "clippy", "formatting", "other")
    }
    cargo_categories = {
        "check": "check",
        "test": "test",
        "nextest": "test",
        "clippy": "clippy",
        "fmt": "formatting",
    }
    samples_by_lane = {lane: [] for lane in lanes}
    for step, command in zip(ty_steps, ty_commands, strict=True):
        if step["label"] != command["label"]:
            raise ValueError("ty commands differ from the fixture")
        category = (
            cargo_categories.get(command["args"][0], "other")
            if command["program"] == "cargo"
            else "other"
        )
        for index, lane in enumerate(lanes):
            samples = step[lane]["seconds"]["samples"]
            if not samples or not all(math.isfinite(v) and v > 0 for v in samples):
                raise ValueError("Invalid ty command samples")
            samples_by_lane[lane].append(samples)
            ty_categories[category][index] += mean(samples)
    for lane in lanes:
        totals = ty_worktree["session"][lane]["commands"]["samples"]
        if not totals or any(
            len(samples) != len(totals) for samples in samples_by_lane[lane]
        ):
            raise ValueError("ty command sample counts differ")
        if any(
            not math.isclose(sum(samples[i] for samples in samples_by_lane[lane]), total)
            for i, total in enumerate(totals)
        ):
            raise ValueError("ty command totals differ from their samples")

    session_rows = []
    totals = [0.0, 0.0]
    for project, label in SESSION_LABELS.items():
        if project not in projects:
            session_rows.append([f"{label} (incomplete)", "—", "—", "—"])
            continue
        pair = [
            mean(sessions["timed_session_seconds"][project][lane])
            for lane in ("stock", "ohm")
        ]
        totals = [a + b for a, b in zip(totals, pair, strict=True)]
        session_rows.append([label, *seconds(pair)])
    ty_pair = []
    for lane in lanes:
        ty_total("session", lane)
        ty_pair.append(mean(ty_worktree["session"][lane]["total"]["samples"]))
    session_rows.append(["ty session", *seconds(ty_pair)])
    totals = [a + b for a, b in zip(totals, ty_pair, strict=True)]
    session_rows.append(["Completed sessions" if incomplete else "All sessions", *seconds(totals)])
    for category, label in (
        ("check", "`cargo check`"),
        ("test", "`cargo test`, `cargo nextest`, `just test`"),
        ("clippy", "`cargo clippy`"),
        ("formatting", "`cargo fmt`"),
        ("other", "Other commands"),
    ):
        pair = [
            sum(
                mean(c["wall_seconds"][lane])
                for p in projects
                for c in sessions["commands"][p]
                if c["category"] == category
                or (category == "other" and c["category"] not in ty_categories)
            )
            + ty_categories[category][index]
            for index, lane in enumerate(lanes)
        ]
        session_rows.append([label, *seconds(pair)])
    session_rows.append(
        [
            "Commands in completed sessions" if incomplete else "All commands",
            *seconds(
                [
                    sum(
                        mean(sessions["timed_command_seconds"][p][lane])
                        for p in projects
                    )
                    + mean(ty_worktree["session"][lane]["commands"]["samples"])
                    for lane in lanes
                ]
            ),
        ]
    )

    disk_rows = []
    savings = []
    for item in reports["disk"]["readme_comparisons"]:
        row = item["comparison"]
        project = "Ruff/ty" if item["project"] == "ruff" else "uv"
        label = project + (
            " session" if row["worktrees"] == 1 else f", {row['worktrees']} worktrees"
        )
        disk_rows.append(
            [
                label,
                f"{row['stock_retained_bytes'] / 2**30:.2f} GiB",
                f"{row['ohm_retained_bytes'] / 2**30:.2f} GiB",
                f"{row['percent_less_disk']:.2f}%",
            ]
        )
        if row["worktrees"] == 10:
            savings.append(row["percent_less_disk"])

    comparisons = reports["workflow"]["comparisons"]
    indexed = {(r["project"], r["workflow"], r["phase"]): r for r in comparisons}

    def workflow_row(key, labels):
        row = indexed[key]
        return [
            *labels,
            f"{row['stock_seconds']:.2f} s",
            f"{row['ohm_seconds']:.2f} s",
            f"{row['speedup']:.2f}×",
        ]

    rendered = {
        "sessions": table(
            ["Scope", f"Rust {rust}", "Ohm", "Time saved"], session_rows
        ),
        "disk": table(
            ["Scope", f"Rust {rust}", f"Ohm {version}", "Space saved"], disk_rows
        ),
    }
    for phase in ("direct", "dependency"):
        rows = []
        for project, label, package, dependency, commands in (
            (
                "uv",
                "uv",
                "uv",
                "uv-normalize",
                ("cargo check", "cargo clippy", "cargo test --test it"),
            ),
            (
                "codex-core",
                "Codex",
                "codex-core",
                "codex-utils-string",
                ("cargo check", "just clippy", "just test"),
            ),
        ):
            for workflow, command in zip(
                ("check", "clippy", "test"), commands, strict=True
            ):
                rows.append(
                    workflow_row(
                        (project, workflow, phase),
                        [
                            label,
                            f"`{command}`",
                            f"`{package if phase == 'direct' else dependency}`",
                        ],
                    )
                )
        rendered[phase] = table(
            [
                "Project",
                "Workflow",
                "Edited crate" if phase == "direct" else "Edited dependency",
                f"Rust {rust}",
                f"Ohm {version}",
                "Speedup",
            ],
            rows,
        )
    features = [
        (("uv", "build-check", "transition"), ["uv", "Check after build", "`uv`"]),
        (
            ("uv", "shared-build", "reuse"),
            ["uv", "Shared-worktree build", "`uv-normalize`"],
        ),
        (
            ("codex-core", "build-check", "transition"),
            ["Codex", "Check after build", "`codex-core`"],
        ),
        (("codex-core", "fmt", "noop"), ["Codex", "No-op formatting", "Workspace"]),
        (
            ("codex-core", "fmt", "direct"),
            ["Codex", "Formatting after an edit", "`codex-core`"],
        ),
        (
            ("codex-core", "shared-build", "reuse"),
            ["Codex", "Shared-worktree build", "`codex-utils-string`"],
        ),
    ]
    feature_rows = [workflow_row(key, labels) for key, labels in features]
    for group, filesystem in (
        ("worktree", "ext4"),
        ("worktree_copy_on_write", "Btrfs"),
    ):
        stock = ty_total(group, "stock")
        ohm = ty_total(group, "ohm-trusted")
        feature_rows.append(
            [
                "ty",
                f"Worktree startup ({filesystem})",
                "`ty_python_semantic`",
                f"{stock:.2f} s",
                f"{ohm:.2f} s",
                f"{stock / ohm:.2f}×",
            ]
        )
    rendered["features"] = table(
        ["Project", "Workflow", "Package", f"Rust {rust}", "Ohm", "Speedup"],
        feature_rows,
    )
    headlines = {
        r"incremental builds can be up to \d+×": f"incremental builds can be up to {math.floor(max(r['speedup'] for r in comparisons if r['workflow'] in ('check', 'clippy', 'test') and r['phase'] in ('direct', 'dependency', 'noop')))}×",
        r"\d+% less time": f"{round(100 * (totals[0] - totals[1]) / totals[0])}% less time",
        DISK_HEADLINE: (
            f"disk usage decreases by around {5 * round(mean(savings) / 5)}%"
            + (
                " in completed ten-worktree comparisons"
                if reports["disk"]["validation"]["status"] == "partial"
                else ""
            )
            if savings
            else "disk usage comparisons are incomplete"
        ),
    }
    return rendered, headlines


def documents(reports):
    tables, headlines = render_tables(
        reports, load(RESULTS / TY_WORKTREE_REPORT), load(ROOT / TY_SCENARIO)
    )
    workflows = load(RESULTS / DEVELOPER_WORKFLOW_REPORT)
    tables["developer-workflows"] = table(
        [
            "Project",
            "Workflow",
            f"Rust {workflows['rust_version']}",
            f"Ohm {workflow_results.toolchain_label(workflows)}",
            "Time saved",
        ],
        workflow_results.table_rows(workflows),
    )
    result = {
        name: (ROOT / name).read_text() for name in ("README.md", "BENCHMARKS.md")
    }
    for key, value in tables.items():
        pattern = rf"(<!-- benchmark:{key} -->\n).*?(\n<!-- /benchmark:{key} -->)"
        count = 0
        for name, text in result.items():
            result[name], found = re.subn(
                pattern, lambda m: m[1] + value + m[2], text, flags=re.S
            )
            count += found
        if count != 1:
            raise ValueError(f"Expected one {key} table, found {count}")
    for pattern, value in headlines.items():
        result["README.md"], count = re.subn(pattern, value, result["README.md"])
        if count != 1:
            raise ValueError(f"Expected one README headline matching {pattern}")
    return result


def normalized_markdown(text):
    # Prettier owns alignment and whitespace; this check owns the table contents.
    text = re.sub(r"(?m)^\|[ |:-]+\|\n", "", text)
    return re.sub(r"\s+", " ", text).strip()


def publish(directory):
    reports = {kind: load(directory / f"{kind}.json") for kind in KINDS}
    release, _ = validate(reports)
    updated = documents(reports)
    prettier = ROOT / "node_modules/.bin/prettier"
    if not prettier.is_file():
        raise ValueError("Run npm ci --ignore-scripts before publishing benchmarks")
    paths = {kind: f"scripts/benchmark_results/{kind}.json" for kind in KINDS}
    current = RESULTS / "sessions.json"
    if current.exists() and load(current)["ohm_release"] == release:
        raise ValueError(
            "Results already exist for this release; refusing to replace them"
        )
    for kind, path in paths.items():
        write_json(ROOT / path, compact(reports[kind]))
    for name, text in updated.items():
        (ROOT / name).write_text(text)
    subprocess.run(
        [
            str(prettier),
            "--write",
            *paths.values(),
            *updated,
        ],
        cwd=ROOT,
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "reports",
        type=Path,
        nargs="?",
        help="directory of audited workflow, sessions, historical, ablation, and disk JSON reports",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--check",
        action="store_true",
        help="verify the latest checked-in reports and generated tables without publishing",
    )
    modes.add_argument(
        "--render",
        action="store_true",
        help="regenerate the Markdown tables from the checked-in reports",
    )
    args = parser.parse_args()
    if (args.check or args.render) == (args.reports is not None):
        parser.error("select a reports directory, --check, or --render")
    if args.check:
        for name, expected in documents(latest_reports()).items():
            if normalized_markdown((ROOT / name).read_text()) != normalized_markdown(
                expected
            ):
                raise ValueError(f"{name}: benchmark tables are stale")
        print("Benchmark reports and tables match")
    elif args.render:
        prettier = ROOT / "node_modules/.bin/prettier"
        if not prettier.is_file():
            raise ValueError("Run npm ci --ignore-scripts before rendering benchmarks")
        updated = documents(latest_reports())
        for name, text in updated.items():
            (ROOT / name).write_text(text)
        subprocess.run([str(prettier), "--write", *updated], cwd=ROOT, check=True)
        print("Benchmark tables refreshed")
    else:
        publish(args.reports)


if __name__ == "__main__":
    main()
