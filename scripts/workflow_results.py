#!/usr/bin/env python3
"""Validate paired workflow measurements and assemble their publication report."""

import argparse
import copy
import json
import math
from pathlib import Path
import re
import statistics

from benchmark_workflows import WORKFLOWS


def compact_run(run):
    result = copy.deepcopy(run)
    for sample in [*result["samples"], *result.get("failures", [])]:
        commands = (
            [sample["failed_command"]]
            if "failed_command" in sample
            else [sample["normalization"], *sample["warmups"], *sample["commands"]]
        )
        for command in commands:
            if "cargo_reported_crates" in command:
                command["cargo_reported_crate_count"] = len(
                    command.pop("cargo_reported_crates")
                )
            for key in (
                "actual_compiler_invocations",
                "cargo_status_without_compiler_invocation",
                "kind",
            ):
                command.pop(key, None)
            command["log"] = "logs/" + command["log"].split("/logs/", 1)[1]
        sample["cpu"]["path"] = "logs/" + sample["cpu"]["path"].split("/logs/", 1)[1]
        for diagnostic in sample.get("diagnostics", []):
            diagnostic["path"] = "logs/" + diagnostic["path"].split("/logs/", 1)[1]
        preflight = sample["preflight"]
        if preflight:
            sample["preflight"] = {
                "samples": len(preflight),
                "minimum_idle_percent": min(s["idle_percent"] for s in preflight),
                "maximum_iowait_percent": max(s["iowait_percent"] for s in preflight),
                "maximum_steal_percent": max(s["steal_percent"] for s in preflight),
            }
    return result


def validate_readiness(sample):
    preflight = sample["preflight"]
    if (
        not isinstance(preflight, dict)
        or preflight["samples"] < 1
        or preflight["minimum_idle_percent"] < 95
        or preflight["maximum_iowait_percent"] > 0.5
        or preflight["maximum_steal_percent"] > 0.1
    ):
        raise ValueError("Workflow did not pass its idle preflight")
    if sample["cpu"]["intervals"] < 1 or not re.fullmatch(
        r"[0-9a-f]{64}", sample["cpu"]["sha256"] or ""
    ):
        raise ValueError("Workflow has no continuous host CPU evidence")


