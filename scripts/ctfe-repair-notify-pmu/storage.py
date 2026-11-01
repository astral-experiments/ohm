"""Count retained allocations and relate the newly finalized Rust tables/objects to their real inodes."""

from collections import Counter
from pathlib import PurePosixPath
import stat

from protocol import require


def name_class(path, mode):
    name = path.name
    if stat.S_ISDIR(mode):
        return "directories"
    if stat.S_ISLNK(mode):
        return "symlinks"
    if not stat.S_ISREG(mode):
        return "other-types"
    for kind in ("dep-graph", "query-cache"):
        if name == "ohm-packed-" + kind + ".bin":
            return "packed-" + kind
        if name in (kind + ".bin", "ohm-build-" + kind + ".bin", "ohm-check-" + kind + ".bin"):
            return "raw-" + kind
    if name.startswith("ohm-packed-object-"):
        return "packed-objects"
    if name.endswith(".o"):
        return "raw-objects"
    if name.endswith(".rlib"):
        return "rlibs"
    if name.endswith(".rmeta"):
        return "rmeta"
    if mode & 0o111:
        return "executables"
    return "other-files"


def allocation(ledger, expected_total):
    entries = {}
    for key, row in ledger.items():
        path = PurePosixPath(key)
        require(
            path.as_posix() == key
            and path.parts[0] in ("build", "target")
            and ".." not in path.parts
            and len(row) == 6
            and all(type(n) is int and n >= 0 for n in row),
            "invalid raw allocation path",
        )
        dev, ino, links, mode, blocks, size = row
        require(ino > 0 and links > 0, "incomplete actual file identity")
        identity = tuple(row)
        first, scopes, names, observed = entries.setdefault((dev, ino), (identity, set(), set(), []))
        require(first == identity, "one inode reported conflicting physical extents")
        scopes.add(path.parts[0])
        names.add(name_class(path, mode))
        observed.append(key)
    by_class = Counter()
    by_root = Counter()
    logical = Counter()
    counts = Counter()
    for first, scopes, names, paths in entries.values():
        key = "+".join(sorted(names))
        scope = "+".join(sorted(scopes))
        if not stat.S_ISDIR(first[3]):
            require(len(paths) <= first[2], "more names than physical hard links")
        counts[key] += 1
        by_class[key] += first[4] * 512
        by_root[scope] += first[4] * 512
        logical[key] += first[5]
    require(
        sum(by_root.values()) == sum(by_class.values()) == expected_total,
        "whole owned-root allocation did not reconcile",
    )
    return {
        "allocated": expected_total,
        "unique_inodes": len(entries),
        "allocated_by_name_class": dict(sorted(by_class.items())),
        "allocated_by_visibility": dict(sorted(by_root.items())),
        "logical_by_name_class": dict(sorted(logical.items())),
        "inodes_by_name_class": dict(sorted(counts.items())),
    }


def owners(placements, mode, reg):
    require(set(placements) == set(reg["selected"] + reg["other"]), "missing actual selected session")
    totals, all_obj = Counter(), {}
    result = {}
    for owner, v in placements.items():
        objects = v["objects"]
        actual = sum(x["packed"] for x in objects.values())
        n_packed, n_raw = reg["packed_raw_objects"][owner]
        wanted = (0, n_raw + n_packed) if mode == "E" else (n_packed, n_raw)
        require(
            (actual, len(objects) - actual) == wanted, ("unexpected native object representation", owner)
        )
        packed = mode in ("O", "P") and owner in reg["selected"]
        require(
            v["packed_pair"] == packed
            and len(v["tables"]) == 2
            and all(t["aliases"] == 3 for t in v["tables"]),
            "unexpected repaired tables",
        )
        tables = []
        for name, t in zip(("dep-graph", "query-cache"), v["tables"], strict=True):
            key = "packed" if packed else "raw"
            physical = t[key]
            tables.append(
                {
                    "table": name,
                    "form": key,
                    "logical_bytes": t["body_bytes"],
                    "body_sha256": t["body_sha256"],
                    "storage_bytes": physical["bytes"],
                    "allocated": physical["blocks"],
                    "alias_mask": t["aliases"],
                    "dev": physical["dev"],
                    "ino": physical["ino"],
                    "links": physical["links"],
                    "sha256": physical["sha256"],
                }
            )
        counts = Counter()
        for name, x in objects.items():
            key = (x["stat"]["dev"], x["stat"]["ino"])
            value = (x["stat"]["bytes"], x["stat"]["blocks"], x["stat"]["sha256"])
            require(all_obj.setdefault(key, value) == value, "one native inode with conflicting bytes")
            form = "packed" if x["packed"] else "raw"
            counts[form + "_logical_bytes"] += x["bytes"]
            counts[form + "_stored_bytes"] += x["stat"]["bytes"]
            counts[form + "_named_allocated"] += x["blocks"]
            counts["logical"] += x["bytes"]
            counts["named_allocated"] += x["blocks"]
            counts["packed_entries" if x["packed"] else "raw_entries"] += 1
        result[owner] = {
            "final": v["final"],
            "donor": v.get("donor"),
            "tables": tables,
            "objects": dict(counts),
            "object_ids": sorted(objects),
        }
        totals.update(counts)
    require(
        (totals["packed_entries"], totals["raw_entries"]) == ((0, 1666) if mode == "E" else (748, 918)),
        "different native eligibility",
    )
    return {
        "owners": result,
        "object_entry_totals": dict(totals),
        "unique_native_inodes": len(all_obj),
        "unique_native_allocated": sum(a[1] for a in all_obj.values()),
    }


def parent_objects(parent, candidate, reg):
    """Report native object changes across distinct compilers. The native output gate is separate."""
    require(
        set(parent) == set(candidate) == set(reg["packed_raw_objects"]), "different native owner set"
    )
    out = {}
    for name in sorted(parent):
        e, c = parent[name]["objects"], candidate[name]["objects"]
        common = set(e) & set(c)
        differ = sorted(
            k for k in common if (e[k]["digest"], e[k]["bytes"]) != (c[k]["digest"], c[k]["bytes"])
        )
        out[name] = {
            "same_native_bodies": len(common) - len(differ),
            "different_native_bodies": differ,
            "parent_only": sorted(set(e) - set(c)),
            "candidate_only": sorted(set(c) - set(e)),
            "representation_changes": sum(e[k]["packed"] != c[k]["packed"] for k in common),
        }
    return out
