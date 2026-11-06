"""Check that worktree startup uses distinct targets and seeds from the warm parent."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import benchmark_worktree_start as benchmark


class WorktreeStartTests(unittest.TestCase):
    def test_create_uses_parent_cache_and_validation_uses_private_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            (source / "Cargo.toml").write_text("[workspace]\n")
            subprocess.run(["git", "add", "."], cwd=source, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-qm",
                    "Base",
                ],
                cwd=source,
                check=True,
            )
            revision = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=source, text=True
            ).strip()
            fixture = root / "fixture.json"
            fixture.write_text(
                json.dumps(
                    {
                        "project": "ruff",
                        "repository": str(source),
                        "base_revision": revision,
                        "session": {"id": "worktree-start-test"},
                        "steps": [benchmark.VALIDATION],
                    }
                )
            )
            study = benchmark.WorktreeStart(
                benchmark.parser().parse_args(
                    [
                        "--scenario",
                        str(fixture),
                        "--source-path",
                        str(source),
                        "--ohm",
                        "test-ohm",
                        "--output-dir",
                        str(root / "results"),
                        "--minimum-free-gb",
                        "0",
                    ]
                )
            )
            study.sources["ruff"] = source
            scenario = study.scenarios[0]
            real_run = subprocess.run
            creation_environments = []
            validation_environments = []

            def create(arguments, **kwargs):
                if arguments[0] != "cargo":
                    return real_run(arguments, **kwargs)
                environment = kwargs["env"]
                parent_target = Path(environment["CARGO_TARGET_DIR"])
                self.assertEqual((parent_target / "warm.marker").read_text(), "warm")
                creation_environments.append(environment)
                target_index = arguments.index("--target-dir")
                child_target = Path(arguments[target_index + 1])
                self.assertNotEqual(parent_target, child_target)
                self.assertFalse(child_target.exists())
                child_target.mkdir(parents=True)
                (child_target / "seed.marker").write_text("seeded")
                git_arguments = [
                    "git",
                    *arguments[2:target_index],
                    *arguments[target_index + 2 :],
                ]
                return real_run(git_arguments, **kwargs)

            def validate(
                scenario,
                worktree,
                step,
                label,
                selector,
                repetition,
                index,
                *,
                phase="session",
            ):
                environment = study.environment(scenario, label, selector, repetition)
                target = Path(environment["CARGO_TARGET_DIR"])
                if phase == "warmup":
                    target.mkdir(parents=True)
                    (target / "warm.marker").write_text("warm")
                    logs = study.output / "logs" / "ruff" / label / str(repetition)
                    logs.mkdir(parents=True)
                else:
                    self.assertFalse((target / "warm.marker").exists())
                    self.assertEqual(
                        (target / "seed.marker").exists(), label != "stock"
                    )
                    validation_environments.append((label, environment))
                return {"wall_seconds": 1.0, "tests_started": 1}

            with (
                mock.patch.object(benchmark.subprocess, "run", side_effect=create),
                mock.patch.object(study, "run_command", side_effect=validate),
            ):
                for label, selector in study.toolchains:
                    study.run_session(scenario, label, selector, 0)
            self.assertEqual(len(study.samples), 3)
            self.assertEqual(len(creation_environments), 2)
            targets = [
                environment["CARGO_TARGET_DIR"]
                for _, environment in validation_environments
            ]
            self.assertEqual(len(set(targets)), 3)
            for label, environment in validation_environments:
                trusted = label == "ohm-trusted"
                self.assertEqual(
                    environment.get("CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST") == "all",
                    trusted,
                )
                self.assertEqual(
                    environment.get("CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST") == "all",
                    trusted,
                )
                self.assertEqual(
                    "CARGO_BUILD_BUILD_DIR" in environment, label != "stock"
                )
            for sample in study.samples:
                self.assertEqual(
                    sample["wall_seconds"], sample["creation"]["wall_seconds"] + 1.0
                )


if __name__ == "__main__":
    unittest.main()
