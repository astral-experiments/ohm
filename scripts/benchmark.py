#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Compare stock Rust and Ohm against representative uv and Codex workflows."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from pathlib import Path


class BenchmarkError(Exception):
    """A benchmark configuration or measurement cannot be trusted."""


class ContaminatedBenchmarkError(BenchmarkError):
    """Compiler activity or cache contention invalidated a measurement."""


def toolchain_order(
    toolchains: tuple[tuple[str, str], ...], index: int
) -> tuple[tuple[str, str], ...]:
    """Balance each toolchain's position and the order of each pair."""
    if len(toolchains) == 2:
        return toolchains if index % 2 == 0 else toolchains[::-1]
    offset = index // 2 % len(toolchains)
    order = toolchains[offset:] + toolchains[:offset]
    return order if index % 2 == 0 else order[::-1]


def configure_ready_tests(environment: dict[str, str], label: str) -> None:
    environment.pop("CARGO_UNSTABLE_OHM_READY_TESTS", None)
    if label == "ohm-ready-tests":
        environment["CARGO_UNSTABLE_OHM_READY_TESTS"] = "true"


@dataclasses.dataclass(frozen=True)
class Edit:
    path: str
    before: str
    after: str
    crate: str


@dataclasses.dataclass(frozen=True)
class Workload:
    name: str
    repository: str
    package: str
    workspace: str
    dependency: Edit
    direct: Edit
    selected_test: str


REPOSITORIES = {
    "uv": {
        "url": "https://github.com/astral-sh/uv.git",
        "revision": "c22e6b71933443e9cd299d4b6ac8de035ed4825b",
    },
    "codex": {
        "url": "https://github.com/openai/codex.git",
        "revision": "5157493c23713ac12034cf250ffb0a8ce0670277",
    },
}


UV_DEPENDENCY = Edit(
    "crates/uv-normalize/src/lib.rs",
    "b'a'..=b'z' | b'0'..=b'9' => {\n                normalized.push",
    "b'0'..=b'9' | b'a'..=b'z' => {\n                normalized.push",
    "uv-normalize",
)
CODEX_DEPENDENCY = Edit(
    "codex-rs/utils/string/src/lib.rs",
    "matches!(ch, '.' | '_' | '-' | '/')",
    "matches!(ch, '_' | '.' | '-' | '/')",
    "codex-utils-string",
)
WORKLOADS = {
    "uv": Workload(
        "uv",
        "uv",
        "uv",
        ".",
        UV_DEPENDENCY,
        Edit(
            "crates/uv/src/install_source.rs",
            "component == cellar && next == formula",
            "{\n"
            '                component == cellar && (next == formula || next == OsStr::new("uv-preview"))\n'
            "            }",
            "uv",
        ),
        "help::help",
    ),
    "codex-core": Workload(
        "codex-core",
        "codex",
        "codex-core",
        "codex-rs",
        CODEX_DEPENDENCY,
        Edit(
            "codex-rs/core/src/audio_preparation.rs",
            'if mime.eq_ignore_ascii_case("audio/wav")\n'
            '        || mime.eq_ignore_ascii_case("audio/x-wav")',
            'if mime.eq_ignore_ascii_case("audio/x-wav")\n'
            '        || mime.eq_ignore_ascii_case("audio/wav")',
            "codex-core",
        ),
        "preparation_canonicalizes_data_urls_and_rejects_remote_urls",
    ),
}
WORKFLOWS = ("check", "clippy", "test")
FEATURE_WORKFLOWS = ("build-check", "fmt", "shared-build")
WORKFLOW_PHASES = {
    **{workflow: ("cold", "noop", "dependency", "direct") for workflow in WORKFLOWS},
    "build-check": ("transition",),
    "fmt": ("noop", "direct"),
    "shared-build": ("reuse",),
}
COMPILATION = re.compile(r"^\s*(?:Checking|Compiling)\s+([^\s]+)", re.MULTILINE)
TEST_COUNT = re.compile(r"(?mi)^\s*(?:running|Starting)\s+(\d+)\s+tests?\b")
FAILURE_DIAGNOSTIC = re.compile(
    r"(?im)^\s*(?:error(?:\[[^\]]+\])?:|fatal(?: error)?:|diff in\b|"
    r"error writing files\b|thread .* panicked at\b|aborting due to\b)"
)
CACHE_FAILURE_DIAGNOSTIC = re.compile(
    r"(?i)\b(?:failed to (?:acquire|obtain|lock)|timed out (?:while )?waiting "
    r"for|blocking waiting for)\b.*\b(?:file lock|package cache|target cache|lock)\b"
)
COMPILER_PROCESSES = {
    "cargo",
    "cargo-nextest",
    "nextest",
    "rustc",
    "rustdoc",
    "rustfmt",
    "cargo-fmt",
    "clippy-driver",
    "rust-lld",
    "ld",
    "ld64",
    "clang",
    "clang++",
    "cc1",
    "cc1plus",
}


