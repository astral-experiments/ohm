"""Describe candidate-written pairs using actual per-path geometry and decoded native streams."""

import collections
from pathlib import Path, PurePosixPath
import re
import stat
from protocol import need

FINAL = re.compile(r"s-[0-9a-z]+-_([0-9a-f]{16})_[0-9a-z]+-([0-9a-z]+)")
GRAPH = ("dep-graph.bin", "query-cache.bin")
LIBS = {
    "ruff_python_parser",
    "ruff_python_codegen",
    "ruff_python_semantic",
    "ruff_db",
    "ruff_python_importer",
    "ruff_ranged_value",
    "ty_module_resolver",
    "ruff_linter",
    "ty_site_packages",
    "ruff_python_formatter",
    "ruff_graph",
    "ruff_workspace",
    "ruff_markdown",
    "ruff_server",
    "ruff",
}
EXPECTED = {(n, "lib") for n in LIBS} | {("ruff", "bin")}


def donor_capture(before, work, version, lib):
    """Read both saved headers on the actual newest finalized donor before Cargo can collect it."""
    held = {}
    for owner, slots in before.items():
        ownername = PurePosixPath(owner).name.rsplit("-", 1)[0]
        if ownername not in LIBS:
            continue
        # Some of the 38 unchanged units have only one retained checkout.
        if len(slots) != 2:
            continue
        names = sorted(slots, key=lambda n: int(n.split("-")[1], 36))
        latest = names[-1]
        desc = slots[latest]
        if desc["actual"] != "packed":
            continue
        base = work / owner / latest
        streams = {}
        for name, tag in lib.TABLES:
            path = base / ("ohm-packed-" + name)
            facts = lib.packed_file(path, tag, latest.rsplit("-", 1)[0].encode(), lib.raw_header(version))
            streams[name] = {
                "mask": facts["aliases"],
                "stored": facts["stored_sha256"],
                "raw": facts["sha256"],
                "path": str(path),
            }
        held[owner] = {"two_paths": names, "latest": latest, "previous": desc, "streams": streams}
    return held


def returned(lines):
    """Join strace original and resumed returns by live TID before matching a physical path."""
    pending = {}
    records = []
    for raw in lines:
        line = raw.rstrip()
        resumed = re.match(r"^(\d+)\s+<\.\.\. (openat2?|flock) resumed>(.*)$", line)
        if resumed:
            tid, op, finish = resumed.groups()
            need(tid in pending and pending[tid][0] == op, ("missing syscall entry", line))
            _, start = pending.pop(tid)
            line = start + finish
        else:
            began = re.match(r"^(\d+)\s+(openat2?|flock)\(", line)
            if not began:
                continue
            tid, op = began.groups()
            need(tid not in pending, ("second pending file read", tid))
            if line.endswith("<unfinished ...>"):
                pending[tid] = op, line.removesuffix("<unfinished ...>").rstrip()
                continue
        if "/incremental/" in line and ("flock(" in line or "ohm-packed-" in line):
            records.append(line)
    need(
        not any("/incremental/" in s and ("flock(" in s or "ohm-packed-" in s) for _, s in pending.values()),
        "unclosed selected file or lock operation",
    )
    return records


def positive_read(trace, prior, work, owner):
    """Read only returned descriptors and successful locks in this stage's unscored original strace."""
    wanted = {v["path"] for v in prior["streams"].values()}
    lock = str(work / owner / (prior["latest"].rsplit("-", 1)[0] + ".lock"))
    hits = {p: [] for p in wanted}
    locks = []
    for line in trace:
        if ("openat(" in line or "openat2(" in line) and "O_RDONLY" in line:
            for p in wanted:
                if '"' + p + '"' in line and re.search(r"= [0-9]+<" + re.escape(p) + r">$", line):
                    hits[p].append(line)
        if "flock(" in line and "<" + lock + ">" in line and "LOCK_SH" in line and re.search(r"=\s*0$", line):
            locks.append(line)
    need(
        locks and all(hits.values()), ("missing real selected session lock or physical packed inputs", owner)
    )
    return {"lock": locks, "opened": hits}


