"""Reopen the literal Cargo stages and run original and independently relinked metadata clients."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import zipfile

CHECK = [
    "cargo",
    "+ohm",
    "check",
    "-p",
    "ruff_markdown",
    "--lib",
    "--locked",
    "--offline",
    "--message-format=json",
]
BUILD = [
    "cargo",
    "+ohm",
    "build",
    "-p",
    "ruff",
    "--bin",
    "ruff",
    "--locked",
    "--offline",
    "--message-format=json",
]
PHASES = (
    "scope-old",
    "scope-old-unchanged",
    "scope-edit",
    "scope-traced-edit",
    "scope-new-unchanged",
    "scope-repaired",
    "scope-empty-new",
)
OLD = "`incorrect-blank-line-before-class` (D203) and `no-blank-line-before-class` (D211) are incompatible. Ignoring `incorrect-blank-line-before-class`."
NEW = OLD.replace("`no-blank-line-before-class`", "`blank-line-before-class`")
OTHER = "`multi-line-summary-first-line` (D212) and `multi-line-summary-second-line` (D213) are incompatible. Ignoring `multi-line-summary-second-line`."
ROOT = Path(__file__).resolve().parents[4]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def verify(z, prefix, tmp):
    read = lambda n: z.read(prefix + n)
    record = lambda n: json.loads(read(n))
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": str(tmp), "TMPDIR": str(tmp)}
    seen = {}
    summaries = {}
    for phase in PHASES:
        get = lambda n: record(phase + "/" + n)
        truth = [OLD if phase.startswith("scope-old") else NEW, OTHER]
        name = phase + "/"
        c = get("command.json")
        assert c["argv"][-len(CHECK) :] == CHECK and c["exit"] == 0
        raw = [json.loads(line) for line in read(name + "stdout").splitlines()]
        assert [r["success"] for r in raw if r["reason"] == "build-finished"] == [True]
        messages = get("cargo.json")
        artifacts = [r for r in raw if r["reason"] == "compiler-artifact"]
        assert len(messages["inventory"]) == len(artifacts) == 308
        dirty = sorted(r["target"]["name"] for r in artifacts if not r["fresh"])
        assert dirty == sorted(r[1] for r in messages["inventory"] if not r[-1])
        if "unchanged" in phase:
            assert not dirty
        inv = get("native.json")
        body = read(name + "oracle.o")
        exe = read(name + "oracle")
        assert (
            sha(body) == inv["native_object"]
            and sha(exe) == inv["executable"]
            and truth == inv["messages"]
        )
        assert body[:6] == exe[:6] == b"\x7fELF\x02\x01" and struct.unpack_from(
            "<HH", body, 16
        ) == (1, 62)
        identity = (sha(body), sha(exe))
        if identity not in seen:
            original = tmp / "native"
            obj = tmp / "oracle.o"
            linked = tmp / "linked"
            original.write_bytes(exe)
            original.chmod(0o700)
            obj.write_bytes(body)
            subprocess.run(
                [
                    "/usr/bin/cc",
                    "-O1",
                    "-no-pie",
                    ROOT / "scripts/ruff-linter-check-attribution/oracle.c",
                    obj,
                    "-o",
                    linked,
                ],
                check=True,
                env=env,
                cwd=tmp,
                timeout=25,
            )
            seen[identity] = [
                subprocess.check_output([p], env=env, cwd=tmp, timeout=3)
                .decode()
                .splitlines()
                for p in (original, linked)
            ]
        assert seen[identity] == [truth, truth]
        sums = get("scope-rmetas.json")
        assert inv["metadata"] == sums["ruff_linter"]["sha256"]
        summaries[phase] = {
            "dirty": dirty,
            "native": list(identity),
            "rmetas": {o: p["sha256"] for o, p in sums.items()},
        }
    for phase in (
        "scope-edit",
        "scope-new-unchanged",
        "scope-traced-edit",
        "scope-repaired",
    ):
        assert summaries[phase]["native"] == summaries["scope-empty-new"]["native"]
        assert summaries[phase]["rmetas"] == summaries["scope-edit"]["rmetas"]
    assert (
        summaries["scope-old"]["rmetas"] == summaries["scope-old-unchanged"]["rmetas"]
        and summaries["scope-old"]["native"] != summaries["scope-edit"]["native"]
    )
    traced = record("scope-traced-edit/native-execs.json")
    owners = []
    for ln in traced["execs"]:
        m = re.fullmatch(
            r'\s*\d+\s+execve\("([^"\s]+)", \[(.*?)\], (?:0x[a-f0-9]+ /\* \d+ vars \*/|\[.*\])\) += 0',
            ln,
        )
        assert (
            m and m[1].endswith("/bin/rustc") and '"--emit=dep-info,metadata"' in m[2]
        ), ln[:220]
        owners.append(re.search(r'"--crate-name", "([a-z0-9_]+)"', m[2])[1])
    assert (
        sorted(owners)
        == traced["compiler_owners"]
        == summaries["scope-edit"]["dirty"]
        == summaries["scope-traced-edit"]["dirty"]
    )
    errs = [
        r["message"]
        for line in read("scope-invalid/stdout").splitlines()
        if (r := json.loads(line))["reason"] == "compiler-message"
        and r["message"]["level"] == "error"
    ]
    assert [v["code"]["code"] for v in errs if v["code"]] == ["E0308"]
    assert any(
        sp["is_primary"]
        and sp["file_name"].endswith("crates/ruff_linter/src/registry.rs")
        for e in errs
        for sp in e["spans"]
    )
    active = record("scope-admitted.json")
    cli = active["cli"]
    for k, p in (("old", "old"), ("new", "new"), ("empty", "empty-new")):
        v = cli[k]
        assert (
            record("scope-cli-" + p + "/scope-cli.json") == v
            and record("scope-cli-" + p + "/command.json")["argv"] == BUILD
            and v["exit"] == 0
        )
        assert v["stderr"] == [
            "warning: " + msg for msg in ([OLD, OTHER] if k == "old" else [NEW, OTHER])
        ]
        assert (
            v["stdout"] == "All checks passed!\n"
            and 20 * 2**20 < v["bytes"] < 400 * 2**20
            and re.fullmatch("[a-f0-9]{64}", v["binary"])
        )
    assert cli["old"]["binary"] != cli["new"]["binary"]
    return dict(
        phases=summaries,
        raw_rustc=sorted(owners),
        invalid="E0308",
        actual_cli={k: [v["binary"], v["bytes"]] for k, v in cli.items()},
        native_clients=len(seen),
        warm_clean_cli_identical=cli["new"]["binary"] == cli["empty"]["binary"],
    )
