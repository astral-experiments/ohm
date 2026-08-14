#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Add bounded real Ohm development workflows to upstream compiler training."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

CORPUS_PATH = (
    Path(__file__).resolve().parents[1] / "release/development-pgo-corpus.json"
)
PUBLIC_REPOSITORIES = {
    "ruff": "https://github.com/astral-sh/ruff.git",
    "uv": "https://github.com/astral-sh/uv.git",
    "codex": "https://github.com/openai/codex.git",
}
REVISION = re.compile(r"[0-9a-f]{40}\Z")
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
SAFE_ENVIRONMENT = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "TMPDIR",
        "RUNNER_TEMP",
        "CARGO_HOME",
        "CARGO_BUILD_JOBS",
        "RUSTUP_HOME",
        "RUST_BOOTSTRAP_CONFIG",
        "LLVM_PROFILE_FILE",
        "GITHUB_ACTIONS",
        "CC",
        "CXX",
        "AR",
        "RANLIB",
        "CFLAGS",
        "CXXFLAGS",
        "LDFLAGS",
        "DEVELOPER_DIR",
        "SDKROOT",
        "MACOSX_DEPLOYMENT_TARGET",
        "MACOSX_STD_DEPLOYMENT_TARGET",
    }
)


class ProfileError(Exception):
    """Development training could not preserve its release-safety guarantees."""


@dataclasses.dataclass(frozen=True)
class Project:
    name: str
    repository: str
    revision: str
    edit_revision: str
    edit_paths: tuple[str, ...]
    working_directory: str
    commands: tuple[tuple[str, ...], ...]


