"""Count actual Wild reads by name, opened generation and complete typed input digest."""

from collections import defaultdict
import gzip, hashlib, json, re, sys
from pathlib import Path
from zipfile import ZipFile

SHA = "82148079f32d04d8d230d7a6c264c0a42407c038b61dc62e14b0d08095292eee"


def tag(path):
    if re.search(r"/rustc[A-Za-z0-9]{6}/symbols\.o$", path):
        return "generated symbols"
    if path.startswith(("/usr", "/lib")):
        return "system native"
    if ".rlink-objects/" in path:
        return "target's individual codegen objects"
    if path.endswith(".rlib"):
        return "Rust library archives"
    if path.endswith(".a"):
        return "other archives"
    return "other selected inputs"


def count(seen, previous_unleaseable):
    by_name = defaultdict(set)
    by_inode = defaultdict(set)
    by_full = defaultdict(list)
    family = defaultdict(list)
    for role, dev, ino, size, digest, path in seen:
        by_name[path].add((dev, ino, size, digest))
        by_inode[(dev, ino)].add((path, size, digest))
        by_full[(path, dev, ino, size, digest)].append(role)
        family[tag(path)].append((path, dev, ino, size, digest))
    prior = [r for r in seen if r[-1] in previous_unleaseable]
    same_size = defaultdict(set)
    for role, dev, ino, size, digest, path in seen:
        same_size[(dev, ino, size)].add((role, path, digest))
    collisions = [
        {"dev": a, "ino": b, "size": n, "actual": [list(row) for row in sorted(rows)]}
        for (a, b, n), rows in sorted(same_size.items())
        if len({digest for role, path, digest in rows}) > 1
    ]
    return {
        "occurrences": len(seen),
        "bytes_actually_frozen": sum(r[3] for r in seen),
        "different_paths": len(by_name),
        "distinct_name_generation_and_digest": len(by_full),
        "one_read_per_historically_equal_complete_name_and_generation": sum(
            k[3] for k in by_full
        ),
        "repeated_path_with_different_observed_generation": sorted(
            k for k, v in by_name.items() if len(v) > 1
        ),
        "repeated_inode_with_multiple_names_or_payloads": sum(
            len(v) > 1 for v in by_inode.values()
        ),
        "same_inode_and_size_with_different_whole_bytes": collisions,
        "mode_by_bytes": {
            t: {
                "occurrences": len(rows),
                "distinct": len(set(rows)),
                "all_bytes": sum(x[3] for x in rows),
                "historically_unique_bytes": sum(x[3] for x in set(rows)),
            }
            for t, rows in sorted(family.items())
        },
        "known_explicit_paths_rejected_for_leasing_on_previous_host": {
            "reselected": sorted({r[-1] for r in prior}),
            "bytes_here": sum(r[3] for r in prior),
            "unique_named_generation_bytes": sum(
                x[2] for x in {tuple(r[1:]) for r in prior}
            ),
        },
        "top_repeated_native_inputs": [
            {"name": k[0], "bytes": k[3], "roles": len(v), "complete_b3": k[4]}
            for k, v in sorted(
                by_full.items(),
                key=lambda kv: (len(kv[1]) - 1) * kv[0][3],
                reverse=True,
            )[:8]
        ],
    }


def run(archive, accepted, prior):
    with archive.open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == SHA
    assert len(accepted) == 48 and len(prior) == 6
    out = {}
    with ZipFile(archive) as z:
        for phase in ("edit", "first-unchanged", "second-unchanged", "third-unchanged"):
            registered = json.loads(gzip.decompress(z.read(phase + "-native.json.gz")))
            seen = []
            for role, rec in registered.items():
                raw = gzip.decompress(z.read(phase + "/" + rec["log"]))
                assert hashlib.sha256(raw).hexdigest() == rec["raw_sha256"]
                opened = {}
                used = {}
                for row in raw.decode().splitlines():
                    if row.startswith("FROZEN\t"):
                        _, dev, ino, size, digest, path = row.split("\t")
                        assert path not in opened and re.fullmatch(
                            r"[a-f0-9]{64}", digest
                        )
                        opened[path] = (int(dev), int(ino), int(size), digest)
                    elif row.startswith("USED\t"):
                        _, idx, num, digest, mods, path = row.split("\t")
                        assert path not in used and int(idx) == len(used)
                        used[path] = (int(num), digest)
                assert set(used) == set(opened) and all(
                    opened[k][2:] == v for k, v in used.items()
                )
                assert sum(v[2] for v in opened.values()) == rec["bytes"]
                seen.extend((role, *v, k) for k, v in opened.items())
            assert len(registered) == 50
            out[phase] = {
                "fifty": count(seen, prior),
                "first_registered_48": count(
                    [r for r in seen if r[0] in accepted], prior
                ),
            }
    return out


if __name__ == "__main__":
    _, arc, scope, older = sys.argv
    a = set(
        json.loads(Path(scope).read_bytes())["decisions"]["first-unchanged"][
            "strict_equal_roles"
        ]
    )
    previous = json.loads(Path(older).read_bytes())
    assert (
        previous["sha256"]
        == "9c5a3ac75da6e79b13042be19228a37418f46fc356cc40e5f77cddd2147ecf57"
    )
    p = {r["path"] for r in previous["unleased"]}
    print(json.dumps(run(Path(arc), a, p), sort_keys=True, indent=2))