def command_output(arguments: list[str], *, cwd: Path | None = None) -> str:
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
        raise BenchmarkError(
            f"command failed: {' '.join(arguments)}: {detail}"
        ) from error
    except OSError as error:
        raise BenchmarkError(
            f"command failed: {' '.join(arguments)}: {error}"
        ) from error
    return result.stdout.strip()


def competing_processes(owner: int | None = None) -> list[str]:
    """Return compiler processes outside this benchmark's own process tree."""
    owner = os.getpid() if owner is None else owner
    output = command_output(["ps", "-ax", "-o", "pid=,ppid=,comm="])
    if not output:
        raise BenchmarkError("process inspection returned no process information")

    processes: dict[int, tuple[int, str]] = {}
    for line in output.splitlines():
        parts = line.split(None, 2)
        if len(parts) != 3:
            raise BenchmarkError(f"invalid process inspection result: {line!r}")
        try:
            process, parent = int(parts[0]), int(parts[1])
        except ValueError as error:
            raise BenchmarkError(
                f"invalid process inspection result: {line!r}"
            ) from error
        processes[process] = parent, Path(parts[2]).name

    def belongs_to_benchmark(process: int) -> bool:
        visited: set[int] = set()
        while process in processes and process not in visited:
            if process == owner:
                return True
            visited.add(process)
            process = processes[process][0]
        return process == owner

    return [
        f"{process} {name}"
        for process, (_, name) in processes.items()
        if name in COMPILER_PROCESSES and not belongs_to_benchmark(process)
    ]


def edit_contents(worktree: Path, edit: Edit) -> tuple[Path, bytes, bytes]:
    relative = Path(edit.path)
    if relative.is_absolute() or ".." in relative.parts:
        raise BenchmarkError(f"edit path must remain within its worktree: {relative}")
    path = (worktree / relative).resolve()
    if not path.is_relative_to(worktree.resolve()) or not path.is_file():
        raise BenchmarkError(
            f"edited source file does not exist in its worktree: {path}"
        )
    if not edit.before or edit.before == edit.after:
        raise BenchmarkError(f"invalid reversible source edit: {path}")
    original = path.read_bytes()
    before = edit.before.encode()
    if (count := original.count(before)) != 1:
        raise BenchmarkError(
            f"expected exactly one source match in {path}; found {count}"
        )
    return path, original, original.replace(before, edit.after.encode(), 1)


@contextlib.contextmanager
def reversible_edit(worktree: Path, edit: Edit) -> Iterator[Callable[[bool], None]]:
    path, original, alternate = edit_contents(worktree, edit)

    def activate(changed: bool) -> None:
        contents = alternate if changed else original
        if path.read_bytes() != contents:
            path.write_bytes(contents)
            os.utime(path, None)

    try:
        yield activate
    finally:
        if path.exists() and path.read_bytes() != original:
            path.write_bytes(original)
            os.utime(path, None)


def validate_output(
    output: str, *, expected_crate: str | None, selected_test: str | None
) -> None:
    if "blocking waiting for file lock" in output.lower():
        raise ContaminatedBenchmarkError(
            "benchmark encountered Cargo package or target cache contention"
        )
    if expected_crate is not None and expected_crate not in COMPILATION.findall(output):
        raise BenchmarkError(f"edited crate {expected_crate!r} was not rebuilt")
    if selected_test is not None:
        counts = [int(match.group(1)) for match in TEST_COUNT.finditer(output)]
        if not counts or any(count != 1 for count in counts):
            raise BenchmarkError("benchmark must execute exactly one existing test")
        test_name = rf"(?<![A-Za-z0-9_]){re.escape(selected_test)}(?![A-Za-z0-9_])"
        if re.search(test_name, output) is None:
            raise BenchmarkError(f"selected test {selected_test!r} was not executed")