def comparisons(report):
    rows = []
    seen_projects = set()
    compiler_identities = None
    runner_identities = None
    for run in report["runs"]:
        configuration = run["configuration"]
        metadata = run["metadata"]
        selectors = {"stock": report["rust_version"], "ohm": report["ohm_release"]}
        if configuration["toolchains"] != selectors:
            raise ValueError("Workflow toolchain versions differ")
        if (
            configuration["jobs"] != report["jobs"]
            or configuration["repetitions"] != report["repetitions"]
        ):
            raise ValueError("Workflow sampling settings differ")
        if (
            not configuration["require_idle"]
            or configuration["quiet_seconds"] < 30
            or configuration.get("idle_preflight") != "after_warmup"
        ):
            raise ValueError(
                "Published workflows require a 30-second idle preflight after warmup"
            )
        if configuration.get("failure_policy") != "record_and_continue":
            raise ValueError("Workflow runs must retain failed executions")
        if configuration.get("source_normalization") != "ohm_rustfmt_before_warmup":
            raise ValueError("Workflow runs must use the shared formatting baseline")
        if configuration.get("cpu_accounting") != "host_busy_minus_process_tree":
            raise ValueError("Workflow CPU accounting must include exited processes")
        if (
            not metadata.get("finished_at")
            or metadata["finished_at"] <= metadata["started_at"]
        ):
            raise ValueError("Workflow run has not completed")
        identities = metadata["toolchains"]
        if set(identities) != set(selectors):
            raise ValueError("Workflow compiler identities are incomplete")
        for lane, tools in identities.items():
            if set(tools) != {"cargo", "rustc", "rustfmt", "clippy-driver"} or any(
                not re.fullmatch(r"[0-9a-f]{64}", tool["sha256"])
                for tool in tools.values()
            ):
                raise ValueError("Workflow compiler hashes are incomplete")
            compiler_release = report["ohm_release"].partition("-cargo-")[0]
            if lane == "ohm" and compiler_release not in tools["rustc"]["version"]:
                raise ValueError("Ohm compiler does not identify the measured release")
            libraries = tools["rustc"].get("libraries", {})
            if (
                not any("rustc_driver" in name for name in libraries)
                or not any("LLVM" in name for name in libraries)
                or any(
                    not re.fullmatch(r"[0-9a-f]{64}", value)
                    for value in libraries.values()
                )
            ):
                raise ValueError("Workflow compiler library hashes are incomplete")
            if lane == "ohm" and (revision := report.get("ohm_source_revision")):
                if f"commit-hash: {revision}" not in tools["rustc"]["version"]:
                    raise ValueError("Ohm compiler source revision differs")
            if lane == "ohm" and (revision := report.get("ohm_cargo_source_revision")):
                if f"commit-hash: {revision}" not in tools["cargo"]["version"]:
                    raise ValueError("Ohm Cargo source revision differs")
        if compiler_identities is not None and identities != compiler_identities:
            raise ValueError("Workflow hosts used different toolchain binaries")
        compiler_identities = identities
        if (
            runner_identities is not None
            and configuration["runner_sha256"] != runner_identities
        ):
            raise ValueError("Workflow hosts used different benchmark runners")
        runner_identities = configuration["runner_sha256"]
        if set(configuration["workflows"]) != set(WORKFLOWS):
            raise ValueError("Workflow coverage is incomplete")
        for name, workflow in WORKFLOWS.items():
            actual = configuration["workflows"][name]
            if (actual["edit"], actual["warmup"], actual["commands"]) != (
                workflow.edit,
                list(workflow.warmup),
                list(workflow.commands),
            ):
                raise ValueError("Workflow sequence differs from its definition")
        projects = configuration["projects"]
        if seen_projects.intersection(projects):
            raise ValueError("Project appears in more than one workflow run")
        seen_projects.update(projects)
        samples = {}
        targets = set()
        for sample in run["samples"]:
            key = (
                sample["project"],
                sample["workflow"],
                sample["toolchain"],
                sample["repetition"],
            )
            if key in samples:
                raise ValueError("Duplicate workflow sample")
            project, workflow_id, lane, repetition = key
            if (
                project not in projects
                or workflow_id not in WORKFLOWS
                or lane not in selectors
                or type(repetition) is not int
                or not 0 <= repetition < report["repetitions"]
            ):
                raise ValueError("Unexpected workflow sample")
            if sample["selector"] != selectors[lane]:
                raise ValueError("Sample toolchain differs from its run")
            if sample["target_directory"] in targets:
                raise ValueError("Workflow samples reused a target directory")
            targets.add(sample["target_directory"])
            workflow = WORKFLOWS[workflow_id]
            normalization = [
                "cargo",
                f"+{selectors['ohm']}",
                *projects[project]["commands"]["fmt"],
            ]
            if sample["normalization"]["command"] != normalization:
                raise ValueError("Source normalization differs between toolchains")
            if (
                workflow.edit is None
                and sample["baseline_diff_sha256"] != sample["edited_diff_sha256"]
            ):
                raise ValueError("A workflow without edits changed its source")
            if [c["name"] for c in sample["commands"]] != list(workflow.commands) or [
                c["name"] for c in sample["warmups"]
            ] != list(workflow.warmup):
                raise ValueError("Workflow command order or warmup differs")
            for command in [
                sample["normalization"],
                *sample["warmups"],
                *sample["commands"],
            ]:
                seconds = command["wall_seconds"]
                if (
                    not math.isfinite(seconds)
                    or seconds <= 0
                    or command["returncode"]
                    or command["external_compilation"]
                ):
                    raise ValueError("Invalid or contaminated workflow command")
                if not re.fullmatch(r"[0-9a-f]{64}", command["log_sha256"]):
                    raise ValueError("Workflow log has no content identity")
            for command in [*sample["warmups"], *sample["commands"]]:
                expected = [
                    "cargo",
                    f"+{selectors[lane]}",
                    *projects[project]["commands"][command["name"]],
                ]
                if command["command"] != expected:
                    raise ValueError(
                        "Measured command differs from the pinned workflow"
                    )
                if command["tests_started"] != int(command["name"] == "test"):
                    raise ValueError("Workflow must run exactly one selected test")
            total = sample["wall_seconds"]
            command_total = sum(c["wall_seconds"] for c in sample["commands"])
            if (
                not math.isfinite(total)
                or total <= 0
                or not math.isclose(command_total, sample["command_seconds"])
                or total < command_total + sample["edit_seconds"]
            ):
                raise ValueError("Workflow total does not cover its measured commands")
            if (
                not math.isfinite(sample["edit_seconds"])
                or sample["edit_seconds"] < 0
                or (workflow.edit is None and sample["edit_seconds"] != 0)
            ):
                raise ValueError("Invalid workflow edit duration")
            validate_readiness(sample)
            samples[key] = sample
        for failure in run.get("failures", []):
            key = (
                failure["project"],
                failure["workflow"],
                failure["toolchain"],
                failure["repetition"],
            )
            project, workflow_id, lane, repetition = key
            if key in samples:
                raise ValueError("Duplicate workflow outcome")
            if (
                project not in projects
                or workflow_id not in WORKFLOWS
                or lane not in selectors
                or type(repetition) is not int
                or not 0 <= repetition < report["repetitions"]
                or failure["selector"] != selectors[lane]
            ):
                raise ValueError("Unexpected failed workflow")
            if failure["target_directory"] in targets:
                raise ValueError("Failed workflow reused a target directory")
            targets.add(failure["target_directory"])
            command = failure["failed_command"]
            phase, index = command["phase"], command["index"]
            workflow = WORKFLOWS[workflow_id]
            if phase not in {"warmup", "session"} or type(index) is not int:
                raise ValueError("Invalid failed command position")
            sequence = workflow.warmup if phase == "warmup" else workflow.commands
            position = index - 1
            if (
                not 0 <= position < len(sequence)
                or command["name"] != sequence[position]
            ):
                raise ValueError("Failed command differs from the workflow")
            selector = selectors[lane]
            arguments = projects[project]["commands"][command["name"]]
            if (
                command["command"] != ["cargo", f"+{selector}", *arguments]
                or type(command["returncode"]) is not int
                or command["returncode"] == 0
                or not math.isfinite(command["wall_seconds"])
                or command["wall_seconds"] <= 0
                or command["external_compilation"]
                or not re.fullmatch(r"[0-9a-f]{64}", command["log_sha256"])
                or command["tests_started"] not in (0, int(command["name"] == "test"))
            ):
                raise ValueError("Invalid failed command evidence")
            if phase == "session":
                validate_readiness(failure)
            for diagnostic in failure["diagnostics"]:
                if not re.fullmatch(r"[0-9a-f]{64}", diagnostic["sha256"]):
                    raise ValueError("Compiler diagnostic has no content identity")
            samples[key] = failure
        for project in projects:
            for workflow_id in WORKFLOWS:
                durations = {lane: [] for lane in selectors}
                failures = {lane: 0 for lane in selectors}
                for repetition in range(report["repetitions"]):
                    pair = []
                    for lane in selectors:
                        key = (project, workflow_id, lane, repetition)
                        if key not in samples:
                            raise ValueError(f"Missing workflow sample: {key}")
                        sample = samples[key]
                        if "failed_command" in sample:
                            failures[lane] += 1
                        else:
                            durations[lane].append(sample["wall_seconds"])
                        pair.append(sample)
                    if all(
                        sample.get("failed_command", {}).get("phase") != "warmup"
                        for sample in pair
                    ):
                        for field in ("baseline_diff_sha256", "edited_diff_sha256"):
                            if pair[0][field] != pair[1][field]:
                                raise ValueError(
                                    "Paired workflow source contents differ"
                                )
                stock, ohm = (
                    None if failures[lane] else statistics.median(durations[lane])
                    for lane in selectors
                )
                rows.append(
                    {
                        "project": project,
                        "workflow": workflow_id,
                        "stock_seconds": stock,
                        "ohm_seconds": ohm,
                        "stock_failures": failures["stock"],
                        "ohm_failures": failures["ohm"],
                        "percent_saved": (
                            100 * (stock - ohm) / stock
                            if stock is not None and ohm is not None
                            else None
                        ),
                    }
                )
    if seen_projects != {"ruff", "uv", "codex"}:
        raise ValueError("Workflow report must cover Ruff/ty, uv, and Codex")
    return sorted(
        rows,
        key=lambda row: (
            ("ruff", "uv", "codex").index(row["project"]),
            list(WORKFLOWS).index(row["workflow"]),
        ),
    )


