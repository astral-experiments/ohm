"""Checks for matching arbitrary source changes against independently restarted rustc."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from measure_arbitrary import (
    CASES,
    MISSING_ERROR,
    PARSE_ERROR,
    TYPE_ERROR,
    Worker,
    compare,
    diagnostic_locations,
    run_revision,
    source_diagnostics,
    test_output,
    write_sources,
)


class TestArbitrary(unittest.TestCase):
    def test_scenarios_cover_structural_edits_and_real_behavior_changes(self):
        cases = {case.name: case for case in CASES}
        self.assertEqual(next(iter(cases)), "initial-malformed")
        self.assertEqual(cases["initial-malformed"].diagnostic, PARSE_ERROR)
        self.assertEqual(cases["type-error"].diagnostic, TYPE_ERROR)
        self.assertEqual(cases["missing-module"].diagnostic, MISSING_ERROR)
        self.assertEqual(
            cases["multiple-function-bodies"].failed_tests,
            ("tests::behavior", "tests::helper"),
        )
        old_signature = cases["multiple-function-repair"].files
        new_signature = cases["signature-and-callers"].files
        self.assertIn("pub fn calculate(input: i32)", old_signature["model.rs"])
        self.assertIn("super::compute(3)", old_signature["lib.rs"])
        self.assertIn(
            "pub fn calculate(input: i32, offset: i32)", new_signature["model.rs"]
        )
        self.assertIn("super::compute(2, 2)", new_signature["lib.rs"])
        self.assertIn("{ 7 }", cases["macro-definition"].files["lib.rs"])
        self.assertIn(
            "use model::alternative as compute",
            cases["import-resolution"].files["lib.rs"],
        )
        self.assertIn("extra.rs", cases["module-added"].files)
        self.assertNotIn("extra.rs", cases["module-removed"].files)
        self.assertEqual(
            cases["module-behavior"].tests["tests::extra_module"], "FAILED"
        )

    def test_source_writer_removes_deleted_modules_but_keeps_unchanged_mtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_sources(directory, {"lib.rs": "lib", "extra.rs": "extra"})
            lib = directory / "lib.rs"
            previous_mtime = lib.stat().st_mtime_ns
            write_sources(directory, {"lib.rs": "lib", "extra.rs": "changed"})
            self.assertEqual(lib.stat().st_mtime_ns, previous_mtime)
            self.assertEqual((directory / "extra.rs").read_text(), "changed")
            write_sources(directory, {"lib.rs": "lib"})
            self.assertFalse((directory / "extra.rs").exists())
            self.assertEqual(lib.stat().st_mtime_ns, previous_mtime)

    def test_diagnostics_preserve_codes_and_messages_but_ignore_footer(self):
        parse_error = {
            "level": "error",
            "spans": [
                {
                    "is_primary": True,
                    "file_name": "/temporary/source.rs",
                    "line_start": 2,
                    "line_end": 2,
                    "column_start": 3,
                    "column_end": 4,
                }
            ],
            "code": None,
            "message": "expected expression, found `;`",
        }
        type_error = dict(
            parse_error, code={"code": "E0308"}, message="mismatched types"
        )
        footer = dict(parse_error, spans=[], message="aborting due to 1 previous error")
        text = "\n".join(
            [
                "resident-started\t1",
                json.dumps(parse_error),
                json.dumps({"reason": "compiler-message", "message": type_error}),
                json.dumps(footer),
                "resident-finished\t1",
            ]
        )
        self.assertEqual(
            source_diagnostics(text),
            [
                {"code": None, "message": "expected expression, found `;`"},
                {"code": "E0308", "message": "mismatched types"},
            ],
        )
        location = [
            {
                "file": "source.rs",
                "line_start": 2,
                "line_end": 2,
                "column_start": 3,
                "column_end": 4,
            }
        ]
        self.assertEqual(diagnostic_locations(text), [location, location])

    @patch("measure_arbitrary.run_test")
    def test_rejected_compile_does_not_run_stale_executable(self, run_test):
        case = next(case for case in CASES if case.name == "type-error")
        compile_case = Mock(
            return_value={
                "status": 1,
                "diagnostics": [{"code": "E0308", "message": "mismatched types"}],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "test-bin"
            binary.write_bytes(b"old executable must not run")
            result = run_revision(compile_case, case, binary, root, {}, root, 9, 10)
            self.assertTrue(result["stale_artifact_preserved"])
            self.assertIsNone(result["test"])
            self.assertEqual(binary.read_bytes(), b"old executable must not run")
            compile_case.assert_called_once_with(9)
        run_test.assert_not_called()

    def test_exact_libtest_output_compares_except_elapsed_time(self):
        template = (
            "running 2 tests\n"
            "test tests::behavior ... FAILED\n"
            "test tests::helper ... ok\n\n"
            "failures:\n\n---- tests::behavior stdout ----\n"
            "thread 'tests::behavior' ({thread}) panicked at source.rs:4:1:\n"
            "assertion `left == right` failed\n  left: 8\n right: 6\n\n"
            "test result: FAILED. 1 passed; 1 failed; 0 ignored; 0 measured; "
            "0 filtered out; finished in {timing}\n"
        )
        first = test_output(template.format(timing="0.01s", thread=123), "")
        second = test_output(template.format(timing="0.21s", thread=456), "")
        self.assertEqual(first, second)
        self.assertEqual(first["counts"], [1, 1, 0, 0, 0])
        self.assertEqual(
            first["tests"], {"tests::behavior": "FAILED", "tests::helper": "ok"}
        )
        case = next(case for case in CASES if case.name == "macro-definition")
        result = {
            "status": 0,
            "diagnostics": [],
            "diagnostic_locations": [],
            "test": dict(first, status=101),
        }
        compare(case, result, result)
        differing = {
            **result,
            "test": dict(result["test"], normalized_output="unexpected panic"),
        }
        with self.assertRaisesRegex(RuntimeError, "normalized_output differs"):
            compare(case, result, differing)

    def test_worker_reads_result_and_actual_compiler_pid_before_next_revision(self):
        fixture = """import json, os, sys
pid = os.getpid()
print(f'ready\\t{pid}', flush=True)
for line in sys.stdin:
    fields = line.strip().split('\\t')
    if fields[0] == 'quit':
        print(f'bye\\t{pid}', flush=True)
        break
    version = fields[1]
    print(f'resident-started\\t{version}', file=sys.stderr)
    print(f'resident-route\\t{version}\\tsame-process\\t{pid}', file=sys.stderr)
    if version == '1':
        print(json.dumps(dict(level='error', spans=[{}], code=None, message='bad syntax')), file=sys.stderr)
    print(f'resident-finished\\t{version}', file=sys.stderr, flush=True)
    print(f'result\\t{version}\\t{pid}\\t{int(version == "1")}\\t23', flush=True)
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root / "compiler.py"
            fake.write_text(fixture)
            with Worker(
                [sys.executable, str(fake)], root, os.environ, root / "logs"
            ) as worker:
                first = worker.compile(1)
                second = worker.compile(2)
                self.assertEqual(first["route"], "same-process")
                self.assertEqual(first["compiler_pid"], worker.pid)
                self.assertEqual(second["compiler_pid"], worker.pid)
                self.assertEqual(first["status"], 1)
                self.assertEqual(first["internal_ns"], 23)
                self.assertEqual(
                    first["diagnostics"], [{"code": None, "message": "bad syntax"}]
                )
                self.assertEqual(second["diagnostics"], [])
            self.assertIn("bye", (root / "logs" / "protocol.txt").read_text())


if __name__ == "__main__":
    unittest.main()
