"""Add target standard libraries to the normal GNU PGO and BOLT build for this comparison."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

work = Path(os.environ["GITHUB_WORKSPACE"])
root = work / "release-candidate"
out = work / "cross-evidence"
rust = work / "source/rust"
plan = json.loads((Path(__file__).resolve().parent / "protocol.json").read_text())
host = "x86_64-unknown-linux-gnu"
gnu = "aarch64-unknown-linux-gnu"
musl = "x86_64-unknown-linux-musl"
tools = {name: shutil.which(name) for name in ("aarch64-linux-gnu-gcc", "aarch64-linux-gnu-g++", "musl-gcc", "qemu-aarch64")}
assert all(tools.values())
headers = Path("/usr/include/x86_64-linux-musl")
libraries = Path("/usr/lib/x86_64-linux-musl")
assert (headers / "stdlib.h").is_file() and all((libraries / lib).is_file() for lib in ("libc.a", "crt1.o", "crti.o", "crtn.o"))
prefix = Path(os.environ["RUNNER_TEMP"]) / "rc23-musl"
prefix.mkdir()
(prefix / "include").symlink_to(headers, target_is_directory=True)
(prefix / "lib").symlink_to(libraries, target_is_directory=True)
config = root / "release/bootstrap.toml"
assert hashlib.sha256(config.read_bytes()).hexdigest() == plan["bootstrap_sha256"]
extra = f"""
[target.{gnu}]
cc = "{tools['aarch64-linux-gnu-gcc']}"
cxx = "{tools['aarch64-linux-gnu-g++']}"
linker = "{tools['aarch64-linux-gnu-gcc']}"

[target.{musl}]
cc = "{tools['musl-gcc']}"
linker = "{tools['musl-gcc']}"
musl-root = "{prefix}"
musl-libdir = "{libraries}"
"""
cfg = out / "cross-bootstrap.toml"
cfg.write_text(config.read_text() + extra)
source = root / "scripts/build-optimized-dist.sh"
assert hashlib.sha256(source.read_bytes()).hexdigest() == plan["build_script_sha256"]
script = source.read_text()
for previous, added in [('  --std-target wasm32-unknown-unknown\n', f'  --std-target wasm32-unknown-unknown\n  --std-target {gnu}\n  --std-target {musl}\n'), ('  --target "$target,wasm32-unknown-unknown"', f'  --target "$target,wasm32-unknown-unknown,{gnu},{musl}"')]:
    assert script.count(previous) == 1
    script = script.replace(previous, added)
assert hashlib.sha256((root / "release/rustc-perf-relocated-dependencies.patch").read_bytes()).hexdigest() == plan["profile_patch_sha256"]
driver = source.with_name("build-cross-dist.sh")
assert not driver.exists()
driver.write_text(script)
(out / "build-cross-dist.sh").write_text(script)
subprocess.run(["bash", "-n", driver], check=True)
subprocess.run(["bash", driver, host, "ohm-1.99.0-23", rust, cfg], check=True)
