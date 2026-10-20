#!/usr/bin/env python3
"""Measure short developer workflows with continuous, isolated Cargo state."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import threading
import time

import replay_sessions as replay
from benchmark import BenchmarkError, Edit, REPOSITORIES, WORKLOADS, edit_contents


@dataclasses.dataclass(frozen=True)
class Workflow:
    label: str
    edit: str | None
    warmup: tuple[str, ...]
    commands: tuple[str, ...]


WORKFLOWS = {
    "edit-test": Workflow("Edit → focused test", "direct", ("test",), ("test",)),
    "dependency-test": Workflow(
        "Edit dependency → downstream test", "dependency", ("test",), ("test",)
    ),
    "edit-check-test-check": Workflow(
        "Edit → check → test → check",
        "direct",
        ("check", "test", "check"),
        ("check", "test", "check"),
    ),
    "check-build-check": Workflow(
        "Check → build → check", None, ("check",), ("check", "build", "check")
    ),
    "edit-fmt-clippy-test": Workflow(
        "Edit → fmt → clippy → test",
        "direct",
        ("fmt", "clippy", "test"),
        ("fmt", "clippy", "test"),
    ),
}


def project_definitions():
    projects = {}
    for project, workload in (
        ("uv", WORKLOADS["uv"]),
        ("codex", WORKLOADS["codex-core"]),
    ):
        common = ["-p", workload.package, "--lib", "--locked"]
        test = (
            [
                "test",
                "-p",
                "uv",
                "--test",
                "it",
                "--locked",
                "help::help",
                "--",
                "--exact",
            ]
            if project == "uv"
            else ["nextest", "run", *common, "-E", f"test({workload.selected_test})"]
        )
        projects[project] = {
            "label": "uv" if project == "uv" else "Codex",
            "repository": REPOSITORIES[project]["url"],
            "revision": REPOSITORIES[project]["revision"],
            "workspace": workload.workspace,
            "package": workload.package,
            "environment": {},
            "edits": {
                kind: dataclasses.asdict(getattr(workload, kind))
                for kind in ("direct", "dependency")
            },
            "commands": {
                "check": ["check", *common],
                "build": ["build", *common],
                "test": test,
                "clippy": ["clippy", *common],
                "fmt": [
                    "fmt",
                    "-p",
                    workload.package,
                    "--",
                    *(
                        ["--config", "imports_granularity=Item"]
                        if project == "codex"
                        else []
                    ),
                ],
            },
        }
    projects["ruff"] = {
        "label": "Ruff/ty",
        "repository": "https://github.com/astral-sh/ruff.git",
        "revision": "4d6a7db787130c5a4a95bd835369babd78e4a1f6",
        "workspace": ".",
        "package": "ty_python_semantic",
        "environment": {
            "CARGO_PROFILE_DEV_OPT_LEVEL": "1",
            "CARGO_PROFILE_DEV_LTO": "off",
            "CARGO_PROFILE_DEV_DEBUG": "line-tables-only",
        },
        "edits": {
            "direct": dataclasses.asdict(
                Edit(
                    "crates/ty_python_semantic/src/types.rs",
                    "DynamicType::Unknown\n                    | DynamicType::UnknownGeneric(_)",
                    "DynamicType::UnknownGeneric(_)\n                    | DynamicType::Unknown",
                    "ty_python_semantic",
                )
            ),
            "dependency": dataclasses.asdict(
                Edit(
                    "crates/ty_python_core/src/platform.rs",
                    "_ => PythonPlatform::Identifier(platform.clone()),",
                    "_ => PythonPlatform::Identifier(platform),",
                    "ty_python_core",
                )
            ),
        },
        "commands": {
            **{
                name: [name, "-p", "ty_python_semantic", "--lib", "--locked"]
                for name in ("check", "build", "clippy")
            },
            "test": [
                "nextest",
                "run",
                "-p",
                "ty_python_semantic",
                "--test",
                "mdtest",
                "--locked",
                "-E",
                "test(=mdtest::liskov.md)",
            ],
            "fmt": ["fmt", "-p", "ty_python_semantic", "--"],
        },
    }
    return {name: projects[name] for name in ("ruff", "uv", "codex")}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def cpu_evidence(path):
    data = path.read_bytes() if path.exists() else b""
    samples = [json.loads(line) for line in data.splitlines()]
    return {
        "path": str(path),
        "sha256": sha256(data) if data else None,
        "intervals": len(samples),
        "maximum_external_percent": max(
            (sample["external_percent"] for sample in samples), default=0
        ),
    }


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def cpu_snapshot():
    """Read host CPU counters and process identities without collecting arguments."""
    cpu = list(map(int, Path("/proc/stat").read_text().splitlines()[0].split()[1:9]))
    processes = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            text = path.read_text()
            end = text.rindex(")")
            fields = text[end + 2 :].split()
            processes[int(path.parent.name)] = {
                "name": text[text.index("(") + 1 : end],
                "parent": int(fields[1]),
                "ticks": int(fields[11]) + int(fields[12]),
                "children_ticks": int(fields[13]) + int(fields[14]),
                "start": int(fields[19]),
            }
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return cpu, processes


def cpu_interval(previous, current, owner):
    before, old_processes = previous
    after, processes = current
    elapsed = sum(after) - sum(before)
    if elapsed <= 0:
        raise BenchmarkError("host CPU counters did not advance")

    def owned(pid, snapshot):
        visited = set()
        while pid in snapshot and pid not in visited:
            if pid == owner:
                return True
            visited.add(pid)
            pid = snapshot[pid]["parent"]
        return pid == owner

    def own_ticks(snapshot):
        # Reaped children move into their parent's counters; live descendants
        # still have their own counters. Count both at each snapshot boundary.
        return sum(
            process["ticks"] + process.get("children_ticks", 0)
            for pid, process in snapshot.items()
            if owned(pid, snapshot)
        )

    own = max(0, own_ticks(processes) - own_ticks(old_processes))
    busy = elapsed - sum(after[index] - before[index] for index in (3, 4, 7))
    external = []
    for pid, process in processes.items():
        old = old_processes.get(pid)
        if old and old["start"] == process["start"] and not owned(pid, processes):
            ticks = max(0, process["ticks"] - old["ticks"])
            if ticks:
                external.append(
                    {
                        "pid": pid,
                        "name": process["name"],
                        "percent": 100 * ticks / elapsed,
                    }
                )
    return {
        "time": time.time(),
        "idle_percent": 100 * (after[3] - before[3]) / elapsed,
        "iowait_percent": 100 * (after[4] - before[4]) / elapsed,
        "steal_percent": 100 * (after[7] - before[7]) / elapsed,
        "owned_percent": 100 * own / elapsed,
        # Host counters also capture external work that exits between snapshots.
        "external_percent": 100 * max(0, busy - own) / elapsed,
        "external_processes": sorted(
            external, key=lambda row: row["percent"], reverse=True
        )[:8],
    }


class HostMonitor:
    def __init__(self, path, enabled):
        self.path = path
        self.enabled = enabled
        self.stop = threading.Event()
        self.failure = None
        self.samples = []
        self.thread = None
        self.previous = None

    def __enter__(self):
        if self.enabled:
            self.previous = cpu_snapshot()
            self.thread = threading.Thread(target=self.watch, daemon=True)
            self.thread.start()
        return self

    def watch(self):
        try:
            previous = self.previous
            noisy = 0
            with self.path.open("w") as trace:
                while True:
                    stopped = self.stop.wait(2)
                    current = cpu_snapshot()
                    sample = cpu_interval(previous, current, os.getpid())
                    sample["final_interval"] = stopped
                    previous = current
                    self.samples.append(sample)
                    trace.write(json.dumps(sample) + "\n")
                    trace.flush()
                    if not stopped:
                        noisy = noisy + 1 if sample["external_percent"] > 5 else 0
                    if noisy >= 3 or sample["steal_percent"] > 0.1:
                        self.failure = (
                            "host CPU contention exceeded the measurement limits"
                        )
                    if stopped:
                        break
        except Exception as error:
            self.failure = f"host CPU monitor failed: {error}"

    def __exit__(self, *_):
        self.stop.set()
        if self.thread:
            self.thread.join()


class WorkflowStudy(replay.Replay):
    def __init__(self, options):
        self.definitions = project_definitions()
        self.workflows = options.workflow or list(WORKFLOWS)
        self.discarded = []
        self.failures = []
        self.case_context = {}
        self.metadata = {}
        self.monitor = None
        self.timed = False
        defaults = vars(
            replay.parser().parse_args(["--output-dir", str(options.output_dir)])
        )
        defaults.update(vars(options))
        defaults.update(
            feature_matrix=False,
            no_shared_build=False,
            native_tool_trust="all",
            offline=True,
        )
        super().__init__(argparse.Namespace(**defaults))
        if len(set(self.workflows)) != len(self.workflows):
            raise BenchmarkError("workflows must not be repeated")
        if self.options.quiet_seconds < 0 or self.options.contention_retries < 0:
            raise BenchmarkError("quiet seconds and retries must be nonnegative")

    def select_scenarios(self):
        selected = self.options.project or list(self.definitions)
        if len(selected) != len(set(selected)):
            raise BenchmarkError("projects must not be repeated")
        return [
            replay.Scenario(
                path=Path(__file__).resolve(),
                project=name,
                repository=self.definitions[name]["repository"],
                base_revision=self.definitions[name]["revision"],
                fetch_refs=(),
                environment={
                    **self.definitions[name]["environment"],
                    "CARGO_INCREMENTAL": "1",
                    "CARGO_TERM_COLOR": "never",
                    "INSTA_FORCE_PASS": "0",
                    "INSTA_UPDATE": "no",
                    "MDTEST_UPDATE_SNAPSHOTS": "0",
                    "GIT_CONFIG_COUNT": "2",
                    "GIT_CONFIG_KEY_0": "maintenance.auto",
                    "GIT_CONFIG_VALUE_0": "false",
                    "GIT_CONFIG_KEY_1": "gc.auto",
                    "GIT_CONFIG_VALUE_1": "0",
                },
                session={"id": "developer-workflows"},
                warmup=(),
                steps=(),
            )
            for name in selected
        ]

    def configuration(self):
        return {
            "toolchains": dict(self.toolchains),
            "jobs": self.options.jobs,
            "repetitions": self.options.repetitions,
            "require_idle": self.options.require_idle,
            "quiet_seconds": self.options.quiet_seconds,
            "idle_preflight": "after_warmup",
            "source_normalization": "ohm_rustfmt_before_warmup",
            "cpu_accounting": "host_busy_minus_process_tree",
            "failure_policy": "record_and_continue",
            "timeout": self.options.timeout,
            "projects": {
                s.project: self.definitions[s.project] for s in self.scenarios
            },
            "workflows": {
                key: dataclasses.asdict(WORKFLOWS[key]) for key in self.workflows
            },
            "runner_sha256": {
                name: sha256(Path(__file__).with_name(name).read_bytes())
                for name in (
                    "benchmark_workflows.py",
                    "replay_sessions.py",
                    "benchmark.py",
                )
            },
        }

    def restore_results(self):
        result = json.loads((self.output / "results.json").read_text())
        if result["configuration"] != json.loads(json.dumps(self.configuration())):
            raise BenchmarkError(
                "cannot resume with different sources, commands, settings, or runner code"
            )
        self.samples = result["samples"]
        self.discarded = result["discarded"]
        self.failures = result.get("failures", [])
        self.metadata = result["metadata"]

    def persist(self):
        self.output.mkdir(parents=True, exist_ok=True)
        write_json(
            self.output / "results.json",
            {
                "benchmark": "developer-workflows",
                "configuration": self.configuration(),
                "metadata": self.metadata,
                "samples": self.samples,
                "failures": self.failures,
                "discarded": self.discarded,
            },
        )

    def command_step(self, project, name):
        definition = self.definitions[project]
        return {
            "kind": "command",
            "label": name,
            "program": "cargo",
            "args": definition["commands"][name],
            "cwd": definition["workspace"],
        }

    def environment(self, scenario, label, selector, repetition):
        environment = super().environment(scenario, label, selector, repetition)
        for key in list(environment):
            if key.startswith("CARGO_PROFILE_") or key in {
                "RUSTC",
                "RUSTDOC",
                "RUSTC_WRAPPER",
                "RUSTC_WORKSPACE_WRAPPER",
                "RUSTFMT",
                "RUSTFMT_WRAPPER",
                "CARGO_BUILD_TARGET",
                "CARGO_BUILD_RUSTFLAGS",
                "CARGO_BUILD_RUSTC_WRAPPER",
                "LD_LIBRARY_PATH",
                "LIBRARY_PATH",
            }:
                environment.pop(key)
        environment.update(scenario.environment)
        return environment

    def run_command(self, *args, **kwargs):
        if self.monitor and self.monitor.failure:
            raise BenchmarkError(self.monitor.failure)
        failure = None
        try:
            sample = super().run_command(*args, **kwargs)
        except BenchmarkError as error:
            if not hasattr(error, "command_sample"):
                raise
            sample = error.command_sample
            failure = error
        if self.monitor and self.monitor.failure:
            raise BenchmarkError(self.monitor.failure)
        sample["log_sha256"] = sha256(Path(sample["log"]).read_bytes())
        sample.update(
            name=args[2]["label"], phase=kwargs.get("phase", "session"), index=args[6]
        )
        if failure:
            if sample["phase"] == "warmup" and sample["index"] == 0:
                raise BenchmarkError(
                    f"source normalization failed; inspect {sample['log']}"
                ) from failure
            if sample["external_compilation"]:
                raise BenchmarkError("unrelated compiler overlapped failed command")
            raise failure
        if args[2]["label"] == "test" and sample["tests_started"] != 1:
            raise BenchmarkError("focused workflow must execute exactly one test")
        return sample

    def preflight(self):
        if not self.options.require_idle:
            return []
        self.wait_until_idle()
        deadline = time.monotonic() + self.options.idle_timeout
        samples = []
        previous = cpu_snapshot()
        quiet_since = time.monotonic()
        while time.monotonic() - quiet_since < self.options.quiet_seconds:
            if time.monotonic() > deadline:
                raise BenchmarkError("timed out waiting for an idle host")
            time.sleep(2)
            current = cpu_snapshot()
            sample = cpu_interval(previous, current, os.getpid())
            previous = current
            samples.append(sample)
            if (
                sample["idle_percent"] < 95
                or sample["iowait_percent"] > 0.5
                or sample["steal_percent"] > 0.1
                or replay.competing_processes()
            ):
                quiet_since = time.monotonic()
                samples.clear()
        return samples

    def wait_until_idle(self):
        if self.timed:
            if self.options.require_idle and replay.competing_processes():
                raise BenchmarkError("unrelated compiler appeared during the workflow")
        else:
            super().wait_until_idle()

    def run_case(self, scenario, workflow_id, label, selector, repetition, attempt):
        self.case_context = {}
        self.check_disk()
        workflow = WORKFLOWS[workflow_id]
        cell = f"{workflow_id}-{repetition}-{attempt}"
        worktree = self.output / "worktrees" / scenario.project / label / cell
        if worktree.exists():
            raise BenchmarkError(f"sample worktree already exists: {worktree}")
        worktree.parent.mkdir(parents=True, exist_ok=True)
        source = self.sources[scenario.project]
        replay.command_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=source,
        )
        replay.command_output(
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
        environment = self.environment(scenario, label, selector, cell)
        if Path(environment["CARGO_TARGET_DIR"]).exists():
            raise BenchmarkError("sample target directory must start empty")
        print(
            f"\n{scenario.project} / {workflow_id} / {label} / repetition {repetition + 1}",
            flush=True,
        )

        # Use one formatter to give both lanes identical source before warming.
        formatting = self.command_step(scenario.project, "fmt")
        normalization = self.run_command(
            scenario,
            worktree,
            formatting,
            label,
            self.options.ohm,
            cell,
            0,
            phase="warmup",
        )
        baseline = replay.command_output(["git", "diff", "--binary"], cwd=worktree)
        self.case_context["baseline_diff_sha256"] = sha256(baseline.encode())
        warmups = []
        for index, name in enumerate(workflow.warmup, 1):
            print(f"  warmup: {name}", flush=True)
            warmups.append(
                self.run_command(
                    scenario,
                    worktree,
                    self.command_step(scenario.project, name),
                    label,
                    selector,
                    cell,
                    index,
                    phase="warmup",
                )
                | {"name": name}
            )
        print("  Waiting for an idle host after warmup", flush=True)
        preflight = self.preflight()
        self.case_context["preflight"] = preflight
        cpu_path = self.output / "logs" / scenario.project / label / cell / "cpu.jsonl"
        command_failure = None
        with HostMonitor(cpu_path, self.options.require_idle) as monitor:
            self.monitor = monitor
            try:
                edit = None
                if workflow.edit:
                    descriptor = self.definitions[scenario.project]["edits"][
                        workflow.edit
                    ]
                    edit = edit_contents(worktree, Edit(**descriptor))
                self.timed = True
                started = time.perf_counter()
                edit_seconds = 0.0
                if edit:
                    before_edit = time.perf_counter()
                    edit[0].write_bytes(edit[2])
                    edit_seconds = time.perf_counter() - before_edit
                expected_edit = edit[2] if edit else None
                commands = []
                for index, name in enumerate(workflow.commands, 1):
                    observed = self.run_command(
                        scenario,
                        worktree,
                        self.command_step(scenario.project, name),
                        label,
                        selector,
                        cell,
                        index,
                    )
                    commands.append(observed | {"name": name})
                    if edit and name == "fmt":
                        expected_edit = edit[0].read_bytes()
                    print(f"  {name}: {observed['wall_seconds']:.3f}s", flush=True)
                total = time.perf_counter() - started
            except BenchmarkError as error:
                if not hasattr(error, "command_sample"):
                    raise
                command_failure = error
            finally:
                self.timed = False
                self.monitor = None
        if monitor.failure:
            raise BenchmarkError(monitor.failure)
        if command_failure:
            raise command_failure
        if edit and edit[0].read_bytes() != expected_edit:
            raise BenchmarkError("workflow changed the edited source unexpectedly")
        after = replay.command_output(["git", "diff", "--binary"], cwd=worktree)
        if edit:
            edit[0].write_bytes(edit[1])
        if replay.command_output(["git", "diff", "--binary"], cwd=worktree) != baseline:
            raise BenchmarkError("workflow changed source outside the declared edit")
        sample = {
            "project": scenario.project,
            "workflow": workflow_id,
            "toolchain": label,
            "selector": selector,
            "repetition": repetition,
            "attempt": attempt,
            "wall_seconds": total,
            "command_seconds": sum(command["wall_seconds"] for command in commands),
            "edit_seconds": edit_seconds,
            "commands": commands,
            "warmups": warmups,
            "normalization": normalization,
            "baseline_diff_sha256": sha256(baseline.encode()),
            "edited_diff_sha256": sha256(after.encode()),
            "preflight": preflight,
            "cpu": cpu_evidence(cpu_path),
            "target_directory": environment["CARGO_TARGET_DIR"],
            "shared_build_directory": environment.get("CARGO_BUILD_BUILD_DIR"),
        }
        self.samples.append(sample)
        self.persist()
        print(f"  Full workflow: {total:.3f}s", flush=True)
        if self.options.discard_targets:
            self.retire(scenario, label, selector, cell, worktree)
        return sample

    def record_failure(
        self, scenario, workflow_id, label, selector, repetition, attempt, error
    ):
        cell = f"{workflow_id}-{repetition}-{attempt}"
        worktree = self.output / "worktrees" / scenario.project / label / cell
        logs = self.output / "logs" / scenario.project / label / cell
        environment = self.environment(scenario, label, selector, cell)
        diagnostics = []
        for path in worktree.rglob("rustc-ice-*.txt"):
            if path.is_file() and not path.is_symlink():
                destination = logs / path.name
                shutil.copyfile(path, destination)
                diagnostics.append(
                    {"path": str(destination), "sha256": sha256(path.read_bytes())}
                )
        self.failures.append(
            {
                "project": scenario.project,
                "workflow": workflow_id,
                "toolchain": label,
                "selector": selector,
                "repetition": repetition,
                "attempt": attempt,
                "failed_command": error.command_sample,
                "reason": str(error),
                "baseline_diff_sha256": self.case_context.get("baseline_diff_sha256"),
                "edited_diff_sha256": sha256(
                    replay.command_output(
                        ["git", "diff", "--binary"], cwd=worktree
                    ).encode()
                ),
                "preflight": self.case_context.get("preflight", []),
                "cpu": cpu_evidence(logs / "cpu.jsonl"),
                "diagnostics": diagnostics,
                "target_directory": environment["CARGO_TARGET_DIR"],
                "shared_build_directory": environment.get("CARGO_BUILD_BUILD_DIR"),
            }
        )
        self.persist()
        print(f"  Workflow failed: {error}", flush=True)

    def retire(self, scenario, label, selector, cell, worktree):
        environment = self.environment(scenario, label, selector, cell)
        for key in ("CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"):
            if key not in environment:
                continue
            path = Path(environment[key])
            if path.is_symlink() or not path.resolve().is_relative_to(self.output):
                raise BenchmarkError(f"unsafe sample artifact path: {path}")
            if path.exists():
                shutil.rmtree(path)
        replay.command_output(
            ["git", "worktree", "remove", "--force", str(worktree)],
            cwd=self.sources[scenario.project],
        )

    def collect_metadata(self):
        if any(
            s.project in {"ruff", "codex"} for s in self.scenarios
        ) and not shutil.which("cargo-nextest"):
            raise BenchmarkError("Ruff/ty and Codex workflows require cargo-nextest")
        versions = {}
        for label, selector in self.toolchains:
            versions[label] = {}
            for tool in ("cargo", "rustc", "rustfmt", "clippy-driver"):
                path = Path(
                    replay.command_output(
                        ["rustup", "which", "--toolchain", selector, tool]
                    )
                )
                versions[label][tool] = {
                    "version": replay.command_output(
                        [str(path), "-vV" if tool in {"cargo", "rustc"} else "--version"]
                    ),
                    "sha256": sha256(path.read_bytes()),
                }
                if tool == "rustc":
                    libraries = {}
                    for library in sorted((path.parent.parent / "lib").iterdir()):
                        if library.is_file() and (
                            "rustc_driver" in library.name or "LLVM" in library.name
                        ):
                            with library.open("rb") as stream:
                                libraries[library.name] = hashlib.file_digest(
                                    stream, "sha256"
                                ).hexdigest()
                    versions[label][tool]["libraries"] = libraries
                    provenance = path.parent.parent / "workflow-build-provenance.json"
                    if provenance.is_file():
                        versions[label][tool]["build_provenance"] = json.loads(
                            provenance.read_text()
                        )
        self.metadata = {
            "host": platform.node(),
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
            "cpu_model": next(
                (
                    line.split(":", 1)[1].strip()
                    for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")
                ),
                "unknown",
            ),
            "toolchains": versions,
            "started_at": time.time(),
            "helpers": {
                name: {
                    "path": str(path),
                    "sha256": sha256(path.read_bytes()),
                    "version": replay.command_output([str(path), "--version"]),
                }
                for name in ("cargo-nextest",)
                if (location := shutil.which(name)) and (path := Path(location))
            },
        }

    def run(self):
        if self.options.dry_run:
            print(json.dumps(self.configuration(), indent=2))
            return
        self.check_disk()
        if not self.options.resume and (self.output / "results.json").exists():
            raise BenchmarkError("output already contains results; use --resume")
        previous_metadata = self.metadata
        self.collect_metadata()
        if previous_metadata:
            for key in (
                "host",
                "platform",
                "logical_cpus",
                "cpu_model",
                "toolchains",
                "helpers",
            ):
                if self.metadata[key] != previous_metadata[key]:
                    raise BenchmarkError(f"cannot resume with different {key}")
            self.metadata = previous_metadata
        for scenario in self.scenarios:
            self.sources[scenario.project] = self.prepare_source(scenario)
        if self.options.prepare_only:
            for scenario in self.scenarios:
                source = self.sources[scenario.project]
                worktree = self.output / "fetch" / scenario.project
                worktree.parent.mkdir(parents=True, exist_ok=True)
                replay.command_output(
                    ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                    cwd=source,
                )
                replay.command_output(
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
                environment = self.environment(
                    scenario, "stock", self.options.upstream, "fetch"
                )
                environment.pop("CARGO_NET_OFFLINE", None)
                subprocess.run(
                    [
                        "cargo",
                        f"+{self.options.upstream}",
                        "fetch",
                        "--locked",
                        "--target",
                        "x86_64-unknown-linux-gnu",
                    ],
                    cwd=worktree / self.definitions[scenario.project]["workspace"],
                    env=environment,
                    check=True,
                )
            print("Dependencies prepared; no measurements run.", flush=True)
            return
        self.persist()
        for repetition in range(self.options.repetitions):
            for scenario in self.scenarios:
                for workflow_index, workflow_id in enumerate(self.workflows):
                    order = (
                        self.toolchains
                        if (repetition + workflow_index) % 2 == 0
                        else self.toolchains[::-1]
                    )
                    for label, selector in order:
                        if any(
                            (
                                s["project"],
                                s["workflow"],
                                s["toolchain"],
                                s["repetition"],
                            )
                            == (scenario.project, workflow_id, label, repetition)
                            for s in (*self.samples, *self.failures)
                        ):
                            continue
                        for attempt in range(self.options.contention_retries + 1):
                            cell = f"{workflow_id}-{repetition}-{attempt}"
                            worktree = (
                                self.output
                                / "worktrees"
                                / scenario.project
                                / label
                                / cell
                            )
                            if worktree.exists():
                                continue
                            try:
                                self.run_case(
                                    scenario,
                                    workflow_id,
                                    label,
                                    selector,
                                    repetition,
                                    attempt,
                                )
                                break
                            except BenchmarkError as error:
                                if hasattr(error, "command_sample"):
                                    self.record_failure(
                                        scenario,
                                        workflow_id,
                                        label,
                                        selector,
                                        repetition,
                                        attempt,
                                        error,
                                    )
                                    break
                                self.discarded.append(
                                    {
                                        "project": scenario.project,
                                        "workflow": workflow_id,
                                        "toolchain": label,
                                        "repetition": repetition,
                                        "attempt": attempt,
                                        "reason": str(error),
                                    }
                                )
                                self.persist()
                                if not any(
                                    word in str(error)
                                    for word in ("contention", "unrelated compiler")
                                ):
                                    raise
                                print(
                                    f"Discarding contaminated sample: {error}",
                                    flush=True,
                                )
                        else:
                            raise BenchmarkError("all sample attempts exhausted")
        self.metadata["finished_at"] = time.time()
        self.persist()


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--project", action="append", choices=project_definitions())
    result.add_argument("--workflow", action="append", choices=WORKFLOWS)
    result.add_argument("--source-path", action="append", default=[])
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--upstream", default="1.99.0")
    result.add_argument("--ohm", default="ohm-1.99.0-5")
    result.add_argument("--jobs", type=int, default=8)
    result.add_argument("--repetitions", type=int, default=4)
    result.add_argument("--timeout", type=int, default=3600)
    result.add_argument("--minimum-free-gb", type=int, default=60)
    result.add_argument("--require-idle", action="store_true")
    result.add_argument("--idle-timeout", type=int, default=3600)
    result.add_argument("--quiet-seconds", type=int, default=30)
    result.add_argument("--contention-retries", type=int, default=3)
    result.add_argument("--discard-targets", action="store_true")
    result.add_argument("--resume", action="store_true")
    result.add_argument("--dry-run", action="store_true")
    result.add_argument(
        "--prepare-only",
        action="store_true",
        help="fetch pinned dependencies online without measuring",
    )
    return result


def main():
    try:
        study = WorkflowStudy(parser().parse_args())
        study.run()
        if study.failures:
            raise SystemExit(
                f"{len(study.failures)} workflow executions failed; inspect results.json"
            )
    except (BenchmarkError, OSError, ValueError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