def relative_path(value: object, *, context: str, allow_current: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ProfileError(f"invalid {context}: {value!r}")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ProfileError(f"{context} escapes its pinned checkout: {value!r}")
    if str(candidate) == "." and not allow_current:
        raise ProfileError(f"invalid {context}: {value!r}")
    if str(candidate) != value:
        raise ProfileError(f"non-canonical {context}: {value!r}")
    return value


def validate_command(value: object, *, project: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(arg, str) for arg in value):
        raise ProfileError(f"invalid {project} Cargo training command")
    command = tuple(value)
    if len(command) < 4 or command[1] != "-p" or not PACKAGE.fullmatch(command[2]):
        raise ProfileError(f"{project} training must select one valid Cargo package")

    expected = (
        ("check", "-p", command[2], "--locked")
        if command[0] == "check"
        else ("test", "-p", command[2], "--lib", "--no-run", "--locked")
    )
    if command != expected or command[0] not in {"check", "test"}:
        raise ProfileError(
            f"{project} training must use a locked development check or non-running library test"
        )
    return command


def load_corpus(path: Path = CORPUS_PATH) -> tuple[Project, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProfileError(f"cannot read development corpus {path}: {error}") from error

    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ProfileError("development corpus must use schema version 1")
    entries = raw.get("projects")
    if not isinstance(entries, list) or len(entries) != len(PUBLIC_REPOSITORIES):
        raise ProfileError(
            "development corpus must contain exactly Ruff, uv, and public Codex"
        )

    projects: list[Project] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ProfileError("development corpus contains an invalid project")
        name = entry.get("name")
        if name not in PUBLIC_REPOSITORIES:
            raise ProfileError(
                f"development corpus contains an unapproved project: {name!r}"
            )
        if entry.get("repository") != PUBLIC_REPOSITORIES[name]:
            raise ProfileError(f"{name} must use its exact public HTTPS repository")

        revision = entry.get("revision")
        edit_revision = entry.get("edit_revision")
        if not isinstance(revision, str) or not REVISION.fullmatch(revision):
            raise ProfileError(
                f"{name} base revision must be a full immutable commit SHA"
            )
        if not isinstance(edit_revision, str) or not REVISION.fullmatch(edit_revision):
            raise ProfileError(
                f"{name} edit revision must be a full immutable commit SHA"
            )
        if revision == edit_revision:
            raise ProfileError(
                f"{name} training must contain a real committed source edit"
            )

        edit_paths = entry.get("edit_paths")
        if not isinstance(edit_paths, list) or len(edit_paths) != 1:
            raise ProfileError(f"{name} training must select exactly one source file")
        checked_paths = tuple(
            relative_path(value, context=f"{name} edited source")
            for value in edit_paths
        )
        if not all(value.endswith(".rs") for value in checked_paths):
            raise ProfileError(f"{name} training may edit only Rust source files")

        commands = entry.get("commands")
        if not isinstance(commands, list) or len(commands) != 2:
            raise ProfileError(
                f"{name} training must contain exactly one check and one test"
            )
        checked_commands = tuple(
            validate_command(command, project=name) for command in commands
        )
        if tuple(command[0] for command in checked_commands) != ("check", "test"):
            raise ProfileError(
                f"{name} training must warm checking and test compilation"
            )

        projects.append(
            Project(
                name=name,
                repository=PUBLIC_REPOSITORIES[name],
                revision=revision,
                edit_revision=edit_revision,
                edit_paths=checked_paths,
                working_directory=relative_path(
                    entry.get("working_directory"),
                    context=f"{name} working directory",
                    allow_current=True,
                ),
                commands=checked_commands,
            )
        )

    if tuple(project.name for project in projects) != tuple(PUBLIC_REPOSITORIES):
        raise ProfileError(
            "development corpus must contain Ruff, uv, and Codex exactly once"
        )
    return tuple(projects)


def sanitized_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    inherited = os.environ if source is None else source
    environment = {
        name: value for name, value in inherited.items() if name in SAFE_ENVIRONMENT
    }
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def git_output(
    checkout: Path,
    arguments: Sequence[str],
    *,
    environment: Mapping[str, str],
) -> str:
    result = subprocess.run(
        ["git", "-C", str(checkout), *arguments],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def prepare_checkout(
    project: Project,
    workspace: Path,
    *,
    environment: Mapping[str, str],
    source_root: Path | None = None,
) -> Path:
    checkout = workspace / "sources" / project.name
    source = project.repository
    if source_root is not None:
        local_source = source_root / project.name
        if not local_source.is_dir():
            raise ProfileError(
                f"local {project.name} source does not exist: {local_source}"
            )
        promisor = subprocess.run(
            [
                "git",
                "-C",
                str(local_source),
                "config",
                "--bool",
                "remote.origin.promisor",
            ],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if promisor.returncode == 0 and promisor.stdout.strip() == "true":
            print(
                f"Fetching pinned {project.name} revisions from their public repository "
                "because the local source is a partial clone",
                flush=True,
            )
        else:
            source = str(local_source.resolve())

    if checkout.exists():
        origin = git_output(
            checkout, ["remote", "get-url", "origin"], environment=environment
        )
        if origin != source:
            raise ProfileError(
                f"existing {project.name} checkout has an unexpected source"
            )
    else:
        checkout.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "init", "--quiet", str(checkout)],
            env=environment,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(checkout), "remote", "add", "origin", source],
            env=environment,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "fetch",
                "--quiet",
                "--no-tags",
                "--depth=2",
                "origin",
                project.revision,
                project.edit_revision,
            ],
            env=environment,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "checkout",
                "--quiet",
                "--detach",
                project.revision,
            ],
            env=environment,
            check=True,
        )

    actual_revision = git_output(
        checkout, ["rev-parse", "HEAD"], environment=environment
    )
    if actual_revision != project.revision:
        raise ProfileError(
            f"{project.name} checkout does not match its pinned revision: {actual_revision}"
        )
    actual_parent = git_output(
        checkout, ["rev-parse", f"{project.edit_revision}^"], environment=environment
    )
    if actual_parent != project.revision:
        raise ProfileError(
            f"{project.name} edit is not the pinned revision's direct child"
        )
    if git_output(
        checkout,
        ["status", "--porcelain", "--untracked-files=no"],
        environment=environment,
    ):
        raise ProfileError(f"{project.name} checkout contains existing source changes")
    return checkout


