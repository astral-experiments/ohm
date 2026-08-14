"""Build-free regression tests for the supplemental Ohm development corpus."""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("profile-development-workflows.py")
SPEC = importlib.util.spec_from_file_location("ohm_development_profiling", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to import development profiling runner: {SCRIPT}")
profiling = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = profiling
SPEC.loader.exec_module(profiling)

PROXY_SCRIPT = Path(__file__).with_name("pgo-stage0-cargo.py")
PROXY_SPEC = importlib.util.spec_from_file_location(
    "ohm_stage0_cargo_proxy", PROXY_SCRIPT
)
if PROXY_SPEC is None or PROXY_SPEC.loader is None:
    raise RuntimeError(
        f"unable to import stage-zero Cargo profiling proxy: {PROXY_SCRIPT}"
    )
proxy = importlib.util.module_from_spec(PROXY_SPEC)
sys.modules[PROXY_SPEC.name] = proxy
PROXY_SPEC.loader.exec_module(proxy)


class CorpusValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = json.loads(profiling.CORPUS_PATH.read_text(encoding="utf-8"))

    def load(self, corpus: dict[str, object]) -> tuple[profiling.Project, ...]:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "development-pgo-corpus.json"
            manifest.write_text(json.dumps(corpus), encoding="utf-8")
            return profiling.load_corpus(manifest)

    def test_pins_three_real_public_development_workflows(self) -> None:
        projects = profiling.load_corpus()

        self.assertEqual(
            tuple(project.name for project in projects), ("ruff", "uv", "codex")
        )
        self.assertEqual(projects[1].commands[0][2], "uv-metadata")
        self.assertEqual(projects[1].commands[1][2], "uv-pypi-types")
        self.assertEqual(projects[2].commands[0][2], "codex-async-utils")
        for project in projects:
            with self.subTest(project=project.name):
                self.assertRegex(project.revision, r"\A[0-9a-f]{40}\Z")
                self.assertRegex(project.edit_revision, r"\A[0-9a-f]{40}\Z")
                self.assertTrue(project.repository.startswith("https://github.com/"))
                self.assertEqual(len(project.edit_paths), 1)
                self.assertEqual(len(project.commands), 2)
                self.assertEqual(
                    [command[0] for command in project.commands], ["check", "test"]
                )
                self.assertIn("--no-run", project.commands[1])
                self.assertIn("--lib", project.commands[1])
                self.assertTrue(
                    all("--locked" in command for command in project.commands)
                )
                self.assertTrue(
                    all("--release" not in command for command in project.commands)
                )

    def test_rejects_unpinned_or_private_sources(self) -> None:
        for key, value in (
            ("revision", "main"),
            ("revision", "6e29838d"),
            ("edit_revision", "HEAD"),
            ("repository", "https://github.com/openai/codex-internal.git"),
            ("repository", "https://secret-token@github.com/astral-sh/ruff.git"),
        ):
            with self.subTest(key=key, value=value):
                corpus = copy.deepcopy(self.raw)
                corpus["projects"][0][key] = value
                with self.assertRaises(profiling.ProfileError):
                    self.load(corpus)

    def test_rejects_unbounded_or_release_commands(self) -> None:
        for command in (
            ["build", "-p", "ruff_python_parser", "--release", "--locked"],
            ["check", "--workspace", "--locked"],
            ["check", "-p", "ruff_python_parser", "--profile", "release", "--locked"],
            ["test", "-p", "ruff_python_parser", "--lib", "--locked"],
            ["test", "-p", "ruff_python_parser", "--no-run", "--locked"],
            ["test", "-p", "ruff_python_parser", "--lib", "--no-run"],
        ):
            with self.subTest(command=command):
                corpus = copy.deepcopy(self.raw)
                index = 1 if command[0] == "test" else 0
                corpus["projects"][0]["commands"][index] = command
                with self.assertRaises(profiling.ProfileError):
                    self.load(corpus)

    def test_rejects_duplicate_projects_and_escaping_source_paths(self) -> None:
        for mutation in (
            lambda corpus: corpus["projects"].append(
                copy.deepcopy(corpus["projects"][0])
            ),
            lambda corpus: corpus["projects"][0].update(
                edit_paths=["../../private.rs"]
            ),
            lambda corpus: corpus["projects"][0].update(working_directory="../private"),
            lambda corpus: corpus["projects"][0].update(edit_paths=["Cargo.toml"]),
            lambda corpus: corpus["projects"][0].update(edit_paths=[]),
            lambda corpus: corpus["projects"][0].update(commands=[]),
        ):
            with self.subTest(mutation=mutation):
                corpus = copy.deepcopy(self.raw)
                mutation(corpus)
                with self.assertRaises(profiling.ProfileError):
                    self.load(corpus)


class EnvironmentTests(unittest.TestCase):
    def test_preserves_instrumentation_and_strips_release_credentials(self) -> None:
        inherited = {
            "PATH": "/usr/bin",
            "HOME": "/home/runner",
            "LLVM_PROFILE_FILE": "/private/profiles/default_%m_%p.profraw",
            "SDKROOT": "/fixture/sdk",
            "CARGO_BUILD_JOBS": "16",
            "OHM_RELEASE_APP_PRIVATE_KEY": "fixture-release-private-key",
            "MIRROR_R2_SECRET_ACCESS_KEY": "fixture-r2-key",
            "GH_TOKEN": "fixture-github-token",
            "GITHUB_TOKEN": "fixture-github-token",
            "ACTIONS_RUNTIME_TOKEN": "fixture-actions-token",
            "EXAMPLE_PASSWORD": "fixture-password",
            "CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST": "all",
            "RUSTFLAGS": "-Zunsupported-override",
            "GIT_ASKPASS": "/fixture/credential-helper",
        }

        environment = profiling.sanitized_environment(inherited)

        self.assertEqual(
            environment["LLVM_PROFILE_FILE"], inherited["LLVM_PROFILE_FILE"]
        )
        self.assertEqual(environment["SDKROOT"], inherited["SDKROOT"])
        self.assertEqual(environment["CARGO_BUILD_JOBS"], "16")
        self.assertEqual(environment["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")
        for sensitive in inherited.keys() - profiling.SAFE_ENVIRONMENT:
            with self.subTest(sensitive=sensitive):
                self.assertNotIn(sensitive, environment)


class CheckoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = profiling.load_corpus()[0]
        self.environment = {"PATH": "/usr/bin"}

    def test_fetches_only_both_immutable_public_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            checkout = workspace / "sources" / self.project.name

            def subprocess_run(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                if command[1] == "init":
                    checkout.mkdir(parents=True)
                return subprocess.CompletedProcess(command, 0, stdout="")

            with (
                mock.patch.object(
                    profiling.subprocess, "run", side_effect=subprocess_run
                ) as run,
                mock.patch.object(
                    profiling,
                    "git_output",
                    side_effect=[self.project.revision, self.project.revision, ""],
                ),
            ):
                result = profiling.prepare_checkout(
                    self.project, workspace, environment=self.environment
                )

        self.assertEqual(result, checkout)
        self.assertEqual(run.call_count, 4)
        fetch = run.call_args_list[2].args[0]
        self.assertEqual(
            fetch[-4:],
            ["--depth=2", "origin", self.project.revision, self.project.edit_revision],
        )
        self.assertIn("--no-tags", fetch)
        self.assertEqual(run.call_args_list[1].args[0][-1], self.project.repository)

    def test_local_source_override_never_uses_the_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "local"
            source = source_root / self.project.name
            source.mkdir(parents=True)
            checkout = root / "workspace" / "sources" / self.project.name

            def subprocess_run(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                if command[1] == "init":
                    checkout.mkdir(parents=True)
                return subprocess.CompletedProcess(command, 0, stdout="")

            with (
                mock.patch.object(
                    profiling.subprocess, "run", side_effect=subprocess_run
                ) as run,
                mock.patch.object(
                    profiling,
                    "git_output",
                    side_effect=[self.project.revision, self.project.revision, ""],
                ),
            ):
                profiling.prepare_checkout(
                    self.project,
                    root / "workspace",
                    environment=self.environment,
                    source_root=source_root,
                )

        added_origin = next(
            call.args[0][-1]
            for call in run.call_args_list
            if call.args[0][3:6] == ["remote", "add", "origin"]
        )
        self.assertEqual(added_origin, str(source.resolve()))
        self.assertNotIn("https://", added_origin)

    def test_partial_local_source_uses_only_the_allowlisted_public_repository(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "local"
            source = source_root / self.project.name
            source.mkdir(parents=True)
            checkout = root / "workspace" / "sources" / self.project.name

            def subprocess_run(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                if command[1] == "init":
                    checkout.mkdir(parents=True)
                output = "true\n" if command[-1] == "remote.origin.promisor" else ""
                return subprocess.CompletedProcess(command, 0, stdout=output)

            with (
                mock.patch.object(
                    profiling.subprocess, "run", side_effect=subprocess_run
                ) as run,
                mock.patch.object(
                    profiling,
                    "git_output",
                    side_effect=[self.project.revision, self.project.revision, ""],
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                profiling.prepare_checkout(
                    self.project,
                    root / "workspace",
                    environment=self.environment,
                    source_root=source_root,
                )

        added_origin = next(
            call.args[0][-1]
            for call in run.call_args_list
            if call.args[0][3:6] == ["remote", "add", "origin"]
        )
        self.assertEqual(added_origin, self.project.repository)

    def test_rejects_wrong_checkout_head_edit_parent_or_existing_changes(self) -> None:
        for outputs in (
            [self.project.repository, "0" * 40],
            [self.project.repository, self.project.revision, "0" * 40],
            [
                self.project.repository,
                self.project.revision,
                self.project.revision,
                " M source.rs",
            ],
        ):
            with (
                self.subTest(outputs=outputs),
                tempfile.TemporaryDirectory() as directory,
            ):
                workspace = Path(directory)
                (workspace / "sources" / self.project.name).mkdir(parents=True)
                with (
                    mock.patch.object(profiling, "git_output", side_effect=outputs),
                    self.assertRaises(profiling.ProfileError),
                ):
                    profiling.prepare_checkout(
                        self.project, workspace, environment=self.environment
                    )

    def test_missing_local_override_fails_without_falling_back_to_public_network(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                mock.patch.object(profiling.subprocess, "run") as run,
                self.assertRaisesRegex(profiling.ProfileError, "local ruff source"),
            ):
                profiling.prepare_checkout(
                    self.project,
                    root / "workspace",
                    environment=self.environment,
                    source_root=root / "missing",
                )

            run.assert_not_called()

    def test_real_shallow_local_checkout_retains_the_edited_commits_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "local"
            source = source_root / self.project.name
            source.mkdir(parents=True)
            subprocess.run(["git", "init", "--quiet", str(source)], check=True)
            source_file = source / "private.rs"
            source_file.write_text(
                "fn private_value() -> usize { 1 }\n", encoding="utf-8"
            )
            subprocess.run(["git", "-C", str(source), "add", "private.rs"], check=True)

            commit_prefix = [
                "git",
                "-C",
                str(source),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.test",
                "commit",
                "--quiet",
                "--message",
            ]
            subprocess.run([*commit_prefix, "Baseline"], check=True)
            revision = subprocess.run(
                ["git", "-C", str(source), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            source_file.write_text(
                "fn private_value() -> usize { 2 }\n", encoding="utf-8"
            )
            subprocess.run(["git", "-C", str(source), "add", "private.rs"], check=True)
            subprocess.run([*commit_prefix, "Edit"], check=True)
            edit_revision = subprocess.run(
                ["git", "-C", str(source), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            project = dataclasses.replace(
                self.project,
                revision=revision,
                edit_revision=edit_revision,
                edit_paths=("private.rs",),
            )
            checkout = profiling.prepare_checkout(
                project,
                root / "workspace",
                environment=profiling.sanitized_environment(),
                source_root=source_root,
            )

            self.assertEqual(
                profiling.git_output(
                    checkout,
                    ["rev-parse", f"{edit_revision}^"],
                    environment=profiling.sanitized_environment(),
                ),
                revision,
            )


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = profiling.load_corpus()[1]

    def fixture(self, directory: str) -> tuple[Path, Path, Path, bytes, dict[str, str]]:
        root = Path(directory)
        checkout = root / "checkout"
        checkout.mkdir()
        (checkout / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
        source = checkout / self.project.edit_paths[0]
        source.parent.mkdir(parents=True)
        original = b"fn private_parser() -> usize { 1 }\n"
        source.write_bytes(original)
        environment = {
            "PATH": "/usr/bin",
            "LLVM_PROFILE_FILE": str(root / "upstream/default_%m_%p.profraw"),
        }
        return root, checkout, source, original, environment

    def test_profiles_only_real_incremental_edits_in_the_upstream_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, checkout, source, original, inherited = self.fixture(directory)
            edited = b"fn private_parser() -> usize { 2 }\n"
            cargo_calls: list[tuple[list[str], dict[str, str], bytes]] = []

            def subprocess_run(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[bytes]:
                if command[0] == "git":
                    return subprocess.CompletedProcess(command, 0, stdout=edited)
                cargo_calls.append((command, kwargs["env"], source.read_bytes()))
                return subprocess.CompletedProcess(command, 0)

            with (
                mock.patch.object(
                    profiling.subprocess, "run", side_effect=subprocess_run
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                profiling.run_project(
                    self.project,
                    checkout,
                    cargo=root / "ohm-cargo",
                    rustc=root / "instrumented-rustc",
                    workspace=root / "training",
                    environment=inherited,
                )

            self.assertEqual(len(cargo_calls), 4)
            self.assertEqual(
                [command[1:4] for command, _, _ in cargo_calls],
                [
                    ["check", "-p", "uv-metadata"],
                    ["test", "-p", "uv-pypi-types"],
                    ["check", "-p", "uv-metadata"],
                    ["test", "-p", "uv-pypi-types"],
                ],
            )
            self.assertEqual(
                [contents for _, _, contents in cargo_calls],
                [original, original, edited, edited],
            )
            self.assertEqual(source.read_bytes(), original)

            warmup_profile = str(
                (root / "training/warmup-profiles/uv/warmup_%m_%p.profraw").resolve()
            )
            self.assertEqual(cargo_calls[0][1]["LLVM_PROFILE_FILE"], warmup_profile)
            self.assertEqual(cargo_calls[1][1]["LLVM_PROFILE_FILE"], warmup_profile)
            self.assertEqual(
                cargo_calls[2][1]["LLVM_PROFILE_FILE"], inherited["LLVM_PROFILE_FILE"]
            )
            self.assertEqual(
                cargo_calls[3][1]["LLVM_PROFILE_FILE"], inherited["LLVM_PROFILE_FILE"]
            )

            for command, environment, _ in cargo_calls:
                with self.subTest(command=command):
                    self.assertEqual(
                        environment["RUSTC"], str(root / "instrumented-rustc")
                    )
                    self.assertEqual(environment["CARGO_INCREMENTAL"], "1")
                    self.assertEqual(
                        environment["CARGO_TARGET_DIR"],
                        str(root / "training/targets/uv"),
                    )
                    self.assertNotIn("--release", command)

    def test_bolt_reuses_the_same_target_without_inventing_pgo_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, checkout, source, original, _ = self.fixture(directory)
            edited = b"fn private_parser() -> usize { 2 }\n"
            cargo_calls: list[dict[str, str]] = []

            def subprocess_run(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[bytes]:
                if command[0] == "git":
                    return subprocess.CompletedProcess(command, 0, stdout=edited)
                cargo_calls.append(kwargs["env"])
                return subprocess.CompletedProcess(command, 0)

            with (
                mock.patch.object(
                    profiling.subprocess, "run", side_effect=subprocess_run
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                profiling.run_project(
                    self.project,
                    checkout,
                    cargo=root / "ohm-cargo",
                    rustc=root / "instrumented-rustc",
                    workspace=root / "training",
                    environment={"PATH": "/usr/bin"},
                )

            self.assertEqual(len(cargo_calls), 4)
            self.assertTrue(all("LLVM_PROFILE_FILE" not in env for env in cargo_calls))
            self.assertEqual(
                {environment["CARGO_TARGET_DIR"] for environment in cargo_calls},
                {str(root / "training/targets/uv")},
            )
            self.assertEqual(source.read_bytes(), original)

    def test_discards_only_regular_immediate_cold_dependency_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, checkout, source, original, inherited = self.fixture(directory)
            edited = b"fn private_parser() -> usize { 2 }\n"
            warmup_root = (root / "training/warmup-profiles/uv").resolve()
            profile = warmup_root / "cold.profraw"
            preserved = warmup_root / "keep.txt"
            nested = warmup_root / "nested/protected.profraw"
            outside = root / "outside.profraw"
            outside.write_bytes(b"untouched")
            symbolic_link = warmup_root / "linked.profraw"

            def subprocess_run(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[bytes]:
                if command[0] == "git":
                    return subprocess.CompletedProcess(command, 0, stdout=edited)

                if source.read_bytes() == original:
                    profile.write_bytes(b"cold profiles")
                    preserved.write_text("keep", encoding="utf-8")
                    nested.parent.mkdir(exist_ok=True)
                    nested.write_bytes(b"nested")
                    if not symbolic_link.is_symlink():
                        symbolic_link.symlink_to(outside)
                else:
                    self.assertFalse(profile.exists())
                return subprocess.CompletedProcess(command, 0)

            with (
                mock.patch.object(
                    profiling.subprocess, "run", side_effect=subprocess_run
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                profiling.run_project(
                    self.project,
                    checkout,
                    cargo=root / "ohm-cargo",
                    rustc=root / "instrumented-rustc",
                    workspace=root / "training",
                    environment=inherited,
                )

            self.assertFalse(profile.exists())
            self.assertEqual(preserved.read_text(encoding="utf-8"), "keep")
            self.assertEqual(nested.read_bytes(), b"nested")
            self.assertTrue(symbolic_link.is_symlink())
            self.assertEqual(outside.read_bytes(), b"untouched")
            self.assertEqual(source.read_bytes(), original)

    def test_rejects_cold_profiles_inside_upstream_merge_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, checkout, _, _, inherited = self.fixture(directory)
            workspace = root / "upstream/training"

            with (
                mock.patch.object(profiling.subprocess, "run") as run,
                self.assertRaisesRegex(
                    profiling.ProfileError, "outside the PGO merge root"
                ),
            ):
                profiling.run_project(
                    self.project,
                    checkout,
                    cargo=root / "ohm-cargo",
                    rustc=root / "instrumented-rustc",
                    workspace=workspace,
                    environment=inherited,
                )

            run.assert_not_called()

    def test_restores_original_source_when_edited_compilation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, checkout, source, original, inherited = self.fixture(directory)
            edited = b"fn private_parser() -> usize { 2 }\n"

            def subprocess_run(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[bytes]:
                if command[0] == "git":
                    return subprocess.CompletedProcess(command, 0, stdout=edited)
                if source.read_bytes() == edited:
                    raise subprocess.CalledProcessError(101, command)
                return subprocess.CompletedProcess(command, 0)

            with (
                mock.patch.object(
                    profiling.subprocess, "run", side_effect=subprocess_run
                ),
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                profiling.run_project(
                    self.project,
                    checkout,
                    cargo=root / "ohm-cargo",
                    rustc=root / "instrumented-rustc",
                    workspace=root / "training",
                    environment=inherited,
                )

            self.assertEqual(source.read_bytes(), original)

    def test_rejects_unchanged_commit_contents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, checkout, source, original, inherited = self.fixture(directory)

            def subprocess_run(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[bytes]:
                if command[0] == "git":
                    return subprocess.CompletedProcess(command, 0, stdout=original)
                return subprocess.CompletedProcess(command, 0)

            with (
                mock.patch.object(
                    profiling.subprocess, "run", side_effect=subprocess_run
                ),
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaisesRegex(profiling.ProfileError, "did not change"),
            ):
                profiling.run_project(
                    self.project,
                    checkout,
                    cargo=root / "ohm-cargo",
                    rustc=root / "instrumented-rustc",
                    workspace=root / "training",
                    environment=inherited,
                )

            self.assertEqual(source.read_bytes(), original)


class StageZeroProxyTests(unittest.TestCase):
    def fixture(self, directory: str) -> tuple[Path, Path, Path, Path, list[str]]:
        target_root = Path(directory) / "target"
        invoked = target_root / "ohm-pgo-stage0/bin/cargo"
        upstream = target_root / "stage0/bin/cargo"
        ohm = target_root / "stage1-tools-bin/cargo"
        rustc = target_root / "stage2/bin/rustc"
        for executable in (upstream, ohm, rustc):
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.touch(mode=0o755)
        invoked.parent.mkdir(parents=True)
        invoked.symlink_to(PROXY_SCRIPT)
        collector = [
            "run",
            "-p",
            "collector",
            "--bin",
            "collector",
            "--",
            "profile_local",
            "eprintln",
            str(rustc),
            "--id",
            "Test",
            "--cargo",
            str(invoked),
            "--profiles",
            "Check,Debug,Opt",
            "--scenarios",
            "All",
            "--exact-match",
            "externs,ctfe-stress-5,cargo-0.87.1",
        ]
        return target_root, invoked, upstream, ohm, collector

    def test_supplements_only_after_the_unchanged_complete_upstream_corpus(
        self,
    ) -> None:
        for phase, inherited in (
            ("pgo", {"LLVM_PROFILE_FILE": "/upstream/default_%m_%p.profraw"}),
            ("bolt", {}),
        ):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                target_root, invoked, upstream, ohm, collector = self.fixture(directory)
                source_root = str(Path(directory) / "sources")
                inherited["OHM_DEVELOPMENT_SOURCE_ROOT"] = source_root

                with (
                    mock.patch.object(proxy.sys, "argv", [str(invoked), *collector]),
                    mock.patch.dict(os.environ, inherited, clear=True),
                    mock.patch.object(
                        proxy.subprocess,
                        "run",
                        side_effect=[
                            subprocess.CompletedProcess([], 0),
                            subprocess.CompletedProcess([], 0),
                        ],
                    ) as run,
                ):
                    self.assertEqual(proxy.main(), 0)

                self.assertEqual(run.call_count, 2)
                self.assertEqual(
                    run.call_args_list[0].args[0], [str(upstream), *collector]
                )
                supplement = run.call_args_list[1].args[0]
                self.assertEqual(
                    supplement,
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--cargo",
                        str(ohm),
                        "--rustc",
                        str(target_root / "stage2/bin/rustc"),
                        "--workspace",
                        str(target_root / "ohm-development-workflows"),
                        "--phase",
                        phase,
                        "--source-root",
                        source_root,
                    ],
                )
                self.assertIn("Check,Debug,Opt", run.call_args_list[0].args[0])

    def test_forwards_nested_collector_cargo_without_retriggering_training(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, invoked, upstream, _, _ = self.fixture(directory)
            nested = ["build", "-p", "collector", "--release"]

            with (
                mock.patch.object(proxy.sys, "argv", [str(invoked), *nested]),
                mock.patch.object(
                    proxy.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0),
                ) as run,
            ):
                self.assertEqual(proxy.main(), 0)

            run.assert_called_once_with([str(upstream), *nested], check=False)

    def test_failed_upstream_training_never_runs_supplemental_workloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, invoked, _, _, collector = self.fixture(directory)
            with (
                mock.patch.object(proxy.sys, "argv", [str(invoked), *collector]),
                mock.patch.object(
                    proxy.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 101),
                ) as run,
            ):
                self.assertEqual(proxy.main(), 101)

            run.assert_called_once()

    def test_rejects_a_non_instrumented_compiler(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, invoked, _, _, collector = self.fixture(directory)
            collector[8] = str(Path(directory) / "different-rustc")
            with (
                mock.patch.object(proxy.sys, "argv", [str(invoked), *collector]),
                mock.patch.object(
                    proxy.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0),
                ) as run,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(proxy.main(), 1)

            run.assert_called_once()

    def test_does_not_supplement_llvm_or_custom_profile_training(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, invoked, _, _, collector = self.fixture(directory)
            collector[collector.index("--profiles") + 1] = "Debug,Opt"
            with (
                mock.patch.object(proxy.sys, "argv", [str(invoked), *collector]),
                mock.patch.object(
                    proxy.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0),
                ) as run,
            ):
                self.assertEqual(proxy.main(), 0)

            run.assert_called_once()


class EntrypointTests(unittest.TestCase):
    def test_pgo_requires_profile_destination_but_bolt_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cargo = root / "cargo"
            rustc = root / "rustc"
            cargo.touch(mode=0o755)
            rustc.touch(mode=0o755)
            arguments = [
                "--cargo",
                str(cargo),
                "--rustc",
                str(rustc),
                "--workspace",
                str(root / "work"),
            ]

            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(
                    profiling.ProfileError, "LLVM_PROFILE_FILE"
                ):
                    profiling.main([*arguments, "--phase", "pgo"])

                with (
                    mock.patch.object(profiling, "load_corpus", return_value=()),
                    mock.patch.object(profiling, "prepare_checkout") as prepare,
                ):
                    self.assertEqual(profiling.main([*arguments, "--phase", "bolt"]), 0)
                prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