def cache_contention_only(output: str) -> bool:
    if "blocking waiting for file lock" not in output.lower():
        return False
    return all(
        CACHE_FAILURE_DIAGNOSTIC.search(line) is not None
        for line in output.splitlines()
        if FAILURE_DIAGNOSTIC.match(line)
    )


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--uv-path", type=Path)
    argument_parser.add_argument("--codex-path", type=Path)
    argument_parser.add_argument("--uv-rev", default=REPOSITORIES["uv"]["revision"])
    argument_parser.add_argument(
        "--codex-rev", default=REPOSITORIES["codex"]["revision"]
    )
    argument_parser.add_argument("--upstream", default="1.98.0")
    argument_parser.add_argument("--ohm", default="ohm")
    argument_parser.add_argument(
        "--compare-ready-tests",
        action="store_true",
        help="also measure the same Ohm toolchain with test/build overlap enabled",
    )
    argument_parser.add_argument(
        "--project",
        action="append",
        choices=WORKLOADS,
        help="repeat to select projects",
    )
    argument_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "ohm-benchmarks",
    )
    argument_parser.add_argument("--jobs", type=int, default=8)
    argument_parser.add_argument("--cold-runs", type=int, default=1)
    argument_parser.add_argument("--noop-runs", type=int, default=3)
    argument_parser.add_argument("--dependency-runs", type=int, default=7)
    argument_parser.add_argument("--direct-runs", type=int, default=5)
    argument_parser.add_argument("--minimum-free-gb", type=int, default=10)
    argument_parser.add_argument("--timeout", type=int, default=1800)
    argument_parser.add_argument(
        "--require-idle",
        action="store_true",
        help="wait for unrelated Rust builds and reject samples that overlap them",
    )
    argument_parser.add_argument("--idle-timeout", type=int, default=900)
    argument_parser.add_argument("--contention-retries", type=int, default=3)
    argument_parser.add_argument("--quiet-seconds", type=int, default=10)
    argument_parser.add_argument(
        "--discard-targets",
        action="store_true",
        help="remove owned build artifacts after each completed workflow",
    )
    argument_parser.add_argument("--dry-run", action="store_true")
    return argument_parser


