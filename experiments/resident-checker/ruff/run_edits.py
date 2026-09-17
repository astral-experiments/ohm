"""Run real Ruff tail replacements in one Ohm GlobalCtxt and compare fresh diagnostics."""

import argparse
import json
import os
import subprocess
from collections import defaultdict
from pathlib import Path

CONTROLS = (
    "strip_underscores",
    "is_known_future_feature",
    "is_identifier_continuation",
    "single_char_prefix",
)
FRESH = {
    "is_unicode_identifier_start": "parser-identifier-type",
    "parse_octet": "string-method-type",
}


def build(host, output):
    stage0, stage1 = host / "stage0", host / "stage1"
    deps = output / "driver-deps"
    deps.mkdir(exist_ok=True)
    stamp = host / "stage1-rustc" / host.name / "release/.librustc-stamp"
    for entry in stamp.read_bytes().split(b"\0"):
        if not entry:
            continue
        artifact = Path(os.fsdecode(entry[1:]))
        destination = deps / artifact.name
        if artifact.is_file() and not destination.exists():
            destination.symlink_to(artifact)
    binary = output / "targeted-driver"
    source = Path(__file__).with_name("edits.rs")
    command = [
        str(stage0 / "bin/rustc"),
        "--edition=2024",
        str(source),
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
    result = subprocess.run(
        command,
        env=dict(os.environ, RUSTC_BOOTSTRAP="1"),
        capture_output=True,
        text=True,
        check=False,
    )
    (output / "targeted-build.log").write_text(
        "$ " + " ".join(command) + "\n" + result.stdout + result.stderr
    )
    if result.returncode:
        raise SystemExit(result.stderr)
    return binary


def arguments(data, output, sysroot):
    result = []
    iterator = iter(data["argv"][1:])
    for arg in iterator:
        if arg == "-C":
            value = next(iterator)
            if not value.startswith("incremental="):
                result.extend([arg, value])
        elif arg == "--out-dir":
            next(iterator)
            result.extend([arg, str(output)])
        elif arg.startswith("-Cincremental=") or arg == "-Zohm-resident-query-graph":
            continue
        elif arg == "--sysroot":
            next(iterator)
        elif arg.startswith("--emit="):
            result.append("--emit=metadata")
        else:
            result.append(arg)
    return result + [
        "--cap-lints=allow",
        "-Zthreads=1",
        "--sysroot",
        str(sysroot),
        "-Zohm-resident-query-graph",
    ]


def diagnostic(line):
    try:
        item = json.loads(line)
    except (ValueError, TypeError):
        return None
    if item.get("reason") == "compiler-message":
        item = item["message"]
    if item.get("level") != "error" or not item.get("spans"):
        return None
    code = item.get("code")
    return {
        "code": code.get("code") if isinstance(code, dict) else code,
        "message": item["message"],
        "spans": item["spans"],
        "children": item.get("children", []),
    }


def normalized(item, include_end):
    fields = ["file_name", "line_start", "column_start"]
    if include_end:
        fields.extend(["line_end", "column_end"])
    primary = []
    for span in item["spans"]:
        if not span["is_primary"]:
            continue
        span = dict(span)
        span["file_name"] = "src/" + span["file_name"].rsplit("/src/", 1)[-1]
        primary.append([span[field] for field in fields])
    return {"code": item["code"], "message": item["message"], "primary_spans": primary}


def parse(stdout, stderr, returncode, fresh_reference):
    rows = defaultdict(list)
    for line in stdout.splitlines():
        if "\t" in line:
            kind, *values = line.split("\t")
            rows[kind].append(values)
    phase = None
    diagnostics = defaultdict(list)
    misc = []
    for line in stderr.splitlines():
        if line.startswith("targeted-start:"):
            phase = line.removeprefix("targeted-start:")
        elif line.startswith("targeted-end:"):
            phase = None
        elif item := diagnostic(line):
            diagnostics[phase or "outside"].append(item)
        elif line.startswith("control-recomputed:"):
            misc.append(line)
    states = defaultdict(dict)
    for (
        phase,
        name,
        owner,
        type_count,
        borrow_count,
        pointer,
        success,
        borrow_demanded,
    ) in rows["owner"]:
        states[phase][name] = {
            "id": int(owner),
            "type_count": int(type_count),
            "borrow_count": int(borrow_count),
            "pointer": int(pointer),
            "success": success == "true",
            "borrow_demanded": borrow_demanded == "true",
        }
    error_counts = {phase: int(count) for phase, count in rows["errors"]}
    comparisons = {}
    if fresh_reference:
        for owner, filename in FRESH.items():
            fresh = [
                item
                for line in (fresh_reference / f"{filename}.stderr")
                .read_text()
                .splitlines()
                if (item := diagnostic(line))
            ]
            for iteration in range(1, 3):
                phase = f"{owner}:{iteration}:changed"
                native = diagnostics.get(phase, [])
                comparisons[phase] = {
                    "code_message_file_line_column_start_match": [
                        normalized(item, False) for item in native
                    ]
                    == [normalized(item, False) for item in fresh],
                    "primary_span_end_also_matches": [
                        normalized(item, True) for item in native
                    ]
                    == [normalized(item, True) for item in fresh],
                    "native": [normalized(item, True) for item in native],
                    "fresh": [normalized(item, True) for item in fresh],
                }
    all_controls_cached = bool(states.get("baseline")) and all(
        states.get("baseline", {}).get(control) == state.get(control)
        for phase, state in states.items()
        if phase != "baseline"
        for control in CONTROLS
    )
    return {
        "returncode": returncode,
        "context": rows["context"],
        "completed": rows["complete"],
        "identities": rows["identity"],
        "classifiers": rows["classifier"],
        "states": states,
        "error_counts": error_counts,
        "evictions": rows["eviction"],
        "diagnostics": diagnostics,
        "control_recomputations": misc,
        "additional_control_dependency_paths": rows["control-path"],
        "all_controls_cached": all_controls_cached,
        "fresh_comparisons": comparisons,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", type=Path, required=True)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fresh-reference", type=Path)
    parser.add_argument("--target", default="aarch64-apple-darwin")
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    if not args.build_only and args.capture is None:
        parser.error("--capture is required unless --build-only is used")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    host = args.bootstrap.resolve() / args.target
    binary = build(host, output)
    if args.build_only:
        return
    data = json.loads(args.capture.read_text())
    env = dict(os.environ, RUSTC_BOOTSTRAP="1", **data["env"])
    env.pop("CARGO_MAKEFLAGS", None)
    artifact = output / "rust-output"
    artifact.mkdir(exist_ok=True)
    command = [str(binary), *arguments(data, artifact, host / "stage1")]
    (output / "targeted-command.json").write_text(json.dumps(command, indent=2) + "\n")
    with (
        (output / "targeted.stdout").open("w") as stdout,
        (output / "targeted.stderr").open("w") as stderr,
    ):
        result = subprocess.run(
            command, cwd=data["cwd"], env=env, stdout=stdout, stderr=stderr, check=False
        )
    summary = parse(
        (output / "targeted.stdout").read_text(),
        (output / "targeted.stderr").read_text(),
        result.returncode,
        args.fresh_reference,
    )
    (output / "targeted.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "returncode",
                    "context",
                    "completed",
                    "error_counts",
                    "all_controls_cached",
                    "fresh_comparisons",
                )
            },
            indent=2,
        )
    )
    if (
        result.returncode
        or not summary["completed"]
        or any(
            not match["code_message_file_line_column_start_match"]
            for match in summary["fresh_comparisons"].values()
        )
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
