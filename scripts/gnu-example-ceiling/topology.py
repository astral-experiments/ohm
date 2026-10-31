"""Reconstruct Linux fork/exec/exit relationships and inclusive PMU readings from original ledgers."""

from pathlib import Path
import json
import os
import struct

ROLES = ("rustc", "cc", "collect2", "wild")


def location(path):
    p = Path(path).resolve(strict=True)
    s = p.stat()
    return [s.st_dev, s.st_ino, str(p)]


def lines(d, f):
    return [line.split("\t") for line in (d / f).read_text().splitlines()]


def option(argv, needle):
    hits = [argv[i + 1] for i, v in enumerate(argv[:-1]) if v == needle]
    assert len(hits) == 1, (needle, hits)
    return hits[0]


def ancestry(pid, root, edges):
    chain = []
    while pid != root:
        assert pid not in chain and pid in edges, (pid, root, "broken ancestry")
        chain.append(pid)
        pid = edges[pid][0]
    return chain + [root]


def read(d, selectors, mode, *, synthetic=False, names=(), registry_target=None):
    (abi,) = lines(d, "abi.tsv")
    size, kind, config, read_format, inherit, disabled, kernel, hv, cloexec = map(int, abi)
    assert 96 <= size <= 256 and (
        kind,
        config,
        read_format,
        inherit,
        disabled,
        kernel,
        hv,
        cloexec,
    ) == (0, 1, 3, 1, 1, 1, 1, 8)
    for label, on in [("whole", True), ("subtree", False)]:
        raw = (d / (label + "-attr.bin")).read_bytes()
        assert len(raw) == size
        typ, attrsize, cfg, period, sample_type, fmt, flags = struct.unpack_from("<IIQQQQQ", raw)
        assert (typ, attrsize, cfg, period, sample_type, fmt, flags) == (
            0,
            size,
            1,
            0,
            0,
            3,
            1 | 2 | 32 | 64 | (4096 if on else 0),
        ) and not any(raw[48:])
    edges = {}
    tasks = {}
    exits = {}
    serials = {}
    root = None
    for line in lines(d, "tasks.tsv"):
        k = line[0]
        a = list(map(int, line[1:]))
        pid = a[0]
        if k == "root":
            assert len(a) == 1 and root is None
            root = pid
        elif k == "task":
            assert len(a) == 3 and pid not in tasks
            tasks[pid] = a[1:]
        elif k == "spawn":
            child, ev = a[1:]
            assert child not in edges and ev in (1, 2, 3)
            edges[child] = [pid, ev]
        elif k == "exec":
            assert a[1] not in serials
            serials[a[1]] = pid
        elif k == "exit":
            assert pid not in exits and len(a) == 3
            exits[pid] = a[1:]
        else:
            raise ValueError(line)
    assert root and exits[root] == [0, 0]
    events = []
    selected = {}
    seen_ids = set()
    for line in lines(d, "exec.tsv"):
        idx, pid, kind, enrolled, dev, ino = map(int, line[:6])
        path = line[6]
        assert serials[idx] == pid and idx == len(events) + 1
        match = [i for i, name in enumerate(ROLES, 1) if [dev, ino] == selectors[name][:2]]
        assert len(match) <= 1 and kind == (match[0] if match else 0)
        b = (d / f"args-{idx:04d}").read_bytes()
        assert b and b.endswith(b"\0") and len(b) > 1
        argv = b[:-1].decode().split("\0")
        should = (kind == 1 and "--crate-name" in argv and "--out-dir" in argv) or (
            kind in (2, 4) and "-o" in argv
        )
        assert bool(enrolled) == should
        if kind:
            assert path == selectors[ROLES[kind - 1]][2], (kind, path)
        e = {"serial": idx, "pid": pid, "kind": kind, "path": path, "argv": argv}
        events.append(e)
        if enrolled:
            selected[idx] = e
    assert {f.name for f in d.glob("args-*")} == {f"args-{i:04d}" for i in serials}
    samples = {}
    for row in lines(d, "samples.tsv"):
        idx, pid, kind, error, size, ins, en, run = map(int, row)
        assert idx not in samples and (
            idx == 0
            and (pid, kind) == (root, 0)
            or idx in selected
            and (pid, kind) == (selected[idx]["pid"], selected[idx]["kind"])
        )
        if mode == "topology":
            assert (error, size, ins, en, run) == (0, -1, 0, 0, 0)
        else:
            assert error == 0 and size == 24 and ins > 0 and en == run > 0, (
                d.name,
                idx,
                pid,
                kind,
                error,
                size,
                ins,
                en,
                run,
            )
        samples[idx] = ins
    assert set(samples) == set(selected) | {0} and len(serials) == len(events)
    if mode == "plain":
        assert (
            not edges
            and not tasks
            and not events
            and len(samples) == 1
            and all(v == [0, 0] for v in exits.values())
        )
        return {"whole": samples[0], "root": root, "examples": {}, "tasks": len(exits)}
    assert set(exits) == set(tasks) == set(edges) | {root}, (
        set(exits) ^ set(tasks),
        set(edges) ^ set(tasks),
    )
    chains = {p: ancestry(p, root, edges) for p in tasks}
    for pid, (tgid, _) in tasks.items():
        assert tgid in tasks and (tgid == pid or tgid in chains[pid]), (pid, tgid)
    if synthetic:
        sigs = [pid for pid, v in exits.items() if v != [0, 0]]
        assert len(sigs) == 1 and exits[sigs[0]] == [143, 15] and edges[sigs[0]][0] == root
        assert any(
            edges.get(p) == [root, 1] and p not in serials.values() and exits[p] == [0, 0]
            for p in tasks
        )
    else:
        assert all(v == [0, 0] for v in exits.values()), {
            p: v for p, v in exits.items() if v != [0, 0]
        }
    compilers = [e for e in selected.values() if e["kind"] == 1]
    roots = {e["pid"] for e in compilers}
    assert len(roots) == len(compilers)
    clis = {}
    identities = {}
    libs = []
    visited = set()
    for e in compilers:
        a = e["argv"]
        pid = e["pid"]
        name = option(a, "--crate-name")
        src = [v for v in a if v.endswith(".rs")]
        assert (
            not (set(chains[pid][1:]) & roots)
            and "--target" not in a
            and not any("link-only" in v for v in a)
        )
        kind = option(a, "--crate-type")
        out = Path(option(a, "--out-dir"))
        inc = [v.removeprefix("incremental=") for v in a if v.startswith("incremental=")]
        assert len(inc) == 1 and out.is_absolute()
        if not synthetic:
            assert (
                (
                    out.is_relative_to(Path(registry_target) / "debug/build")
                    or out.is_relative_to(Path(registry_target).parent / "shared")
                )
                and out.name == "out"
                and out.parent.parent.name == "ruff_annotate_snippets"
                and Path(inc[0]).is_relative_to(Path(registry_target) / "debug/incremental")
            ), (out, inc)
        subset = [x for x in events if pid in chains[x["pid"]] and x["serial"] > e["serial"]]
        assert not any(x["pid"] == pid for x in subset), "selected rustc re-executed"
        visited.add(e["serial"])
        if name == "annotate_snippets":
            assert (
                not synthetic
                and kind == "lib"
                and src == ["crates/ruff_annotate_snippets/src/lib.rs"]
                and "--emit=dep-info,metadata,link" in a
                and not subset
            )
            libs.append(samples[e["serial"]])
            continue
        assert (
            kind == "bin"
            and src == [f"crates/ruff_annotate_snippets/examples/{name}.rs"]
            and "--emit=dep-info,link" in a
            and name not in clis
        )
        assert sorted(x["kind"] for x in subset) == [2, 3, 4], (
            name,
            [(x["kind"], x["path"]) for x in subset],
        )
        by = {x["kind"]: x for x in subset}
        cc, col, w = (by[i] for i in (2, 3, 4))
        assert cc["pid"] in chains[col["pid"]][1:] and col["pid"] in chains[w["pid"]][1:]
        target = str(out / name)
        assert all(option(x["argv"], "-o") == target for x in subset)
        # A forked Wild group may start worker threads. Its main task must be
        # observed independently, without a subsequent exec in its group.
        below = [p for p, c in chains.items() if w["pid"] in c[1:]]
        workers = [p for p in below if tasks[p][0] == p and not any(x["pid"] == p for x in events)]
        assert len(workers) == 1 and all(x["pid"] not in below for x in events), (
            name,
            below,
            workers,
        )
        if synthetic:
            assert len([p for p in below if tasks[p][0] == workers[0] and p != workers[0]]) == 2
        if not synthetic:
            externs = [
                a[i + 1].split("=", 1)[1]
                for i, v in enumerate(a[:-1])
                if v == "--extern" and a[i + 1].startswith("snapbox=")
            ]
            assert (
                sorted(Path(x).suffix for x in externs) == [".rlib", ".rmeta"]
                and "-lutil" in w["argv"]
                and "-lgcc_s" in w["argv"]
            )
        visited.update((cc["serial"], w["serial"]))
        clis[name] = {
            "rustc_tree": samples[e["serial"]],
            "cc_tree": samples[cc["serial"]],
            "wild_tree": samples[w["serial"]],
        }
        identities[name] = {
            "pids": [pid, cc["pid"], col["pid"], w["pid"], workers[0]],
            "out": target,
            "incremental": inc[0],
        }
    assert visited == set(selected) and set(clis) == set(names) and len(libs) <= 1
    return {
        "whole": samples[0],
        "root": root,
        "examples": clis,
        "identities": identities,
        "library": libs,
        "tasks": len(tasks),
        "execs": len(events),
    }
