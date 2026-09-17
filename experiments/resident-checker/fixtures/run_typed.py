"""Build/run the exact in-tree query graph embedding after stage1 rustc and std are built."""

import argparse
import json
import os
import pathlib
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--bootstrap",
    type=pathlib.Path,
    required=True,
    help="bootstrap output root that contains the host directory",
)
parser.add_argument("--target", default="aarch64-apple-darwin")
parser.add_argument("--output", type=pathlib.Path, required=True)
parser.add_argument(
    "--allow-conservative",
    action="store_true",
    help="record over-invalidation without making the command fail",
)
parser.add_argument(
    "--require-auxiliary-cache",
    action="store_true",
    help="also require unrelated generic trait helper caches to stay warm",
)
args = parser.parse_args()
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
source = pathlib.Path(__file__).resolve().parent
host = args.bootstrap.resolve() / args.target
stage0 = host / "stage0"
stage1 = host / "stage1"
stamp = host / "stage1-rustc" / args.target / "release/.librustc-stamp"
deps = output / "deps"
deps.mkdir(exist_ok=True)
for entry in stamp.read_bytes().split(b"\0"):
    if not entry:
        continue
    artifact = pathlib.Path(os.fsdecode(entry[1:]))
    dest = deps / artifact.name
    if artifact.is_file() and not dest.exists():
        dest.symlink_to(artifact)

env = dict(os.environ, RUSTC_BOOTSTRAP="1")
binary = output / "typed-graph-driver"
command = [
    str(stage0 / "bin/rustc"),
    "--edition=2024",
    str(source / "typed_graph_driver.rs"),
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
compiled = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
(output / "build.log").write_text(
    f"$ {' '.join(command)}\n{compiled.stdout}{compiled.stderr}"
)
compiled.check_returncode()

suites = {
    "ordinary": ("false,value,false,value", [1, 0, 1, 0]),
    "const": ("3,2,4,2", [1, 0, 1, 0]),
    "opaque": ("non_send,send,non_send,send", [1, 0, 1, 0]),
    "opaque-indirect": ("non_send,send,non_send,send", [2, 0, 2, 0]),
}
summary = {}
for name, (edits, expected) in suites.items():
    command = [
        str(binary),
        str(source / f"typed-{name}.rs"),
        "--sysroot",
        str(stage1),
        "--crate-type=lib",
        "--edition=2024",
        "--error-format=json",
        "-A",
        "warnings",
        "-Zohm-resident-query-graph",
    ]
    proc = subprocess.run(
        command,
        env=dict(env, OHM_TYPED_EDITS=edits),
        capture_output=True,
        text=True,
        check=False,
    )
    (output / f"{name}.stdout").write_text(proc.stdout)
    (output / f"{name}.stderr").write_text(proc.stderr)
    errors = [
        int(line.split("\t")[-1])
        for line in proc.stdout.splitlines()
        if line.startswith("errors\t")
    ]
    plans = [
        line.split("\t")
        for line in proc.stdout.splitlines()
        if line.startswith("plan\t")
    ]
    phases = [[] for _ in expected]
    owner_phases = [[] for _ in expected]
    owner_lines = {}
    for line_number, line in enumerate(
        (source / f"typed-{name}.rs").read_text().splitlines(), 1
    ):
        if match := re.search(r"\bfn\s+(\w+)", line):
            owner_lines[line_number] = match.group(1)
    phase = None
    for line in proc.stderr.splitlines():
        if line.startswith("typed-start:"):
            phase = int(line.split(":")[1])
        elif line.startswith("typed-end:"):
            phase = None
        elif phase is not None and line.startswith("{"):
            diagnostic = json.loads(line)
            if diagnostic.get("level") == "error" and diagnostic.get("code"):
                phases[phase].append(diagnostic["code"]["code"])
                owner_phases[phase].append(
                    sorted(
                        {
                            owner_lines.get(span["line_start"])
                            for span in diagnostic.get("spans", [])
                            if span.get("is_primary")
                        }
                        - {None}
                    )
                )
    checks = [
        line.split("\t")
        for line in proc.stdout.splitlines()
        if line.startswith("check\t")
    ]
    contexts = [
        line.split("\t")[1]
        for line in proc.stdout.splitlines()
        if line.startswith("context\t")
    ]
    by_owner = {}
    for check in checks:
        _, edit, owner, success, typeck, borrow, pointer = check
        by_owner.setdefault(owner, []).append(
            [edit, int(typeck), int(borrow), int(pointer)]
        )
    untouched_rows = by_owner.get("untouched", [])
    untouched = len(untouched_rows) >= len(expected) + 1 and all(
        row[1:] == untouched_rows[0][1:] for row in untouched_rows
    )
    expected_owners = {
        "ordinary": ["selected"],
        "const": ["downstream"],
        "opaque": ["caller"],
        "opaque-indirect": ["first_caller", "second_caller"],
    }[name]
    expected_code = "E0277" if name.startswith("opaque") else "E0308"
    diagnostic_codes_match = phases == [[expected_code] * count for count in expected]
    primary_owners_match = all(
        sorted(owners) == ([[owner] for owner in expected_owners] if count else [])
        for count, owners in zip(expected, owner_phases)
    )
    affected_advances = True
    if name != "ordinary":
        for owner in expected_owners:
            type_counts = [row[1] for row in by_owner.get(owner, [])]
            borrow_counts = [row[2] for row in by_owner.get(owner, [])]
            affected_advances &= type_counts == [1, 2, 3, 4, 5] and borrow_counts == [
                1,
                1,
                2,
                2,
                3,
            ]
    selective_expectations = {
        "ordinary": ["caller", "transitively_calls"],
        "opaque": ["transitively_calls"],
        "opaque-indirect": ["other_opaque", "other_caller"],
        "const": [],
    }[name]
    conservative_candidates = ["requires_send"] if name.startswith("opaque") else []

    def recomputed(owners, by_owner, expected_count):
        return {
            owner: [row[1:] for row in by_owner.get(owner, [])]
            for owner in owners
            if len(by_owner.get(owner, [])) != expected_count
            or any(row[1:] != by_owner[owner][0][1:] for row in by_owner.get(owner, []))
        }

    unnecessary = recomputed(selective_expectations, by_owner, len(expected) + 1)
    auxiliary = recomputed(conservative_candidates, by_owner, len(expected) + 1)
    summary[name] = {
        "returncode": proc.returncode,
        "expected_error_counts": expected,
        "error_counts": errors,
        "error_codes": phases,
        "primary_owners": owner_phases,
        "plans": plans,
        "checks": checks,
        "untouched_stays_cached": untouched,
        "affected_provider_advances": affected_advances,
        "unnecessary_recomputations": unnecessary,
        "conservative_recomputations": auxiliary,
        "auxiliary_selectivity_success": not auxiliary,
        "selectivity_success": not unnecessary,
        "success": proc.returncode == 0
        and len(contexts) == 1
        and len(plans) == len(expected)
        and errors == expected
        and diagnostic_codes_match
        and primary_owners_match
        and untouched
        and affected_advances,
    }
(output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
if not all(
    value["success"]
    and (value["selectivity_success"] or args.allow_conservative)
    and (value["auxiliary_selectivity_success"] or not args.require_auxiliary_cache)
    for value in summary.values()
):
    raise SystemExit(
        json.dumps(
            {
                name: [
                    data["returncode"],
                    data["error_counts"],
                    data["error_codes"],
                    data["unnecessary_recomputations"],
                    data["conservative_recomputations"],
                ]
                for name, data in summary.items()
            }
        )
    )
