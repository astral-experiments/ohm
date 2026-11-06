#!/usr/bin/env python3
"""Publish benchmark measurements and refresh the tables and charts."""

import argparse
import copy
import json
import math
from pathlib import Path
import re
import statistics
import subprocess

import benchmark_charts
import workflow_results

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "scripts/benchmark_results"
TIMING_KINDS = ("workflow", "sessions", "historical", "ablation")
KINDS = (*TIMING_KINDS, "disk")
TY_WORKTREE_REPORT = "ty-worktree.json"
TY_SCENARIO = "scripts/session_replays/ty-29327.json"
RUFF_DOCTEST_REPORT = "ruff-doctests.json"
DEVELOPER_WORKFLOW_REPORT = "developer-workflows.json"


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


def disk_versions(report):
    manifest = re.fullmatch(
        r"toolchains/(\d+\.\d+\.\d+)/([1-9]\d*)\.json",
        report["release_manifest"]["path"],
    )
    if not manifest:
        raise ValueError("Invalid disk release manifest")
    rust, revision = manifest.groups()
    return rust, f"{rust}-{revision}"


def validate(reports):
    release = reports["sessions"]["ohm_release"]
    if not re.fullmatch(r"ohm-\d+\.\d+\.\d+-[1-9]\d*", release):
        raise ValueError("Invalid Ohm release identity")
    rust = reports["sessions"]["rust_version"]
    if not release.startswith(f"ohm-{rust}-"):
        raise ValueError("Ohm and stock Rust versions differ")
    for kind in TIMING_KINDS:
        report = reports[kind]
        if (report["ohm_release"], report["rust_version"]) != (release, rust):
            raise ValueError(f"{kind}: mismatched toolchain identity")
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
                    counts = list(command["tests_started"].values())
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
    disk_rust, disk_version = disk_versions(disk)
    if disk["validation"]["status"] != "pass" or set(disk["toolchains"]) != {
        f"ohm-{disk_version}",
        f"stock-{disk_rust}",
    }:
        raise ValueError("Disk audit or toolchain identity differs")
    for item in disk["readme_comparisons"]:
        row = item["comparison"]
        stock, ohm = row["stock_retained_bytes"], row["ohm_retained_bytes"]
        if min(stock, ohm) <= 0 or not math.isclose(
            100 * (stock - ohm) / stock, row["percent_less_disk"]
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
    projects = ("ruff", "uv", "codex")

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
        saved = 100 * (stock - ohm) / stock
        return [f"{stock:,.2f} s", f"{ohm:,.2f} s", f"{saved:.2f}%".replace("-", "−")]

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

    session_times = {}
    totals = [0.0, 0.0]
    for project, label in zip(
        projects, ("Ruff session", "uv session", "Codex session"), strict=True
    ):
        pair = [
            mean(sessions["timed_session_seconds"][project][lane])
            for lane in ("stock", "ohm")
        ]
        totals = [a + b for a, b in zip(totals, pair, strict=True)]
        session_times[label] = pair
    ty_pair = []
    for lane in lanes:
        ty_total("session", lane)
        ty_pair.append(mean(ty_worktree["session"][lane]["total"]["samples"]))
    session_times["ty session"] = ty_pair
    totals = [a + b for a, b in zip(totals, ty_pair, strict=True)]
    session_rows = [[label, *seconds(pair)] for label, pair in session_times.items()]
    session_rows.append(["All sessions", *seconds(totals)])
    command_chart = []
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
        stock, ohm = pair
        delta = stock - ohm
        change = "less" if delta >= 0 else "more"
        command = "Tests" if category == "test" else label.strip("`")
        command_chart.append((command, [delta], f"{100 * abs(delta) / stock:.1f}% {change}"))
    session_rows.append(
        [
            "All commands",
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
    disk_chart = []
    savings = []
    disk_rust, disk_version = disk_versions(reports["disk"])
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
            sizes = [row[f"{lane}_retained_bytes"] / 2**30 for lane in lanes]
            disk_chart.append((project, sizes, f"{row['percent_less_disk']:.1f}%"))

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
            ["Scope", f"Rust {disk_rust}", f"Ohm {disk_version}", "Space saved"],
            disk_rows,
        ),
    }
    edits = {}
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
                key = (project, workflow, phase)
                edits.setdefault(f"{label} · {command}", []).append(indexed[key]["speedup"])
                rows.append(
                    workflow_row(
                        key,
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
    session_percent = round(100 * (totals[0] - totals[1]) / totals[0])
    session_direction = "less" if session_percent >= 0 else "more"
    headlines = {
        r"incremental builds can be up to \d+×": f"incremental builds can be up to {math.floor(max(r['speedup'] for r in comparisons if r['workflow'] in ('check', 'clippy', 'test') and r['phase'] in ('direct', 'dependency', 'noop')))}×",
        r"\d+% (?:less|more) time": f"{abs(session_percent)}% {session_direction} time",
        r"disk usage decreases by around \d+%": f"disk usage decreases by around {5 * round(mean(savings) / 5)}%",
    }
    charts = {
        "sessions": benchmark_charts.bars(
            "Mean replay time by project",
            [(label.removesuffix(" session"), (stock, ohm), f"{stock / ohm:.2f}×")
             for label, (stock, ohm) in sorted(session_times.items(), key=lambda r: -r[1][0])],
            legend=(f"Rust {rust}", f"Ohm {version}"), value_label=benchmark_charts.elapsed,
            left=88, column="Speedup",
        ),
        "commands": benchmark_charts.bars(
            "Wall time saved by command across the four replays",
            sorted(command_chart, key=lambda r: -r[1][0]), legend=(),
            value_label=lambda delta: benchmark_charts.elapsed(abs(delta)) + (" longer" if delta < 0 else ""),
            left=140, column="Time vs. Rust",
        ),
        "edits": benchmark_charts.bars(
            "Speedup over stock Rust after a direct or dependency edit",
            [(label, pair, "") for label, pair in edits.items()],
            legend=("Direct edit", "Dependency edit"), value_label=lambda v: f"{v:.2f}×", left=182,
        ),
        "disk": benchmark_charts.bars(
            "Disk space retained by ten worktrees on APFS", disk_chart,
            legend=(f"Rust {disk_rust}", f"Ohm {disk_version}"), value_label=lambda v: f"{v:.2f} GiB",
            left=88, column="Space saved",
        ),
    }
    return rendered, headlines, charts


def ruff_doctest_table(report):
    medians = {}
    for lane in ("stock", "ohm"):
        samples = [s for s in report["samples"] if s["toolchain"] == lane]
        if [s["pair"] for s in samples] != list(range(6)):
            raise ValueError(f"Expected one cold run and five warm Ruff doctest runs for {lane}")
        times = [s["seconds"] for s in samples[1:]]
        if not all(math.isfinite(t) and t > 0 for t in times):
            raise ValueError(f"Invalid Ruff doctest time for {lane}")
        medians[lane] = statistics.median(times)
    stock, ohm = medians["stock"], medians["ohm"]
    version = report["ohm"].removeprefix("ohm-")
    headers = ["Workload", f"Rust {report['upstream']}", f"Ohm {version}", "Speedup"]
    row = [
        "Ruff doctests (`cargo test --doc`)",
        f"{stock:.3f} s",
        f"{ohm:.3f} s",
        f"{stock / ohm:.2f}×",
    ]
    return table(headers, [row])


def documents(reports):
    tables, headlines, charts = render_tables(
        reports, load(RESULTS / TY_WORKTREE_REPORT), load(ROOT / TY_SCENARIO)
    )
    tables["ruff-doctests"] = ruff_doctest_table(load(RESULTS / RUFF_DOCTEST_REPORT))
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
    result.update({f"docs/benchmarks/{name}.svg": svg for name, svg in charts.items()})
    return result


def normalized_markdown(text):
    # Prettier owns alignment and whitespace; this check owns the table contents.
    text = re.sub(r"(?m)^\|[ |:-]+\|\n", "", text)
    return re.sub(r"\s+", " ", text).strip()


def write_documents(updated):
    for name, text in updated.items():
        path = ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def publish(directory):
    kinds = KINDS if (directory / "disk.json").exists() else TIMING_KINDS
    reports = {kind: load(directory / f"{kind}.json") for kind in kinds}
    if "disk" not in reports:
        reports["disk"] = load(RESULTS / "disk.json")
    release, _ = validate(reports)
    if "disk" in kinds and release not in reports["disk"]["toolchains"]:
        raise ValueError("New disk measurements must match the timing release")
    updated = documents(reports)
    prettier = ROOT / "node_modules/.bin/prettier"
    if not prettier.is_file():
        raise ValueError("Run npm ci --ignore-scripts before publishing benchmarks")
    paths = {kind: f"scripts/benchmark_results/{kind}.json" for kind in kinds}
    current = RESULTS / "sessions.json"
    if current.exists() and load(current)["ohm_release"] == release:
        raise ValueError(
            "Results already exist for this release; refusing to replace them"
        )
    for kind, path in paths.items():
        write_json(ROOT / path, compact(reports[kind]))
    write_documents(updated)
    subprocess.run(
        [
            str(prettier),
            "--write",
            "--ignore-unknown",
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
        help="directory of audited timing reports and an optional disk.json",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--check",
        action="store_true",
        help="verify the generated tables and charts against the checked-in reports",
    )
    modes.add_argument(
        "--render",
        action="store_true",
        help="regenerate the Markdown tables and SVG charts from the checked-in reports",
    )
    args = parser.parse_args()
    if (args.check or args.render) == (args.reports is not None):
        parser.error("select a reports directory, --check, or --render")
    if args.check:
        for name, expected in documents(latest_reports()).items():
            actual = (ROOT / name).read_text()
            if name.endswith(".md"):
                actual, expected = normalized_markdown(actual), normalized_markdown(expected)
            if actual != expected:
                raise ValueError(f"{name}: benchmark output is stale")
        print("Benchmark reports, tables, and charts match")
    elif args.render:
        prettier = ROOT / "node_modules/.bin/prettier"
        if not prettier.is_file():
            raise ValueError("Run npm ci --ignore-scripts before rendering benchmarks")
        updated = documents(latest_reports())
        write_documents(updated)
        subprocess.run([str(prettier), "--write", "--ignore-unknown", *updated], cwd=ROOT, check=True)
        print("Benchmark tables and charts refreshed")
    else:
        publish(args.reports)


if __name__ == "__main__":
    main()
