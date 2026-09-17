#!/usr/bin/env python3
"""Compare same-session resident real uv const diagnostics with fresh patched rustc."""

import argparse
import collections
import itertools
import json
import os
import subprocess
from pathlib import Path


def span(raw):
    def simple_path(raw_path):
        if not raw_path:
            return None
        value = raw_path.replace("\\", "/")
        for marker in ["crates/uv-pep440/", "library/core/", "library/std/"]:
            if marker in value:
                return value[value.index(marker) :]
        return Path(value).name

    def expansion(value):
        return (
            {
                "span": span(value["span"]) if value.get("span") else None,
                "macro_decl_name": value.get("macro_decl_name"),
                "def_site_span": span(value["def_site_span"])
                if value.get("def_site_span")
                else None,
            }
            if value
            else None
        )

    return {
        "file": simple_path(raw.get("file_name")),
        **{
            key: raw.get(key)
            for key in [
                "byte_start",
                "byte_end",
                "line_start",
                "line_end",
                "column_start",
                "column_end",
                "is_primary",
                "label",
                "suggested_replacement",
                "suggestion_applicability",
            ]
        },
        "expansion": expansion(raw.get("expansion")),
    }


def detail(raw):
    return {
        "level": raw.get("level"),
        "message": raw.get("message"),
        "spans": [span(item) for item in raw.get("spans", [])],
        "children": [detail(item) for item in raw.get("children", [])],
    }


def diagnosis(line):
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if data.get("reason") == "compiler-message":
        data = data["message"]
    if data.get("level") != "error" or not data.get("spans"):
        return None
    code = data.get("code")
    return {
        "code": code.get("code") if isinstance(code, dict) else code,
        "details": detail(data),
    }


def threshold_snippets(line):
    try:
        raw = json.loads(line)
    except ValueError:
        return []

    def walk(value):
        if isinstance(value, dict):
            for name, item in value.items():
                if (
                    name == "text"
                    and isinstance(item, str)
                    and "strings.len() <=" in item
                ):
                    yield item.strip()
                else:
                    yield from walk(item)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)

    return sorted(set(walk(raw)))


def sorted_diagnostics(data):
    return sorted(data, key=lambda entry: json.dumps(entry, sort_keys=True))


