#!/usr/bin/env python3
"""Measure consecutive Ruff test builds in one resident native compiler process."""

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

from measure import clock, compiler, distribution, machine, write_json
from measure_source import build, protocol
from measure_test import (
    PHASES as BASE_PHASES,
)
from measure_test import (
    SOURCE,
    TEST,
    cargo_compile,
    cargo_transaction,
    compiler_command,
    fingerprint,
    internal_passes,
    quick_fingerprint,
    require,
    run_binary,
    save,
    source_error_codes,
    text_variants,
)
from run_tests import PACKAGE, REVISION, archive_ruff

PHASES = (
    BASE_PHASES[0],
    ("unchanged-rebuild", "good", "good", "pass"),
    *BASE_PHASES[1:],
)
NOOP_PHASES = ("baseline", "unchanged-rebuild")


def disable_native_debuginfo(command):
    result = []
    iterator = iter(command)
    for arg in iterator:
        if arg == "-C":
            option = next(iterator)
            if option.split("=", 1)[0] not in ("debuginfo", "split-debuginfo"):
                result.extend((arg, option))
        elif not arg.startswith(("-Cdebuginfo=", "-Csplit-debuginfo=")):
            result.append(arg)
    return [*result, "-C", "debuginfo=0", "-C", "split-debuginfo=off"]


def validate_capture_profile(capture):
    options = {}
    iterator = iter(capture["argv"])
    for arg in iterator:
        if arg == "-C":
            arg = next(iterator)
        elif arg.startswith("-C"):
            arg = arg[2:]
        else:
            continue
        key, separator, value = arg.partition("=")
        if separator:
            options[key] = value
    require(
        options.get("debuginfo", "0") in ("0", "none")
        and options.get("split-debuginfo", "off") == "off",
        "the captured Cargo invocation must also use debug=0 and split-debuginfo=off; otherwise its dependencies may have a different profile from paired Cargo",
    )


def disable_cargo_debuginfo(environment):
    for profile in ("DEV", "TEST"):
        environment[f"CARGO_PROFILE_{profile}_DEBUG"] = "0"
        environment[f"CARGO_PROFILE_{profile}_SPLIT_DEBUGINFO"] = "off"


