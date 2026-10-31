"""Explain the mixed state from physical per-path stat rows, separately from the registered gates."""

from collections import defaultdict
import gzip, json, re, statistics, sys
from pathlib import Path

D = Path(__file__).resolve().parent
sys.path.insert(0, str(D))
import reopen as r


def by_region(raw):
    inode = {}
    categories = defaultdict(set)
    families = defaultdict(set)
    owners = defaultdict(set)
    semantic = []
    for path, dev, ino, mode, blocks, size, nlinks in json.loads(gzip.decompress(raw)):
        k = dev, ino
        assert inode.setdefault(k, blocks) == blocks
        parts = Path(path).parts
        if parts[:3] == ("target", "debug", "incremental"):
            reg = "/".join(parts[:3])
            kind = (
                parts[-1]
                if parts[-1]
                in (
                    "dep-graph.bin",
                    "ohm-check-dep-graph.bin",
                    "query-cache.bin",
                    "work-products.bin",
                )
                else "native-object" if parts[-1].endswith(".o") else "other-incremental"
            )
            owner = (
                re.match(r"^(.+)-[0-9a-z]+$", parts[4])[1]
                if len(parts) >= 5 and re.match(r"^(.+)-[0-9a-z]+$", parts[4])
                else "<incremental directory>"
            )
            if owner == "ty_python_semantic" and kind in (
                "ohm-check-dep-graph.bin",
                "query-cache.bin",
            ):
                semantic.append([path, dev, ino, blocks * 512])
        else:
            reg = (
                "/".join(parts[:3])
                if parts[:2] in (("target", "debug"), ("shared", "debug")) and len(parts) >= 3
                else "other"
            )
            owner = kind = "outside-incremental"
        categories[k].add(reg)
        families[k].add(kind)
        owners[k].add(owner)

    def charge(sets):
        out = defaultdict(int)
        for k, values in sets.items():
            out[
                (
                    next(iter(values))
                    if len(values) == 1
                    else "<multiple categories; one physical inode>"
                )
            ] += (inode[k] * 512)
        return dict(out)

    return {
        "regions": charge(categories),
        "types": charge(families),
        "owners": charge(owners),
        "all": sum(inode.values()) * 512,
        "semantic": sorted(semantic),
    }


def main(directory):
    rows = []
    for row in sorted(r.REG):
        stem = directory / ("one-package-" + row)
        meta = json.loads(stem.with_suffix(".json").read_bytes())
        raw = r.open_archive(stem.with_suffix(".zip").read_bytes(), meta, row)
        current = {}
        for arm in ("0", "1"):
            source = by_region(raw["opt" + arm + "/first-unchanged/allocated-ledger.gz"])
            dest = by_region(raw["opt" + arm + "/switch-unchanged/allocated-ledger.gz"])
            assert (
                sum(source["regions"].values()) == source["all"]
                and sum(dest["types"].values()) == dest["all"]
            )
            delta = {}
            for bucket in ("regions", "types", "owners"):
                delta[bucket] = {
                    key: dest[bucket].get(key, 0) - source[bucket].get(key, 0)
                    for key in sorted(set(source[bucket]) | set(dest[bucket]))
                }
                assert sum(delta[bucket].values()) == dest["all"] - source["all"]
            old = source["semantic"]
            mixed = dest["semantic"]
            assert len(old) == 2 and len(mixed) == 4 and len({tuple(f[1:3]) for f in mixed}) == 4
            assert set(tuple(f) for f in old) <= set(tuple(f) for f in mixed)
            current[arm] = {
                "original_B": source["all"],
                "mixed_B": dest["all"],
                "delta": delta,
                "semantic_original": old,
                "semantic_mixed": mixed,
            }
        rows.append({"row": row, "arms": current})
    return {
        "method": "After-the-fact descriptive file accounting. Every device/inode is charged once in each snapshot; aliases in multiple classes get their own class. The allocation differences do not assert identical contents.",
        "rows": rows,
    }


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]) if len(sys.argv) > 1 else D), indent=2, sort_keys=True))
