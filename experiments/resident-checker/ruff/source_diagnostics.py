"""Project resident rustc diagnostics onto a narrowly edited Ruff source snapshot.

The resident checker still emits byte positions from the original compiler source
map. This module uses that output and the two source snapshots only; freshly
compiled diagnostics are a separate correctness oracle, never an input here.
Edits crossing a diagnostic boundary, changed multiline labels, or unfamiliar
changed terminal annotations require the caller to fall back to a fresh check.
"""

import bisect
import difflib
import json
import re
from collections.abc import Iterable, Mapping

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
HEADER = re.compile(r"^(\s*)(-->|:::)(\s+)(.+):(\d+):(\d+)$")
SOURCE_ROW = re.compile(r"^(\s*)(\d+) \|(.*)$")
ANNOTATION = re.compile(r"^\s*\|(.*)$")
MARKS = re.compile(r"^(\s*)([\^~-]+)(.*)$")
WORKSPACE_PATH = re.compile(
    r"(?:[^\s():]*[/\\])?crates[/\\]ruff_python_parser[/\\](src[/\\][^\s():]+)"
)


class UnmappableDiagnostic(ValueError):
    """The original emitted positions do not determine exact current diagnostics."""


def path_key(path):
    """Make package source paths independent of archive and invocation directories."""
    path = str(path).replace("\\", "/")
    anchor = "crates/ruff_python_parser/"
    if anchor in path:
        return path.split(anchor, 1)[1]
    if "/crates/" in path:
        return "crates/" + path.split("/crates/", 1)[1]
    return path.removeprefix("./")


def parse_diagnostics(lines: Iterable[str], *, include_warnings=True):
    """Read span-bearing errors from either raw rustc or Cargo JSON streams."""
    if isinstance(lines, str):
        lines = lines.splitlines()
    allowed = {"error", "warning"} if include_warnings else {"error"}
    result = []
    for line in lines:
        try:
            item = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(item, dict):
            continue
        if item.get("reason") == "compiler-message":
            item = item["message"]
        if item.get("level") in allowed and item.get("spans"):
            result.append(item)
    return result


def _common_prefix(left, right):
    count = 0
    for a, b in zip(left, right):
        if a != b:
            break
        count += 1
    return count


def _utf8_boundary(source, offset):
    return offset == len(source) or source[offset] & 0xC0 != 0x80


def _matching_edge(left, right, *, suffix=False):
    low, high = 0, min(len(left), len(right))
    while low < high:
        middle = (low + high + 1) // 2
        a, b = (
            (left[-middle:], right[-middle:])
            if suffix
            else (
                left[:middle],
                right[:middle],
            )
        )
        if a == b:
            low = middle
        else:
            high = middle - 1
    return low


