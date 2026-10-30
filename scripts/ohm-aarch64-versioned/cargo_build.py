"""Build and stamp this Cargo from the exact original #293 source and release tool operands."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ohm-aarch64-fallback"))
import build as original
from transport import SOURCES, apply

baseline = original.materialize
meta = SOURCES["cargo"]

def materialize(src):
    entry = baseline(src)
    assert entry["commit"] == meta["parent"]
    now = apply("cargo", src)
    return {**entry, "parent": now["parent"], "commit": now["source"], "tree": now["tree"],
            "source_changes": now, "derived_from": entry}

def unit():
    rt = original.rt
    job = rt.ROOT / "cargo-build"
    env = rt.environment()
    env.update(CARGO_HOME=str(job / "registry"), CARGO_TARGET_DIR=str(job / "target"),
               CARGO_BUILD_BUILD_DIR=str(job / "shared"))
    args = ["cargo", "+ohm", "-Zohm-defaults=no", "test", "--release", "--locked", "--offline",
            "-p", "cargo", "--lib", "--features", original.FEATURES, "-j8",
            "recheck_links_only_for_the_compiler_generated_marker"]
    result = rt.record(args, rt.LOG / "cargo-293-source" / "marker-unit", rt.ROOT / "exact-cargo-source", env)
    assert b"1 passed; 0 failed;" in result.stdout
    assert b"recheck_links_only_for_the_compiler_generated_marker ... ok" in result.stdout

if __name__ == "__main__":
    if sys.argv[1:] == ["unit"]:
        unit()
    else:
        original.CANDIDATE, original.TREE, original.materialize = meta["source"], meta["tree"], materialize
        original.main()
