"""Regression checks for the real-source resident test-binary experiment."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from measure_test import compiler_command, internal_passes, resident_transaction
from run_tests import PACKAGE


class TestResidentTestBenchmark(unittest.TestCase):
    def test_actual_test_and_codegen_flags_survive_output_isolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture = {
                "cwd": "/original",
                "argv": [
                    "/tools/rustc",
                    "--crate-name",
                    "ruff_python_parser",
                    "/original/crates/ruff_python_parser/src/lib.rs",
                    "--test",
                    "--emit=dep-info,link",
                    "--json=diagnostic-rendered-ansi,artifacts",
                    "--out-dir",
                    "/original-target",
                    "-C",
                    "extra-filename=-test",
                    "-C",
                    "opt-level=1",
                    "-C",
                    "incremental=/original-target/inc",
                    "--extern",
                    "a=/external/liba.rlib",
                    "-Zohm-resident-query-graph",
                ],
                "env": {"CARGO_MANIFEST_DIR": "/original/crates/ruff_python_parser"},
            }
            command, env, binary = compiler_command(
                Path("/driver"),
                capture,
                root / "workspace",
                root / "output",
                Path("/sysroot"),
            )
            self.assertIn("--test", command)
            self.assertIn("--emit=dep-info,link", command)
            self.assertIn("--json=diagnostic-rendered-ansi,artifacts,timings", command)
            self.assertIn("opt-level=1", command)
            self.assertIn("a=/external/liba.rlib", command)
            self.assertIn(str(root / "workspace" / PACKAGE / "src/lib.rs"), command)
            self.assertNotIn("incremental=/original-target/inc", command)
            self.assertNotIn("/original-target", command)
            self.assertEqual(command.count("-Zohm-resident-query-graph"), 1)
            self.assertEqual(
                env["CARGO_MANIFEST_DIR"], str(root / "workspace" / PACKAGE)
            )
            self.assertEqual(binary, root / "output" / "ruff_python_parser-test")

    def test_timing_sections_and_link_artifact_are_distinct_from_diagnostics(self):
        events = [
            {
                "$message_type": "section_timing",
                "name": "codegen",
                "event": "start",
                "timestamp": 10,
            },
            {
                "$message_type": "section_timing",
                "name": "codegen",
                "event": "end",
                "timestamp": 25,
            },
            {
                "$message_type": "section_timing",
                "name": "link",
                "event": "start",
                "timestamp": 26,
            },
            {"$message_type": "diagnostic", "level": "error", "message": "not a stage"},
            {
                "$message_type": "section_timing",
                "name": "link",
                "event": "end",
                "timestamp": 48,
            },
            {"$message_type": "artifact", "emit": "metadata", "artifact": "a.rmeta"},
            {"$message_type": "artifact", "emit": "link", "artifact": "/out/test"},
        ]
        stages, artifacts = internal_passes(
            "non-json\n" + "\n".join(map(json.dumps, events))
        )
        self.assertEqual(stages, {"codegen": 15_000, "link": 22_000})
        self.assertEqual(artifacts, ["/out/test"])

    @patch("measure_test.run_binary")
    @patch("measure_test.Resident")
    def test_rejected_compilation_never_launches_the_existing_binary(
        self, fake_resident, run_binary
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            file = root / PACKAGE / "src/string.rs"
            file.parent.mkdir(parents=True)
            file.write_text("good")
            binary = root / "old-binary"
            binary.write_bytes(b"old still-runnable artifact")
            process = fake_resident.return_value
            process.startup = {"external_ns": 1}
            process.check.return_value = {"route": "resident", "errors": 1}
            process.finish.return_value = {
                "state": "rejected",
                "returncode": 1,
                "completed_ns": 2,
                "error_codes": ["E0308"],
                "link_artifacts": [],
                "compiler_timing_ns": {},
            }
            result = resident_transaction(
                [],
                {},
                root,
                binary,
                {"good": "good", "error": "broken"},
                ("compile-error", "good", "error", "compile_error"),
                root / "logs",
            )
            self.assertEqual(result["outcome"], "compile_error")
            self.assertTrue(result["binary_unchanged"])
            self.assertFalse(result["binary_executed"])
            run_binary.assert_not_called()


if __name__ == "__main__":
    unittest.main()
