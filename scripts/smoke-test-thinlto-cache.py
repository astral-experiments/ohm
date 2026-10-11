#!/usr/bin/env python3
"""Exercise managed ThinLTO caching with an installed Ohm toolchain."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", default="ohm")
    parser.add_argument("--output", type=Path, help="Save a compact validation receipt")
    parser.add_argument("--fallback-rustc", type=Path, help="Also check an older Ohm compiler")
    args = parser.parse_args()
    env = os.environ.copy()
    for key in (
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
        "CARGO_BUILD_RUSTFLAGS",
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
        "RUSTC",
        "CARGO_INCREMENTAL",
        "CARGO_UNSTABLE_OHM_DEFAULTS",
        "CARGO_UNSTABLE_OHM_THINLTO_CACHE",
        "CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST",
        "CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST",
    ):
        env.pop(key, None)
    env["CARGO_TERM_COLOR"] = "never"
    env["RUSTC_LOG"] = "rustc_codegen_llvm::back::lto=info"
    compiler = subprocess.check_output(
        ["rustc", f"+{args.toolchain}", "-Vv"], env=env, text=True
    )
    if "host: x86_64-unknown-linux-gnu" not in compiler:
        raise SystemExit("This smoke test currently requires native x86-64 GNU Linux")

    with tempfile.TemporaryDirectory(prefix="ohm-thinlto-smoke-") as temporary:
        root = Path(temporary)
        source = root / "project"
        (source / "src").mkdir(parents=True)
        (source / "dep/src").mkdir(parents=True)
        (source / "Cargo.toml").write_text(
            '[package]\nname = "ohm-thinlto-smoke"\nversion = "0.0.0"\n'
            'edition = "2024"\n[dependencies]\ndep = { path = "dep" }\n'
            '[profile.release]\nlto = "thin"\ncodegen-units = 4\n'
        )
        (source / "dep/Cargo.toml").write_text(
            '[package]\nname = "dep"\nversion = "0.0.0"\nedition = "2024"\n'
        )
        (source / "dep/src/lib.rs").write_text(
            "#[inline(always)] pub fn answer() -> u32 { 42 }\n"
        )
        (source / "src/main.rs").write_text(
            'fn main() { println!("{}", dep::answer()); }\n'
        )
        env["CARGO_TARGET_DIR"] = str(root / "target")
        env["CARGO_BUILD_BUILD_DIR"] = str(root / "build")
        cache = root / "build/.ohm-thinlto-cache"

        def cargo(*command):
            result = subprocess.run(
                ["cargo", f"+{args.toolchain}", *command],
                cwd=source,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if result.returncode:
                raise RuntimeError(f"Cargo {command} failed:\n{result.stderr}")
            return result.stderr

        def build(*options):
            return cargo(*options, "build", "--release", "--offline", "-vv")

        def clean_leaf():
            cargo("clean", "--release", "-p", "ohm-thinlto-smoke")

        def output():
            executable = root / "target/release/ohm-thinlto-smoke"
            assert subprocess.check_output([executable], text=True) == "42\n"
            return executable.read_bytes()

        cold = build()
        assert "-Zthinlto-cache=" in cold, cold
        expected = output()
        assert list(cache.glob("*/*.cache")), "The default build did not populate the cache"
        assert (cache / ".prune-lock").is_file(), "Cargo did not run cache maintenance"

        # Sparse files exercise the actual managed limit without allocating GiBs.
        eviction = cache / ("0" * 32)
        eviction.mkdir()
        oversized = eviction / ("0" * 32 + ".cache")
        with oversized.open("wb") as file:
            file.truncate(2 * 1024**3 + 1)
        os.utime(oversized, (time.time() - 60, time.time() - 60))
        expired = eviction / ("1" * 32 + ".cache")
        expired.write_bytes(b"expired")
        age = time.time() - 31 * 24 * 60 * 60
        os.utime(expired, (age, age))

        clean_leaf()
        warm = build()
        hits = warm.count("ohm_thinlto_cache_hit ")
        assert hits > 0, warm
        assert output() == expected, "Warm-cache executable differs"
        assert not oversized.exists(), "Cargo did not enforce the size limit"
        assert not expired.exists(), "Cargo did not expire the old entry"

        clean_leaf()
        disabled = build("-Zohm-thinlto-cache=no")
        assert "-Zthinlto-cache=" not in disabled, disabled
        assert "ohm_thinlto_cache_hit " not in disabled, disabled
        assert output() == expected, "Opt-out executable differs"

        clean_leaf()
        globally_disabled = build("-Zohm-defaults=no")
        assert "-Zthinlto-cache=" not in globally_disabled, globally_disabled
        output()

        # Fat LTO must remain fat and must not use the ThinLTO backend cache.
        fat = cargo(
            "build", "--release", "--offline", "-vv",
            "--config", 'profile.release.lto="fat"',
        )
        assert "-C lto=fat" in fat, fat
        assert "-Zthinlto-cache=" not in fat, fat
        output()

        if args.fallback_rustc:
            env["RUSTC"] = str(args.fallback_rustc.resolve())
            fallback = build()
            assert "-Zthinlto-cache=" not in fallback, fallback
            output()

        receipt = {
            "compiler": compiler,
            "warm_backend_hits": hits,
            "cache_entries": len(list(cache.glob("*/*.cache"))),
            "byte_identical_cold_warm_and_opt_out": True,
            "targeted_and_global_opt_out": True,
            "fat_lto_preserved": True,
            "managed_eviction_and_expiry": True,
            "older_compiler_fallback": bool(args.fallback_rustc),
            "binary_sha256": hashlib.sha256(expected).hexdigest(),
        }
        print(json.dumps(receipt, indent=2))
        if args.output:
            args.output.write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