class _Source:
    def __init__(self, original, current):
        self.old = original.encode()
        self.new = current.encode()
        self.old_lines = self.old.splitlines(keepends=True)
        self.new_lines = self.new.splitlines(keepends=True)
        self.old_starts = self._starts(self.old_lines)
        self.new_starts = self._starts(self.new_lines)
        self.edits = []
        if self.old == self.new:
            return
        # Strip the identical outer bytes before diffing lines: checking one small
        # edit should not require matching every repeated line in a parser file.
        prefix = _matching_edge(self.old, self.new)
        while prefix and (
            not _utf8_boundary(self.old, prefix) or not _utf8_boundary(self.new, prefix)
        ):
            prefix -= 1
        suffix = _matching_edge(self.old[prefix:], self.new[prefix:], suffix=True)
        while suffix and (
            not _utf8_boundary(self.old, len(self.old) - suffix)
            or not _utf8_boundary(self.new, len(self.new) - suffix)
        ):
            suffix -= 1
        old_fragment = self.old[prefix : len(self.old) - suffix].splitlines(
            keepends=True
        )
        new_fragment = self.new[prefix : len(self.new) - suffix].splitlines(
            keepends=True
        )
        old_offsets, new_offsets = (
            self._starts(old_fragment),
            self._starts(new_fragment),
        )
        matcher = difflib.SequenceMatcher(
            None, old_fragment, new_fragment, autojunk=False
        )
        for tag, a1, a2, b1, b2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            old_start, old_end = prefix + old_offsets[a1], prefix + old_offsets[a2]
            new_start, new_end = prefix + new_offsets[b1], prefix + new_offsets[b2]
            old_piece, new_piece = (
                self.old[old_start:old_end],
                self.new[new_start:new_end],
            )
            shared_start = _common_prefix(old_piece, new_piece)
            while shared_start and (
                not _utf8_boundary(old_piece, shared_start)
                or not _utf8_boundary(new_piece, shared_start)
            ):
                shared_start -= 1
            old_start += shared_start
            new_start += shared_start
            old_piece, new_piece = (
                self.old[old_start:old_end],
                self.new[new_start:new_end],
            )
            suffix = _common_prefix(reversed(old_piece), reversed(new_piece))
            while suffix and (
                not _utf8_boundary(old_piece, len(old_piece) - suffix)
                or not _utf8_boundary(new_piece, len(new_piece) - suffix)
            ):
                suffix -= 1
            self.edits.append(
                (old_start, old_end - suffix, new_start, new_end - suffix)
            )

    @staticmethod
    def _starts(lines):
        result = [0]
        for line in lines:
            result.append(result[-1] + len(line))
        return result

    def point(self, offset, *, right):
        delta = 0
        for old_start, old_end, new_start, new_end in self.edits:
            if offset < old_start:
                return offset + delta
            if old_start == old_end and offset == old_start:
                return new_end if right else new_start
            if offset == old_start:
                return new_start
            if offset < old_end:
                raise UnmappableDiagnostic(f"byte {offset} is inside replaced source")
            if offset == old_end:
                return new_end
            delta = new_end - old_end
        return offset + delta

    def span(self, start, end):
        if end < start or start < 0 or end > len(self.old):
            raise UnmappableDiagnostic(f"invalid original span {start}..{end}")
        for old_start, old_end, new_start, new_end in self.edits:
            if start == end == old_start == old_end:
                raise UnmappableDiagnostic(
                    "zero-width diagnostic at an insertion boundary"
                )
            if old_start != old_end and start == old_start and end == old_end:
                return new_start, new_end
            if old_start == old_end:
                if start < old_start < end:
                    raise UnmappableDiagnostic("insertion crosses a diagnostic span")
            elif start < old_end and end > old_start:
                raise UnmappableDiagnostic("replacement crosses a diagnostic span")
        return self.point(start, right=True), self.point(end, right=False)

    def position(self, offset, *, current):
        source = self.new if current else self.old
        starts = self.new_starts if current else self.old_starts
        lines = self.new_lines if current else self.old_lines
        if offset < 0 or offset > len(source):
            raise UnmappableDiagnostic(f"byte offset {offset} is outside the source")
        index = bisect.bisect_right(starts, offset) - 1
        if index == len(lines) and lines and not lines[-1].endswith((b"\n", b"\r")):
            index -= 1
        return index + 1, len(source[starts[index] : offset].decode()) + 1

    def byte(self, line, column, *, current):
        starts = self.new_starts if current else self.old_starts
        if line < 1 or line > len(starts) or column < 1:
            raise UnmappableDiagnostic(f"invalid diagnostic location {line}:{column}")
        text = self.line(line, current=current)
        if column > len(text) + 1:
            raise UnmappableDiagnostic(f"invalid diagnostic column {line}:{column}")
        return starts[line - 1] + len(text[: column - 1].encode())

    def line(self, line, *, current):
        lines = self.new_lines if current else self.old_lines
        if line == len(lines) + 1:
            return ""
        if line < 1 or line > len(lines):
            raise UnmappableDiagnostic(f"missing source line {line}")
        return lines[line - 1].decode().removesuffix("\n").removesuffix("\r")

    def text(self, start, end):
        start_line, start_column = self.position(start, current=True)
        end_line, end_column = self.position(end, current=True)
        result = []
        for number in range(start_line, end_line + 1):
            line = self.line(number, current=True)
            result.append(
                {
                    "text": line,
                    "highlight_start": start_column if number == start_line else 1,
                    "highlight_end": end_column
                    if number == end_line
                    else len(line) + 1,
                }
            )
        return result


def _all_spans(diagnostic):
    yield from diagnostic.get("spans", [])
    for child in diagnostic.get("children", []):
        yield from _all_spans(child)


def _rendered_path(text, names):
    for old, new in sorted(names.items(), key=lambda item: -len(item[0])):
        if old != new:
            text = text.replace(old, new)
    return WORKSPACE_PATH.sub(lambda match: match[1].replace("\\", "/"), text)


