"""Compare native outputs across an export rename using the installed +ohm toolchain."""
import argparse
import json
import os
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("directory", type=Path, help="new private directory for this replay")
parser.add_argument("mode", choices=["build", "test"])
parser.add_argument("--defaults-off", action="store_true")
options = parser.parse_args()
root = options.directory.resolve()
root.mkdir()
project = root / "source"
fixture = json.loads(Path(__file__).with_name("early-release-export.json").read_text())["fixture"]
for name, contents in fixture["common_files"].items():
    if name == ("app/tests/control.rs" if options.mode == "build" else "app/src/main.rs"):
        continue
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
env = {**os.environ, "CARGO_HOME": str(root / "cargo-home"), "CARGO_NET_OFFLINE": "true"}
command = ["cargo", "+ohm"]
if options.defaults_off:
    command.append("-Zohm-defaults=no")
if options.mode == "test":
    command.extend(["test", "-p", "app", "--test", "control", "--no-run"])
else:
    command.extend(["build", "-p", "app", "--bin", "app"])
command.extend(["--offline", "--locked", "--message-format=json"])

matches = True
for phase, source, lane, expected in [
    ("before edit", "original", "warm", 17),
    ("after edit", "edit", "warm", 83),
    ("unchanged retry", "edit", "warm", 83),
    ("independent empty build", "edit", "empty", 83),
]:
    source_path = project / fixture["source_path"]
    if not source_path.exists() or source_path.read_text() != fixture[source]:
        source_path.write_text(fixture[source])
    env.update(CARGO_TARGET_DIR=str(root / lane / "target"), CARGO_BUILD_BUILD_DIR=str(root / lane / "build"))
    cargo = subprocess.run(command, cwd=project, env=env, text=True, stdout=subprocess.PIPE, check=True)
    messages = [json.loads(line) for line in cargo.stdout.splitlines()]
    executable, = [m["executable"] for m in messages if m.get("executable")]
    argv = [executable]
    if options.mode == "test":
        argv += ["--exact", "root_value", "--nocapture"]
    outcomes = {v: subprocess.run(argv, env={**env, "WANT": str(v)}, capture_output=True).returncode for v in [3, 17, 83]}
    observed, = [value for value, status in outcomes.items() if status == 0]
    matches &= observed == expected
    print(f"{phase}: {observed} (expected {expected})", flush=True)
raise SystemExit(0 if matches else 1)
