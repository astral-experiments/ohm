import json
import unittest

from source_diagnostics import (
    DiagnosticProjector,
    UnmappableDiagnostic,
    merge_diagnostics,
    normalize_diagnostics,
    parse_diagnostics,
)

FILE = "src/lexer.rs"
RAW_FILE = "/snapshot/crates/ruff_python_parser/src/lexer.rs"
SOURCE = """#![allow(dead_code)]
fn source(x: u8) -> u8 { x }
fn local(x: u8) -> bool {
    source(x)
}
fn unrelated() -> bool { 42u8 }
"""


def span(source, value, *, after="", primary=True, label=None):
    start = source.index(value, source.index(after))
    line = source.count("\n", 0, start) + 1
    column = start - source.rfind("\n", 0, start)
    return {
        "file_name": RAW_FILE,
        "byte_start": len(source[:start].encode()),
        "byte_end": len(source[: start + len(value)].encode()),
        "line_start": line,
        "line_end": line,
        "column_start": column,
        "column_end": column + len(value),
        "is_primary": primary,
        "text": [
            {
                "text": source.splitlines()[line - 1],
                "highlight_start": column,
                "highlight_end": column + len(value),
            }
        ],
        "label": label,
        "suggested_replacement": None,
        "suggestion_applicability": None,
        "expansion": None,
    }


def local_error(source, tail):
    primary = span(source, tail, label="expected `bool`, found `u8`")
    secondary = span(
        source,
        "bool",
        after="fn local",
        primary=False,
        label="expected `bool` because of return type",
    )
    rendered = f"\x1b[91merror[E0308]\x1b[0m: mismatched types\n --> {RAW_FILE}:{primary['line_start']}:{primary['column_start']}\n  |\n"
    for item, glyph in ((secondary, "-"), (primary, "^")):
        line = item["line_start"]
        column = item["column_start"]
        width = item["column_end"] - column
        rendered += f"{line} | {source.splitlines()[line - 1]}\n  |{' ' * column}{glyph * width} {item['label']}\n"
    return {
        "$message_type": "diagnostic",
        "message": "mismatched types",
        "code": {"code": "E0308", "explanation": "expected type did not match"},
        "level": "error",
        "spans": [primary, secondary],
        "children": [],
        "rendered": rendered + "\n",
    }


def one_span_diagnostic(source, value, *, after="", level="error", code="E0308"):
    item = span(source, value, after=after)
    return {
        "$message_type": "diagnostic",
        "message": "independent diagnostic",
        "code": {"code": code, "explanation": None},
        "level": level,
        "spans": [item],
        "children": [],
        "rendered": None,
    }


def project(diagnostics, old, new):
    return DiagnosticProjector({FILE: old}, {FILE: new}).project_diagnostics(
        diagnostics
    )


class SourceDiagnosticsTest(unittest.TestCase):
    def test_replacement_updates_complete_rendered_diagnostic(self):
        current = SOURCE.replace("source(x)\n", "0u8\n")
        actual = project([local_error(SOURCE, "source(x)")], SOURCE, current)
        expected = normalize_diagnostics([local_error(current, "0u8")], {FILE: current})
        self.assertEqual(actual, expected)
        self.assertEqual(actual[0]["spans"][0]["column_end"], 8)
        self.assertEqual(
            actual[0]["rendered"],
            "error[E0308]: mismatched types\n"
            " --> src/lexer.rs:4:5\n"
            "  |\n"
            "3 | fn local(x: u8) -> bool {\n"
            "  |                    ---- expected `bool` because of return type\n"
            "4 |     0u8\n"
            "  |     ^^^ expected `bool`, found `u8`\n\n",
        )

    def test_line_shift_preserves_utf8_byte_offsets_and_unrelated_error(self):
        original = SOURCE.replace("fn source", "// café λ\nfn source")
        current = original.replace("fn local", "// naïve β\nfn local").replace(
            "source(x)\n", "0u8\n"
        )
        old = [
            local_error(original, "source(x)"),
            one_span_diagnostic(original, "42u8"),
        ]
        fresh = [local_error(current, "0u8"), one_span_diagnostic(current, "42u8")]
        actual = project(old, original, current)
        self.assertEqual(actual, normalize_diagnostics(fresh, {FILE: current}))
        main = actual[0]["spans"][0]
        self.assertEqual(main["line_start"], 6)
        self.assertEqual(main["byte_start"], len(current.split("0u8")[0].encode()))
        self.assertIn("src/lexer.rs:6:5", actual[0]["rendered"])
        unrelated = actual[1]["spans"][0]
        self.assertEqual(unrelated["line_start"], 8)
        self.assertEqual(
            unrelated["text"][0]["text"], "fn unrelated() -> bool { 42u8 }"
        )

    def test_owner_clear_removes_warnings_but_preserves_independent_errors(self):
        warning = one_span_diagnostic(
            SOURCE, "x", after="fn local", level="warning", code="unused_variables"
        )
        local = local_error(SOURCE, "source(x)")
        unrelated = one_span_diagnostic(SOURCE, "42u8")
        owner = (
            SOURCE.encode().index(b"fn local"),
            SOURCE.encode().index(b"fn unrelated"),
        )
        self.assertEqual(
            merge_diagnostics([local, warning, unrelated], [unrelated], FILE, owner),
            [unrelated],
        )
        self.assertEqual(
            len(merge_diagnostics([unrelated], [local, unrelated], FILE, owner)), 2
        )
        self.assertEqual(
            parse_diagnostics(
                [
                    "source-start\t1",
                    json.dumps({"reason": "compiler-message", "message": warning}),
                ]
            ),
            [warning],
        )

    def test_ambiguous_insertion_inside_original_highlight_falls_back(self):
        current = SOURCE.replace("source(x)\n", "source(x, 1)\n")
        with self.assertRaisesRegex(UnmappableDiagnostic, "crosses a diagnostic span"):
            project([local_error(SOURCE, "source(x)")], SOURCE, current)

    def test_changed_distance_between_rendered_labels_falls_back(self):
        current = SOURCE.replace(
            "    source(x)", "    // newly added context\n    source(x)"
        )
        with self.assertRaisesRegex(UnmappableDiagnostic, "terminal snippet context"):
            project([local_error(SOURCE, "source(x)")], SOURCE, current)


if __name__ == "__main__":
    unittest.main()
