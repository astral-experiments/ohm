# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Exercise native Clippy/codegen integration with a small dependency-free crate.

Pass --cargo and --rustc to validate locally built, matching Ohm components.
"""

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

LINT = "clippy::zero_sized_map_values"
LINT_ARGS = ["-Aclippy::all", f"-W{LINT}", "-Wclippy::disallowed_names"]
LIBRARY = """pub type Map = std::collections::HashMap<u8, ()>;

/// ```
/// assert_eq!(clippy_test_smoke::value(41), 42);
/// ```
pub fn value(input: u8) -> u8 {
    input + 1
}
"""
TEST = """pub type TestMap = std::collections::HashMap<u8, ()>;

#[test]
fn executes() {
    std::fs::write(std::env::var("SMOKE_EXECUTED").unwrap(), "ran").unwrap();
    let expected = if std::env::var_os("SMOKE_FAIL").is_some() { 0 } else { 42 };
    assert_eq!(clippy_test_smoke::value(41), expected);
}

#[test]
fn records_compilation_mode() {
    std::fs::write(std::env::var("SMOKE_MODE").unwrap(), cfg!(clippy).to_string()).unwrap();
}
"""


def cargo_messages(stdout: str) -> list[dict]:
    records = []
    for line in stdout.splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def diagnostics(stdout: str) -> list[dict]:
    messages = []
    for record in cargo_messages(stdout):
        if record.get("reason") != "compiler-message":
            continue
        message = record["message"]
        code = (message.get("code") or {}).get("code", "")
        if not code.startswith("clippy::"):
            continue
        messages.append(
            {
                "code": code,
                "level": message["level"],
                "message": message["message"],
                "spans": [
                    {
                        key: span[key]
                        for key in (
                            "file_name",
                            "line_start",
                            "column_start",
                            "line_end",
                            "column_end",
                            "is_primary",
                        )
                    }
                    for span in message["spans"]
                ],
            }
        )
    return sorted(messages, key=lambda message: json.dumps(message, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cargo", type=Path)
    parser.add_argument("--rustc", type=Path)
    parser.add_argument(
        "--cargo-home",
        type=Path,
        help="Defaults to CARGO_HOME or an isolated home under the artifact root",
    )
    parser.add_argument(
        "--if-supported",
        action="store_true",
        help="Skip older Cargo versions without -Zohm-clippy-codegen",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path(tempfile.gettempdir()) / "ohm-clippy-codegen-smoke",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="Defaults to the evidence directory under the artifact root",
    )
    args = parser.parse_args()
    root = args.artifact_root.resolve()
    evidence = (args.evidence_dir or root / "evidence").resolve()
    if args.cargo:
        args.cargo = args.cargo.absolute()
    if args.rustc:
        args.rustc = args.rustc.absolute()
    cargo = [str(args.cargo)] if args.cargo else ["cargo", "+ohm"]
    rustc = [str(args.rustc)] if args.rustc else ["rustc", "+ohm"]
    if args.if_supported:
        help_result = subprocess.run(
            [*cargo, "-Zhelp"], text=True, capture_output=True, check=True
        )
        if "ohm-clippy-codegen" not in help_result.stdout:
            print(
                "Skipping Clippy/codegen smoke: selected Cargo does not support -Zohm-clippy-codegen"
            )
            return
    fixture = root / "fixture"
    for path in (fixture / "src", fixture / "tests", evidence):
        path.mkdir(parents=True, exist_ok=True)
    (fixture / "Cargo.toml").write_text(
        '[package]\nname = "clippy-test-smoke"\nversion = "0.0.0"\nedition = "2024"\n\n[workspace]\n'
    )
    (fixture / "src/lib.rs").write_text(LIBRARY)
    (fixture / "tests/smoke.rs").write_text(TEST)
    config = fixture / "clippy.toml"
    config.write_text("disallowed-names = []\n")
    marker, mode = evidence / "executed", evidence / "mode"
    env = dict(os.environ)
    for name in (
        "RUSTC",
        "RUSTDOC",
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
        "CLIPPY_ARGS",
        "CLIPPY_CODEGEN",
        "CARGO_OHM_CLIPPY_ARGS",
        "__CARGO_OHM_CLIPPY_CODEGEN",
        "CARGO_BUILD_BUILD_DIR",
        "SMOKE_FAIL",
    ):
        env.pop(name, None)
    env.update(
        CARGO_HOME=str(
            (
                args.cargo_home or Path(env.get("CARGO_HOME", root / "cargo-home"))
            ).resolve()
        ),
        CARGO_TARGET_DIR=str(root / "fused/ohm"),
        CARGO_INCREMENTAL="1",
        CARGO_BUILD_WARNINGS="warn",
        CLIPPY_CONF_DIR=str(fixture),
        SMOKE_EXECUTED=str(marker),
        SMOKE_MODE=str(mode),
    )
    if args.rustc:
        env["RUSTC"] = str(args.rustc)
        env["RUSTDOC"] = str(args.rustc.with_name("rustdoc"))
        env["PATH"] = str(args.rustc.parent) + os.pathsep + env["PATH"]
    records = []

    def run(
        label: str, command: list[str], *, expected: int = 0, extra: dict | None = None
    ) -> dict:
        marker.unlink(missing_ok=True)
        mode.unlink(missing_ok=True)
        started = time.monotonic()
        started_at = time.time()
        result = subprocess.run(
            command,
            cwd=fixture,
            env=env | (extra or {}),
            text=True,
            capture_output=True,
            check=False,
        )
        record = {
            "label": label,
            "command": command,
            "started_at": started_at,
            "seconds": time.monotonic() - started,
            "exit_code": result.returncode,
            "diagnostics": diagnostics(result.stdout),
            "artifacts": [
                {key: message[key] for key in ("fresh", "executable", "filenames")}
                for message in cargo_messages(result.stdout)
                if message.get("reason") == "compiler-artifact"
            ],
            "test_executed": marker.exists(),
            "clippy_mode": mode.read_text() if mode.exists() else None,
        }
        (evidence / f"{label}.stdout").write_text(result.stdout)
        (evidence / f"{label}.stderr").write_text(result.stderr)
        records.append(record)
        (evidence / "results.json").write_text(json.dumps(records, indent=2) + "\n")
        print(
            f"{label}: exit {result.returncode}, {record['seconds']:.2f}s", flush=True
        )
        assert result.returncode == expected, (
            f"{label}: {result.stderr}\n{result.stdout}"
        )
        return record

    cargo_args = ["--offline", "--test", "smoke", "--message-format=json"]

    def fused(
        label: str,
        *,
        lint_args: list[str] = LINT_ARGS,
        expected: int = 0,
        extra: dict | None = None,
        test_args: list[str] | None = None,
    ) -> dict:
        return run(
            label,
            [
                *cargo,
                "-Zohm-clippy-codegen",
                "test",
                *cargo_args,
                "--",
                *(test_args or ["--nocapture"]),
            ],
            expected=expected,
            extra={"CARGO_OHM_CLIPPY_ARGS": " ".join(lint_args)} | (extra or {}),
        )

    run("toolchain", [*rustc, "--version", "--verbose"])
    reference = run(
        "reference-clippy",
        [*cargo, "clippy", *cargo_args, "--no-deps", "--", *LINT_ARGS],
        extra={"CARGO_TARGET_DIR": str(root / "separate/ohm")},
    )
    assert len(reference["diagnostics"]) == 2, reference
    assert {
        span["file_name"]
        for diagnostic in reference["diagnostics"]
        for span in diagnostic["spans"]
        if span["is_primary"]
    } == {"src/lib.rs", "tests/smoke.rs"}, reference
    first = fused("fused-warning")
    assert first["diagnostics"] == reference["diagnostics"], first
    assert first["test_executed"] and first["clippy_mode"] == "false", first
    repeat = fused("fused-noop")
    assert repeat["diagnostics"] == first["diagnostics"], repeat
    assert repeat["test_executed"], repeat
    assert len(repeat["artifacts"]) == 2 and all(
        artifact["fresh"] for artifact in repeat["artifacts"]
    ), repeat

    listed = fused("fused-list", test_args=["--list"])
    plain = run(
        "plain-list",
        [*cargo, "test", *cargo_args, "--", "--list"],
        extra={"CARGO_TARGET_DIR": str(root / "separate/ohm")},
    )
    assert not listed["test_executed"] and not plain["test_executed"]
    test_names = lambda label: sorted(
        line
        for line in (evidence / f"{label}.stdout").read_text().splitlines()
        if line.endswith(": test")
    )
    assert (
        test_names("fused-list")
        == test_names("plain-list")
        == ["executes: test", "records_compilation_mode: test"]
    )
    ordinary = run(
        "plain-same-target",
        [*cargo, "test", *cargo_args],
    )
    assert ordinary["clippy_mode"] == "false", ordinary
    combined = fused("fused-after-plain")
    assert combined["clippy_mode"] == "false", combined
    ordinary_binary = next(
        artifact["executable"]
        for artifact in ordinary["artifacts"]
        if artifact["executable"]
    )
    combined_binary = next(
        artifact["executable"]
        for artifact in combined["artifacts"]
        if artifact["executable"]
    )
    assert ordinary_binary != combined_binary
    assert Path(ordinary_binary).is_file() and Path(combined_binary).is_file()

    denied = fused(
        "denied-existing-binary", lint_args=[*LINT_ARGS, f"-D{LINT}"], expected=101
    )
    assert not denied["test_executed"] and not denied["clippy_mode"], denied
    assert any(
        diagnostic["level"] == "error" and diagnostic["code"] == LINT
        for diagnostic in denied["diagnostics"]
    ), denied
    recovered = fused("warning-after-deny")
    assert (
        recovered["diagnostics"] == first["diagnostics"] and recovered["test_executed"]
    ), recovered

    cargo_config = fixture / ".cargo/config.toml"
    cargo_config.parent.mkdir(exist_ok=True)
    cargo_config.write_text(
        f'[env]\nCARGO_OHM_CLIPPY_ARGS = "-Aclippy::all -D{LINT}"\n'
    )
    try:
        configured = run(
            "config-env-deny",
            [*cargo, "-Zohm-clippy-codegen", "test", *cargo_args],
            expected=101,
        )
        assert not configured["test_executed"] and not configured["clippy_mode"], (
            configured
        )
        assert any(
            diagnostic["level"] == "error" and diagnostic["code"] == LINT
            for diagnostic in configured["diagnostics"]
        ), configured
    finally:
        cargo_config.unlink()

    (fixture / "src/lib.rs").write_text(
        LIBRARY.replace("HashMap<u8, ()>", "HashMap<u8, u8>")
    )
    (fixture / "tests/smoke.rs").write_text(
        TEST.replace("HashMap<u8, ()>", "HashMap<u8, u8>")
    )
    assert fused("source-clean")["diagnostics"] == []
    config.write_text('disallowed-names = ["input"]\n')
    changed_config = fused("config-warning")
    assert [message["code"] for message in changed_config["diagnostics"]] == [
        "clippy::disallowed_names"
    ], changed_config
    config.write_text("disallowed-names = []\n")
    assert fused("config-reverted")["diagnostics"] == []
    config.unlink()
    assert fused("config-absent")["diagnostics"] == []
    config.write_text('disallowed-names = ["input"]\n')
    created_config = fused("config-created")
    assert [message["code"] for message in created_config["diagnostics"]] == [
        "clippy::disallowed_names"
    ], created_config
    config.unlink()
    assert fused("config-deleted")["diagnostics"] == []
    config.write_text("disallowed-names = []\n")
    (fixture / "src/lib.rs").write_text(LIBRARY)
    (fixture / "tests/smoke.rs").write_text(TEST)
    assert fused("source-reverted")["diagnostics"] == first["diagnostics"]
    failed = fused("runtime-failure", expected=101, extra={"SMOKE_FAIL": "1"})
    assert failed["test_executed"], failed
    nextest = subprocess.run(
        [*cargo, "nextest", "--version"],
        cwd=fixture,
        env=env,
        capture_output=True,
        check=False,
    )
    assert nextest.returncode == 0, (
        "cargo-nextest is required for this integration check"
    )
    nextest_command = [*cargo, "-Zohm-clippy-codegen", "nextest", "run"]
    nextest_args = ["--offline", "--test", "smoke", "--status-level=fail"]
    ran_nextest = run(
        "nextest",
        [*nextest_command, *nextest_args],
        extra={"CARGO_OHM_CLIPPY_ARGS": " ".join(LINT_ARGS)},
    )
    assert ran_nextest["test_executed"] and ran_nextest["clippy_mode"] == "false", (
        ran_nextest
    )
    nextest_denied = run(
        "nextest-denied",
        [*nextest_command, *nextest_args],
        extra={"CARGO_OHM_CLIPPY_ARGS": " ".join([*LINT_ARGS, f"-D{LINT}"])},
        expected=101,
    )
    assert not nextest_denied["test_executed"] and not nextest_denied["clippy_mode"], (
        nextest_denied
    )
    assert (
        "map with zero-sized value type"
        in (evidence / "nextest-denied.stderr").read_text()
    )
    default_targets = run(
        "default-targets-and-doctests",
        [*cargo, "-Zohm-clippy-codegen", "test", "--offline", "--message-format=json"],
        extra={"CARGO_OHM_CLIPPY_ARGS": " ".join(LINT_ARGS)},
    )
    assert (
        default_targets["test_executed"] and default_targets["clippy_mode"] == "false"
    )
    assert (
        "1 passed; 0 failed"
        in (evidence / "default-targets-and-doctests.stdout").read_text()
    )
    wrapper_command = [
        *cargo,
        "-Zohm-clippy-codegen",
        "test",
        "--offline",
        "--test",
        "smoke",
    ]
    for name in ("RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER"):
        rejected = run(
            f"reject-{name.lower()}",
            wrapper_command,
            expected=101,
            extra={name: "/bin/false"},
        )
        assert not rejected["test_executed"], rejected
    rejected_config = run(
        "reject-config",
        [*wrapper_command, "--config", 'build.rustc-workspace-wrapper="/bin/false"'],
        expected=101,
    )
    assert not rejected_config["test_executed"], rejected_config
    print(f"Smoke checks passed; raw evidence: {evidence}")


if __name__ == "__main__":
    main()