class DiagnosticProjector:
    def __init__(
        self, original_sources: Mapping[str, str], current_sources: Mapping[str, str]
    ):
        old = {path_key(key): value for key, value in original_sources.items()}
        new = {path_key(key): value for key, value in current_sources.items()}
        if old.keys() != new.keys():
            raise UnmappableDiagnostic(
                "old and new snapshots must contain the same source files"
            )
        self.sources = {key: _Source(value, new[key]) for key, value in old.items()}

    def _span(self, span):
        result = dict(span)
        file = result["file_name"] = path_key(span["file_name"])
        if source := self.sources.get(file):
            start, end = source.span(span["byte_start"], span["byte_end"])
            result.update(
                byte_start=start,
                byte_end=end,
                line_start=source.position(start, current=True)[0],
                column_start=source.position(start, current=True)[1],
                line_end=source.position(end, current=True)[0],
                column_end=source.position(end, current=True)[1],
                text=source.text(start, end),
            )
        if expansion := span.get("expansion"):
            result["expansion"] = dict(expansion)
            for name in ("span", "def_site_span"):
                if expansion.get(name):
                    result["expansion"][name] = self._span(expansion[name])
        return result

    def _diagnostic(self, item):
        result = {
            name: item.get(name)
            for name in ("message", "code", "level", "spans", "children", "rendered")
        }
        result["spans"] = [self._span(span) for span in item.get("spans", [])]
        result["children"] = [
            self._diagnostic(child) for child in item.get("children", [])
        ]
        if item.get("rendered") is not None:
            result["rendered"] = self._render(item["rendered"], item, result)
        return result

    def _render(self, text, old, new):
        pairs = list(zip(_all_spans(old), _all_spans(new)))
        names = {
            old_span["file_name"]: new_span["file_name"] for old_span, new_span in pairs
        }
        plain = _rendered_path(ANSI.sub("", text), names)
        if not any(source.edits for source in self.sources.values()):
            return plain
        rows = []
        file = None
        old_line = new_line = None
        previous_source = None
        for row in plain.splitlines(keepends=True):
            end = "\n" if row.endswith("\n") else ""
            content = row.removesuffix("\n")
            if header := HEADER.match(content):
                indent, arrow, spacing, file, line, column = header.groups()
                file = path_key(file)
                source = self.sources.get(file)
                line, column = int(line), int(column)
                for a, b in pairs:
                    if (
                        path_key(a["file_name"]) == file
                        and a["line_start"] == line
                        and a["column_start"] == column
                    ):
                        line, column = b["line_start"], b["column_start"]
                        break
                else:
                    if source and source.edits:
                        offset = source.byte(line, column, current=False)
                        line, column = source.position(
                            source.point(offset, right=True), current=True
                        )
                rows.append(
                    ("header", (indent, arrow, spacing, file, line, column), end)
                )
                old_line = new_line = previous_source = None
                continue
            if numeric := SOURCE_ROW.match(content):
                indent, number, code = numeric.groups()
                old_line = int(number)
                new_line = old_line
                source = self.sources.get(file)
                if source and source.edits:
                    eligible = [
                        (a, b)
                        for a, b in pairs
                        if path_key(a["file_name"]) == file
                        and a["line_start"] == old_line
                    ]
                    if eligible:
                        _, span = max(eligible, key=lambda pair: pair[0]["is_primary"])
                        new_line = span["line_start"]
                    else:
                        offset = source.byte(old_line, 1, current=False)
                        new_line, _ = source.position(
                            source.point(offset, right=True), current=True
                        )
                    original_line = source.line(old_line, current=False)
                    current_line = source.line(new_line, current=True)
                    if original_line != current_line:
                        if (
                            code != " " + original_line
                            or "\t" in original_line + current_line
                        ):
                            raise UnmappableDiagnostic(
                                "changed rendered source has unfamiliar formatting"
                            )
                        code = " " + current_line
                    if previous_source:
                        previous_old, previous_new = previous_source
                        if (old_line - previous_old) != (new_line - previous_new):
                            raise UnmappableDiagnostic(
                                "changed terminal snippet context is ambiguous"
                            )
                    previous_source = old_line, new_line
                rows.append(("source", (indent, number, new_line, code), end))
                continue
            if annotation := ANNOTATION.match(content):
                payload = annotation[1]
                source = self.sources.get(file)
                marks = MARKS.match(payload)
                if source and source.edits and old_line is not None and marks:
                    indent, glyphs, remainder = marks.groups()
                    candidates = []
                    for a, b in pairs:
                        if (
                            path_key(a["file_name"]) == file
                            and a["line_start"] == old_line == a["line_end"]
                            and a["column_start"] == len(indent)
                            and max(1, a["column_end"] - a["column_start"])
                            == len(glyphs)
                            and (glyphs[0] == "^") == a["is_primary"]
                        ):
                            candidates.append((a, b))
                    if len(candidates) > 1:
                        candidates = [
                            pair
                            for pair in candidates
                            if pair[0].get("label") and pair[0]["label"] in remainder
                        ]
                    if len(candidates) == 1:
                        _, span = candidates[0]
                        if span["line_start"] != span["line_end"]:
                            raise UnmappableDiagnostic(
                                "changed terminal multiline annotation"
                            )
                        width = max(1, span["column_end"] - span["column_start"])
                        payload = (
                            " " * span["column_start"] + glyphs[0] * width + remainder
                        )
                    elif source.line(old_line, current=False) != source.line(
                        new_line, current=True
                    ):
                        raise UnmappableDiagnostic(
                            "changed terminal annotation has no unique rustc span"
                        )
                elif (
                    source
                    and source.edits
                    and old_line is not None
                    and payload.strip()
                    and not payload.lstrip().startswith("=")
                ):
                    if source.line(old_line, current=False) != source.line(
                        new_line, current=True
                    ):
                        raise UnmappableDiagnostic(
                            "changed terminal annotation uses unsupported layout"
                        )
                rows.append(("annotation", payload, end))
                continue
            rows.append(("other", content, end))
        old_width = max(
            (len(data[0]) + len(data[1]) for kind, data, _ in rows if kind == "source"),
            default=0,
        )
        new_width = max(
            (len(str(data[2])) for kind, data, _ in rows if kind == "source"),
            default=old_width,
        )
        rendered = []
        for kind, data, end in rows:
            if kind == "header":
                indent, arrow, spacing, file, line, column = data
                indent = " " * max(0, len(indent) + new_width - old_width)
                content = f"{indent}{arrow}{spacing}{file}:{line}:{column}"
            elif kind == "source":
                _, _, number, code = data
                content = f"{number:>{new_width}} |{code}"
            elif kind == "annotation" and old_width:
                content = " " * (new_width + 1) + "|" + data
            else:
                content = data
            rendered.append(content + end)
        return "".join(rendered)

    def project_diagnostics(self, diagnostics):
        return sorted(
            (self._diagnostic(item) for item in diagnostics), key=_diagnostic_key
        )


