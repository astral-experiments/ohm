"""Measure physically shareable standalone objects in the alternate Ruff checkout, read-only."""
import argparse
from collections import defaultdict
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess


SESSION = re.compile(r"s-[a-z0-9]+-_([a-f0-9]{16})_[a-z0-9]+-[a-z0-9]+")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def session(name):
    parts = PurePosixPath(name).parts
    if "incremental" in parts:
        for i in range(parts.index("incremental") + 1, len(parts)):
            match = SESSION.fullmatch(parts[i])
            if match:
                return "/".join(parts[:i]), match.group(1)
    return None


def labels(ledger):
    result = defaultdict(set)
    for name, row in ledger.items():
        if stat.S_ISDIR(row[3]) and SESSION.fullmatch(PurePosixPath(name).name):
            label = session(name)
            if label:
                result[label[0]].add(label[1])
    return result


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def compare(target, build, cold, live):
    roots = {"target": target, "build": build}
    require(all(r.resolve() == r and r.is_dir() for r in roots.values()) and target != build
            and not (target.is_relative_to(build) or build.is_relative_to(target)), "owned disjoint roots")
    before, now = labels(cold), labels(live)
    older = {unit: next(iter(keys)) for unit, keys in before.items()
             if len(keys) == 1 and len(now.get(unit, ())) == 2 and keys < now[unit]}
    require(older, "no current-and-alternate Rust sessions in this actual branch history")
    by_key = {}
    all_names = defaultdict(list)
    names = defaultdict(list)
    for name, row in live.items():
        path = PurePosixPath(name)
        require(path.parts[0] in roots and ".." not in path.parts and path.as_posix() == name, name)
        key = tuple(row[:2])
        require(by_key.setdefault(key, row) == row, "inconsistent physical alias")
        all_names[key].append(name)
        if stat.S_ISREG(row[3]) and (path.suffix == ".o" or path.name.startswith("ohm-packed-object-")):
            names[key].append(name)

    @contextmanager
    def open_key(key):
        rel = PurePosixPath(min(names[key]))
        path = roots[rel.parts[0]].joinpath(*rel.parts[1:])
        require(path.resolve() == path, ("aliased object path", str(path)))
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOATIME)
        with os.fdopen(fd, "rb") as f:
            st = os.fstat(f.fileno())
            require([st.st_dev, st.st_ino, st.st_nlink, st.st_mode, st.st_blocks, st.st_size] ==
                    by_key[key], ("object changed since census", str(rel)))
            yield f
            after = os.fstat(f.fileno())
            require((st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_blocks) ==
                    (after.st_mtime_ns, after.st_ctime_ns, after.st_size, after.st_blocks),
                    "object changed while reading")

    classes = {}
    old = set()
    groups = defaultdict(list)
    excluded = []
    for key, aliases in names.items():
        streams = {"packed" if PurePosixPath(n).name.startswith("ohm-packed-object-")
                   else "loose-elf" for n in aliases}
        require(len(streams) == 1, "ambiguous packed object alias")
        kind = next(iter(streams))
        if kind == "loose-elf":
            with open_key(key) as handle:
                h = handle.read(20)
            if len(h) < 20 or h[:6] != b"\x7fELF\x02\x01" or h[16:20] != b"\x01\x00\x3e\x00":
                excluded.append(min(aliases))
                continue
        classes[key] = kind
        links = all_names[key]
        eligible = all((s := session(n)) and s[0] in older and older[s[0]] == s[1] for n in links)
        if eligible and len(links) == by_key[key][2]:
            old.add(key)
        groups[(key[0], kind, by_key[key][5])].append(key)

    # Retain at least one physical object if a candidate bucket consists only of older files.
    def removable(bucket):
        choices = set(bucket) & old
        if choices and len(choices) == len(bucket):
            choices.remove(min(choices, key=lambda k: (by_key[k][4], k)))
        return choices

    def sum_blocks(bucket):
        return 512 * sum(by_key[k][4] for k in bucket)

    size_cap = set()
    equality = set()
    reads = {}
    comparisons = []
    for bucket in groups.values():
        possible = removable(bucket)
        if not possible:
            continue
        size_cap.update(possible)
        hashes = defaultdict(list)
        for key in sorted(bucket):
            with open_key(key) as f:
                h = hashlib.file_digest(f, "sha256").hexdigest()
            hashes[h].append(key)
            reads[min(names[key])] = h
        for h, matches in hashes.items():
            real = removable(matches)
            if not real:
                continue
            keep = min(set(matches) - real)
            with open_key(keep) as witness:
                for key in sorted(real):
                    with open_key(key) as test:
                        one, two = witness.fileno(), test.fileno()
                        rc = subprocess.run(["cmp", "--silent", "--", f"/proc/self/fd/{one}",
                                             f"/proc/self/fd/{two}"], pass_fds=(one, two)).returncode
                        require(rc == 0, "equal SHA-256 failed complete direct byte comparison")
                    comparisons.append({"older": min(names[key]), "surviving": min(names[keep]),
                                        "kind": classes[key], "sha256": h,
                                        "allocated_bytes": 512 * by_key[key][4]})
            equality.update(real)
    require(sum_blocks(equality) <= sum_blocks(size_cap) <= sum_blocks(old), "impossible storage")
    summary = {}
    for kind in ("loose-elf", "packed"):
        keys = {k for k, c in classes.items() if c == kind}
        summary[kind] = {"unique_object_inodes": len(keys), "older_only_inodes": len(keys & old),
                         "older_only_bytes": sum_blocks(keys & old),
                         "length_only_ceiling_bytes": sum_blocks(keys & size_cap),
                         "byte_equal_older_inodes": len(keys & equality),
                         "byte_equal_older_bytes": sum_blocks(keys & equality)}
    return {"scope": "same-filesystem byte-identical loose ELF/packed objects at visit end",
            "two_checkout_units": older, "summary": summary, "non_elf_objects_excluded": excluded,
            "candidate_sha256": reads, "complete_cmp": comparisons}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("target", "build", "cold-ledger", "ledger", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    def load(path):
        with gzip.open(path, "rt") as f:
            return json.load(f)
    require(a.out.resolve() == a.out and not a.out.is_relative_to(a.build) and
            not a.out.is_relative_to(a.target), "receipt outside the measured roots")
    r = compare(a.target, a.build, load(a.cold_ledger), load(a.ledger))
    r["source_ledgers"] = {"cold": digest(a.cold_ledger), "visit": digest(a.ledger)}
    with a.out.open("xb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as out:
        out.write((json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n").encode())
    print(json.dumps(r["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
