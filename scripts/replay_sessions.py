#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Replay actual editing sessions against matched toolchains or Ohm features."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import platform
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from benchmark import COMPILER_PROCESSES, BenchmarkError

SCENARIO_DIRECTORY = Path(__file__).with_name("session_replays")
PROJECTS = ("ruff", "uv", "codex")
CARGO_STATUS = re.compile(
    r"^\s*(?P<action>Compiling|Checking)\s+(?P<crate>[^\s]+)", re.MULTILINE
)
VERBOSE_COMMAND = re.compile(r"^\s*Running\s+`(?P<command>.+)`\s*$", re.MULTILINE)
TEST_COUNT = re.compile(r"(?mi)^\s*(?:running|Starting)\s+(\d+)\s+tests?\b")
SAFE_REVISION = re.compile(r"^[0-9a-f]{40}$")
FEATURE_MATRIX: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ohm-all", ()),
    ("ohm-no-public-api-hash", ("-Zpublic-api-hash=no",)),
    ("ohm-no-proc-macro-cache", ("-Zcache-proc-macros=no",)),
    (
        "ohm-neither",
        ("-Zpublic-api-hash=no", "-Zcache-proc-macros=no"),
    ),
)
FEATURE_OVERRIDES = dict(FEATURE_MATRIX)


def competing_processes(owner: int | None = None) -> list[str]:
    """Ignore owned compiler descendants, including briefly reparented helpers."""
    owner = os.getpid() if owner is None else owner
    output = command_output(["ps", "-ax", "-o", "pid=,ppid=,pgid=,comm="])
    if not output:
        raise BenchmarkError("process inspection returned no process information")

    processes: dict[int, tuple[int, int, str]] = {}
    for line in output.splitlines():
        parts = line.split(None, 3)
        if len(parts) != 4:
            raise BenchmarkError(f"invalid process inspection result: {line!r}")
        try:
            process, parent, group = map(int, parts[:3])
        except ValueError as error:
            raise BenchmarkError(
                f"invalid process inspection result: {line!r}"
            ) from error
        processes[process] = parent, group, Path(parts[3]).name

    if owner not in processes:
        raise BenchmarkError("process inspection omitted the benchmark process")
    owner_group = processes[owner][1]

    def belongs_to_benchmark(process: int) -> bool:
        visited: set[int] = set()
        while process in processes and process not in visited:
            if process == owner or processes[process][1] == owner_group:
                return True
            visited.add(process)
            process = processes[process][0]
        return process == owner

    return [
        f"{process} {name}"
        for process, (_, _, name) in processes.items()
        if name in COMPILER_PROCESSES and not belongs_to_benchmark(process)
    ]


def compiler_invocations(output: str) -> list[dict[str, str | None]]:
    """Extract real compiler executions from Cargo's verbose command stream."""
    invocations: list[dict[str, str | None]] = []
    for match in VERBOSE_COMMAND.finditer(output):
        try:
            arguments = shlex.split(match.group("command"))
        except ValueError as error:
            raise BenchmarkError("cannot parse a verbose Cargo command") from error

        compiler = next(
            (
                Path(argument).name.removesuffix(".exe")
                for argument in arguments
                if Path(argument).name.removesuffix(".exe")
                in ("rustc", "clippy-driver")
            ),
            None,
        )
        if compiler is None:
            continue

        crate = next(
            (
                arguments[index + 1]
                for index, argument in enumerate(arguments[:-1])
                if argument == "--crate-name"
            ),
            None,
        )
        if crate is None:
            crate = next(
                (
                    argument.removeprefix("--crate-name=")
                    for argument in arguments
                    if argument.startswith("--crate-name=")
                ),
                None,
            )

        invocations.append({"compiler": compiler, "crate": crate})
    return invocations


def status_only_crates(
    reported: list[str], invocations: list[dict[str, str | None]]
) -> list[str]:
    """Identify progress messages that have no matching compiler execution."""
    remaining = Counter(
        crate.replace("-", "_")
        for invocation in invocations
        if (crate := invocation["crate"]) is not None
    )
    without_compiler: list[str] = []
    for crate in reported:
        normalized = crate.replace("-", "_")
        if remaining[normalized]:
            remaining[normalized] -= 1
        else:
            without_compiler.append(crate)
    return without_compiler


@dataclasses.dataclass(frozen=True)
class Scenario:
    path: Path
    project: str
    repository: str
    base_revision: str
    fetch_refs: tuple[str, ...]
    environment: dict[str, str]
    session: dict[str, Any]
    warmup: tuple[dict[str, Any], ...]
    steps: tuple[dict[str, Any], ...]