def _diagnostic_key(item):
    spans = tuple(
        (path_key(span["file_name"]), span["byte_start"], span["byte_end"])
        for span in item.get("spans", [])
        if span.get("is_primary")
    )
    code = item.get("code")
    return (
        spans,
        (code.get("code") if isinstance(code, dict) else code) or "",
        item.get("level", ""),
        item.get("message", ""),
    )


def normalize_diagnostics(diagnostics, sources=None, *, workspace=None):
    """Canonicalize fresh compiler diagnostics for exact projected comparisons."""
    del workspace  # File names are intentionally stable relative to the package.
    sources = sources or {}
    return DiagnosticProjector(sources, sources).project_diagnostics(diagnostics)


def merge_diagnostics(baseline, emitted, edited_file, edited_owner_original_range):
    """Retain old errors outside the edited owner and replace that owner's results.

    Query cache reuse means an unrelated owner may not emit again. The caller must
    store the last complete diagnostics for each compiler epoch and pass byte
    ranges in that epoch's original source. Returned diagnostics remain in that
    source coordinate system, for subsequent projection to the current snapshot.
    """
    owner_start, owner_end = edited_owner_original_range
    edited_file = path_key(edited_file)

    def belongs(item):
        for span in item.get("spans", []):
            if not span.get("is_primary") or path_key(span["file_name"]) != edited_file:
                continue
            start, end = span["byte_start"], span["byte_end"]
            if (start < owner_end and end > owner_start) or (
                owner_start <= start == end <= owner_end
            ):
                return True
        return False

    result = {_diagnostic_key(item): item for item in baseline if not belongs(item)}
    result.update((_diagnostic_key(item), item) for item in emitted)
    return sorted(result.values(), key=_diagnostic_key)
