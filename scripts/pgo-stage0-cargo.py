#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Extend successful upstream rustc profiling with bounded Ohm workflows."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

COLLECTOR_PREFIX = (
    "run",
    "-p",
    "collector",
    "--bin",
    "collector",
    "--",
    "profile_local",
)
RUSTC_PROFILES = "Check,Debug,Opt"


def is_rustc_training(arguments: Sequence[str]) -> bool:
    if tuple(arguments[: len(COLLECTOR_PREFIX)]) != COLLECTOR_PREFIX:
        return False
    try:
        profile_index = arguments.index("--profiles")
    except ValueError:
        return False
    return (
        profile_index + 1 < len(arguments)
        and arguments[profile_index + 1] == RUSTC_PROFILES
    )


def main(arguments: Sequence[str] | None = None) -> int:
    forwarded = list(sys.argv[1:] if arguments is None else arguments)
    configured_target_root = os.environ.get("OHM_PGO_TARGET_ROOT")
    if not configured_target_root:
        print(
            "stage-zero profiling target root is missing: OHM_PGO_TARGET_ROOT",
            file=sys.stderr,
        )
        return 1

    configured_path = Path(configured_target_root)
    if not configured_path.is_absolute() or not configured_path.is_dir():
        print(
            f"invalid stage-zero profiling target root: {configured_target_root}",
            file=sys.stderr,
        )
        return 1
    target_root = configured_path.resolve()

    # rustc-perf canonicalizes its Cargo executable before running nested
    # commands, so argv[0] can be either this symlink or its resolved script.
    invoked_cargo = Path(sys.argv[0]).absolute()
    configured_proxy = target_root / "ohm-pgo-stage0" / "bin" / "cargo"
    actual_proxy = Path(__file__).resolve()
    try:
        proxy_matches = configured_proxy.samefile(actual_proxy)
        invocation_matches = invoked_cargo.samefile(actual_proxy)
    except OSError:
        proxy_matches = False
        invocation_matches = False
    if (
        not proxy_matches
        or not invocation_matches
        or invoked_cargo not in (configured_proxy, actual_proxy)
    ):
        print(
            "stage-zero profiling target root does not match its Cargo proxy: "
            f"{target_root}",
            file=sys.stderr,
        )
        return 1

    upstream_cargo = target_root / "stage0" / "bin" / "cargo"
    if not upstream_cargo.is_file() or not os.access(upstream_cargo, os.X_OK):
        print(
            f"upstream stage-zero Cargo is missing: {upstream_cargo}", file=sys.stderr
        )
        return 1

    upstream = subprocess.run([str(upstream_cargo), *forwarded], check=False)
    if upstream.returncode != 0 or not is_rustc_training(forwarded):
        return upstream.returncode

    instrumented_rustc = target_root / "stage2" / "bin" / "rustc"
    if len(forwarded) <= len(COLLECTOR_PREFIX) + 1:
        print(
            "upstream compiler training omitted its instrumented rustc", file=sys.stderr
        )
        return 1
    requested_rustc = Path(forwarded[len(COLLECTOR_PREFIX) + 1]).resolve()
    if requested_rustc != instrumented_rustc.resolve():
        print(
            "upstream compiler training selected an unexpected instrumented rustc",
            file=sys.stderr,
        )
        return 1

    ohm_cargo = target_root / "stage1-tools-bin" / "cargo"
    if not ohm_cargo.is_file() or not os.access(ohm_cargo, os.X_OK):
        print(f"feature-enabled Ohm Cargo is missing: {ohm_cargo}", file=sys.stderr)
        return 1
    runner = Path(__file__).resolve().with_name("profile-development-workflows.py")
    if not runner.is_file():
        print(f"Ohm development training runner is missing: {runner}", file=sys.stderr)
        return 1

    phase = "pgo" if os.environ.get("LLVM_PROFILE_FILE") else "bolt"
    command = [
        sys.executable,
        str(runner),
        "--cargo",
        str(ohm_cargo),
        "--rustc",
        str(instrumented_rustc),
        "--workspace",
        str(target_root / "ohm-development-workflows"),
        "--phase",
        phase,
    ]
    if source_root := os.environ.get("OHM_DEVELOPMENT_SOURCE_ROOT"):
        command.extend(("--source-root", source_root))
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
