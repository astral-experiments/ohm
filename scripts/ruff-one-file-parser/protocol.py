"""Frozen one-file fixed-revision workload and independent artifact/diagnostic predicates."""

from collections import Counter
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent / "ruff-default-owner-pmu"))
import common as c  # shared source-bound SDK and raw IO API
import fixture as f
import ownership

BRANCH = "charlie/qa-ruff-one-file-parser-20261101"
JOB = "Signed GNU Ruff one-file parser edit"
FIRST = "5cc8582fa5e9c067d1f463cb27b9de311b2ff648"
ROLES = {
    "cli": (["build", "-p", "ruff", "--bin", "ruff"], 375, "ruff", "bin"),
    "parser": (
        ["test", "-p", "ruff_python_parser", "--test", "fixtures", "--no-run"],
        152,
        "fixtures",
        "test",
    ),
}
LANES = {
    "empty-before": ("baseline",),
    "empty-after": ("edited",),
    "empty-invalid": ("invalid",),
    "plain-1": ("baseline", "edited"),
    "inventory": ("baseline", "edited", "unchanged", "invalid", "repair", "revert"),
    "plain-2": ("baseline", "edited"),
}
BAD = b"\nconst _: () = 1u32; // enrolled parser type error\n"
STATE = {"unchanged": "edited", "repair": "edited", "revert": "baseline"}


def command(role):
    return ["cargo", "+ohm", *ROLES[role][0], "--locked", "--offline", "-j4", "--message-format=json"]


def key(row):
    target = row["target"]
    return json.dumps(
        [
            row["package_id"],
            target,
            sorted(row["features"]),
            row["profile"],
            row["filenames"],
            row["executable"],
        ],
        sort_keys=True,
        separators=(",", ":"),
    )


def graph(rows, role, repo, work):
    ownership.check_roots(rows, work)
    f.require(
        rows[-1] == {"reason": "build-finished", "success": True}, "incomplete successful Cargo build"
    )
    f.require(
        not any(r["reason"] == "compiler-message" and r["message"]["level"] == "error" for r in rows),
        "unexpected error",
    )
    products = [r for r in rows if r["reason"] == "compiler-artifact"]
    keys = [key(r) for r in products]
    _, num, name, kind = ROLES[role]
    f.require(len(set(keys)) == len(keys) == num, "incomplete or duplicate Cargo artifact roles")
    (root,) = [
        r
        for r in products
        if r["target"]["name"] == name and r["target"]["kind"] == [kind] and r["executable"]
    ]
    if role == "parser":
        f.require(
            root["target"]["src_path"] == str(repo / "crates/ruff_python_parser/tests/fixtures.rs")
            and root["profile"]["test"]
            and len([v for v in rows if v["reason"] == "build-script-executed"]) == 19,
            "wrong native parser harness or build-script roster",
        )
    else:
        f.require(
            root["target"]["src_path"] == str(repo / "crates/ruff/src/main.rs")
            and not root["profile"]["test"]
            and Path(root["executable"]) == work / "target/debug/ruff",
            "wrong Ruff CLI artifact",
        )
    return (
        sorted(keys),
        sorted(key(r) for r in products if not r["fresh"]),
        products,
        Path(root["executable"]),
    )


def error(rows):
    f.require(rows[-1] == {"reason": "build-finished", "success": False}, "wrong failed Cargo terminal")
    messages = []
    for row in rows:
        if row["reason"] != "compiler-message" or row["message"]["level"] != "error":
            continue
        m = row["message"]
        if m["code"] is None:
            f.require(
                m["message"].startswith("aborting due to 1 previous error") and not m["spans"],
                "unexpected secondary error",
            )
            continue
        (p,) = [s for s in m["spans"] if s["is_primary"]]
        f.require(
            row["target"]["name"] == "ruff_python_parser"
            and m["code"]["code"] == "E0308"
            and m["message"] == "mismatched types"
            and p["file_name"] == f.SRC
            and [t["text"] for t in p["text"]] == [BAD.decode().strip()]
            and "expected `()`, found `u32`" in m["rendered"],
            "wrong parser error/span",
        )
        messages.append(m)
    f.require(len(messages) == 1, "expected a single typed parser error")
    return messages[0]


def change(repo, old, new):
    f.state(repo, old)
    if old == new:
        return
    path = repo / f.SRC
    if old == "invalid":
        path.write_bytes(path.read_bytes()[: -len(BAD)])
        old = "edited"
    if new == "invalid":
        if old == "baseline":
            f.change_control(repo, "edited")
        path.write_bytes(path.read_bytes() + BAD)
    elif old != new:
        f.change_control(repo, new)
    f.state(repo, new)


def unitplan(raw, role, repo):
    units = raw["units"]
    (root,) = [units[n] for n in raw["roots"]]
    args, num, name, kind = ROLES[role]
    f.require(
        raw["version"] == 1 and root["target"]["kind"] == [kind] and root["target"]["name"] == name,
        "wrong ordinary unit-graph root",
    )
    modes = Counter(u["mode"] for u in units)
    f.require(len(units) - modes["run-custom-build"] == num, "wrong planned target count")
    if role == "parser":
        f.require(
            modes == {"build": 151, "run-custom-build": 19, "test": 1}, "different native parser graph"
        )

    def identity(pkg, target, features):
        return json.dumps([pkg, target, sorted(features)], sort_keys=True)

    return Counter(
        identity(u["pkg_id"], u["target"], u["features"])
        for u in units
        if u["mode"] != "run-custom-build"
    )


def validate_planned(plan, rows):
    observed = Counter(
        json.dumps([r["package_id"], r["target"], sorted(r["features"])], sort_keys=True) for r in rows
    )
    f.require(plan == observed, "planned vs physically reported Cargo targets")


__all__ = [
    "c",
    "f",
    "ROLES",
    "LANES",
    "command",
    "unitplan",
    "graph",
    "error",
    "change",
    "validate_planned",
]