def restore_resident_positions(value, deleted_byte, threshold_line, deleted_column):
    if isinstance(value, list):
        return [
            restore_resident_positions(
                item, deleted_byte, threshold_line, deleted_column
            )
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    result = {
        key: restore_resident_positions(
            item, deleted_byte, threshold_line, deleted_column
        )
        for key, item in value.items()
    }
    if result.get("file") == "crates/uv-pep440/src/version.rs":
        for edge in ["start", "end"]:
            offset = result.get(f"byte_{edge}")
            if offset is not None and offset >= deleted_byte:
                result[f"byte_{edge}"] = offset + 1
            column = result.get(f"column_{edge}")
            if (
                result.get(f"line_{edge}") == threshold_line
                and column is not None
                and column >= deleted_column
            ):
                result[f"column_{edge}"] = column + 1
    return result


def prepare_argv(capture, output):
    arguments = []
    stream = iter(capture["argv"][1:])
    for arg in stream:
        if arg == "-C":
            value = next(stream)
            if not value.startswith("incremental="):
                arguments.extend([arg, value])
        elif arg == "--out-dir":
            next(stream)
            arguments.extend([arg, str(output)])
        elif arg.startswith("-Cincremental="):
            continue
        else:
            arguments.append(arg)
    return arguments + ["--cap-lints=allow", "-Zthreads=1"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bootstrap", type=Path, required=True)
    p.add_argument("--capture", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--target", default="aarch64-apple-darwin")
    p.add_argument("--build-only", action="store_true")
    p.add_argument(
        "--check-parser-borrow",
        action="store_true",
        help="also rerun parser function type/borrow checks after checking both diagnostic roots",
    )
    a = p.parse_args()
    output = a.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parent
    host = a.bootstrap.resolve() / a.target
    stage0 = host / "stage0"
    stage1 = host / "stage1"
    env = dict(os.environ, RUSTC_BOOTSTRAP="1")
    if a.check_parser_borrow:
        env["OHM_UV_CHECK_PARSER_BORROW"] = "1"
    stamp = host / "stage1-rustc" / a.target / "release/.librustc-stamp"
    deps = output / "driver-deps"
    deps.mkdir(exist_ok=True)
    for entry in stamp.read_bytes().split(b"\0"):
        if not entry:
            continue
        artifact = Path(os.fsdecode(entry[1:]))
        dest = deps / artifact.name
        if artifact.is_file() and not dest.exists():
            dest.symlink_to(artifact)
    binary = output / "uv-const-driver"
    build = [
        str(stage0 / "bin/rustc"),
        "--edition=2024",
        str(source / "uv_const_driver.rs"),
        "-L",
        f"all={deps}",
        "-C",
        "rpath=yes",
        "-L",
        f"native={stage1 / 'lib'}",
        "-C",
        f"link-arg=-Wl,-rpath,{stage1 / 'lib'}",
        "-o",
        str(binary),
    ]
    built = subprocess.run(build, env=env, capture_output=True, text=True, check=False)
    (output / "driver-build.log").write_text(
        "$ " + " ".join(build) + "\n" + built.stdout + built.stderr
    )
    if built.returncode:
        raise SystemExit(built.stderr)
    if a.build_only:
        return
    capture = json.loads(a.capture.read_text())
    env.update(capture["env"])
    env.pop("CARGO_MAKEFLAGS", None)
    cwd = Path(capture["cwd"])
    archive_marker = cwd / ".ohm-resident-uv-revision"
    if (
        not archive_marker.is_file()
        or archive_marker.read_text().strip()
        != "5d64ede21e9e835e59ecd85329ebefd43faa8211"
    ):
        raise SystemExit(
            "the captured checkout must be the disposable archive for the pinned uv revision"
        )
    rust_output = output / "rust-output"
    rust_output.mkdir(exist_ok=True)
    arguments = prepare_argv(capture, rust_output) + ["--sysroot", str(stage1)]
    resident_command = [str(binary), *arguments, "-Zohm-resident-query-graph"]
    (output / "resident-command.json").write_text(
        json.dumps(resident_command, indent=2) + "\n"
    )
    resident = subprocess.run(
        resident_command, cwd=cwd, env=env, capture_output=True, text=True, check=False
    )
    (output / "resident.stdout").write_text(resident.stdout)
    (output / "resident.stderr").write_text(resident.stderr)
    if resident.returncode:
        raise SystemExit(
            f"resident process exited {resident.returncode}\n{resident.stderr[-14000:]}\n{resident.stdout[-10000:]}"
        )
    expected = {"0:0": False, "1:20": True, "2:0": False, "3:20": True}
    phases = {key: [] for key in expected}
    resident_snippets = {key: set() for key in expected}
    phase = None
    outside = []
    for line in resident.stderr.splitlines():
        if line.startswith("uv-start:"):
            phase = line.removeprefix("uv-start:")
        elif line.startswith("uv-end:"):
            phase = None
        elif data := diagnosis(line):
            (outside if phase is None else phases[phase]).append(data)
            if phase is not None:
                resident_snippets[phase].update(threshold_snippets(line))
    parsed = collections.defaultdict(list)
    for line in resident.stdout.splitlines():
        if "\t" in line:
            category, *values = line.split("\t")
            parsed[category].append(values)
    fresh_command = [str(stage1 / "bin/rustc"), *arguments]
    (output / "fresh-command.json").write_text(
        json.dumps(fresh_command, indent=2) + "\n"
    )
    source_file = cwd / "crates/uv-pep440/src/version.rs"
    original = source_file.read_text()
    assert original.count("strings.len() <= 20") == 1
    threshold = original.index("strings.len() <= 20") + len("strings.len() <= ")
    deleted_byte = len(original[: threshold + 1].encode())
    threshold_line = original[:threshold].count("\n") + 1
    deleted_column = threshold - original.rfind("\n", 0, threshold) + 1
    fresh = {}
    failures = []
    try:
        for name, number in [
            ("initial", 20),
            ("0:0", 0),
            ("1:20", 20),
            ("2:0", 0),
            ("3:20", 20),
        ]:
            desired = (
                original
                if number == 20
                else original.replace("strings.len() <= 20", "strings.len() <= 0")
            )
            if source_file.read_text() != desired:
                source_file.write_text(desired)
            result = subprocess.run(
                fresh_command,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            (output / f"fresh-{name.replace(':', '-')}.stderr").write_text(
                result.stderr
            )
            found = [
                data for line in result.stderr.splitlines() if (data := diagnosis(line))
            ]
            mapped = (
                restore_resident_positions(
                    found, deleted_byte, threshold_line, deleted_column
                )
                if number == 0
                else found
            )
            fresh[name] = {
                "success": result.returncode == 0,
                "diagnostics": found,
                "diagnostics_in_original_source_coordinates": mapped,
                "native_edited_line_snippets": sorted(
                    {
                        snippet
                        for line in result.stderr.splitlines()
                        for snippet in threshold_snippets(line)
                    }
                ),
            }
            if name != "initial" and sorted_diagnostics(mapped) != sorted_diagnostics(
                phases[name]
            ):
                failures.append(f"{name}: resident/fresh diagnostics differ")
            if (result.returncode == 0) != (number == 20):
                failures.append(f"{name}: unexpected fresh status {result.returncode}")
    finally:
        if source_file.read_text() != original:
            source_file.write_text(original)
    for name, success in expected.items():
        reports = [data for data in parsed["constant"] if data[0] == name]
        if len(reports) != 2 or any((data[2] == "true") != success for data in reports):
            failures.append(f"{name}: bad native const statuses: {reports}")
        actual = [data for data in parsed["errors"] if data[0] == name]
        if actual != [[name, "0" if success else "2"]]:
            failures.append(f"{name}: error-count report {actual}")
        codes = sorted(item["code"] for item in phases[name])
        wanted = [] if success else ["E0080", "E0080"]
        if codes != wanted:
            failures.append(f"{name}: error codes {codes}")
        if not success and fresh[name]["native_edited_line_snippets"] != [
            "strings.len() <= 0,"
        ]:
            failures.append(
                f"{name}: fresh diagnostic does not render the actual changed threshold"
            )
        if not success and (
            not resident_snippets[name]
            or not resident_snippets[name]
            <= {"strings.len() <= 20,", "strings.len() <= 0,"}
        ):
            failures.append(
                f"{name}: unrecognized resident diagnostic excerpt {resident_snippets[name]}"
            )
        owners = {
            name
            for item in phases[name]
            for record in item["details"]["spans"]
            if record.get("is_primary")
            for name in ["parse_pre", "parse_post"]
            if name in (record.get("label") or "")
        }
        if owners != (set() if success else {"parse_pre", "parse_post"}):
            failures.append(f"{name}: diagnostic owners {owners}")
    for owner in ["parse_pre", "parse_post"]:
        series = [data[3:] for data in parsed["constant"] if data[1] == owner]
        for column, label in [(0, "eval"), (1, "allocation")]:
            values = [int(row[column]) for row in series]
            if not values or any(b <= a for a, b in itertools.pairwise(values)):
                failures.append(
                    f"{owner}: {label} provider did not rerun on each edit: {values}"
                )
    expected_cached = {"parse_u64", "sortable_tuple", "starts_with_ignore_ascii_case"}
    if len(parsed["cache"]) != len(expected) * len(expected_cached) or any(
        data[1] not in expected_cached or data[2] != "true" for data in parsed["cache"]
    ):
        failures.append(
            f"unrelated provider counts/result pointers changed: {parsed['cache']}"
        )
    if a.check_parser_borrow:
        for owner in ["parse_pre", "parse_post"]:
            rows = [data for data in parsed["function"] if data[1] == owner]
            if (
                len(rows) != len(expected) + 1
                or any(
                    row[2] != "true" or row[3] != rows[0][3] or row[5] != rows[0][5]
                    for row in rows
                )
                or [int(row[4]) for row in rows] != list(range(1, len(expected) + 2))
            ):
                failures.append(
                    f"{owner}: expected retained type result and one additional borrow provider call per edit: {rows}"
                )
    if len(parsed["context"]) != 1:
        failures.append(f"expected exactly one PID/GlobalCtxt, got {parsed['context']}")
    if outside:
        failures.append(f"non-phase resident errors: {outside}")
    raw_snippets_updated = all(
        sorted(resident_snippets[name]) == fresh[name]["native_edited_line_snippets"]
        for name, success in expected.items()
        if not success
    )
    payload = {
        "scope": "Full production uv-pep440 library crate and exact Cargo dependencies; in-memory one-literal edits; same patched Ohm compiler binary family for independent fresh comparison; fresh source applies the real one-character deletion, then maps diagnostic offsets around that deletion back to the resident original source coordinates.",
        "uv_revision": "5d64ede21e9e835e59ecd85329ebefd43faa8211",
        "context": parsed["context"],
        "selected": parsed["selected"],
        "constant_owners": parsed["owner"],
        "plans": parsed["plan"],
        "removed": parsed["removed"],
        "functions": parsed["function"],
        "constants": parsed["constant"],
        "unaffected_cached": parsed["cache"],
        "error_counts": parsed["errors"],
        "resident_diagnostics": phases,
        "checked_parser_borrow": a.check_parser_borrow,
        "diagnostic_excerpt_limitation": {
            "raw_diagnostic_snippet_updated": raw_snippets_updated,
            "resident_native_edited_line_snippets": {
                name: sorted(values) for name, values in resident_snippets.items()
            },
            "raw_excerpt_and_ansi_rendering_excluded_from_structured_differential": True,
        },
        "fresh": fresh,
        "failures": failures,
    }
    (output / "summary.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"{len(expected)} resident edits; {len(fresh)} fresh checks; {len(failures)} failure(s)"
    )
    for failure in failures:
        print(failure)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
