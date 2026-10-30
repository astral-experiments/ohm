"""Run the native reviewer and count the host Cargo and rustc work in a fresh Ruff history."""

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import replay


COUNTER = ROOT / "replay/ohm-aarch64-registers"
VALGRIND = Path("/usr/bin/valgrind.bin")
VALGRIND_SHA256 = "def5fdcf6ae64a4d3e6af3786b622978d8313e0734ecf3f6cbe71d8be9e274c8"


def sdk_snapshot(directory, role):
    table = json.loads((ROOT / "source/sdk-members.json").read_bytes())
    expected = table["common"] | {table["driver_path"]: table["roles"][role]["driver"]}
    actual = {}
    for name, (digest, length, mode) in expected.items():
        path = directory / name
        stat = path.stat()
        assert (replay.hash_file(path), stat.st_size, stat.st_mode & 0o777) == (digest, length, mode), name
        actual[name] = [stat.st_dev, stat.st_ino, stat.st_ctime_ns, stat.st_mtime_ns, digest, length, mode]
    assert len(actual) == 119
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("A", "N", "V"))
    parser.add_argument("sdk", type=Path)
    parser.add_argument("fresh_directory", type=Path, help="a new directory on a filesystem with over 12 GiB free")
    args = parser.parse_args()
    assert replay.hash_file(VALGRIND) == VALGRIND_SHA256 and shutil.which("cc")
    role = "M" if args.role == "V" else args.role

    # The same standalone entry creates the independent old, edited, invalid and clean native references.
    replay.main()
    sys.path.insert(0, str(COUNTER))
    import cycle
    import tree_ir

    q, rt = tree_ir.q, tree_ir.rt
    assert rt.ROOT == args.fresh_directory.resolve() and rt.SDK == rt.ROOT / "rustup/toolchains/ohm"
    snapshot = sdk_snapshot(rt.SDK, role)
    def select(requested):
        assert requested == role and sdk_snapshot(rt.SDK, role) == snapshot
    rt.select = select
    q.save(rt.LOG / "reviewer-physical-kit.json", snapshot)
    tree_ir.calibrate()
    prior = rt.LOG / "review-history"
    common = {"role": role}
    for branch, phase in (("old", "old-empty"), ("cold", "empty-edited")):
        common[branch] = q.semantic(q.load(prior / phase / "verified.json"))
    cycle.OLD, cycle.NEW = (common[name]["reader"] for name in ("old", "cold"))

    # The previous clean build left an ordinary edited target at its original visible paths.
    # Take a new unchanged native reference before counting the settled state.
    clean = q.load(prior / "empty-edited/native.json")
    ast, = [row["argv"] for row in clean["rustcs"] if row["crate"] == "ruff_python_ast"]
    searches = [arg for flag, arg in zip(ast, ast[1:]) if flag == "-L" and arg.startswith("dependency=")]
    assert searches
    settled = q.visit(prior, "count-settled-reference", "new", rt.environment(), searches)
    assert q.semantic(settled) == common["cold"]
    assert sorted(settled["crates"]) == sorted(replay.ROLE_HARD[role])
    assert settled["typed"] == q.load(prior / "unchanged-2/verified.json")["typed"]
    assert settled["dirty"] == q.load(prior / "unchanged-2/verified.json")["dirty"]
    measured = tree_ir.measure(prior / "counter", rt.environment(), prior / "count-settled-reference")
    assert set(measured) == {"cargo"} | replay.ROLE_HARD[role]
    q.park("review-counter-native-reference")

    # This is the original independently trained edit and immediate repeat from the registered acquisition.
    totals = cycle.counted_cycle(prior, role, common)
    totals["settled"] = sum(record["Ir"] for record in measured.values())
    select(role)
    q.save(rt.LOG / "review-counter.json", {
        "role": args.role,
        "independent_reviewer": True,
        "formal_observations": 0,
        "source": q.load(rt.LOG / "reviewed-native.json")["source"],
        "native": q.sha(rt.LOG / "reviewed-native.json"),
        "physical_kit": q.sha(rt.LOG / "reviewer-physical-kit.json"),
        "calibration": q.sha(rt.LOG / "counter-calibrated.json"),
        "settled": q.sha(prior / "counter/verified.json"),
        "cycle": q.sha(rt.LOG / "review-history-edit-cycle/complete.json"),
        "host_Cargo_and_all_rustc_Ir": totals,
    })
    print(json.dumps(totals, sort_keys=True))


if __name__ == "__main__":
    main()
