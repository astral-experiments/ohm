"""Join older lease attempts to current native inputs by full normalized name and size only."""

from pathlib import Path
from zipfile import ZipFile
from collections import Counter, defaultdict
import hashlib, json, gzip, posixpath, re, sys

OLD = "9dc7adaa541bb2d2e9cc4c9287a6c56fa9b850fffad3218bf13c321572b52f9d"
NEW = "941425ee53b9993f2337cf7d6a8f031ac2420e86e708751a0d3208b2af852713"


def run(old, new):
    for path, digest in [(old, OLD), (new, NEW)]:
        with path.open("rb") as f:
            assert hashlib.file_digest(f, "sha256").hexdigest() == digest
    with ZipFile(old) as z:
        paths = z.read("phase-price/unique-held/paths.nul").decode().split("\0")
        assert paths.pop() == ""
        rows = [
            s.split()
            for s in z.read("phase-price/unique-held/observed.txt")
            .decode()
            .splitlines()
        ]
        assert len(paths) == len(rows) == 3465
        lookup = {}
        expected = {}
        for i, (parts, pth) in enumerate(zip(rows, paths, strict=True)):
            idx, n, e, dev, ino, sha = parts
            assert i == int(idx) and len(sha) == 64
            key = posixpath.normpath(pth)
            if key in lookup:
                assert lookup[key] == (int(n), int(e))
            lookup[key] = (int(n), int(e))
            if int(e):
                expected[key] = (int(n), int(e))
        assert len(expected) == 19 and sum(n for n, e in expected.values()) == 7627189
        audits = sorted(
            n
            for n in z.namelist()
            if re.fullmatch(r"phase-price/role-\d+-audit/stderr", n)
        )
        assert len(audits) == 50
        authenticated = defaultdict(set)
        old_observations = 0
        for name in audits:
            for line in z.read(name).decode().splitlines():
                if not line.startswith("QA_INPUT\t"):
                    continue
                _, n, h, original = line.split("\t")
                old_observations += 1
                k = posixpath.normpath(original)
                n = int(n)
                if k in lookup:
                    assert lookup[k][0] == n and len(h) == 64
                    authenticated[(Path(k).name, n, h)].add(lookup[k][1])
        assert old_observations == 12708
    with ZipFile(new) as z:
        tag = "C-exec-warm-stable"
        a = json.loads(z.read(tag + "/physical-decisions.json"))["actors"]
        counts = Counter()
        allids = defaultdict(set)
        changed = defaultdict(list)
        unique = {}
        files = defaultdict(Counter)
        contents = defaultdict(Counter)
        content_unique = {}
        for k, v in a.items():
            with z.open(tag + "/actor-" + v["pid"] + ".tsv.gz") as fp, gzip.GzipFile(
                fileobj=fp
            ) as g:
                for raw in g:
                    if not raw.startswith(b"FROZEN\t"):
                        continue
                    _, ds, ins, ns, bs, sp = raw.rstrip(b"\n").split(b"\t")
                    dev, ino, n = int(ds), int(ins), int(ns)
                    b = bs.decode()
                    path = posixpath.normpath(sp.decode())
                    assert len(b) == 64
                    allids[(dev, ino)].add((n, b, path))
                    if Path(path).name == "symbols.o":
                        cls = "this_link_private"
                        gen = ("private", k)
                    elif lookup.get(path, (None, None))[0] == n:
                        cls = "prior_no_lease" if lookup[path][1] else "prior_lease"
                        gen = (dev, ino, n, b)
                    else:
                        cls = "prior_identity_unmatched"
                        gen = (dev, ino, n, b)
                    if gen in unique:
                        assert unique[gen] == (n, cls), (path, unique[gen], (n, cls))
                    unique[gen] = (n, cls)
                    counts[(cls, "occurrence_bytes")] += n
                    counts[(cls, "occurrences")] += 1
                    prior_status = authenticated.get((Path(path).name, n, b))
                    status = (
                        "private"
                        if Path(path).name == "symbols.o"
                        else (
                            "prior_lease"
                            if prior_status == {0}
                            else (
                                "prior_no_lease"
                                if prior_status and 0 not in prior_status
                                else (
                                    "changed_or_unmatched"
                                    if not prior_status
                                    else "mixed"
                                )
                            )
                        )
                    )
                    contents[status]["occurrence_bytes"] += n
                    contents[status]["occurrences"] += 1
                    if gen in content_unique:
                        assert content_unique[gen] == (n, status)
                    content_unique[gen] = (n, status)
                    if cls == "prior_no_lease":
                        files[path]["occurrences"] += 1
                        files[path]["bytes"] += n
        for gen, (n, cls) in unique.items():
            counts[(cls, "distinct_bytes")] += n
            counts[(cls, "distinct_generations")] += 1
        c = {
            cls: {k: v for (name, k), v in counts.items() if name == cls}
            for cls, xx in counts
        }
        for cls, r in c.items():
            r["repeated_bytes"] = r["occurrence_bytes"] - r["distinct_bytes"]
        for n, status in content_unique.values():
            contents[status]["distinct_bytes"] += n
            contents[status]["distinct_generations"] += 1
        for rec in contents.values():
            rec["repeated_bytes"] = rec["occurrence_bytes"] - rec["distinct_bytes"]
        diff = [
            {
                "device_inode": list(di),
                "observations": [
                    {"bytes": n, "hash": b, "path": p} for n, b, p in sorted(items)
                ],
            }
            for di, items in allids.items()
            if len({(n, b) for n, b, p in items}) > 1
        ]
        return {
            "old_signer_archive": OLD,
            "current_native_archive": NEW,
            "classification": c,
            "independent_same_basename_and_full_contents": dict(contents),
            "current_system_paths_prior_lease_refused": dict(files),
            "same_inode_multiple_actual_payloads": diff,
            "limits": "Earlier leases were attempted on another boot in an isolated scan. The same normalized path and size give no current-generation identity or guarantee. Current boxes physically carried complete actual bytes. Temporary symbols are charged per link.",
        }


if __name__ == "__main__":
    print(json.dumps(run(*map(Path, sys.argv[1:])), sort_keys=True, indent=2))
