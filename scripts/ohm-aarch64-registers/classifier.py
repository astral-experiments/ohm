"""Run each checked-in GNU target case independently and retain the actual emitted depfiles."""
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ohm-aarch64-linux"))
import runtime as rt
from study import MISSING, RECHECK, need, save, sha

CASES = ("ordinary", "general_only", "vector_only", "scalar_modifier", "vector_modifier",
         "spaced", "input_only", "instruction", "file", "escape", "raw", "global")
ALLOWED = set(CASES[:3])


def check(original):
    label = "old" if original else "new"
    root, folder = rt.LOG / ("direct-" + label), rt.ROOT / ("direct-" + label)
    folder.mkdir()
    env = rt.environment()
    (folder / "payload.bin").write_bytes(b"\x00" * 4)
    source = folder / "gnu_aarch64.rs"
    shutil.copyfile(HERE / source.name, source)
    flags = ["rustc", "+ohm", source.name, "--crate-type=rlib", "--target", rt.TARGET,
             "-Zohm-check-relink-inputs", "--emit=link,dep-info=-"]
    results = {}
    for cfg in CASES:
        result = rt.record([*flags, "--cfg", cfg], root / cfg, folder, env)
        allowed = not original and cfg in ALLOWED
        hard = MISSING in result.stdout
        recheck = RECHECK in result.stdout
        need(hard == (not allowed) and recheck == allowed, f"unexpected {cfg}: hard={hard} recheck={recheck}")
        results[cfg] = {"hard": hard, "recheck": recheck, "compile": sha(root / cfg / "command.json")}
    (folder / "payload.bin").unlink()
    for cfg in ("file", "escape"):
        out = folder / "libgnu_aarch64.rlib"
        out.unlink(missing_ok=True)
        error = rt.record([*flags, "--cfg", cfg], root / ("missing-" + cfg), folder, env, 1)
        need(b"payload.bin" in error.stderr and not out.exists(), f"false success on missing input: {cfg}")
    save(root / "complete.json", {"source": sha(source), "results": results, "file_removed": ["file", "escape"]})


if __name__ == "__main__":
    mode, = sys.argv[1:]
    need(mode in ("before", "after"), "select exact version")
    check(mode == "before")
