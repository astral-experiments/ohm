#!/usr/bin/env python3
"""Capture the production uv-pep440 crate invocation with exact patched Ohm dependencies."""

import argparse
import os
import subprocess
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--repo", type=Path, required=True)
p.add_argument("--revision", default="5d64ede21e9e835e59ecd85329ebefd43faa8211")
p.add_argument("--checkout", type=Path, required=True)
p.add_argument("--stage", type=Path, required=True)
p.add_argument("--target-dir", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
p.add_argument(
    "--offline",
    action="store_true",
    help="require dependencies to be available locally",
)
a = p.parse_args()
for path in [a.checkout, a.target_dir, a.output]:
    path.mkdir(parents=True, exist_ok=True)
archive_marker = a.checkout / ".ohm-resident-uv-revision"
if not (a.checkout / "Cargo.toml").exists():
    with subprocess.Popen(
        ["git", "-C", str(a.repo), "archive", a.revision], stdout=subprocess.PIPE
    ) as archive:
        subprocess.run(
            ["tar", "-xf", "-", "-C", str(a.checkout)], stdin=archive.stdout, check=True
        )
        if archive.wait():
            raise SystemExit("git archive failed")
    archive_marker.write_text(a.revision + "\n")
elif not archive_marker.is_file() or archive_marker.read_text().strip() != a.revision:
    raise SystemExit(
        "--checkout must be an empty directory or an archive created by this script for the same revision"
    )
source = Path(__file__).resolve().parent
capture = (a.output / "capture.json").resolve()
if not capture.exists():
    (a.checkout / "crates/uv-pep440/src/lib.rs").touch()
env = dict(
    os.environ,
    CARGO_TARGET_DIR=str(a.target_dir.resolve()),
    CARGO_BUILD_BUILD_DIR=str((a.target_dir / "build").resolve()),
    CARGO_INCREMENTAL="0",
    RUSTC=str((a.stage / "bin/rustc").resolve()),
    RUSTC_WRAPPER=str(source / "capture_rustc.py"),
    OHM_UV_CAPTURE=str(capture),
    RUSTC_BOOTSTRAP="1",
)
command = [
    "cargo",
    "+ohm",
    "-Zohm-defaults=no",
    "check",
    "-p",
    "uv-pep440",
    "--lib",
    "-v",
]
if a.offline:
    command.append("--offline")
proc = subprocess.run(
    command, cwd=a.checkout, env=env, capture_output=True, text=True, check=False
)
(a.output / "cargo.log").write_text(
    "$ " + " ".join(command) + "\n" + proc.stdout + proc.stderr
)
print(proc.stdout + proc.stderr, end="")
if not capture.is_file() or proc.returncode:
    raise SystemExit(proc.returncode or 1)
