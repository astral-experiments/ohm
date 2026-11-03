"""Reopen the known lifetime permutations and reject a partial permutation and unrelated edits."""

import hashlib, json, resource, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import opaque_bijection as wire

CASES = {
    "P": (
        "ba1da2d3de90e743b8ab581c0cc9dff74e8d8a39a58bc1149d62cbdfbe9f8a9e",
        "b8bc0d2506fef136d9383e4bfc6c588d023abb129a2c37298e628a91fc8ecf31",
        16,
        436,
    ),
    "C": (
        "7c5c4851a317041723d51469bd8d8b5ef59b674681e08a432d0f2f5a8d5284fe",
        "d21b824e88c505e3af3bef08e173490c1f5ab4119c3aa5d9d41f56d496dcd026",
        21,
        636,
    ),
}


def guard():
    available = (
        int(
            next(
                l.split()[1]
                for l in Path("/proc/meminfo").read_text().splitlines()
                if l.startswith("MemAvailable:")
            )
        )
        * 1024
    )
    assert available >= 8 << 30, ("prior-reader resource floor", available)


def main():
    root, out = map(Path, sys.argv[1:])
    tests = {}
    resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))
    for role, (old, new, moves, diffs) in CASES.items():
        guard()
        a, b = [subprocess.check_output(["zstd", "-qdc", root / (h + ".rmeta.zst")]) for h in (old, new)]
        assert [hashlib.sha256(x).hexdigest() for x in (a, b)] == [old, new]

        def run(current):
            return wire.compare(a, current, role, "rustc 1.99.0-dev (Ohm metadata 3)", "2024")

        row = run(b)
        assert (
            len(row["actual_reordered_synthetic_definitions"]) == moves
            and row["different_bytes"] == diffs
            and not row["unattributed"]
        )
        rejected = []
        for kind in (
            "DefPathHash -> DefIndex reverse lookup",
            "definition and identifier span payload",
            "rdr_local physical table slot",
            "unregistered tail",
        ):
            guard()
            i = len(b) - 1 if kind == "unregistered tail" else row["physical_field_witnesses"][kind]
            damaged = bytearray(b)
            damaged[i] = a[i] if kind != "unregistered tail" else b[i] ^ 1
            assert damaged != b
            try:
                run(bytes(damaged))
            except (AssertionError, KeyError, ValueError, IndexError, UnicodeDecodeError):
                rejected.append(kind)
            else:
                raise RuntimeError(("admitted corrupt metadata", role, kind, i))
        tests[role] = {
            "originals": [old, new],
            "lifetime_keys": moves,
            "changed_bytes": diffs,
            "rejections": rejected,
        }
        out.write_text(json.dumps(tests, sort_keys=True, indent=1) + "\n")
        print(role, moves, diffs, len(rejected), flush=True)


if __name__ == "__main__":
    main()