def output_kind(newpath, crate, messages, lib):
    found = []
    meta = newpath / "metadata.rmeta"
    for m in messages:
        if m["reason"] != "compiler-artifact" or m["target"]["name"] != crate or m["fresh"]:
            continue
        k = m["target"]["kind"]
        if k == ["lib"]:
            for n in m["filenames"]:
                p = Path(n)
                if p.suffix == ".rmeta" and meta.is_file() and p.samefile(meta):
                    st = meta.stat()
                    found.append(("lib", {"path": str(p), "returned_inode": [st.st_dev, st.st_ino]}))
        elif k == ["bin"] and m["executable"]:
            p = Path(m["executable"])
            stable, sym = lib.binary_disambiguator(p, crate)
            if int(newpath.parent.name.rsplit("-", 1)[1], 36) == stable:
                found.append(("bin", {"path": str(p), "native_main": sym, "stable_id": stable}))
    need(len(found) == 1, ("unbound/ambiguous producing crate artifact", newpath, crate, found))
    return found[0]


def names(ledger):
    result = {}
    for name, row in ledger.items():
        p = PurePosixPath(name)
        m = FINAL.fullmatch(p.name)
        if not (m and not p.name.endswith("-working") and stat.S_ISDIR(row[3]) and "incremental" in p.parts):
            continue
        owner = p.parent.name
        crate = owner.rsplit("-", 1)[0]
        paths = {
            v: ledger.get(str(p / v))
            for g in GRAPH
            for v in (g, "ohm-build-" + g, "ohm-check-" + g, "ohm-packed-" + g)
        }
        packed = all(paths["ohm-packed-" + g] is not None for g in GRAPH)
        raw = all(paths[g] is not None for g in GRAPH)
        need(
            raw != packed and all((paths["ohm-packed-" + g] is not None) == packed for g in GRAPH),
            "partial fresh table pair",
        )
        if packed:
            need(all(not paths[g] for g in GRAPH), "packed base also has a raw shadow")
        k = str(p.parent)
        result.setdefault(k, {})[p.name] = {
            "crate": crate,
            "key": m[1],
            "svh": m[2],
            "actual": "packed" if packed else "raw",
            "directory": row[:2],
            "paths": {k: v for k, v in paths.items() if v is not None},
        }
    return result


def fresh_body(directory, description, version, lib):
    header = lib.raw_header(version)
    prefix = directory.name.rsplit("-", 1)[0].encode()
    info = {}
    leftovers = {}
    for base, tag in lib.TABLES:
        if description["actual"] == "packed":
            packed = directory / ("ohm-packed-" + base)
            facts = lib.packed_file(packed, tag, prefix, header)
            mask = facts["aliases"]
            for i, pre in enumerate(lib.ALIASES):
                alias = directory / (pre + base)
                if alias.exists():
                    need(not mask & (1 << i) and not alias.samefile(packed), "packed alias has a raw shadow")
                    leftovers[pre + base] = lib.raw_file(alias, header)
        else:
            facts = lib.raw_file(directory / base, header)
        info[base] = facts
    objects = [
        p for p in directory.iterdir() if p.name.endswith(".o") or p.name.startswith("ohm-packed-object-")
    ]
    need(
        objects and all(p.is_file() and not p.is_symlink() and p.stat().st_size > 0 for p in objects),
        "missing fresh native work products",
    )
    return {
        "representation": description["actual"],
        "tables": info,
        "independent_stage_tables": leftovers,
        "packed_objects": sum(p.name.startswith("ohm-packed-object-") for p in objects),
        "objects": len(objects),
        "work_products": lib.raw_file(directory / "work-products.bin", header),
    }


