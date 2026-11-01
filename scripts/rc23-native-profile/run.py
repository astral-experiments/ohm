"""Test the release profile step with its original collector and an independently prepared copy."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

(mode,) = sys.argv[1:]
assert mode in ("exact", "prepare")
w = Path(os.environ["GITHUB_WORKSPACE"])
qa = Path(__file__).resolve().parent
d = w / "native-evidence"
recipe = json.loads((qa / "recipe.json").read_bytes())
coordinator = w / "release-candidate"
rust = w / "source/rust"
driver = coordinator / "scripts/build-optimized-dist.sh"
official_sha = hashlib.sha256(driver.read_bytes()).hexdigest()
assert official_sha == json.loads((d / "identity.json").read_bytes())["official_build"]
env = dict(os.environ)
if mode == "prepare":
    perf = rust / "src/tools/rustc-perf"
    subprocess.run(
        [
            "git",
            "-C",
            rust,
            "submodule",
            "update",
            "--init",
            "--depth=1",
            "--",
            "src/tools/rustc-perf",
        ],
        check=True,
    )
    assert (
        subprocess.check_output(
            ["git", "-C", perf, "rev-parse", "HEAD"], text=True
        ).strip()
        == recipe["rustc_perf"]
    )
    checkout = Path(env["RUNNER_TEMP"]) / "prepared-rustc-perf"
    shutil.copytree(
        perf, checkout, symlinks=True, ignore=shutil.ignore_patterns(".git")
    )
    source = checkout / recipe["collector_path"]
    patch = qa / "prepare-relocated-dependencies.patch"
    assert (
        hashlib.sha256(source.read_bytes()).hexdigest() == recipe["before"]
        and hashlib.sha256(patch.read_bytes()).hexdigest() == recipe["patch_sha"]
    )
    subprocess.run(
        ["patch", "--batch", "--forward", "--fuzz=0", "-p1", "-i", patch],
        cwd=checkout,
        check=True,
    )
    assert hashlib.sha256(source.read_bytes()).hexdigest() == recipe["after"]
    original = driver.read_text()
    target = "opt_dist_arguments=(\n  local\n"
    assert original.count(target) == 1
    driver = d / "build-prepared-dist.sh"
    driver.write_text(
        original.replace(
            target,
            target + '  --rustc-perf-checkout-dir "${OHM_TRAINING_COLLECTOR:?}"\n',
        )
    )
    env["OHM_TRAINING_COLLECTOR"] = str(checkout)
    subprocess.run(["bash", "-n", driver], check=True)
(d / "recipe-used.json").write_text(
    json.dumps(
        {
            "mode": mode,
            "recipe": recipe,
            "executed_script": hashlib.sha256(driver.read_bytes()).hexdigest(),
        },
        indent=2,
    )
    + "\n"
)
# Collect Cargo's reasons during this diagnostic replay. Neither invocation changes the toolchain's defaults.
env["CARGO_LOG"] = (
    "cargo::compiler::fingerprint=info,cargo::core::compiler::fingerprint=info"
)
subprocess.run(
    [
        "bash",
        driver,
        "x86_64-unknown-linux-gnu",
        "ohm-1.99.0-23",
        rust,
        coordinator / "release/bootstrap.toml",
    ],
    env=env,
    check=True,
)