def run_project(
    project: Project,
    checkout: Path,
    *,
    cargo: Path,
    rustc: Path,
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    working_directory = checkout / project.working_directory
    if not (working_directory / "Cargo.toml").is_file():
        raise ProfileError(
            f"{project.name} does not contain its pinned Cargo workspace"
        )

    target = workspace / "targets" / project.name
    target.parent.mkdir(parents=True, exist_ok=True)
    cargo_environment = {
        **environment,
        "RUSTC": str(rustc),
        "CARGO_INCREMENTAL": "1",
        "CARGO_TARGET_DIR": str(target),
    }
    warmup_environment = cargo_environment
    warmup_root: Path | None = None
    if profile_template := environment.get("LLVM_PROFILE_FILE"):
        profile_root = Path(profile_template).parent.resolve()
        warmup_root = (workspace / "warmup-profiles" / project.name).resolve()
        if warmup_root.is_relative_to(profile_root):
            raise ProfileError(
                "cold dependency profiles must remain outside the PGO merge root"
            )
        warmup_root.mkdir(parents=True, exist_ok=True)
        warmup_environment = {
            **cargo_environment,
            "LLVM_PROFILE_FILE": str(warmup_root / "warmup_%m_%p.profraw"),
        }

    def run_commands(stage: str, current_environment: Mapping[str, str]) -> None:
        for command in project.commands:
            print(
                f"Profiling {project.name} {stage}: cargo {' '.join(command)}",
                flush=True,
            )
            subprocess.run(
                [str(cargo), *command],
                cwd=working_directory,
                env=current_environment,
                check=True,
            )

    run_commands("warm", warmup_environment)
    if warmup_root is not None:
        for profile in warmup_root.glob("*.profraw"):
            if (
                profile.parent == warmup_root
                and not profile.is_symlink()
                and profile.is_file()
            ):
                profile.unlink()

    original_sources: list[tuple[Path, bytes]] = []
    try:
        for edit_path in project.edit_paths:
            destination = checkout / edit_path
            if not destination.resolve().is_relative_to(checkout.resolve()):
                raise ProfileError(
                    f"{project.name} edit resolves outside its private checkout"
                )
            original = destination.read_bytes()
            updated = subprocess.run(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "show",
                    f"{project.edit_revision}:{edit_path}",
                ],
                env=environment,
                check=True,
                capture_output=True,
            ).stdout
            if updated == original:
                raise ProfileError(
                    f"{project.name} committed edit did not change its source"
                )
            original_sources.append((destination, original))
            destination.write_bytes(updated)

        run_commands("edited", cargo_environment)
    finally:
        for destination, original in reversed(original_sources):
            destination.write_bytes(original)


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--cargo", type=Path, required=True)
    argument_parser.add_argument("--rustc", type=Path, required=True)
    argument_parser.add_argument("--workspace", type=Path, required=True)
    argument_parser.add_argument("--phase", choices=("pgo", "bolt"), required=True)
    argument_parser.add_argument("--source-root", type=Path)
    argument_parser.add_argument("--manifest", type=Path, default=CORPUS_PATH)
    return argument_parser


def main(arguments: Sequence[str] | None = None) -> int:
    options = parser().parse_args(arguments)
    cargo = options.cargo.resolve()
    rustc = options.rustc.resolve()
    for description, executable in (
        ("Ohm Cargo", cargo),
        ("instrumented rustc", rustc),
    ):
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ProfileError(f"{description} executable does not exist: {executable}")
    if options.phase == "pgo" and not os.environ.get("LLVM_PROFILE_FILE"):
        raise ProfileError("instrumented PGO training requires LLVM_PROFILE_FILE")

    projects = load_corpus(options.manifest)
    workspace = options.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    source_root = (
        options.source_root.resolve() if options.source_root is not None else None
    )
    environment = sanitized_environment()

    for project in projects:
        checkout = prepare_checkout(
            project,
            workspace,
            environment=environment,
            source_root=source_root,
        )
        run_project(
            project,
            checkout,
            cargo=cargo,
            rustc=rustc,
            workspace=workspace,
            environment=environment,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ProfileError, subprocess.CalledProcessError, OSError) as error:
        print(f"Ohm development profiling failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
