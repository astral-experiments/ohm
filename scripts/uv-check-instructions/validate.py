"""Run the fixture and run-make checks with both measured compiler builds."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

here = Path(__file__).resolve().parent
scratch = Path(os.environ["RUNNER_TEMP"])
out = scratch / "out"
kits = scratch / "kits"
tests = Path("source/tests").resolve()
recipes = [
    "incremental-check-dependency-salt",
    "incremental-missing-query-cache",
    "incremental-loaded-cache-values",
    "incremental-retained-cache-snapshot",
    "incremental-recomputed-query-spans",
    "incremental-module-syntax",
    "rdr-public-hash-ctfe-literal-identity",
]
roles = ("control", "candidate")


def env(kit):
    lib = str(kit / "lib")
    host = "x86_64-unknown-linux-gnu"
    return dict(
        os.environ,
        HOST=host, TARGET=host, HOST_RUSTC_DYLIB_PATH=lib, LD_LIBRARY_PATH=lib,
        LD_LIB_PATH_ENVVAR="LD_LIBRARY_PATH",
        TARGET_EXE_DYLIB_PATH=str(kit / "lib/rustlib" / host / "lib"),
        RUSTC=str(kit / "bin/rustc"), RUSTC_BOOTSTRAP="1",
        CARGO_HOME=str(scratch / "registry"), CARGO_INCREMENTAL="0",
        CARGO_TARGET_DIR=str(scratch / "recipe-build"),
    )


def run(command, **options):
    print(*command, flush=True)
    subprocess.run(command, check=True, **options)


def corpus():
    suites = {}
    for role in roles:
        rustc = kits / role / "bin/rustc"
        with (out / role / "suppliers.json").open("w") as f:
            run([sys.executable, here / "suppliers.py", rustc, "--rotate"], stdout=f)
        path = out / role / "salt.jsonl"
        with path.open("w") as f:
            run([sys.executable, here / "corpus.py", rustc, tests, "salt", "--jobs", "6"], stdout=f)
        cases = [json.loads(line) for line in path.open()]
        suites[role] = {(r["fixture"], r["edit"]): r for r in cases}
        assert len(cases) == len(suites[role])
    control, candidate = map(suites.get, roles)
    assert control.keys() == candidate.keys()
    for key, row in control.items():
        other = candidate[key]
        for field in ("source_sha256", "status", "exit"):
            assert row.get(field) == other.get(field), (field, key)
        if "warm" in row:
            assert row["warm"]["exit"] == other["warm"]["exit"], key
        if row["status"] == "different":
            def differences(r):
                return [k for k, v in r["warm"].items() if v != r["fresh"].get(k)]
            assert differences(row) == differences(other), key
    from collections import Counter
    print(Counter(x["status"] for x in candidate.values()), flush=True)


def run_make():
    project = scratch / "recipes"
    project.mkdir()
    support = tests.parent / "src/tools/run-make-support"
    manifest = f"""[package]
name = "recipes"
version = "0.0.0"
edition = "2024"

[dependencies]
run_make_support = {{ path = "{support}" }}
"""
    for recipe in recipes:
        manifest += f'\n[[bin]]\nname = "{recipe}"\npath = "{tests}/run-make/{recipe}/rmake.rs"\n'
    (project / "Cargo.toml").write_text(manifest)
    shutil.copy2(tests.parent / "Cargo.lock", project)
    run([kits / "cargo", "build", "--profile", "dev", "--bins"], cwd=project, env=env(kits / "control"))
    for recipe in recipes:
        executable = scratch / "recipe-build/debug" / recipe
        for role in roles:
            path = out / role / (recipe + ".log")
            work = scratch / "recipe"
            shutil.copytree(tests / "run-make" / recipe, work)
            try:
                with path.open("w") as log:
                    run([executable], cwd=work, env=env(kits / role), stdout=log, stderr=log)
            except Exception:
                print(path.read_text()[-4000:])
                raise
            shutil.rmtree(work)


corpus()
run_make()
