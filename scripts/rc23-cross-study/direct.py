"""Run the release compiler against the source PRs' positive and negative asm fixtures."""

import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent / "fixtures"
V2 = "/dev/null/ohm-recheck-dependent-links-v2:"
UNTRACKED = "/dev/null/ohm-untracked-relink-inputs:"
V1 = "/dev/null/ohm-recheck-dependent-links:"


def verify(arm, target, sdk, work, evidence):
    work.mkdir()
    evidence.mkdir()
    for name, meta in json.loads((HERE / "sources.json").read_bytes()).items():
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == meta["sha256"]
    rmake = (HERE / "rmake.rs").read_text()
    gnu = target == "aarch64-unknown-linux-gnu"
    assert gnu or target == "x86_64-unknown-linux-musl"
    source = HERE / ("gnu_aarch64.rs" if gnu else "musl_x86_64.rs")
    env = {
        "PATH": str(sdk / "bin") + ":/usr/bin:/bin",
        "LC_ALL": "C",
        "RUSTC_BOOTSTRAP": "1",
    }
    compiler = [str(sdk / "bin/rustc"), "--target", target]
    (work / "payload.bin").write_bytes(bytes(4))
    (work / "payload.s").write_text(".byte 0\n")

    def invoke(name, args, exit_ok=True):
        proc = subprocess.run(compiler + args, cwd=work, env=env, capture_output=True)
        (evidence / (name + ".stdout")).write_bytes(proc.stdout)
        (evidence / (name + ".stderr")).write_bytes(proc.stderr)
        assert (proc.returncode == 0) == exit_ok, (
            name,
            proc.returncode,
            proc.stderr[-750:],
        )
        return proc

    if gnu:
        section = rmake.split('if target() == "aarch64-unknown-linux-gnu" {', 1)[1]
        cases = re.findall(
            r'"(\w+)"', section.split("for cfg in [", 1)[1].split("] {", 1)[0]
        )
        safe = set(
            re.findall(
                r'"(\w+)"',
                section.split("let accepted = matches!(", 1)[1].split(");", 1)[0],
            )
        )
        assert (
            len(cases) == 31
            and len(safe) == 8
            and {"syscall", "atomic_loop", "atomic_feature"} <= safe
        )
        flags = []
    else:
        safe = {"spaced", "compact", "both"}
        cases = sorted(safe) + [
            "instruction",
            "include",
            "escape",
            "modifier",
            "class",
            "options",
            "symbol",
            "raw",
            "att",
            "global",
        ]
        invoke(
            "minicore",
            [
                "--crate-name",
                "minicore",
                "--crate-type",
                "rlib",
                str(HERE / "minicore.rs"),
                "-o",
                "libminicore.rlib",
            ],
        )
        flags = ["-Zunstable-options", "--extern", "minicore=libminicore.rlib"]
    results = {}

    def check(case, name=None, extra=(), ok=True, expected=None):
        label = name or case
        proc = invoke(
            label,
            [
                "--crate-name",
                "probe",
                "--cfg",
                case,
                "-Zohm-check-relink-inputs",
                "--emit",
                "link,dep-info=-",
                *flags,
                str(source),
                *extra,
            ],
            ok,
        )
        rows = proc.stdout.decode().splitlines()
        markers = {s: s in rows for s in (V1, V2, UNTRACKED)}
        if expected is not None:
            assert markers == {V1: False, V2: expected, UNTRACKED: not expected}, (
                arm,
                label,
                markers,
                rows[-12:],
            )
        results[label] = dict(exit=proc.returncode, markers=markers)
        return proc

    for case in cases:
        # The previous compiler may already understand a subset of the positives.
        want = case in safe if arm == "cross" or case not in safe else None
        check(case, expected=want)
    if not gnu:
        check(
            "both",
            "unbundled",
            ["-lstatic:-bundle=ohm_missing_archive"],
            expected=True if arm == "cross" else None,
        )
        missing = check(
            "both",
            "missing-bundled",
            ["-lstatic=ohm_missing_archive"],
            ok=False,
            expected=False,
        )
        assert b"ohm_missing_archive" in missing.stderr
        (work / "payload.s").write_text(".ohm_invalid_directive\n")
        bad = check("include", "invalid-include", ok=False, expected=False)
        assert b".ohm_invalid_directive" in bad.stderr
    (evidence / "results.json").write_text(json.dumps(results, indent=2) + "\n")