class RepeatedResident:
    def __init__(self, command, env, workspace, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.stderr_path = directory / "compiler.stderr"
        self.stdout_path = directory / "compiler.stdout"
        self.stderr = self.stderr_path.open("wb")
        self.stdout = self.stdout_path.open("w")
        self.cache = (
            Path(value) if (value := env.get("OHM_RUFF_CODEGEN_CACHE")) else None
        )
        self.version = 0
        self.process = None
        started = clock()
        try:
            self.process = subprocess.Popen(
                command,
                cwd=workspace,
                env=dict(env, OHM_RUFF_SOURCE_MODE="resident-repeat-build"),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.stderr,
                text=True,
                bufsize=1,
            )
            pid, analysis = protocol(self.line(), "ready")
            self.pid = int(pid)
            require(
                self.pid == self.process.pid,
                f"compiler reported PID {self.pid}, started {self.process.pid}",
            )
            self.startup = {
                "external_ns": clock() - started,
                "analysis_ns": int(analysis),
            }
        except BaseException:
            self.close()
            raise

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def line(self):
        line = self.process.stdout.readline()
        self.stdout.write(line)
        self.stdout.flush()
        if not line:
            raise RuntimeError(f"resident protocol stopped; inspect {self.stderr_path}")
        return line

    def send(self, request):
        require(self.alive(), f"resident PID died; inspect {self.stderr_path}")
        self.process.stdin.write(request + "\n")
        self.process.stdin.flush()

    def error_offset(self):
        return self.stderr_path.stat().st_size

    def errors_since(self, offset):
        with self.stderr_path.open("rb") as errors:
            errors.seek(offset)
            return errors.read().decode("utf-8")

    def check(self, workspace):
        self.version += 1
        self.send(f"check\t{self.version}\t{workspace / PACKAGE / SOURCE}")
        version, route, reason, total, analysis, errors, revision, *_positions = (
            protocol(self.line(), "result")
        )
        require(
            version == str(self.version), f"incorrect resident check version {version}"
        )
        return {
            "version": self.version,
            "route": route,
            "reason": reason,
            "internal_ns": int(total),
            "analysis_ns": int(analysis),
            "errors": int(errors),
            "revision": int(revision),
        }

    def compile(self, error_offset, output):
        started = clock()
        self.send(f"build\t{self.version}")
        version, state, reason = protocol(self.line(), "build")
        reply = clock()
        require(
            version == str(self.version), f"incorrect resident build version {version}"
        )
        stages, codegen_units, status = {}, [], None
        if state == "ready":
            while True:
                line = self.line()
                name, event_version, *event_values = line.rstrip("\n").split("\t")
                require(event_version == version, f"unexpected timing version: {line}")
                if name == "build-analysis":
                    require(len(event_values) == 1, f"malformed timing: {line}")
                    stages[name] = int(event_values[0])
                elif name == "build-codegen-unit":
                    codegen_units.append(parse_codegen_unit(event_values))
                elif name == "build-finished":
                    require(len(event_values) == 2, f"malformed timing: {line}")
                    stages[name], status = int(event_values[0]), event_values[1]
                    break
                else:
                    raise RuntimeError(f"unexpected build event: {line}")
        else:
            require(state == "rejected", f"unexpected resident build result {state}")
        ended = clock()
        require(self.alive(), f"resident PID exited after revision {version}")
        raw = self.errors_since(error_offset)
        output.write_text(raw)
        barrier = (
            f"source-build-{'finished' if state == 'ready' else 'rejected'}\t{version}"
        )
        require(
            barrier in raw.splitlines(),
            f"resident stderr is missing completion barrier {barrier!r}",
        )
        timings, artifacts = internal_passes(raw)
        return {
            "state": state,
            "reason": reason,
            "status": status,
            "authorization_ns": reply - started,
            "post_authorization_compile_ns": ended - reply,
            "build_ns": ended - started,
            "completed_ns": ended,
            "error_codes": source_error_codes(raw),
            "compiler_timing_ns": timings,
            "callback_timing_ns": stages,
            "codegen_units": codegen_units,
            "link_artifacts": artifacts,
        }

    def quit(self):
        self.send("quit")
        protocol(self.line(), "bye")
        returncode = self.process.wait(timeout=30)
        require(returncode == 0, f"resident PID exited with status {returncode}")
        return returncode

    def close(self):
        if self.process is not None:
            if self.alive():
                self.process.kill()
                self.process.wait()
            for pipe in (self.process.stdin, self.process.stdout):
                if pipe:
                    pipe.close()
        self.stderr.close()
        self.stdout.close()


def parse_codegen_unit(values):
    require(len(values) in (2, 3), f"malformed codegen unit event: {values}")
    name, disposition, *fingerprint_value = values
    require(
        name and disposition in ("compiled", "reused"),
        f"invalid codegen unit event: {values}",
    )
    return {
        "name": name,
        "disposition": disposition,
        "fingerprint": fingerprint_value[0] if fingerprint_value else None,
    }


def verify_cache_files(directory, units):
    if directory is None or not units:
        return
    for unit in units:
        name = unit["name"]
        require(
            Path(name).name == name and name not in (".", ".."),
            f"codegen unit is not a safe basename: {name!r}",
        )
        regular = fingerprint(directory / f"{name}.o")
        require(regular is not None, f"missing cached regular object for {name}")
        unit["cache_files"] = {
            "regular": regular,
            "global_assembly": fingerprint(directory / f"{name}.asm.o"),
        }


def resident_transaction(resident, workspace, binary, contents, phase, output):
    name, _before, after, expected = phase
    output.mkdir(parents=True, exist_ok=True)
    require(resident.alive(), f"{name}: compiler died before save")
    previous = fingerprint(binary)
    previous_quick = quick_fingerprint(binary)
    offset = resident.error_offset()
    started = clock()
    save(workspace, contents[after])
    check = resident.check(workspace)
    checked = clock()
    require(
        check["route"] == ("noop" if name in NOOP_PHASES else "resident"),
        f"{name}: edited source used an unexpected route {check}",
    )
    require(check["errors"] == int(after == "error"), f"{name}: wrong errors {check}")
    building = resident.compile(offset, output / "compiler.stderr")
    did_run = False
    testing = None
    if building["state"] == "ready" and building["status"] == "ok":
        current_quick = quick_fingerprint(binary)
        require(current_quick is not None, f"{name}: compiler produced no {binary}")
        require(
            set(building["compiler_timing_ns"]) >= {"codegen", "link"}
            and set(building["callback_timing_ns"])
            >= {"build-analysis", "build-finished"},
            f"{name}: missing rustc and resident build timing phases: {building}",
        )
        require(
            building["link_artifacts"] == [str(binary)],
            f"{name}: compiler did not attest expected link artifact: {building['link_artifacts']}",
        )
        if name in ("behavior-edit", "behavior-repair"):
            require(
                previous_quick is not None and current_quick != previous_quick,
                f"{name}: compiler did not replace prior executable metadata",
            )
        did_run = True
        testing = run_binary(binary, workspace, output / "test")
        outcome = testing["result"]
        ended = testing.pop("completed_ns")
        identity = fingerprint(binary)
        if name in ("behavior-edit", "behavior-repair"):
            require(identity != previous, f"{name}: executable bytes did not change")
    else:
        ended = building["completed_ns"]
        outcome = "compile_error"
        identity = fingerprint(binary)
        require(
            building["state"] == "rejected" and building["status"] is None,
            f"{name}: compiler did not safely reject source {building}",
        )
        require(
            previous is not None and identity == previous,
            f"{name}: missing or changed previous output prevents a stale-binary guard",
        )
        require("E0308" in building["error_codes"], f"{name}: expected E0308 in logs")
        require(
            not building["link_artifacts"]
            and "codegen" not in building["compiler_timing_ns"],
            f"{name}: rejected input unexpectedly attempted codegen",
        )
    require(outcome == expected, f"{name}: resident got {outcome}, expected {expected}")
    require(resident.alive(), f"{name}: compiler died before result")
    verify_cache_files(resident.cache, building.get("codegen_units", []))
    building.pop("completed_ns")
    building["link_artifact_attested"] = building.pop("link_artifacts") == [str(binary)]
    return {
        "pid": resident.pid,
        "outcome": outcome,
        "external_ns": ended - started,
        "save_and_check_ns": checked - started,
        "check": check,
        "build": building,
        "test": testing,
        "binary_executed": did_run,
        "binary_existed_before": previous is not None,
        "binary_unchanged": previous is not None and identity == previous,
        "binary_before": previous,
        "binary_after": identity,
    }


def metrics(rows, mode):
    selected = [row[mode] for row in rows]
    fields = {
        "save_to_result_ms": [item["external_ns"] for item in selected],
        "test_ms": [item["test"]["test_ns"] for item in selected if item["test"]],
        "build_ms": [item["build"]["build_ns"] for item in selected],
    }
    if mode == "resident":
        fields.update(
            save_and_check_ms=[item["save_and_check_ns"] for item in selected],
            native_reanalysis_ms=[item["check"]["analysis_ns"] for item in selected],
            native_post_authorization_compile_ms=[
                item["build"]["post_authorization_compile_ns"] for item in selected
            ],
        )
        for key in ("codegen", "link"):
            fields[f"rustc_{key}_ms"] = [
                item["build"]["compiler_timing_ns"][key]
                for item in selected
                if key in item["build"]["compiler_timing_ns"]
            ]
    return {
        name: distribution(values, 1e6) for name, values in fields.items() if values
    }


def objects_summary(rows):
    builds = [row for row in rows if row["resident"]["build"]["state"] == "ready"]
    events = [row["resident"]["build"]["codegen_units"] for row in builds]
    if not any(events):
        return {
            "instrumented": False,
            "explanation": "The native compiler did not provide per-codegen-unit events. Executable replacement and SHA-256 are verified; neither unchanged object reuse nor skipped LLVM work can be inferred from that alone.",
        }
    builds_with_events = sum(bool(event) for event in events)
    fingerprints = {}
    cache_files = {}
    comparisons = []
    for row, units in zip(builds, events, strict=True):
        previous = fingerprints
        previous_cache_files = cache_files
        fingerprints = {unit["name"]: unit["fingerprint"] for unit in units}
        cache_files = {unit["name"]: unit.get("cache_files") for unit in units}
        comparisons.append(
            {
                "phase": row["phase"],
                "reused_matching_previous_fingerprints": sum(
                    unit["disposition"] == "reused"
                    and unit["name"] in previous
                    and unit["fingerprint"] == previous[unit["name"]]
                    for unit in units
                ),
                "reused_with_mismatched_previous_fingerprints": sum(
                    unit["disposition"] == "reused"
                    and unit["name"] in previous
                    and unit["fingerprint"] != previous[unit["name"]]
                    for unit in units
                ),
                "compiled_with_changed_previous_fingerprints": sum(
                    unit["disposition"] == "compiled"
                    and unit["name"] in previous
                    and unit["fingerprint"] != previous[unit["name"]]
                    for unit in units
                ),
                "compiled_with_matching_previous_fingerprints": sum(
                    unit["disposition"] == "compiled"
                    and unit["name"] in previous
                    and unit["fingerprint"] == previous[unit["name"]]
                    for unit in units
                ),
                "reused_matching_previous_external_sha256": sum(
                    unit["disposition"] == "reused"
                    and unit["name"] in previous_cache_files
                    and unit.get("cache_files") is not None
                    and unit["cache_files"] == previous_cache_files[unit["name"]]
                    for unit in units
                ),
                "reused_with_mismatched_previous_external_sha256": sum(
                    unit["disposition"] == "reused"
                    and unit["name"] in previous_cache_files
                    and unit.get("cache_files") is not None
                    and unit["cache_files"] != previous_cache_files[unit["name"]]
                    for unit in units
                ),
                "compiled_with_changed_previous_external_sha256": sum(
                    unit["disposition"] == "compiled"
                    and unit["name"] in previous_cache_files
                    and unit.get("cache_files") is not None
                    and unit["cache_files"] != previous_cache_files[unit["name"]]
                    for unit in units
                ),
                "compiled_with_matching_previous_external_sha256": sum(
                    unit["disposition"] == "compiled"
                    and unit["name"] in previous_cache_files
                    and unit.get("cache_files") is not None
                    and unit["cache_files"] == previous_cache_files[unit["name"]]
                    for unit in units
                ),
            }
        )
    return {
        "instrumented": True,
        "successful_builds": len(builds),
        "successful_builds_with_events": builds_with_events,
        "dispositions_by_phase": {
            name: {
                disposition: sum(
                    item["disposition"] == disposition
                    for row in builds
                    if row["phase"] == name
                    for item in row["resident"]["build"]["codegen_units"]
                )
                for disposition in ("compiled", "reused")
            }
            for name, *_rest in PHASES
            if name != "compile-error"
        },
        "all_events_fingerprinted": all(
            item["fingerprint"] for event in events for item in event
        ),
        "all_regular_cached_objects_independently_sha256_hashed": all(
            len(item.get("cache_files", {}).get("regular", {}).get("sha256", "")) == 64
            for event in events
            for item in event
        ),
        "behavior_transitions_with_changed_and_unchanged_object_sha256": sum(
            item["phase"] in ("behavior-edit", "behavior-repair")
            and item["compiled_with_changed_previous_external_sha256"] > 0
            and item["reused_matching_previous_external_sha256"] > 0
            for item in comparisons
        ),
        "fingerprint_comparisons_by_phase": {
            name: {
                key: sum(item[key] for item in comparisons if item["phase"] == name)
                for key in (
                    "reused_matching_previous_fingerprints",
                    "reused_with_mismatched_previous_fingerprints",
                    "compiled_with_changed_previous_fingerprints",
                    "compiled_with_matching_previous_fingerprints",
                    "reused_matching_previous_external_sha256",
                    "reused_with_mismatched_previous_external_sha256",
                    "compiled_with_changed_previous_external_sha256",
                    "compiled_with_matching_previous_external_sha256",
                )
            }
            for name, *_rest in PHASES
            if name != "compile-error"
        },
    }


def ratio(rows):
    return round(
        statistics.median(row["cargo"]["external_ns"] for row in rows)
        / statistics.median(row["resident"]["external_ns"] for row in rows),
        3,
    )


def summary(raw):
    rows = raw["samples"]
    all_rows = raw["warmups"] + rows
    behavior = [
        row for row in rows if row["phase"] in ("behavior-edit", "behavior-repair")
    ]
    objects = objects_summary(rows)
    return {
        "schema": 1,
        "ruff_revision": REVISION,
        "compiler": raw["compiler"],
        "machine": raw["machine"],
        "test": TEST,
        "rounds": raw["rounds"],
        "warmup_rounds": raw["warmup_rounds"],
        "transitions_per_round": [list(phase) for phase in PHASES],
        "measurement": "Each timer starts before a real source save and ends when the selected exact libtest exits or rustc rejects source. Independent disposable resident and Cargo Ruff archives alternate order each round. No tests run after an unsuccessful build. Artifact fingerprints are computed after timing.",
        "resident": "One native compiler is started before the first warmup and serves every save, code-generation and link request without restarting; each exact libtest still runs in a separate subprocess. Source edit checks and the completed rustc link artifact are attested before running a test. Cargo's captured --test invocation preserves profile, dependency and output flags. Startup is separate from ready-process save-to-result.",
        "cargo": "Ordinary warm cargo +ohm test --locked -p ruff_python_parser --lib --no-run --message-format=json with disk incremental enabled, then the exact emitted executable. Build and test are both in save-to-result.",
        "timing_details": "Rustc JSON section timings report LLVM/code generation and link separately. A source error leaves the prior executable on disk but it is never run. Both executable SHA-256 values and independently hashed regular and optional global-assembly resident object files are retained per transition in raw data; object checksums are computed outside each timed operation.",
        "profile": {
            "resident": {"debuginfo": "0", "split_debuginfo": "off"},
            "cargo_dev_and_test": {"debuginfo": "0", "split_debuginfo": "off"},
            "reason": "Retained source mappings are not sufficient to safely emit revised debug checksums and locations; both native and Cargo measurements use the same profile settings.",
        },
        "resident_codegen_cache_enabled": raw["resident_codegen_cache_enabled"],
        "percentile": "nearest rank",
        "worker_startup_ms": {
            key.removesuffix("_ns") + "_ms": round(value / 1e6, 3)
            for key, value in raw["resident_startup"].items()
        },
        "validation": {
            "transitions": len(rows),
            "single_compiler_pid_across_warmup_and_measured_builds": len(
                {raw["resident_pid"], *(row["resident"]["pid"] for row in all_rows)}
            )
            == 1,
            "continuous_resident_source_versions": [
                row["resident"]["check"]["version"] for row in all_rows
            ]
            == list(range(1, len(all_rows) + 1)),
            "compiler_exited_successfully_only_after_final_quit": raw[
                "resident_final_returncode"
            ]
            == 0,
            "matched_outcomes": all(
                row["resident"]["outcome"] == row["cargo"]["outcome"] for row in rows
            ),
            "native_edits": all(
                row["resident"]["check"]["route"]
                == ("noop" if row["phase"] in NOOP_PHASES else "resident")
                for row in rows
            ),
            "successful_builds_attested_to_real_codegen_and_link": all(
                row["resident"]["build"]["link_artifact_attested"]
                and set(row["resident"]["build"]["compiler_timing_ns"])
                >= {"codegen", "link"}
                for row in rows
                if row["phase"] != "compile-error"
            ),
            "changed_executables_on_behavior_edit_and_repair": all(
                not row[mode]["binary_unchanged"]
                for row in rows
                if row["phase"] in ("behavior-edit", "behavior-repair")
                for mode in ("resident", "cargo")
            ),
            "native_binary_hashes_match_execution": all(
                row["resident"]["binary_after"]
                and len(row["resident"]["binary_after"]["sha256"]) == 64
                for row in rows
            ),
            "cargo_binary_hashes_match_execution": all(
                row["cargo"]["binary_after"]
                and len(row["cargo"]["binary_after"]["sha256"]) == 64
                for row in rows
            ),
            "rejected_E0308_and_never_ran_existing_binary": all(
                row[mode]["binary_existed_before"]
                and row[mode]["binary_unchanged"]
                and not row[mode]["binary_executed"]
                and "E0308" in row[mode]["build"]["error_codes"]
                for row in rows
                if row["phase"] == "compile-error"
                for mode in ("resident", "cargo")
            ),
            **(
                {
                    "unchanged_rebuild_reused_all_regular_codegen_units": all(
                        row["resident"]["build"]["codegen_units"]
                        and all(
                            unit["disposition"] == "reused"
                            for unit in row["resident"]["build"]["codegen_units"]
                        )
                        for row in rows
                        if row["phase"] == "unchanged-rebuild"
                    ),
                    "every_behavior_transition_compiled_and_reused_regular_codegen_units": all(
                        {
                            unit["disposition"]
                            for unit in row["resident"]["build"]["codegen_units"]
                        }
                        >= {"compiled", "reused"}
                        for row in behavior
                    ),
                    "every_reported_codegen_unit_has_a_fingerprint": objects[
                        "instrumented"
                    ]
                    and objects["all_events_fingerprinted"],
                    "every_regular_codegen_unit_was_independently_sha256_hashed": objects[
                        "instrumented"
                    ]
                    and objects[
                        "all_regular_cached_objects_independently_sha256_hashed"
                    ],
                    "every_behavior_transition_changed_an_object_and_reused_unchanged_object_bytes": objects[
                        "instrumented"
                    ]
                    and objects[
                        "behavior_transitions_with_changed_and_unchanged_object_sha256"
                    ]
                    == len(behavior),
                    "reused_codegen_unit_fingerprints_remain_unchanged": objects[
                        "instrumented"
                    ]
                    and all(
                        not phase["reused_with_mismatched_previous_fingerprints"]
                        and not phase["reused_with_mismatched_previous_external_sha256"]
                        for phase in objects[
                            "fingerprint_comparisons_by_phase"
                        ].values()
                    ),
                }
                if raw["resident_codegen_cache_enabled"]
                else {}
            ),
        },
        "codegen_unit_reuse": objects,
        "behavior_edit_and_repair_ms": {
            **{mode: metrics(behavior, mode) for mode in ("resident", "cargo")},
            "ratio_of_medians_cargo_over_resident": ratio(behavior),
        },
        "by_phase_ms": {
            name: {
                **{
                    mode: metrics([row for row in rows if row["phase"] == name], mode)
                    for mode in ("resident", "cargo")
                },
                "ratio_of_medians_cargo_over_resident": ratio(
                    [row for row in rows if row["phase"] == name]
                ),
            }
            for name, *_rest in PHASES
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("bootstrap", "capture", "repo", "cargo-target", "output"):
        parser.add_argument(
            f"--{option}", type=lambda value: Path(value).resolve(), required=True
        )
    parser.add_argument("--target", default="aarch64-apple-darwin")
    parser.add_argument("--compiler-revision", required=True)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--without-codegen-cache", action="store_true")
    parser.add_argument("--driver", type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    if args.rounds < 1 or args.warmups < 0:
        parser.error("--rounds must be positive and --warmups nonnegative")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("--output must be empty to avoid stale benchmark data")
    args.output.mkdir(parents=True, exist_ok=True)
    disable_cargo_debuginfo(os.environ)
    host = args.bootstrap / args.target
    stage = host / "stage1"
    capture = json.loads(args.capture.read_text())
    validate_capture_profile(capture)
    driver = args.driver or build(host, args.output)
    resident_workspace = args.output / "resident-workspace"
    cargo_workspace = args.output / "cargo-workspace"
    for workspace in (resident_workspace, cargo_workspace):
        archive_ruff(args.repo, workspace)
    contents = text_variants(resident_workspace)
    require(contents == text_variants(cargo_workspace), "independent archives differed")
    command, env, native_binary = compiler_command(
        driver, capture, resident_workspace, args.output / "resident-target", stage
    )
    command = disable_native_debuginfo(command)
    disable_cargo_debuginfo(env)
    if not args.without_codegen_cache:
        env["OHM_RUFF_CODEGEN_CACHE"] = str(args.output / "resident-codegen-cache")
    raw = {
        "compiler": compiler(stage, args.compiler_revision),
        "machine": machine(),
        "rounds": args.rounds,
        "warmup_rounds": args.warmups,
        "resident_codegen_cache_enabled": not args.without_codegen_cache,
        "samples": [],
        "warmups": [],
    }
    prime = cargo_compile(
        stage,
        args.cargo_target,
        cargo_workspace,
        args.output / "cargo-prime",
        args.offline,
    )
    cargo_binary = prime.pop("executable")
    require(
        prime["returncode"] == 0 and cargo_binary is not None,
        f"initial Cargo build failed: {prime}",
    )
    raw["cargo_prime"] = prime
    resident = RepeatedResident(
        command, env, resident_workspace, args.output / "resident-process"
    )
    try:
        raw["resident_pid"] = resident.pid
        raw["resident_startup"] = resident.startup
        for index in range(args.warmups + args.rounds):
            warming = index < args.warmups
            round_no = index + 1 if warming else index - args.warmups + 1
            round_name = f"{'warmup' if warming else 'round'}-{round_no}"
            for phase in PHASES:
                name, *_rest = phase
                directory = args.output / "logs" / round_name / name
                directory.mkdir(parents=True, exist_ok=True)

                def native(phase=phase, directory=directory):
                    return resident_transaction(
                        resident,
                        resident_workspace,
                        native_binary,
                        contents,
                        phase,
                        directory / "resident",
                    )

                def cargo(known_binary, phase=phase, directory=directory):
                    before = fingerprint(known_binary)
                    row, known_binary = cargo_transaction(
                        stage,
                        args.cargo_target,
                        cargo_workspace,
                        contents,
                        phase,
                        directory / "cargo",
                        args.offline,
                        known_binary,
                    )
                    row["binary_before"] = before
                    row["binary_after"] = fingerprint(known_binary)
                    return row, known_binary

                if index % 2:
                    cargo_row, cargo_binary = cargo(cargo_binary)
                    resident_row = native()
                else:
                    resident_row = native()
                    cargo_row, cargo_binary = cargo(cargo_binary)
                row = {
                    "round": round_no,
                    "phase": name,
                    "resident": resident_row,
                    "cargo": cargo_row,
                }
                raw["warmups" if warming else "samples"].append(row)
                write_json(args.output / "raw.json", raw)
                print(
                    f"{round_name}/{name}: {resident_row['outcome']}/{cargo_row['outcome']} resident={resident_row['external_ns'] / 1e6:.1f}ms cargo={cargo_row['external_ns'] / 1e6:.1f}ms PID={resident.pid}",
                    flush=True,
                )
        raw["resident_final_returncode"] = resident.quit()
    finally:
        resident.close()
    write_json(args.output / "raw.json", raw)
    compact = summary(raw)
    write_json(args.output / "summary.json", compact)
    require(
        all(compact["validation"].values()),
        f"validation failed: {compact['validation']}",
    )
    print(json.dumps(compact["validation"], indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
