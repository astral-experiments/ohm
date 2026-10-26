#!/usr/bin/env python3
"""Create private compiler, linker and counter entry points for a historical Ruff study."""

import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "wild_measure", HERE.parent / "measure.py"
)
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["build", "test"])
    parser.add_argument("state", type=Path, help="new private experiment directory")
    for name in [
        "ruff",
        "toolchain",
        "cargo",
        "cargo-home",
        "drrun",
        "pidcounter",
        "control",
        "middle",
        "candidate",
    ]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    mode = args.mode
    state = args.state.resolve()
    paths = {
        key: str(getattr(args, key).resolve(strict=True))
        for key in [
            "ruff",
            "toolchain",
            "cargo",
            "cargo_home",
            "drrun",
            "pidcounter",
            "control",
            "middle",
            "candidate",
        ]
    }
    assert (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=paths["ruff"], text=True
        ).strip()
        == helpers.RUFF
    )
    assert not subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=paths["ruff"]
    )
    plan = json.loads((HERE / f"{mode}-plan.json").read_bytes())
    for arm, sha in plan["hashes"].items():
        assert helpers.sha(Path(paths[arm])) == sha, (arm, sha)
    assert (
        helpers.sha(Path(paths["cargo"]))
        == "211465de4b9e4589da2be06871acd9304dd3b94c849c1304f723484cb4f71dfc"
    )
    assert "ohm-1.99.0-14" in subprocess.check_output(
        [Path(paths["toolchain"]) / "bin/rustc", "--version", "--verbose"], text=True
    )
    state.mkdir(parents=True)
    for name in ["target", "shared", "results", "fixtures"]:
        (state / name).mkdir()
    paths.update(target=str(state / "target"), shared=str(state / "shared"))
    rustup, cargo = helpers.private_cargo(Path(paths["toolchain"]), state)
    helpers.replace(Path(paths["cargo"]), cargo)
    linker = state / "ld.bfd"
    helpers.replace(Path(paths["control"]), linker)
    clang = shutil.which("clang")
    assert clang
    driver = state / "clang"
    driver.write_text(
        "#!/bin/sh\nexec "
        + shlex.quote(clang)
        + ' "$@" '
        + shlex.quote("--ld-path=" + str(linker))
        + " -Wl,--no-fork\n"
    )
    driver.chmod(0o755)
    collector = state / f"historical-collectors-{mode}"
    collector.mkdir()
    shutil.copy2(HERE / "rustc-wrapper", collector / "rustc-wrapper")
    fixtures = json.loads((HERE / "fixture-info.json").read_bytes())
    for workload in fixtures["fixtures"]:
        label = workload["label"]
        raw = gzip.decompress((HERE / "fixtures" / (label + ".patch.gz")).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == workload["patch_sha256"]
        (state / "fixtures" / (label + ".patch")).write_bytes(raw)
    (state / "fixtures/manifest.json").write_text(json.dumps(fixtures))
    shutil.copyfile(HERE / f"{mode}-plan.json", state / "results/wall-plan-0.json")
    shutil.copyfile(
        HERE / f"{mode}-elapsed-replication-plan.json",
        state / "results/wall-plan-1.json",
    )
    (state / "paths.json").write_text(json.dumps(paths, indent=2) + "\n")
    print(state / "paths.json")


if __name__ == "__main__":
    main()
