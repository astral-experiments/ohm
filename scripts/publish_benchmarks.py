#!/usr/bin/env python3
"""Archive audited reports, publish compact results, and refresh benchmark tables."""

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "scripts/benchmark_results"
KINDS = ("workflow", "sessions", "historical", "ablation", "disk")
TY_WORKTREE_REPORT = "ty-worktree.json"
TY_SCENARIO = "scripts/session_replays/ty-29327.json"


def load(path):
    return json.loads(path.read_text())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def compact(report, evidence):
    """Keep measurements and audit summaries; the archive retains full provenance."""
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
    result["evidence"] = evidence
    return result


def latest_reports():
    return {kind: load(RESULTS / f"{kind}.json") for kind in KINDS}


def validate(reports):
    release = reports["sessions"]["ohm_release"]
    if not re.fullmatch(r"ohm-\d+\.\d+\.\d+-[1-9]\d*", release):
        raise ValueError("Invalid Ohm release identity")
    rust = reports["sessions"]["rust_version"]
    if not release.startswith(f"ohm-{rust}-"):
        raise ValueError("Ohm and stock Rust versions differ")
    for kind in KINDS[:-1]:
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
    if disk["validation"]["status"] != "pass" or set(disk["toolchains"]) != {
        release,
        "stock-" + rust,
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

    session_rows = []
    totals = [0.0, 0.0]
    for project, label in zip(
        projects, ("Ruff session", "uv session", "Codex session"), strict=True
    ):
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
    session_rows.append(["All sessions", *seconds(totals)])
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
        (("uv", "build-check", "transition"), ["uv", "Build, then check", "`uv`"]),
        (
            ("uv", "shared-build", "reuse"),
            ["uv", "Shared-worktree build", "`uv-normalize`"],
        ),
        (
            ("codex-core", "build-check", "transition"),
            ["Codex", "Build, then check", "`codex-core`"],
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
        r"disk usage decreases by around \d+%": f"disk usage decreases by around {5 * round(mean(savings) / 5)}%",
    }
    return rendered, headlines


def documents(reports):
    tables, headlines = render_tables(
        reports, load(RESULTS / TY_WORKTREE_REPORT), load(ROOT / TY_SCENARIO)
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


def archive_reports(directory, output):
    files = {
        f"{kind}.json": (directory / f"{kind}.json").read_bytes() for kind in KINDS
    }
    manifest = {name: digest(data) for name, data in files.items()}
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in files.items():
            bundle.writestr(
                zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)),
                data,
                compress_type=zipfile.ZIP_DEFLATED,
            )
        bundle.writestr(
            zipfile.ZipInfo("manifest.json", (1980, 1, 1, 0, 0, 0)),
            json.dumps(manifest, indent=2) + "\n",
        )
    return manifest


def publish(directory):
    reports = {kind: load(directory / f"{kind}.json") for kind in KINDS}
    release, _ = validate(reports)
    updated = documents(reports)
    prettier = ROOT / "node_modules/.bin/prettier"
    if not prettier.is_file():
        raise ValueError("Run npm ci --ignore-scripts before publishing benchmarks")
    version = release.removeprefix("ohm-")
    paths = {kind: f"scripts/benchmark_results/{kind}.json" for kind in KINDS}
    current = RESULTS / "sessions.json"
    if current.exists() and load(current)["ohm_release"] == release:
        raise ValueError(
            "Results already exist for this release; refusing to replace them"
        )
    with tempfile.TemporaryDirectory(prefix="ohm-benchmark-publication-") as temporary:
        temporary = Path(temporary)
        archive = temporary / f"benchmark-evidence-{version}.zip"
        manifest = archive_reports(directory, archive)
        with zipfile.ZipFile(archive) as bundle:
            if any(
                json.loads(bundle.read(f"{kind}.json")) != report
                for kind, report in reports.items()
            ):
                raise ValueError("Input reports changed during publication")
        checksum = digest(archive.read_bytes())
        tag = f"benchmark-evidence-{version}-{checksum[:12]}"
        url = f"https://github.com/astral-sh/ohm/releases/download/{tag}/{archive.name}"
        exists = subprocess.run(
            ["gh-auto", "release", "view", tag, "--json", "tagName"],
            cwd=ROOT,
            capture_output=True,
        )
        if exists.returncode:
            subprocess.run(
                [
                    "gh-auto",
                    "release",
                    "create",
                    tag,
                    str(archive),
                    "--latest=false",
                    "--target",
                    subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                    ).strip(),
                    "--title",
                    f"Benchmark evidence for {release}",
                    "--notes",
                    "Detailed audited benchmark reports. The ZIP manifest records each input file's SHA-256. This release contains benchmark evidence only.",
                ],
                cwd=ROOT,
                check=True,
            )
        download = temporary / "download"
        subprocess.run(
            [
                "gh-auto",
                "release",
                "download",
                tag,
                "--pattern",
                archive.name,
                "--dir",
                str(download),
            ],
            cwd=ROOT,
            check=True,
        )
        if digest((download / archive.name).read_bytes()) != checksum:
            raise ValueError(
                "Downloaded evidence differs; local reports were not changed"
            )
        for kind, path in paths.items():
            write_json(
                ROOT / path,
                compact(
                    reports[kind],
                    {
                        "url": url,
                        "sha256": checksum,
                        "path": f"{kind}.json",
                        "report_sha256": manifest[f"{kind}.json"],
                    },
                ),
            )
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
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the latest checked-in reports and generated tables without publishing",
    )
    args = parser.parse_args()
    if args.check == (args.reports is not None):
        parser.error("select a reports directory or --check")
    if args.check:
        for name, expected in documents(latest_reports()).items():
            if normalized_markdown((ROOT / name).read_text()) != normalized_markdown(
                expected
            ):
                raise ValueError(f"{name}: benchmark tables are stale")
        print("Benchmark reports and tables match")
    else:
        publish(args.reports)


if __name__ == "__main__":
    main()