class Study:
    def __init__(self, options: argparse.Namespace) -> None:
        self.options = options
        selected = options.project or list(WORKLOADS)
        if len(set(selected)) != len(selected):
            raise BenchmarkError("benchmark projects must not be repeated")
        self.workloads = [WORKLOADS[name] for name in selected]
        self.toolchains = (("stock", options.upstream), ("ohm", options.ohm))
        if options.compare_ready_tests:
            self.toolchains += (("ohm-ready-tests", options.ohm),)
        self.output = options.output_dir.expanduser().resolve()
        self.sources: dict[str, Path] = {}
        self.revisions: dict[str, str] = {}
        self.source_urls: dict[str, str] = {}
        self.worktrees: dict[tuple[str, str], Path] = {}
        self.samples: list[dict[str, object]] = []
        self.metadata: dict[str, object] = {}

        for name in (
            "jobs",
            "cold_runs",
            "noop_runs",
            "dependency_runs",
            "direct_runs",
        ):
            if getattr(options, name) < 1:
                raise BenchmarkError(f"--{name.replace('_', '-')} must be positive")
        if (
            options.timeout < 1
            or options.idle_timeout < 1
            or options.minimum_free_gb < 0
            or options.contention_retries < 0
            or options.quiet_seconds < 0
        ):
            raise BenchmarkError(
                "timeouts must be positive; minimum free space, contention retries, "
                "and quiet seconds must be nonnegative"
            )
        for _, selector in self.toolchains:
            if not selector or selector.startswith("-"):
                raise BenchmarkError(f"invalid Rust toolchain selector: {selector!r}")
        if self.toolchains[0][1] == self.toolchains[1][1]:
            raise BenchmarkError("upstream and Ohm toolchains must be distinct")

        for workload in self.workloads:
            name = workload.repository
            if name in self.revisions:
                continue
            revision = options.uv_rev if name == "uv" else options.codex_rev
            if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
                raise BenchmarkError(
                    f"source revision must be a full Git SHA: {revision!r}"
                )
            self.revisions[name] = revision
            self.source_urls[name] = REPOSITORIES[name]["url"]
            configured = options.uv_path if name == "uv" else options.codex_path
            if configured is not None:
                configured = configured.expanduser()
                if not configured.is_dir():
                    raise BenchmarkError(
                        f"source repository does not exist: {configured}"
                    )
                self.sources[name] = Path(
                    command_output(
                        ["git", "rev-parse", "--show-toplevel"], cwd=configured
                    )
                ).resolve()

        for name in self.sources:
            self.validate_source(name)

    def validate_source(self, name: str) -> None:
        repository = self.sources[name]
        revision = self.revisions[name]
        resolved = command_output(
            ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
            cwd=repository,
        )
        if resolved != revision:
            raise BenchmarkError(
                f"source revision does not resolve exactly: {revision}"
            )
        for workload in self.workloads:
            if workload.repository != name:
                continue
            manifest = Path(workload.workspace) / "Cargo.toml"
            command_output(["git", "show", f"{revision}:{manifest}"], cwd=repository)
            for edit in (workload.dependency, workload.direct):
                source = command_output(
                    ["git", "show", f"{revision}:{edit.path}"], cwd=repository
                )
                if (count := source.count(edit.before)) != 1:
                    raise BenchmarkError(
                        f"expected exactly one source match in {revision}:{edit.path}; "
                        f"found {count}"
                    )

    def prepare_sources(self) -> None:
        for name, revision in self.revisions.items():
            if name in self.sources:
                continue
            repository = self.output / "sources" / name
            repository.parent.mkdir(parents=True, exist_ok=True)
            print(f"Cloning {self.source_urls[name]} at {revision}", flush=True)
            public_prefix = self.source_urls[name].rsplit("/", 1)[0] + "/"
            preserve_https = f"url.{public_prefix}.insteadOf={public_prefix}"
            with tempfile.TemporaryDirectory(
                prefix=f".{name}-", dir=repository.parent
            ) as temporary:
                checkout = Path(temporary) / "checkout"
                command_output(
                    [
                        "git",
                        "-c",
                        preserve_https,
                        "clone",
                        "--config",
                        preserve_https,
                        "--no-checkout",
                        "--filter=blob:none",
                        "--depth=1",
                        self.source_urls[name],
                        str(checkout),
                    ]
                )
                command_output(
                    ["git", "fetch", "--depth=1", "origin", revision], cwd=checkout
                )
                self.sources[name] = checkout
                try:
                    self.validate_source(name)
                    checkout.rename(repository)
                except BaseException:
                    self.sources.pop(name, None)
                    raise
                self.sources[name] = repository

    def describe(self) -> None:
        print(f"upstream: {self.options.upstream}")
        print(f"ohm: {self.options.ohm}")
        print(f"output: {self.output}")
        repetitions = (
            self.options.cold_runs
            + self.options.noop_runs
            + self.options.dependency_runs
            + self.options.direct_runs
        )
        core_samples = len(self.workloads) * len(WORKFLOWS) * 2 * repetitions
        feature_samples = len(self.workloads) * 4
        feature_samples += sum(
            2 * (self.options.noop_runs + self.options.direct_runs)
            for workload in self.workloads
            if workload.repository == "codex"
        )
        for workload in self.workloads:
            name = workload.repository
            source = self.sources.get(name, self.source_urls[name])
            print(f"\n{workload.name}: {source}")
            print(f"  revision: {self.revisions[name]}")
            print(f"  dependency edit: {workload.dependency.path}")
            print(f"  direct edit: {workload.direct.path}")
            print(f"  workflows: {', '.join(WORKFLOWS)}")
            print("  feature workflows: " + ", ".join(self.feature_workflows(workload)))
            print(f"  selected test: {workload.selected_test}")
        print(f"\ncore timed samples: {core_samples}")
        print(f"feature timed samples: {feature_samples}")
        print(f"timed samples: {core_samples + feature_samples}")

    @staticmethod
    def feature_workflows(workload: Workload) -> tuple[str, ...]:
        return tuple(
            workflow
            for workflow in FEATURE_WORKFLOWS
            if workflow != "fmt" or workload.repository == "codex"
        )

    def check_disk(self) -> None:
        candidate = self.output
        while not candidate.exists():
            candidate = candidate.parent
        free = shutil.disk_usage(candidate).free
        minimum = self.options.minimum_free_gb * 1024**3
        if free < minimum:
            raise BenchmarkError(
                f"only {free / 1024**3:.1f} GiB available; "
                f"at least {self.options.minimum_free_gb} GiB required"
            )

    @contextlib.contextmanager
    def managed_worktrees(self) -> Iterator[None]:
        with contextlib.ExitStack() as cleanup:
            for name, repository in self.sources.items():
                for label, _ in self.toolchains:
                    path = self.output / "worktrees" / name / label
                    path.parent.mkdir(parents=True, exist_ok=True)
                    command_output(
                        [
                            "git",
                            "worktree",
                            "add",
                            "--detach",
                            str(path),
                            self.revisions[name],
                        ],
                        cwd=repository,
                    )
                    cleanup.callback(
                        command_output,
                        ["git", "worktree", "remove", "--force", str(path)],
                        cwd=repository,
                    )
                    self.worktrees[name, label] = path
            yield

    @contextlib.contextmanager
    def managed_shared_worktrees(self, workload: Workload) -> Iterator[dict[str, Path]]:
        repository = self.sources[workload.repository]
        worktrees: dict[str, Path] = {}
        with contextlib.ExitStack() as cleanup:
            for label, _ in self.toolchains:
                path = (
                    self.output / "worktrees" / workload.repository / f"{label}-shared"
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                command_output(
                    [
                        "git",
                        "worktree",
                        "add",
                        "--detach",
                        str(path),
                        self.revisions[workload.repository],
                    ],
                    cwd=repository,
                )
                cleanup.callback(
                    command_output,
                    ["git", "worktree", "remove", "--force", str(path)],
                    cwd=repository,
                )
                worktrees[label] = path
            yield worktrees

    def command(self, workload: Workload, workflow: str, selector: str) -> list[str]:
        target = (
            ["--test", "it"]
            if workload.repository == "uv" and workflow == "test"
            else ["--lib"]
        )
        arguments = ["-p", workload.package, *target, "--locked", "--offline"]
        if workflow == "fmt":
            return [
                "cargo",
                f"+{selector}",
                "fmt",
                "--",
                "--config",
                "imports_granularity=Item",
                "--check",
            ]
        if workflow == "build-check":
            return ["cargo", f"+{selector}", "check", *arguments]
        if workflow == "shared-build":
            return ["cargo", f"+{selector}", "build", *arguments]
        if workload.repository == "uv":
            command = ["cargo", f"+{selector}", workflow, *arguments]
            if workflow == "test":
                command.extend([workload.selected_test, "--", "--exact"])
            return command
        if workflow == "check":
            return ["cargo", f"+{selector}", workflow, *arguments]
        if workflow == "clippy":
            return ["just", "clippy", "-p", workload.package, "--locked", "--offline"]
        return [
            "just",
            "test",
            *arguments,
            "--no-tests",
            "fail",
            workload.selected_test,
        ]

    def target(self, workload: Workload, workflow: str, label: str) -> Path:
        return self.output / "targets" / workload.name / workflow / label

    def reset_target(self, workload: Workload, workflow: str, label: str) -> None:
        target = self.target(workload, workflow, label)
        root = (self.output / "targets").resolve()
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise BenchmarkError(
                f"refusing to remove unsafe benchmark target: {target}"
            )
        if not target.is_dir():
            raise BenchmarkError(
                f"previous cold benchmark target does not exist: {target}"
            )
        shutil.rmtree(target)

    def ordered_toolchains(self, index: int) -> tuple[tuple[str, str], ...]:
        return toolchain_order(self.toolchains, index)

    def wait_until_idle(self, *, quiet_seconds: int = 0) -> None:
        active = competing_processes()
        if not active and quiet_seconds == 0:
            return
        if active:
            print(
                "Waiting for unrelated compiler processes: " + ", ".join(active),
                flush=True,
            )
        deadline = time.monotonic() + self.options.idle_timeout
        idle_since: float | None = None if active else time.monotonic()
        while time.monotonic() < deadline:
            time.sleep(0.5)
            if competing_processes():
                idle_since = None
                continue
            now = time.monotonic()
            if idle_since is None:
                idle_since = now
            elif now - idle_since >= max(2, quiet_seconds):
                return
        raise BenchmarkError("timed out waiting for unrelated compiler processes")

    def execute(
        self,
        workload: Workload,
        workflow: str,
        label: str,
        selector: str,
        *,
        phase: str,
        repetition: int,
        expected_crate: str | None,
        record: bool = True,
        arguments: list[str] | None = None,
        worktree: Path | None = None,
        target_directory: Path | None = None,
        extra_environment: dict[str, str] | None = None,
    ) -> None:
        self.check_disk()
        if self.options.require_idle:
            self.wait_until_idle()
        if worktree is None:
            worktree = self.worktrees[workload.repository, label]
        directory = (
            self.target(workload, workflow, label)
            if target_directory is None
            else target_directory
        )
        directory.mkdir(parents=True, exist_ok=True)
        if arguments is None:
            arguments = self.command(workload, workflow, selector)
        workspace = worktree / workload.workspace
        cwd = worktree if arguments[0] == "just" else workspace
        environment = os.environ.copy()
        environment.pop("CARGO_BUILD_BUILD_DIR", None)
        if workflow == "fmt":
            environment.pop("RUSTFMT", None)
            environment.pop("RUSTFMT_WRAPPER", None)
        environment.update(
            {
                "CARGO_TARGET_DIR": str(directory),
                "CARGO_BUILD_JOBS": str(self.options.jobs),
                "CARGO_INCREMENTAL": "1",
                "CARGO_TERM_COLOR": "never",
                "RUSTUP_TOOLCHAIN": selector,
            }
        )
        if extra_environment is not None:
            environment.update(extra_environment)
        configure_ready_tests(environment, label)
        identifier = (
            f"{len(self.samples) + 1:04d}-{workload.name}-{workflow}-{phase}-{label}"
        )
        log = self.output / "logs" / f"{identifier}.log"
        print(
            f"{workload.name} {workflow} {phase} {label}: {' '.join(arguments)}",
            flush=True,
        )
        interference: list[str] = []
        monitor_errors: list[str] = []
        stop_monitor = threading.Event()

        def monitor_compilers() -> None:
            while not stop_monitor.wait(0.5):
                try:
                    active = competing_processes()
                except BenchmarkError as error:
                    monitor_errors.append(str(error))
                    return
                if active:
                    interference.extend(active)
                    return

        monitor: threading.Thread | None = None
        if self.options.require_idle:
            monitor = threading.Thread(target=monitor_compilers, daemon=True)
            monitor.start()
        started = time.perf_counter()
        try:
            result = subprocess.run(
                arguments,
                cwd=cwd,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.options.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            captured = error.output or ""
            if isinstance(captured, bytes):
                captured = captured.decode(errors="replace")
            if cache_contention_only(captured):
                raise ContaminatedBenchmarkError(
                    "benchmark timed out during Cargo package or target cache contention"
                ) from error
            raise BenchmarkError(f"benchmark command failed: {error}") from error
        except OSError as error:
            raise BenchmarkError(f"benchmark command failed: {error}") from error
        finally:
            duration = time.perf_counter() - started
            stop_monitor.set()
            if monitor is not None:
                monitor.join()
        log.write_text(result.stdout, encoding="utf-8")

        failure: str | None = None
        cache_contention = False
        if monitor_errors:
            failure = "compiler interference monitor failed: " + monitor_errors[0]
        elif self.options.require_idle and not interference:
            try:
                interference = competing_processes()
            except BenchmarkError as error:
                failure = f"compiler interference monitor failed: {error}"
        if failure is None and result.returncode:
            if cache_contention_only(result.stdout):
                failure = (
                    "benchmark encountered Cargo package or target cache contention; "
                    f"inspect {log}"
                )
                cache_contention = True
            else:
                failure = f"benchmark command exited {result.returncode}; inspect {log}"
        elif failure is None:
            try:
                validate_output(
                    result.stdout,
                    expected_crate=expected_crate,
                    selected_test=workload.selected_test
                    if workflow == "test"
                    else None,
                )
            except BenchmarkError as error:
                failure = f"{error}; inspect {log}"
                cache_contention = isinstance(error, ContaminatedBenchmarkError)
        contaminated = cache_contention or (failure is None and bool(interference))
        if contaminated and failure is None:
            failure = "unrelated compiler overlapped benchmark: " + ", ".join(
                interference
            )

        if record:
            sample = {
                "project": workload.name,
                "workflow": workflow,
                "phase": phase,
                "toolchain": label,
                "selector": selector,
                "repetition": repetition,
                "wall_seconds": duration,
                "returncode": result.returncode,
                "external_compilation": interference,
                "valid": failure is None,
                "command": arguments,
                "target_directory": str(directory),
                "log": str(log),
            }
            if workflow == "shared-build":
                sample["package"] = workload.package
                sample["worktree"] = str(worktree)
                sample["shared_build_directory"] = environment["CARGO_BUILD_BUILD_DIR"]
            elif workflow == "build-check" and label.startswith("ohm"):
                sample["registry_build_ready"] = (
                    directory / ".ohm-built-registry-ready"
                ).is_file()
            self.samples.append(sample)
            self.write_results()
        if failure is not None:
            if contaminated:
                raise ContaminatedBenchmarkError(failure)
            raise BenchmarkError(failure)
        print(f"  {duration:.3f}s", flush=True)

    def run_edits(self, workload: Workload, workflow: str, *, direct: bool) -> None:
        edit = workload.direct if direct else workload.dependency
        phase = "direct" if direct else "dependency"
        count = self.options.direct_runs if direct else self.options.dependency_runs
        with contextlib.ExitStack() as cleanup:
            edits = {
                label: cleanup.enter_context(
                    reversible_edit(self.worktrees[workload.repository, label], edit)
                )
                for label, _ in self.toolchains
            }
            for repetition in range(count):
                for label, selector in self.ordered_toolchains(repetition):
                    edits[label](repetition % 2 == 0)
                    self.execute(
                        workload,
                        workflow,
                        label,
                        selector,
                        phase=phase,
                        repetition=repetition,
                        expected_crate=edit.crate,
                    )

    def run_build_check(self, workload: Workload, index: int) -> None:
        workflow = "build-check"
        for label, selector in self.ordered_toolchains(index):
            self.execute(
                workload,
                workflow,
                label,
                selector,
                phase="seed",
                repetition=0,
                expected_crate=workload.package,
                record=False,
                arguments=self.command(workload, "shared-build", selector),
            )
        for label, selector in self.ordered_toolchains(index):
            self.execute(
                workload,
                workflow,
                label,
                selector,
                phase="transition",
                repetition=0,
                expected_crate=workload.package,
            )

    def run_format(self, workload: Workload, index: int) -> None:
        workflow = "fmt"
        environments = {
            label: {
                "CARGO_NET_OFFLINE": "true",
                "OHM_INCREMENTAL_FMT_CACHE_DIR": str(
                    self.target(workload, workflow, label) / "formatter-cache"
                ),
            }
            for label, _ in self.toolchains
        }
        for label, selector in self.ordered_toolchains(index):
            self.execute(
                workload,
                workflow,
                label,
                selector,
                phase="warmup",
                repetition=0,
                expected_crate=None,
                record=False,
                extra_environment=environments[label],
            )
            if label.startswith("ohm"):
                cache = Path(environments[label]["OHM_INCREMENTAL_FMT_CACHE_DIR"])
                if not any(path.is_file() for path in cache.glob("*.json")):
                    raise BenchmarkError(
                        "Ohm incremental formatting did not publish a cache snapshot: "
                        f"{cache}"
                    )
        for repetition in range(self.options.noop_runs):
            for label, selector in self.ordered_toolchains(index + repetition):
                self.execute(
                    workload,
                    workflow,
                    label,
                    selector,
                    phase="noop",
                    repetition=repetition,
                    expected_crate=None,
                    extra_environment=environments[label],
                )

        with contextlib.ExitStack() as cleanup:
            edits = {
                label: cleanup.enter_context(
                    reversible_edit(
                        self.worktrees[workload.repository, label], workload.direct
                    )
                )
                for label, _ in self.toolchains
            }
            for repetition in range(self.options.direct_runs):
                for label, selector in self.ordered_toolchains(index + repetition):
                    edits[label](repetition % 2 == 0)
                    self.execute(
                        workload,
                        workflow,
                        label,
                        selector,
                        phase="direct",
                        repetition=repetition,
                        expected_crate=None,
                        extra_environment=environments[label],
                    )

    def run_shared_build(self, workload: Workload, index: int) -> None:
        # Exercise a real workspace member without root-only native allocators,
        # keeping released and future toolchains directly comparable.
        workload = dataclasses.replace(
            workload, package=workload.dependency.crate, direct=workload.dependency
        )
        workflow = "shared-build"
        # Keep both arms on the same rustup proxy and trusted system tools; an
        # unrelated virtualenv CMake wrapper must not disable registry sharing.
        cargo = shutil.which("cargo")
        if cargo is None or not Path(cargo).is_absolute():
            raise BenchmarkError("shared builds require an absolute Cargo executable")
        executable_path = os.pathsep.join(
            dict.fromkeys((str(Path(cargo).parent), "/usr/bin", "/bin"))
        )
        with self.managed_shared_worktrees(workload) as worktrees:
            for label, selector in self.ordered_toolchains(index):
                root = self.target(workload, workflow, label)
                # Stock Cargo cannot safely share workspace artifacts between
                # worktrees, so match Ohm's correctness with private roots.
                build_directory = root / (
                    "shared-build" if label.startswith("ohm") else "primary-build"
                )
                self.execute(
                    workload,
                    workflow,
                    label,
                    selector,
                    phase="seed",
                    repetition=0,
                    expected_crate=workload.package,
                    record=False,
                    target_directory=root / "primary-target",
                    extra_environment={
                        "CARGO_BUILD_BUILD_DIR": str(build_directory),
                        "PATH": executable_path,
                    },
                )
                if label.startswith("ohm"):
                    marker = build_directory / ".ohm-shared-registry-cache-v1"
                    registries = build_directory / "debug" / "build" / "registries"
                    if not marker.is_file() or not registries.is_dir():
                        raise BenchmarkError(
                            "Ohm shared registry caching did not publish immutable "
                            f"artifacts: {build_directory}"
                        )
            with contextlib.ExitStack() as cleanup:
                for label, _ in self.toolchains:
                    edit = cleanup.enter_context(
                        reversible_edit(worktrees[label], workload.direct)
                    )
                    edit(True)
                for label, selector in self.ordered_toolchains(index):
                    root = self.target(workload, workflow, label)
                    build_directory = root / (
                        "shared-build" if label.startswith("ohm") else "secondary-build"
                    )
                    self.execute(
                        workload,
                        workflow,
                        label,
                        selector,
                        phase="reuse",
                        repetition=0,
                        expected_crate=workload.package,
                        worktree=worktrees[label],
                        target_directory=root / "secondary-target",
                        extra_environment={
                            "CARGO_BUILD_BUILD_DIR": str(build_directory),
                            "PATH": executable_path,
                        },
                    )

    def run_workflow(self, workload: Workload, workflow: str, index: int) -> None:
        if workflow == "build-check":
            self.run_build_check(workload, index)
            return
        if workflow == "fmt":
            self.run_format(workload, index)
            return
        if workflow == "shared-build":
            self.run_shared_build(workload, index)
            return
        for phase, count in (
            ("cold", self.options.cold_runs),
            ("noop", self.options.noop_runs),
        ):
            for repetition in range(count):
                for label, selector in self.ordered_toolchains(index + repetition):
                    if phase == "cold" and repetition > 0:
                        self.reset_target(workload, workflow, label)
                    self.execute(
                        workload,
                        workflow,
                        label,
                        selector,
                        phase=phase,
                        repetition=repetition,
                        expected_crate=None,
                    )
        self.run_edits(workload, workflow, direct=False)
        for label, selector in self.toolchains:
            self.execute(
                workload,
                workflow,
                label,
                selector,
                phase="warmup",
                repetition=0,
                expected_crate=None,
                record=False,
            )
        self.run_edits(workload, workflow, direct=True)

    def run_workflow_with_retries(
        self, workload: Workload, workflow: str, index: int
    ) -> None:
        for attempt in range(self.options.contention_retries + 1):
            if self.options.require_idle:
                self.wait_until_idle(quiet_seconds=self.options.quiet_seconds)
            first_sample = len(self.samples)
            try:
                self.run_workflow(workload, workflow, index)
            except ContaminatedBenchmarkError as error:
                reason = (
                    "discarded entire workflow attempt because a measurement "
                    f"was contaminated: {error}"
                )
                for sample in self.samples[first_sample:]:
                    sample["valid"] = False
                    sample["discard_reason"] = reason
                self.write_results()
                if attempt >= self.options.contention_retries:
                    raise
                print(
                    f"Restarting {workload.name} {workflow} from cold after "
                    f"measurement contamination (retry {attempt + 1}/"
                    f"{self.options.contention_retries})",
                    flush=True,
                )
                for label, _ in self.toolchains:
                    target = self.target(workload, workflow, label)
                    if target.exists() or target.is_symlink():
                        self.reset_target(workload, workflow, label)
            else:
                if self.options.discard_targets:
                    for label, _ in self.toolchains:
                        self.reset_target(workload, workflow, label)
                return

    def comparisons(self) -> list[dict[str, object]]:
        grouped: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
        for sample in self.samples:
            if sample["valid"]:
                key = (
                    str(sample["project"]),
                    str(sample["workflow"]),
                    str(sample["phase"]),
                    str(sample["toolchain"]),
                )
                grouped[key].append(float(sample["wall_seconds"]))
        rows = []
        for workload in self.workloads:
            for workflow in (*WORKFLOWS, *self.feature_workflows(workload)):
                for phase in WORKFLOW_PHASES[workflow]:
                    stock = grouped.get((workload.name, workflow, phase, "stock"))
                    ohm = grouped.get((workload.name, workflow, phase, "ohm"))
                    if stock and ohm:
                        stock_median = statistics.median(stock)
                        ohm_median = statistics.median(ohm)
                        rows.append(
                            {
                                "project": workload.name,
                                "workflow": workflow,
                                "phase": phase,
                                "stock_seconds": stock_median,
                                "ohm_seconds": ohm_median,
                                "speedup": stock_median / ohm_median,
                                "samples": min(len(stock), len(ohm)),
                            }
                        )
        return rows

    def write_results(self) -> None:
        comparisons = self.comparisons()
        payload = {
            "metadata": self.metadata,
            "samples": self.samples,
            "comparisons": comparisons,
        }
        (self.output / "results.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        lines = ["# Ohm benchmark results", ""]
        for workload in self.workloads:
            rows = [row for row in comparisons if row["project"] == workload.name]
            if not rows:
                continue
            lines.extend(
                [
                    f"## {workload.name}",
                    "",
                    "| Workflow | Phase | Stock | Ohm | Speedup | Samples |",
                    "| --- | --- | ---: | ---: | ---: | ---: |",
                ]
            )
            for row in rows:
                lines.append(
                    f"| {row['workflow']} | {row['phase']} | "
                    f"{row['stock_seconds']:.3f}s | {row['ohm_seconds']:.3f}s | "
                    f"{row['speedup']:.2f}× | {row['samples']} |"
                )
            lines.append("")
        (self.output / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    def run(self) -> None:
        self.check_disk()
        if self.output.exists() and any(self.output.iterdir()):
            raise BenchmarkError(
                f"output directory is not empty: {self.output}; choose a new --output-dir"
            )
        (self.output / "logs").mkdir(parents=True, exist_ok=True)
        self.prepare_sources()
        self.metadata = {
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "jobs": self.options.jobs,
            "discard_targets": self.options.discard_targets,
            "compare_ready_tests": self.options.compare_ready_tests,
            "toolchains": {
                label: {
                    "selector": selector,
                    "cargo": command_output(
                        ["cargo", f"+{selector}", "--version", "--verbose"]
                    ),
                    "rustc": command_output(
                        ["rustc", f"+{selector}", "--version", "--verbose"]
                    ),
                }
                for label, selector in self.toolchains
            },
            "repositories": {
                name: {
                    "path": str(repository),
                    "url": self.source_urls[name],
                    "revision": self.revisions[name],
                }
                for name, repository in self.sources.items()
            },
            "repetitions": {
                "cold": self.options.cold_runs,
                "noop": self.options.noop_runs,
                "dependency": self.options.dependency_runs,
                "direct": self.options.direct_runs,
            },
            "feature_workflows": {
                workload.name: self.feature_workflows(workload)
                for workload in self.workloads
            },
        }
        self.write_results()
        with self.managed_worktrees():
            core = [
                (workload, workflow)
                for workload in self.workloads
                for workflow in WORKFLOWS
            ]
            features = [
                (workload, workflow)
                for workload in self.workloads
                for workflow in self.feature_workflows(workload)
            ]
            for index, (workload, workflow) in enumerate((*core, *features)):
                self.run_workflow_with_retries(workload, workflow, index)
        self.metadata["finished_at"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        self.write_results()
        print(f"\nResults: {self.output / 'results.json'}")
        print(f"Summary: {self.output / 'summary.md'}")


def main() -> int:
    try:
        options = parser().parse_args()
        study = Study(options)
        if options.dry_run:
            study.describe()
        else:
            study.run()
        return 0
    except BenchmarkError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