def validate(report):
    identity = re.fullmatch(
        rf"ohm-{re.escape(report['rust_version'])}-[1-9]\d*"
        r"(?:-[a-z][a-z0-9]*(?:-[a-z][a-z0-9]*)*?-([0-9a-f]{12})"
        r"(?:-cargo-([0-9a-f]{12}))?)?",
        report["ohm_release"],
    )
    if not re.fullmatch(r"\d+\.\d+\.\d+", report["rust_version"]) or not identity:
        raise ValueError("Invalid workflow toolchain identities")
    if identity[1] and (
        not re.fullmatch(r"[0-9a-f]{40}", report.get("ohm_source_revision", ""))
        or not report["ohm_source_revision"].startswith(identity[1])
    ):
        raise ValueError("Unreleased compiler must identify its exact source revision")
    if identity[2] and (
        not re.fullmatch(r"[0-9a-f]{40}", report.get("ohm_cargo_source_revision", ""))
        or not report["ohm_cargo_source_revision"].startswith(identity[2])
    ):
        raise ValueError("Unreleased Cargo must identify its exact source revision")
    if report["repetitions"] < 2 or report["jobs"] < 1:
        raise ValueError("Invalid workflow sampling settings")
    if report["comparisons"] != comparisons(report):
        raise ValueError("Workflow table differs from its measurements")