def inspect(before, ledger, where, work, version, arm, phase, library, messages, held=None, trace=None):
    after = names(ledger)
    if not before or not arm.endswith("on"):
        return after
    if phase not in ("repair", "verify-repair", "private-UP035-B", "adjacent-repair", "verify-private-B"):
        return after
    changed = {}
    for owner, current in after.items():
        previous = before.get(owner, {})
        for name in current.keys() - previous.keys():
            new = current[name]
            keys = {v["key"] for v in previous.values()}
            prior = [(n, v) for n, v in previous.items() if v["key"] == new["key"]]
            if not prior:
                continue
            need(len(prior) == 1, "ambiguous retained checkout")
            _, old = prior[0]
            # A restored same-checkout build is in scope only when both aliases are build-stage,
            # the preceding finalized session matches, and the source history kept its alternate.
            eligible = old["actual"] == "packed" and old["svh"] == new["svh"] and len(keys) == 2
            path = work / owner / name
            facts = fresh_body(path, new, version, library)
            need(
                facts["representation"] == new["actual"],
                "physical table decoder/read-only ledger disagreement",
            )
            fresh_eligible = all(65536 <= t["bytes"] <= 512 * 1024**2 for t in facts["tables"].values())
            if new["actual"] == "raw":
                fresh_eligible = fresh_eligible and all(
                    new["paths"][g][2] == 2
                    and new["paths"][g][:2] == new["paths"].get("ohm-build-" + g, [])[:2]
                    for g in GRAPH
                )
            crate_kind, identity = output_kind(path, new["crate"], messages, library)
            changed[owner] = {
                "target": crate_kind,
                "native_owner": identity,
                "prior": old,
                "fresh": new,
                "restored_shape": eligible,
                "eligible_physical_shape": eligible and fresh_eligible,
                "body": facts,
            }
    rows = [row for row in changed.values() if row["eligible_physical_shape"]]
    if phase in ("repair", "verify-repair"):
        need(
            {(r["fresh"]["crate"], r["target"]) for r in changed.values()} == EXPECTED and len(changed) == 16,
            "incorrect repair producer name/type identities",
        )
        need(
            set(held) == set(changed),
            "pre-command selected donor ownership differs from all actual repair producers",
        )
        need(
            {(r["fresh"]["crate"], r["target"]) for r in rows} == {(n, "lib") for n in LIBS},
            "15 libraries and the distinct below-minimum binary did not recur",
        )
        for owner, row in changed.items():
            prev = held[owner]
            latest = prev["latest"]
            need(
                prev["two_paths"] == sorted(before[owner], key=lambda n: int(n.split("-")[1], 36))
                and len(prev["two_paths"]) == 2
                and latest == prev["two_paths"][-1]
                and prev["previous"] == row["prior"]
                and prev["previous"]["key"] == row["fresh"]["key"]
                and prev["previous"]["svh"] == row["fresh"]["svh"]
                and len({r["key"] for r in before[owner].values()}) == 2
                and all(v["mask"] == 3 for v in prev["streams"].values()),
                ("different most-recent retained checkout or alias masks", owner),
            )
            row["donor"] = prev
            if trace is not None:
                row["observed_reads"] = positive_read(trace, prev, work, owner)
            desired = "packed" if arm == "Ron" and row["target"] == "lib" else "raw"
            need(row["fresh"]["actual"] == desired, "wrong per-owner writer decision")
            if row["target"] == "bin":
                need(
                    0 < row["body"]["tables"]["query-cache.bin"]["bytes"] < 65536,
                    "the registered bin was not below codec minimum",
                )
            if desired == "packed":
                need(
                    all(s["aliases"] == 3 for s in row["body"]["tables"].values()),
                    "not build-only native table aliases",
                )
    need(
        all(not v["body"]["packed_objects"] for v in changed.values()),
        "restored build attempted to pack native objects",
    )
    import gzip, json

    (where / "newly-finalized.json.gz").write_bytes(
        gzip.compress(json.dumps(changed, sort_keys=True).encode(), mtime=0)
    )
    return after
