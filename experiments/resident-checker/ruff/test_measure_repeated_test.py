"""Regression checks for building multiple Ruff test artifacts in one compiler."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from measure_repeated_test import (
    RepeatedResident,
    disable_cargo_debuginfo,
    disable_native_debuginfo,
    objects_summary,
    parse_codegen_unit,
    resident_transaction,
    validate_capture_profile,
    verify_cache_files,
)
from run_tests import PACKAGE


class TestRepeatedResident(unittest.TestCase):
    def test_debuginfo_is_disabled_for_cargo_and_native_codegen(self):
        command = [
            "/driver",
            "-C",
            "debuginfo=2",
            "-Csplit-debuginfo=packed",
            "-C",
            "opt-level=1",
            "-Cdebuginfo=line-tables-only",
            "--test",
        ]
        self.assertEqual(
            disable_native_debuginfo(command),
            [
                "/driver",
                "-C",
                "opt-level=1",
                "--test",
                "-C",
                "debuginfo=0",
                "-C",
                "split-debuginfo=off",
            ],
        )
        environment = {
            "CARGO_PROFILE_TEST_DEBUG": "2",
            "CARGO_PROFILE_DEV_SPLIT_DEBUGINFO": "packed",
            "CARGO_PROFILE_BENCH_DEBUG": "2",
        }
        disable_cargo_debuginfo(environment)
        self.assertEqual(
            environment,
            {
                "CARGO_PROFILE_DEV_DEBUG": "0",
                "CARGO_PROFILE_DEV_SPLIT_DEBUGINFO": "off",
                "CARGO_PROFILE_TEST_DEBUG": "0",
                "CARGO_PROFILE_TEST_SPLIT_DEBUGINFO": "off",
                "CARGO_PROFILE_BENCH_DEBUG": "2",
            },
        )
        with self.assertRaisesRegex(RuntimeError, "dependencies may have a different"):
            validate_capture_profile({"argv": command})
        validate_capture_profile(
            {"argv": ["rustc", "-C", "debuginfo=0", "-Csplit-debuginfo=off"]}
        )
        validate_capture_profile({"argv": ["rustc", "-Copt-level=1"]})

    @patch("measure_repeated_test.run_binary")
    def test_compile_error_never_executes_previous_binary_and_worker_survives(
        self, run
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / PACKAGE / "src/string.rs"
            source.parent.mkdir(parents=True)
            source.write_text("good")
            binary = root / "old-binary"
            binary.write_bytes(b"this old artifact still exists")
            process = Mock()
            process.pid = 1234
            process.alive.return_value = True
            process.check.return_value = {"route": "resident", "errors": 1}
            process.compile.return_value = {
                "state": "rejected",
                "status": None,
                "completed_ns": 2,
                "error_codes": ["E0308"],
                "link_artifacts": [],
                "compiler_timing_ns": {},
            }
            result = resident_transaction(
                process,
                root,
                binary,
                {"good": "good", "error": "wrong"},
                ("compile-error", "good", "error", "compile_error"),
                root / "logs",
            )
            self.assertEqual(result["pid"], 1234)
            self.assertEqual(result["outcome"], "compile_error")
            self.assertEqual(result["binary_before"], result["binary_after"])
            self.assertEqual(len(result["binary_after"]["sha256"]), 64)
            self.assertFalse(result["binary_executed"])
            self.assertEqual(process.alive.call_count, 2)
            run.assert_not_called()

    def process(self, path, lines, errors):
        resident = RepeatedResident.__new__(RepeatedResident)
        resident.version = 9
        resident.process = Mock()
        resident.process.poll.return_value = None
        resident.stdout = io.StringIO()
        resident.process.stdout.readline.side_effect = [line + "\n" for line in lines]
        resident.stderr_path = path / "process.stderr"
        resident.stderr_path.write_text(errors)
        return resident

    def test_per_build_protocol_waits_for_link_and_preserves_codegen_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            events = [
                {
                    "$message_type": "section_timing",
                    "name": "codegen",
                    "event": "start",
                    "timestamp": 1,
                },
                {
                    "$message_type": "section_timing",
                    "name": "codegen",
                    "event": "end",
                    "timestamp": 2,
                },
                {
                    "$message_type": "section_timing",
                    "name": "link",
                    "event": "start",
                    "timestamp": 2,
                },
                {
                    "$message_type": "section_timing",
                    "name": "link",
                    "event": "end",
                    "timestamp": 3,
                },
                {"$message_type": "artifact", "emit": "link", "artifact": "/test"},
            ]
            errors = (
                "ignored before transaction\n"
                + "\n".join(map(json.dumps, events))
                + "\nsource-build-finished\t9\n"
            )
            resident = self.process(
                path,
                [
                    "build\t9\tready\t-",
                    "build-analysis\t9\t30",
                    "build-codegen-unit\t9\ta\tcompiled\tfingerprint-a",
                    "build-codegen-unit\t9\tb\treused\tfingerprint-b",
                    "build-finished\t9\t40\tok",
                ],
                errors,
            )
            output = path / "build.stderr"
            result = resident.compile(len("ignored before transaction\n"), output)
            self.assertNotIn("ignored", output.read_text())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(
                result["compiler_timing_ns"], {"codegen": 1000, "link": 1000}
            )
            self.assertEqual(result["link_artifacts"], ["/test"])
            self.assertEqual(
                [unit["disposition"] for unit in result["codegen_units"]],
                ["compiled", "reused"],
            )
            resident.process.stdin.write.assert_called_once_with("build\t9\n")

    def test_rejection_requires_its_stderr_completion_barrier(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            resident = self.process(
                path,
                ["build\t9\trejected\tsource-error"],
                "previous compiler JSON only\n",
            )
            with self.assertRaisesRegex(RuntimeError, "missing completion barrier"):
                resident.compile(0, path / "build.stderr")

    def test_codegen_events_compare_objects_against_previous_revision(self):
        def row(phase, *units):
            parsed = [parse_codegen_unit(unit) for unit in units]
            for unit in parsed:
                unit["cache_files"] = {
                    "regular": {"sha256": unit["fingerprint"] * 64},
                    "global_assembly": None,
                }
            return {
                "phase": phase,
                "resident": {
                    "build": {
                        "state": "ready",
                        "codegen_units": parsed,
                    }
                },
            }

        result = objects_summary(
            [
                row(
                    "baseline", ("first", "compiled", "a"), ("second", "compiled", "x")
                ),
                row(
                    "unchanged-rebuild",
                    ("first", "reused", "a"),
                    ("second", "reused", "x"),
                ),
                row(
                    "behavior-edit",
                    ("first", "compiled", "b"),
                    ("second", "reused", "x"),
                ),
                row(
                    "behavior-repair",
                    ("first", "compiled", "a"),
                    ("second", "reused", "bad"),
                ),
            ]
        )
        unchanged = result["fingerprint_comparisons_by_phase"]["unchanged-rebuild"]
        self.assertEqual(unchanged["reused_matching_previous_external_sha256"], 2)
        self.assertEqual(
            unchanged["compiled_with_matching_previous_external_sha256"], 0
        )
        edit = result["fingerprint_comparisons_by_phase"]["behavior-edit"]
        self.assertEqual(edit["reused_matching_previous_fingerprints"], 1)
        self.assertEqual(edit["compiled_with_changed_previous_fingerprints"], 1)
        self.assertEqual(edit["reused_with_mismatched_previous_fingerprints"], 0)
        self.assertEqual(edit["reused_matching_previous_external_sha256"], 1)
        self.assertEqual(edit["compiled_with_changed_previous_external_sha256"], 1)
        repair = result["fingerprint_comparisons_by_phase"]["behavior-repair"]
        self.assertEqual(repair["reused_with_mismatched_previous_fingerprints"], 1)
        self.assertEqual(repair["reused_with_mismatched_previous_external_sha256"], 1)

    def test_cache_files_are_hashed_independently_from_native_fingerprint(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            (cache / "unit.o").write_bytes(b"actual native object")
            (cache / "unit.asm.o").write_bytes(b"actual native assembly object")
            unit = parse_codegen_unit(["unit", "compiled", "native-128bit"])
            verify_cache_files(cache, [unit])
            self.assertEqual(unit["fingerprint"], "native-128bit")
            self.assertEqual(len(unit["cache_files"]["regular"]["sha256"]), 64)
            self.assertNotEqual(
                unit["cache_files"]["regular"]["sha256"],
                unit["cache_files"]["global_assembly"]["sha256"],
            )
            with self.assertRaisesRegex(RuntimeError, "missing cached regular object"):
                verify_cache_files(
                    cache, [parse_codegen_unit(["missing", "compiled", "hash"])]
                )

    def test_absent_codegen_events_are_not_reported_as_object_reuse(self):
        result = objects_summary(
            [{"resident": {"build": {"state": "ready", "codegen_units": []}}}]
        )
        self.assertFalse(result["instrumented"])
        self.assertIn("neither unchanged object reuse", result["explanation"])


if __name__ == "__main__":
    unittest.main()