def build_report(runs):
    first = runs[0]["configuration"]
    report = {
        "schema_version": 1,
        "rust_version": first["toolchains"]["stock"],
        "ohm_release": first["toolchains"]["ohm"],
        "jobs": first["jobs"],
        "repetitions": first["repetitions"],
        "methodology": {
            "summary_statistic": "median elapsed time of each complete workflow",
            "warmups_excluded": True,
            "fresh_target_and_shared_build_per_sample": True,
            "source_normalization": "Ohm rustfmt before warmup, identical within each pair and accepted by both formatters",
            "formatting": "cargo fmt applies formatting before Clippy and tests",
            "timed_commands_offline": True,
            "ohm_proc_macro_trust": "all",
            "ohm_native_tool_trust": "all",
            "test_scope": "one existing focused test, including compilation and execution",
            "failure_handling": "retain each failed execution; show no lane timing or speedup if any repetition fails",
            "order": "alternate stock/Ohm order by repetition and workflow",
            "idle_preflight": "30 seconds after baseline warmup and immediately before measurement",
            "cpu_guard": "reject unrelated compilers, steal above 0.1%, or three consecutive two-second samples above 5% external host CPU",
        },
        "runs": [compact_run(run) for run in runs],
    }
    for tool, field in (
        ("rustc", "ohm_source_revision"),
        ("cargo", "ohm_cargo_source_revision"),
    ):
        if revision := re.search(
            r"(?m)^commit-hash: ([0-9a-f]{40})$",
            runs[0]["metadata"]["toolchains"]["ohm"][tool]["version"],
        ):
            report[field] = revision[1]
    report["comparisons"] = comparisons(report)
    validate(report)
    return report


def toolchain_label(report):
    version, *build = re.split(
        r"-(?=[a-z])", report["ohm_release"].removeprefix("ohm-"), maxsplit=1
    )
    if not build:
        return version
    return version + (
        " + fix" if build[0].startswith("workflow-cache-fix-") else " + fixes"
    )


def table_rows(report):
    validate(report)
    labels = {"ruff": "Ruff/ty", "uv": "uv", "codex": "Codex"}

    def timing(row, lane):
        if count := row[f"{lane}_failures"]:
            return f"Failed ({count}/{report['repetitions']})"
        return f"{row[f'{lane}_seconds']:.2f} s"

    return [
        [
            labels[row["project"]],
            WORKFLOWS[row["workflow"]].label,
            timing(row, "stock"),
            timing(row, "ohm"),
            (
                f"{row['percent_saved']:.2f}%".replace("-", "−")
                if row["percent_saved"] is not None
                else "—"
            ),
        ]
        for row in report["comparisons"]
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    report = build_report([json.loads(path.read_text()) for path in options.results])
    options.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