def command_output(arguments: list[str], *, cwd: Path | None = None) -> str:
    rendered = re.sub(r"(https?://)[^/\s@]+@", r"\1<redacted>@", shlex.join(arguments))
    try:
        result = subprocess.run(
            arguments,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() if error.stderr else str(error)
        detail = re.sub(r"(https?://)[^/\s@]+@", r"\1<redacted>@", detail)
        raise BenchmarkError(f"command failed: {rendered}: {detail}") from error
    except OSError as error:
        raise BenchmarkError(f"command failed: {rendered}: {error}") from error
    return result.stdout.strip()


def safe_revision(value: object, *, field: str) -> str:
    if not isinstance(value, str) or SAFE_REVISION.fullmatch(value) is None:
        raise BenchmarkError(f"{field} must be a complete lowercase commit SHA")
    return value


def safe_relative(value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise BenchmarkError(f"{field} must be a nonempty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise BenchmarkError(f"{field} must remain within its owned directory")
    return path


def load_scenario(path: Path) -> Scenario:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise BenchmarkError(f"cannot load session replay {path}: {error}") from error
    if not isinstance(data, dict):
        raise BenchmarkError(f"session replay must be an object: {path}")

    project = data.get("project")
    if project not in PROJECTS:
        raise BenchmarkError(f"unknown session replay project: {project!r}")
    repository = data.get("repository")
    if not isinstance(repository, str) or not repository:
        raise BenchmarkError(f"session replay has no source repository: {path}")
    session = data.get("session")
    if not isinstance(session, dict) or not isinstance(session.get("id"), str):
        raise BenchmarkError(f"session replay has no original session ID: {path}")
    environment = data.get("environment", {})
    if not isinstance(environment, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in environment.items()
    ):
        raise BenchmarkError(f"session replay environment must contain strings: {path}")
    forbidden = {"HOME", "CARGO_HOME", "CARGO_TARGET_DIR", "RUSTUP_TOOLCHAIN"}
    if forbidden.intersection(environment):
        raise BenchmarkError("session replay cannot override managed environment")

    fetch_refs = data.get("fetch_refs", [])
    if not isinstance(fetch_refs, list) or not all(
        isinstance(ref, str) and ref.startswith("refs/") for ref in fetch_refs
    ):
        raise BenchmarkError(f"session replay fetch references are invalid: {path}")

    warmup = data.get("warmup", [])
    if not isinstance(warmup, list):
        raise BenchmarkError(f"session replay warmup must be a list: {path}")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise BenchmarkError(f"session replay has no ordered steps: {path}")
    for index, step in enumerate([*warmup, *steps], start=1):
        if not isinstance(step, dict) or not isinstance(step.get("label"), str):
            raise BenchmarkError(f"session step {index} has no descriptive label")
        kind = step.get("kind")
        if kind == "edit":
            if index <= len(warmup):
                raise BenchmarkError("session warmups cannot edit source files")
            if "patch" in step:
                safe_relative(step["patch"], field=f"session step {index} patch")
                if "parent" in step or "commit" in step:
                    raise BenchmarkError("patch edits cannot also specify commit diffs")
            else:
                safe_revision(step.get("parent"), field=f"step {index} parent")
                safe_revision(step.get("commit"), field=f"step {index} commit")
            paths = step.get("paths", [])
            if not isinstance(paths, list):
                raise BenchmarkError(f"session step {index} paths must be a list")
            for source in paths:
                safe_relative(source, field=f"session step {index} source")
        elif kind == "command":
            if step.get("program") not in ("cargo", "just"):
                raise BenchmarkError(f"session step {index} has an unsupported command")
            arguments = step.get("args")
            if (
                not isinstance(arguments, list)
                or not arguments
                or not all(isinstance(argument, str) for argument in arguments)
            ):
                raise BenchmarkError(
                    f"session step {index} has invalid command arguments"
                )
            if arguments[0].startswith("+"):
                raise BenchmarkError(
                    "session commands must not pin their own toolchain"
                )
            if "cwd" in step:
                safe_relative(step["cwd"], field=f"session step {index} directory")
        else:
            raise BenchmarkError(f"session step {index} has unsupported kind {kind!r}")

    return Scenario(
        path=path.resolve(),
        project=project,
        repository=repository,
        base_revision=safe_revision(data.get("base_revision"), field="base revision"),
        fetch_refs=tuple(fetch_refs),
        environment=environment,
        session=session,
        warmup=tuple(warmup),
        steps=tuple(steps),
    )


class InterferenceMonitor:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self.observed: set[str] = set()
        self.failure: str | None = None
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def __enter__(self) -> InterferenceMonitor:
        if self.enabled:
            self.thread = threading.Thread(target=self.watch, daemon=True)
            self.thread.start()
        return self

    def watch(self) -> None:
        while not self.stop.wait(0.35):
            try:
                self.observed.update(competing_processes())
            except BenchmarkError as error:
                self.failure = str(error)
                return

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        if self.thread is not None:
            self.thread.join()


class Replay:
    def __init__(self, options: argparse.Namespace) -> None:
        self.options = options
        self.output = options.output_dir.expanduser().resolve()
        if options.feature_matrix:
            self.toolchains = tuple((label, options.ohm) for label, _ in FEATURE_MATRIX)
        else:
            self.toolchains = (("stock", options.upstream), ("ohm", options.ohm))
        self.samples: list[dict[str, Any]] = []
        self.scenarios = self.select_scenarios()
        self.sources: dict[str, Path] = {}
        self.source_overrides = self.parse_source_overrides()
        if options.jobs < 1 or options.repetitions < 1 or options.timeout < 1:
            raise BenchmarkError("jobs, repetitions, and timeout must be positive")
        if options.idle_timeout < 1 or options.minimum_free_gb < 0:
            raise BenchmarkError("idle timeout and minimum free space are invalid")
        for _, selector in self.toolchains:
            if not selector or selector.startswith("-"):
                raise BenchmarkError(f"invalid Rust toolchain selector: {selector!r}")
        if options.resume:
            self.restore_results()

    def restore_results(self) -> None:
        destination = self.output / "results.json"
        try:
            data = json.loads(destination.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise BenchmarkError(
                f"cannot resume existing session results {destination}: {error}"
            ) from error
        if not isinstance(data, dict):
            raise BenchmarkError("existing session results must be an object")

        settings = (
            ("jobs", self.options.jobs, None),
            ("toolchains", dict(self.toolchains), None),
            ("feature_matrix", self.options.feature_matrix, False),
            ("shared_build_enabled", not self.options.no_shared_build, True),
            ("compiler_accounting", self.options.compiler_accounting, "status"),
        )
        for key, expected, legacy_default in settings:
            actual = data.get(key, legacy_default)
            if actual != expected:
                raise BenchmarkError(
                    f"cannot resume with different {key}: {actual!r} != {expected!r}"
                )
        if "repetitions" in data and data["repetitions"] != self.options.repetitions:
            raise BenchmarkError("cannot resume with a different repetition count")

        recorded_sessions = data.get("sessions")
        if not isinstance(recorded_sessions, list):
            raise BenchmarkError("existing session results have invalid scenarios")
        recorded_by_project: dict[str, dict[str, Any]] = {}
        for recorded in recorded_sessions:
            if not isinstance(recorded, dict):
                raise BenchmarkError("existing session results have invalid scenarios")
            project = recorded.get("project")
            if not isinstance(project, str) or project in recorded_by_project:
                raise BenchmarkError("existing session results have invalid scenarios")
            recorded_by_project[project] = recorded
        selected_projects = {scenario.project for scenario in self.scenarios}
        if set(recorded_by_project) != selected_projects:
            raise BenchmarkError("cannot resume with different session projects")
        for scenario in self.scenarios:
            recorded = recorded_by_project[scenario.project]
            session = recorded.get("session")
            if (
                not isinstance(session, dict)
                or session.get("id") != scenario.session["id"]
                or recorded.get("base_revision") != scenario.base_revision
                or recorded.get("commands")
                != sum(step["kind"] == "command" for step in scenario.steps)
                or recorded.get("edits")
                != sum(step["kind"] == "edit" for step in scenario.steps)
            ):
                raise BenchmarkError(
                    f"cannot resume a different {scenario.project} session scenario"
                )

        samples = data.get("samples")
        if not isinstance(samples, list):
            raise BenchmarkError("existing session results have invalid samples")
        selectors = dict(self.toolchains)
        completed: set[tuple[str, str, int]] = set()
        for sample in samples:
            if not isinstance(sample, dict):
                raise BenchmarkError("existing session results have invalid samples")
            project = sample.get("project")
            label = sample.get("toolchain")
            repetition = sample.get("repetition")
            if (
                project not in selected_projects
                or label not in selectors
                or sample.get("selector") != selectors.get(label)
                or not isinstance(repetition, int)
                or isinstance(repetition, bool)
                or not 0 <= repetition < self.options.repetitions
            ):
                raise BenchmarkError(
                    "existing session results have incompatible samples"
                )
            identity = (project, label, repetition)
            if identity in completed:
                raise BenchmarkError(
                    "existing session results contain duplicate samples"
                )
            completed.add(identity)
        self.samples = samples
        print(f"Resuming {len(samples)} completed session samples", flush=True)

    def select_scenarios(self) -> list[Scenario]:
        selected: dict[str, Scenario] = {}
        paths = [path.resolve() for path in self.options.scenario]
        for path in paths:
            scenario = load_scenario(path)
            if scenario.project in selected:
                raise BenchmarkError(f"duplicate {scenario.project} session replay")
            selected[scenario.project] = scenario
        projects = self.options.project or list(PROJECTS)
        for project in projects:
            if project not in selected:
                candidate = SCENARIO_DIRECTORY / f"{project}.json"
                if not candidate.is_file():
                    raise BenchmarkError(
                        f"no {project} session fixture; provide --scenario PATH"
                    )
                selected[project] = load_scenario(candidate)
        return [selected[project] for project in projects]

    def parse_source_overrides(self) -> dict[str, Path]:
        result: dict[str, Path] = {}
        for value in self.options.source_path:
            project, separator, location = value.partition("=")
            if separator != "=" or project not in PROJECTS or not location:
                raise BenchmarkError("source paths must have form PROJECT=/path")
            if project in result:
                raise BenchmarkError(f"source path repeated for {project}")
            result[project] = Path(location).expanduser().resolve()
        return result

    def check_disk(self) -> None:
        candidate = self.output
        while not candidate.exists():
            candidate = candidate.parent
        free = shutil.disk_usage(candidate).free
        if free < self.options.minimum_free_gb * 1024**3:
            raise BenchmarkError(
                f"only {free / 1024**3:.1f} GiB available in {candidate}"
            )

    def required_commits(self, scenario: Scenario) -> set[str]:
        commits = {scenario.base_revision}
        for step in scenario.steps:
            if step["kind"] == "edit" and "commit" in step:
                commits.add(step["parent"])
                commits.add(step["commit"])
        return commits

    @staticmethod
    def commit_exists(repository: Path, revision: str) -> bool:
        return (
            subprocess.run(
                ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
                cwd=repository,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 0
        )

    def prepare_source(self, scenario: Scenario) -> Path:
        destination = self.output / "sources" / scenario.project
        source = self.source_overrides.get(scenario.project)
        if destination.exists():
            if not (destination / ".git").exists():
                raise BenchmarkError(
                    f"existing source is not an owned Git checkout: {destination}"
                )
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source is not None:
                top_level = Path(
                    command_output(["git", "rev-parse", "--show-toplevel"], cwd=source)
                )
                if top_level.resolve() != source:
                    raise BenchmarkError(
                        f"source path is not its own repository root: {source}"
                    )
                command_output(
                    [
                        "git",
                        "clone",
                        "--shared",
                        "--no-checkout",
                        str(source),
                        str(destination),
                    ]
                )
            else:
                if not scenario.repository.startswith("https://"):
                    raise BenchmarkError(
                        f"private {scenario.project} replay requires --source-path"
                    )
                command_output(
                    [
                        "git",
                        "clone",
                        "--no-checkout",
                        scenario.repository,
                        str(destination),
                    ]
                )

        if source is not None:
            promisor = subprocess.run(
                ["git", "config", "--get", "remote.origin.promisor"],
                cwd=source,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if promisor.returncode == 0 and promisor.stdout.strip() == "true":
                if not scenario.repository.startswith("https://"):
                    raise BenchmarkError(
                        "partial private source requires a complete authorized checkout"
                    )
                for setting, value in (
                    ("remote.origin.url", scenario.repository),
                    ("remote.origin.promisor", "true"),
                    ("remote.origin.partialclonefilter", "blob:none"),
                ):
                    command_output(["git", "config", setting, value], cwd=destination)

        missing = {
            revision
            for revision in self.required_commits(scenario)
            if not self.commit_exists(destination, revision)
        }
        fetch_errors: list[BenchmarkError] = []
        if missing:
            if scenario.repository.startswith("https://"):
                upstream = scenario.repository
            else:
                source = self.source_overrides.get(scenario.project)
                if source is None:
                    raise BenchmarkError("private repository has no authorized source")
                upstream = command_output(
                    ["git", "config", "--get", "remote.origin.url"], cwd=source
                )
            for reference in scenario.fetch_refs:
                try:
                    command_output(
                        ["git", "fetch", upstream, reference], cwd=destination
                    )
                except BenchmarkError as error:
                    fetch_errors.append(error)

            missing = {
                revision
                for revision in missing
                if not self.commit_exists(destination, revision)
            }
            for revision in sorted(missing):
                if self.commit_exists(destination, revision):
                    continue
                try:
                    command_output(
                        ["git", "fetch", "--no-tags", upstream, revision],
                        cwd=destination,
                    )
                except BenchmarkError as error:
                    fetch_errors.append(error)
            missing = {
                revision
                for revision in missing
                if not self.commit_exists(destination, revision)
            }
        if missing:
            detail = (
                f"; most recent fetch failure: {fetch_errors[-1]}"
                if fetch_errors
                else ""
            )
            raise BenchmarkError(
                f"{scenario.project} source is missing replay commits: "
                f"{', '.join(sorted(missing))}{detail}"
            )
        return destination

    def wait_until_idle(self) -> None:
        if not self.options.require_idle:
            return
        deadline = time.monotonic() + self.options.idle_timeout
        while active := competing_processes():
            if time.monotonic() >= deadline:
                raise BenchmarkError(
                    "timed out waiting for competing compiler processes: "
                    + ", ".join(active)
                )
            print(
                "Waiting for unrelated compiler activity: " + ", ".join(active),
                flush=True,
            )
            time.sleep(min(5, max(0.1, deadline - time.monotonic())))

    def environment(
        self, scenario: Scenario, label: str, selector: str, repetition: int
    ) -> dict[str, str]:
        environment = dict(os.environ)
        environment.update(scenario.environment)
        environment["RUSTUP_TOOLCHAIN"] = selector
        environment["CARGO_BUILD_JOBS"] = str(self.options.jobs)
        environment["CARGO_TARGET_DIR"] = str(
            self.output / "targets" / scenario.project / label / str(repetition)
        )
        user_bins = (Path.home() / ".local" / "bin", Path.home() / ".cargo" / "bin")
        environment["PATH"] = os.pathsep.join(
            [*(str(path) for path in user_bins), environment.get("PATH", "")]
        )
        for key in (
            "CARGO_BUILD_BUILD_DIR",
            "CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST",
            "CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST",
            "CARGO_ENCODED_RUSTFLAGS",
            "RUSTFLAGS",
            "CARGO_TERM_VERBOSE",
        ):
            environment.pop(key, None)
        if self.options.compiler_accounting == "verbose":
            environment["CARGO_TERM_VERBOSE"] = "true"
        if label == "ohm" or label in FEATURE_OVERRIDES:
            if not self.options.no_shared_build:
                shared_build = self.output / "shared-build" / scenario.project
                if self.options.feature_matrix:
                    shared_build /= label
                environment["CARGO_BUILD_BUILD_DIR"] = str(
                    shared_build / str(repetition)
                )
            environment["CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST"] = "all"
            if overrides := FEATURE_OVERRIDES.get(label):
                environment["RUSTFLAGS"] = " ".join(overrides)
        if self.options.offline:
            environment["CARGO_NET_OFFLINE"] = "true"
        return environment

    @staticmethod
    def command(step: dict[str, Any], selector: str) -> list[str]:
        arguments = list(step["args"])
        if step["program"] == "cargo":
            return ["cargo", f"+{selector}", *arguments]
        return ["just", *arguments]

    def patch_bytes(
        self, scenario: Scenario, source: Path, step: dict[str, Any]
    ) -> bytes:
        if "patch" in step:
            candidate = (scenario.path.parent / step["patch"]).resolve()
            if not candidate.is_relative_to(scenario.path.parent):
                raise BenchmarkError("session patch escapes its fixture directory")
            try:
                return candidate.read_bytes()
            except OSError as error:
                raise BenchmarkError(
                    f"cannot read session patch {candidate}: {error}"
                ) from error
        arguments = ["git", "diff", "--binary", step["parent"], step["commit"]]
        if paths := step.get("paths"):
            arguments.extend(["--", *paths])
        result = subprocess.run(
            arguments,
            cwd=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode:
            raise BenchmarkError(
                f"cannot obtain real source edit {step['label']}: "
                f"{result.stderr.decode(errors='replace').strip()}"
            )
        if not result.stdout:
            raise BenchmarkError(
                f"real source edit is unexpectedly empty: {step['label']}"
            )
        return result.stdout

    def apply_edit(
        self, scenario: Scenario, source: Path, worktree: Path, step: dict[str, Any]
    ) -> dict[str, Any]:
        patch = self.patch_bytes(scenario, source, step)
        checked = subprocess.run(
            ["git", "apply", "--check", "-"],
            cwd=worktree,
            input=patch,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if checked.returncode:
            raise BenchmarkError(
                f"real edit does not apply cleanly: {step['label']}: "
                f"{checked.stderr.decode(errors='replace').strip()}"
            )
        started = time.perf_counter()
        applied = subprocess.run(
            ["git", "apply", "-"],
            cwd=worktree,
            input=patch,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        duration = time.perf_counter() - started
        if applied.returncode:
            raise BenchmarkError(
                f"cannot apply real edit: {step['label']}: "
                f"{applied.stderr.decode(errors='replace').strip()}"
            )
        files = sum(line.startswith(b"diff --git ") for line in patch.splitlines())
        return {"kind": "edit", "wall_seconds": duration, "files_changed": files}

    def run_command(
        self,
        scenario: Scenario,
        worktree: Path,
        step: dict[str, Any],
        label: str,
        selector: str,
        repetition: int,
        index: int,
        *,
        phase: str = "session",
    ) -> dict[str, Any]:
        arguments = self.command(step, selector)
        directory = worktree / step.get("cwd", ".")
        if not directory.is_dir() or not directory.resolve().is_relative_to(
            worktree.resolve()
        ):
            raise BenchmarkError(f"session command directory is invalid: {directory}")
        self.wait_until_idle()
        started = time.perf_counter()
        with InterferenceMonitor(enabled=self.options.require_idle) as monitor:
            try:
                result = subprocess.run(
                    arguments,
                    cwd=directory,
                    env=self.environment(scenario, label, selector, repetition),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=self.options.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise BenchmarkError(
                    f"session command exceeded {self.options.timeout}s: {shlex.join(arguments)}"
                ) from error
            except OSError as error:
                raise BenchmarkError(
                    f"cannot run session command {shlex.join(arguments)}: {error}"
                ) from error
        duration = time.perf_counter() - started
        logs = self.output / "logs" / scenario.project / label / str(repetition)
        logs.mkdir(parents=True, exist_ok=True)
        prefix = "warmup-" if phase == "warmup" else ""
        log = logs / f"{prefix}{index:02d}.log"
        log.write_text(result.stdout)
        reported_crates = [
            match.group("crate") for match in CARGO_STATUS.finditer(result.stdout)
        ]
        invocations = (
            compiler_invocations(result.stdout)
            if self.options.compiler_accounting == "verbose"
            else None
        )
        sample = {
            "kind": "command",
            "wall_seconds": duration,
            "command": arguments,
            "returncode": result.returncode,
            "cargo_reported_crates": reported_crates,
            "actual_compiler_invocations": invocations,
            "cargo_status_without_compiler_invocation": (
                status_only_crates(reported_crates, invocations)
                if invocations is not None
                else None
            ),
            "tests_started": sum(
                int(match.group(1)) for match in TEST_COUNT.finditer(result.stdout)
            ),
            "external_compilation": sorted(monitor.observed),
            "log": str(log),
        }
        if result.returncode:
            raise BenchmarkError(
                f"{scenario.project} {label} step {index} exited {result.returncode}; inspect {log}"
            )
        if "blocking waiting for file lock" in result.stdout.lower():
            raise BenchmarkError(
                f"session command encountered Cargo lock contention; inspect {log}"
            )
        is_test = (step["program"] == "just" and step["args"][0] == "test") or (
            step["program"] == "cargo"
            and (step["args"][0] == "test" or step["args"][:2] == ["nextest", "run"])
        )
        if is_test and sample["tests_started"] == 0:
            raise BenchmarkError(
                f"session test command selected zero tests; inspect {log}"
            )
        if monitor.failure:
            raise BenchmarkError(
                f"compiler interference monitor failed: {monitor.failure}"
            )
        if monitor.observed:
            raise BenchmarkError(
                "unrelated compiler processes overlapped session command: "
                + ", ".join(sorted(monitor.observed))
            )
        return sample

    def archive_interrupted_session(
        self, scenario: Scenario, label: str, selector: str, repetition: int
    ) -> None:
        """Preserve an incomplete cell without letting its artifacts bias a restart."""
        identity = scenario.project, label, repetition
        if any(
            (sample["project"], sample["toolchain"], sample["repetition"]) == identity
            for sample in self.samples
        ):
            raise BenchmarkError("cannot restart an already completed session sample")

        source = self.sources[scenario.project]
        worktree = (
            self.output / "worktrees" / scenario.project / label / str(repetition)
        )
        artifacts = {
            "worktree": worktree,
            "target": self.output
            / "targets"
            / scenario.project
            / label
            / str(repetition),
            "logs": self.output / "logs" / scenario.project / label / str(repetition),
        }
        environment = self.environment(scenario, label, selector, repetition)
        if shared_build := environment.get("CARGO_BUILD_BUILD_DIR"):
            artifacts["shared-build"] = Path(shared_build)

        existing = {
            name: path
            for name, path in artifacts.items()
            if path.exists() or path.is_symlink()
        }
        if not existing:
            return

        for path in existing.values():
            if (
                path.is_symlink()
                or not path.is_dir()
                or not path.resolve().is_relative_to(self.output)
            ):
                raise BenchmarkError(
                    f"session owned artifact is not a private directory: {path}"
                )

        if "worktree" in existing:
            top_level = Path(
                command_output(["git", "rev-parse", "--show-toplevel"], cwd=worktree)
            )
            if top_level.resolve() != worktree.resolve():
                raise BenchmarkError(
                    f"existing session worktree has an unexpected root: {worktree}"
                )

            def common_directory(repository: Path) -> Path:
                common = Path(
                    command_output(
                        ["git", "rev-parse", "--git-common-dir"], cwd=repository
                    )
                )
                if not common.is_absolute():
                    common = repository / common
                return common.resolve()

            if common_directory(worktree) != common_directory(source):
                raise BenchmarkError(
                    f"existing session worktree belongs to a different source: {worktree}"
                )
            revision = command_output(["git", "rev-parse", "HEAD"], cwd=worktree)
            if revision != scenario.base_revision:
                raise BenchmarkError(
                    f"existing session worktree is not at the exact base revision: {worktree}"
                )

        archive_root = (
            self.output / "interrupted" / scenario.project / label / str(repetition)
        )
        if not archive_root.resolve().is_relative_to(self.output):
            raise BenchmarkError(
                f"session archive escapes its owned output: {archive_root}"
            )
        attempt = 0
        while (archive := archive_root / str(attempt)).exists():
            attempt += 1
        try:
            archive.mkdir(parents=True, exist_ok=False)
        except OSError as error:
            raise BenchmarkError(
                f"cannot create interrupted session archive: {error}"
            ) from error

        if "worktree" in existing:
            command_output(
                ["git", "worktree", "move", str(worktree), str(archive / "worktree")],
                cwd=source,
            )
        for name, path in existing.items():
            if name == "worktree":
                continue
            try:
                path.rename(archive / name)
            except OSError as error:
                raise BenchmarkError(
                    f"cannot preserve interrupted session artifact {path}: {error}"
                ) from error
        print(f"Preserved interrupted {scenario.project} / {label} replay in {archive}")

    def run_session(
        self, scenario: Scenario, label: str, selector: str, repetition: int
    ) -> dict[str, Any]:
        source = self.sources[scenario.project]
        worktree = (
            self.output / "worktrees" / scenario.project / label / str(repetition)
        )
        if self.options.resume:
            self.archive_interrupted_session(scenario, label, selector, repetition)
        elif worktree.exists() or worktree.is_symlink():
            raise BenchmarkError(f"owned session worktree already exists: {worktree}")

        worktree.parent.mkdir(parents=True, exist_ok=True)
        command_output(
            [
                "git",
                "worktree",
                "add",
                "--detach",
                str(worktree),
                scenario.base_revision,
            ],
            cwd=source,
        )
        print(f"\n{scenario.project} / {label} / replay {repetition + 1}", flush=True)
        warmup_steps: list[dict[str, Any]] = []
        if not self.options.no_warmup:
            for index, step in enumerate(scenario.warmup, start=1):
                print(f"  warmup {index:02d}. {step['label']}", flush=True)
                observed = self.run_command(
                    scenario,
                    worktree,
                    step,
                    label,
                    selector,
                    repetition,
                    index,
                    phase="warmup",
                )
                observed.update({"index": index, "label": step["label"]})
                warmup_steps.append(observed)
                print(
                    f"      {observed['wall_seconds']:.2f}s untimed, "
                    f"{len(observed['cargo_reported_crates'])} Cargo status messages",
                    flush=True,
                )
        started = time.perf_counter()
        steps: list[dict[str, Any]] = []
        for index, step in enumerate(scenario.steps, start=1):
            print(f"  {index:02d}. {step['label']}", flush=True)
            if step["kind"] == "edit":
                observed = self.apply_edit(scenario, source, worktree, step)
            else:
                observed = self.run_command(
                    scenario, worktree, step, label, selector, repetition, index
                )
            observed.update({"index": index, "label": step["label"]})
            steps.append(observed)
            if observed["kind"] == "command":
                compiler_count = observed["actual_compiler_invocations"]
                accounting = (
                    f", {len(compiler_count)} actual compiler invocations"
                    if compiler_count is not None
                    else ""
                )
                print(
                    f"      {observed['wall_seconds']:.2f}s, "
                    f"{len(observed['cargo_reported_crates'])} Cargo status messages"
                    f"{accounting}, "
                    f"{observed['tests_started']} tests",
                    flush=True,
                )
        total = time.perf_counter() - started
        command_steps = [step for step in steps if step["kind"] == "command"]
        compiler_invocation_count = (
            sum(len(step["actual_compiler_invocations"]) for step in command_steps)
            if self.options.compiler_accounting == "verbose"
            else None
        )
        status_without_compiler_count = (
            sum(
                len(step["cargo_status_without_compiler_invocation"])
                for step in command_steps
            )
            if self.options.compiler_accounting == "verbose"
            else None
        )
        sample = {
            "project": scenario.project,
            "session_id": scenario.session["id"],
            "toolchain": label,
            "selector": selector,
            "repetition": repetition,
            "wall_seconds": total,
            "command_seconds": sum(
                step["wall_seconds"] for step in steps if step["kind"] == "command"
            ),
            "edit_seconds": sum(
                step["wall_seconds"] for step in steps if step["kind"] == "edit"
            ),
            "cargo_status_message_count": sum(
                len(step["cargo_reported_crates"]) for step in command_steps
            ),
            "actual_compiler_invocation_count": compiler_invocation_count,
            "cargo_status_without_compiler_invocation_count": (
                status_without_compiler_count
            ),
            "worktree": str(worktree),
            "warmup_seconds": sum(step["wall_seconds"] for step in warmup_steps),
            "warmup_steps": warmup_steps,
            "steps": steps,
        }
        self.samples.append(sample)
        self.persist()
        print(f"  Complete workflow: {total:.2f}s", flush=True)
        return sample

    def persist(self) -> None:
        self.output.mkdir(parents=True, exist_ok=True)
        result = {
            "host": platform.node(),
            "platform": platform.platform(),
            "jobs": self.options.jobs,
            "repetitions": self.options.repetitions,
            "toolchains": dict(self.toolchains),
            "feature_matrix": self.options.feature_matrix,
            "shared_build_enabled": not self.options.no_shared_build,
            "compiler_accounting": self.options.compiler_accounting,
            "sessions": [
                {
                    "project": scenario.project,
                    "session": scenario.session,
                    "base_revision": scenario.base_revision,
                    "commands": sum(
                        step["kind"] == "command" for step in scenario.steps
                    ),
                    "edits": sum(step["kind"] == "edit" for step in scenario.steps),
                    "warmups": len(scenario.warmup),
                }
                for scenario in self.scenarios
            ],
            "samples": self.samples,
        }
        destination = self.output / "results.json"
        temporary = self.output / ".results.json.tmp"
        temporary.write_text(json.dumps(result, indent=2) + "\n")
        temporary.replace(destination)

    def summarize(self) -> None:
        heading = (
            "Ohm feature-factorial real-session comparison"
            if self.options.feature_matrix
            else "Complete real-session workflow comparison"
        )
        if self.options.feature_matrix or self.options.no_shared_build:
            sharing = (
                "shared build disabled"
                if self.options.no_shared_build
                else "shared build enabled"
            )
            heading = f"{heading} ({sharing})"
        print(f"\n{heading}", flush=True)
        for scenario in self.scenarios:
            values = {
                label: [
                    sample["wall_seconds"]
                    for sample in self.samples
                    if sample["project"] == scenario.project
                    and sample["toolchain"] == label
                ]
                for label, _ in self.toolchains
            }
            if self.options.feature_matrix:
                if any(not samples for samples in values.values()):
                    continue
                medians = {
                    label: statistics.median(samples)
                    for label, samples in values.items()
                }
                print(f"  {scenario.project}", flush=True)
                for label, _ in self.toolchains:
                    print(f"    {label:25s} {medians[label]:8.2f}s", flush=True)

                hash_disabled = (
                    medians["ohm-no-public-api-hash"],
                    medians["ohm-neither"],
                )
                hash_enabled = (
                    medians["ohm-all"],
                    medians["ohm-no-proc-macro-cache"],
                )
                macro_disabled = (
                    medians["ohm-no-proc-macro-cache"],
                    medians["ohm-neither"],
                )
                macro_enabled = (
                    medians["ohm-all"],
                    medians["ohm-no-public-api-hash"],
                )
                for feature, disabled, enabled in (
                    ("public API hashing", hash_disabled, hash_enabled),
                    ("proc-macro caching", macro_disabled, macro_enabled),
                ):
                    benefit = statistics.mean(disabled) - statistics.mean(enabled)
                    reference = statistics.mean(disabled)
                    percent = benefit / reference * 100 if reference else 0
                    print(
                        f"    marginal {feature}: "
                        f"{benefit:+.2f}s benefit ({percent:+.1f}%)",
                        flush=True,
                    )
                continue
            if not values["stock"] or not values["ohm"]:
                continue
            stock = statistics.median(values["stock"])
            ohm = statistics.median(values["ohm"])
            print(
                f"  {scenario.project:5s}  stock {stock:8.2f}s  "
                f"ohm {ohm:8.2f}s  {stock / ohm:5.2f}x",
                flush=True,
            )
            if self.options.compiler_accounting == "verbose":
                for label, _ in self.toolchains:
                    samples = [
                        sample
                        for sample in self.samples
                        if sample["project"] == scenario.project
                        and sample["toolchain"] == label
                        and sample.get("actual_compiler_invocation_count") is not None
                    ]
                    if not samples:
                        continue
                    invocations = statistics.mean(
                        sample["actual_compiler_invocation_count"] for sample in samples
                    )
                    status_only = statistics.mean(
                        sample["cargo_status_without_compiler_invocation_count"]
                        for sample in samples
                    )
                    print(
                        f"    {label:5s}  {invocations:.1f} actual compiler runs, "
                        f"{status_only:.1f} status-only crates",
                        flush=True,
                    )
        print(f"\nFull data: {self.output / 'results.json'}", flush=True)

    def run(self) -> None:
        self.check_disk()
        for scenario in self.scenarios:
            self.sources[scenario.project] = self.prepare_source(scenario)
        self.persist()
        if self.options.dry_run:
            for scenario in self.scenarios:
                print(f"{scenario.project}: {scenario.session['id']}")
                for index, step in enumerate(scenario.steps, start=1):
                    print(f"  {index:02d}. {step['kind']}: {step['label']}")
            return
        for repetition in range(self.options.repetitions):
            for scenario in self.scenarios:
                if self.options.feature_matrix:
                    order = tuple(
                        self.toolchains[(index + repetition) % len(self.toolchains)]
                        for index in (0, 1, 3, 2)
                    )
                else:
                    order = (
                        self.toolchains
                        if repetition % 2 == 0
                        else self.toolchains[::-1]
                    )
                for label, selector in order:
                    if any(
                        sample["project"] == scenario.project
                        and sample["toolchain"] == label
                        and sample["repetition"] == repetition
                        for sample in self.samples
                    ):
                        print(
                            f"Skipping completed {scenario.project} / {label} / "
                            f"replay {repetition + 1}",
                            flush=True,
                        )
                        continue
                    self.run_session(scenario, label, selector, repetition)
        self.summarize()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--project", action="append", choices=PROJECTS)
    result.add_argument("--scenario", action="append", type=Path, default=[])
    result.add_argument("--source-path", action="append", default=[])
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument(
        "--resume",
        action="store_true",
        help="preserve completed results and restart interrupted cells from fresh artifacts",
    )
    result.add_argument("--upstream", default="1.98.0")
    result.add_argument("--ohm", default="ohm")
    result.add_argument(
        "--feature-matrix",
        action="store_true",
        help=(
            "compare four Ohm-only combinations of public-API hashing and "
            "procedural-macro expansion caching"
        ),
    )
    result.add_argument(
        "--no-shared-build",
        action="store_true",
        help=(
            "omit Ohm's shared build directory to measure feature behavior "
            "without shared-registry fine-grained locking"
        ),
    )
    result.add_argument("--jobs", type=int, default=8)
    result.add_argument("--repetitions", type=int, default=1)
    result.add_argument("--timeout", type=int, default=1800)
    result.add_argument(
        "--compiler-accounting",
        choices=("status", "verbose"),
        default="status",
        help=(
            "label Cargo progress messages honestly, or use verbose Cargo output "
            "to count actual rustc and clippy-driver invocations"
        ),
    )
    result.add_argument("--minimum-free-gb", type=int, default=20)
    result.add_argument("--require-idle", action="store_true")
    result.add_argument("--idle-timeout", type=int, default=600)
    result.add_argument("--offline", action="store_true")
    result.add_argument(
        "--no-warmup",
        action="store_true",
        help="include cold target compilation instead of prewarming the workflow",
    )
    result.add_argument(
        "--background",
        action="store_true",
        help="continue remotely after SSH disconnects; write status and a run log",
    )
    result.add_argument("--dry-run", action="store_true")
    return result


def run_in_background(study: Replay) -> None:
    if not hasattr(os, "fork"):
        raise BenchmarkError("background execution requires a Unix-like host")
    study.output.mkdir(parents=True, exist_ok=True)
    status = study.output / "status.json"
    log = study.output / "run.log"
    try:
        process = os.fork()
    except OSError as error:
        raise BenchmarkError(f"cannot detach benchmark process: {error}") from error
    if process:
        print(f"Background replay process: {process}")
        print(f"Progress log: {log}")
        print(f"Status: {status}")
        return

    os.setsid()
    with (
        open(os.devnull, "rb") as standard_input,
        open(log, "ab", buffering=0) as output,
    ):
        os.dup2(standard_input.fileno(), sys.stdin.fileno())
        os.dup2(output.fileno(), sys.stdout.fileno())
        os.dup2(output.fileno(), sys.stderr.fileno())

    def write_status(state: str, error: str | None = None) -> None:
        contents: dict[str, Any] = {
            "state": state,
            "pid": os.getpid(),
            "updated_at": time.time(),
        }
        if error is not None:
            contents["error"] = error
        temporary = study.output / ".status.json.tmp"
        temporary.write_text(json.dumps(contents, indent=2) + "\n")
        temporary.replace(status)

    write_status("running")
    try:
        study.run()
    except Exception as error:
        write_status("failed", str(error))
        print(f"error: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1) from error
    write_status("succeeded")


def main() -> None:
    try:
        os.umask(0o077)
        options = parser().parse_args()
        study = Replay(options)
        if options.background:
            run_in_background(study)
        else:
            study.run()
    except BenchmarkError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
