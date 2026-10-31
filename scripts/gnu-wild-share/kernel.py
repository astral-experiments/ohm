"""Positive exec, family and inherited instruction-counter evidence for two distinct GNU links."""

import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

COMMAND = [
    "cargo",
    "+ohm",
    "test",
    "-p",
    "ruff",
    "--test",
    "integration_test",
    "--no-run",
    "--locked",
    "--offline",
    "-j4",
    "--message-format=json",
]
SELECTORS = ("rustc", "cc", "collect2", "wild")
ORIGINAL = "c258cd838bae37b9df99a2ee82b932c98b1acf92fe9c3619e02647851ce9940a"
PREDICATE = '(type==1 && arg(b,bytes,"--crate-name") && arg(b,bytes,"--out-dir")) || ((type==2 || type==4) && arg(b,bytes,"-o"))'


def require(test, msg):
    if not test:
        raise ValueError(str(msg))


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dump(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def load(path):
    return json.loads(Path(path).read_bytes())


def identity(path):
    p = Path(path).resolve(strict=True)
    s = p.stat()
    return {"path": str(p), "dev": s.st_dev, "ino": s.st_ino, "sha256": digest(p)}


def build(original, store):
    text = original.read_text()
    require(
        digest(original) == ORIGINAL and text.count(PREDICATE) == 1,
        "unregistered observer",
    )
    source = store / "stock-wild-only.c"
    source.write_text(text.replace(PREDICATE, 'type==4 && arg(b,bytes,"-o")'))
    subprocess.run(
        ["cc", "-Wall", "-Wextra", "-Werror", "-O2", source, "-o", store / "observe"],
        check=True,
    )


def lines(folder, file):
    return [r.split("\t") for r in (folder / file).read_text().splitlines()]


def arguments(args, option):
    values = [args[i + 1] for i, x in enumerate(args[:-1]) if x == option]
    require(len(values) == 1, ("missing/duplicate", option, values))
    return values[0]


def snapshot(folder, mode, ids):
    (abi,) = lines(folder, "abi.tsv")
    size, *desc = map(int, abi)
    require(96 <= size <= 256 and desc == [0, 1, 3, 1, 1, 1, 1, 8], "PMU specification")
    for name, onexec in (("whole", 4096), ("subtree", 0)):
        a = (folder / (name + "-attr.bin")).read_bytes()
        require(
            len(a) == size
            and struct.unpack_from("<IIQQQQQ", a) == (0, size, 1, 0, 0, 3, 99 + onexec)
            and not any(a[48:]),
            ("noncanonical kernel attr", name),
        )
    edges, nodes, exits, sequence = {}, {}, {}, {}
    root = None
    for kind, *v in lines(folder, "tasks.tsv"):
        a = tuple(map(int, v))
        p = a[0]
        if kind == "root" and len(a) == 1 and root is None:
            root = p
        elif (
            kind == "spawn" and len(a) == 3 and a[2] in (1, 2, 3) and a[1] not in edges
        ):
            edges[a[1]] = p
        elif kind == "task" and len(a) == 3 and p not in nodes:
            nodes[p] = a[1:]
        elif kind == "exec" and len(a) == 2 and a[1] not in sequence:
            sequence[a[1]] = p
        elif kind == "exit" and len(a) == 3 and p not in exits:
            exits[p] = a[1:]
        else:
            raise ValueError(("ambiguous lifetime", kind, a))
    require(root and exits[root] == (0, 0), "failed root")
    require(
        len({(v["dev"], v["ino"]) for v in ids.values()}) == len(ids),
        "aliased native catalog",
    )
    rows, wanted = [], {}
    for line in lines(folder, "exec.tsv"):
        idx, p, typ, chosen, dev, ino = map(int, line[:6])
        require(
            len(line) == 7 and sequence.get(idx) == p and idx == len(rows) + 1,
            "exec disagreement",
        )
        names = [n for n, x in ids.items() if (dev, ino) == (x["dev"], x["ino"])]
        name = names[0] if names else None
        require(
            typ == (SELECTORS.index(name) + 1 if name in SELECTORS else 0),
            "native selector identity",
        )
        require(
            not name or line[6] == ids[name]["path"],
            "unexpected physical executable path",
        )
        b = (folder / f"args-{idx:04d}").read_bytes()
        require(len(b) > 1 and b.endswith(b"\0"), "incomplete argv")
        argv = [os.fsdecode(v) for v in b[:-1].split(b"\0")]
        require(
            chosen == int(name == "wild" and "-o" in argv), "unbound output counter"
        )
        rows.append(
            {"seq": idx, "pid": p, "name": name, "argv": argv, "image": line[6]}
        )
        if chosen:
            wanted[idx] = p
    require(
        set(sequence) == set(range(1, len(rows) + 1))
        and {f.name for f in folder.glob("args-*")}
        == {f"args-{k:04d}" for k in sequence},
        "missing original argv",
    )
    samples = {}
    for line in lines(folder, "samples.tsv"):
        i, p, typ, err, n, ins, en, run = map(int, line)
        require(
            i not in samples
            and (
                (i == 0 and p == root and typ == 0) or (wanted.get(i) == p and typ == 4)
            ),
            "unbound PMU row",
        )
        if mode == "topology":
            require(
                (err, n, ins, en, run) == (0, -1, 0, 0, 0), "topology produced counts"
            )
        else:
            require(
                err == 0 and n == 24 and ins > 0 and en == run > 0,
                ("PMU refused, multiplexed or incomplete", line),
            )
        samples[i] = ins
    require(set(samples) == {0, *wanted}, "missing PMU FD")
    if mode == "plain":
        require(
            not (rows or edges or nodes) and all(x == (0, 0) for x in exits.values()),
            "traced sham",
        )
        return {"whole": samples[0]}
    require(set(exits) == set(nodes) == {root, *edges}, "incomplete kernel family")
    ancestry = {}
    for p in nodes:
        chain = [p]
        while chain[-1] != root:
            q = edges[chain[-1]]
            require(q not in chain and q in nodes, "invalid kernel ancestry")
            chain.append(q)
        require(nodes[p][0] in chain, "thread detached from origin")
        ancestry[p] = chain
    return {
        "root": root,
        "nodes": nodes,
        "exits": exits,
        "rows": rows,
        "chains": ancestry,
        "samples": samples,
        "whole": samples[0],
    }


def classify(k, expected, variant):
    """Bind each Wild FD at physical exec to a different output and the full gcc/collect2 family."""
    if "rows" not in k:
        return {"whole": k["whole"]}
    rows, chains, root = k["rows"], k["chains"], k["root"]
    if variant == "ruff":
        roles = [r["name"] for r in rows]
        for n in (*SELECTORS, "cargo", "proxy"):
            require(
                roles.count(n) == (2 if n in SELECTORS else 1),
                ("ordinary native roster", n, roles),
            )
        require(
            len(roles) == 10 and roles[0] == "proxy" and roles[1] == "cargo",
            "foreign or missing exec",
        )
        require(
            rows[0]["argv"][1:] == COMMAND[1:]
            and rows[1]["argv"][1:] == COMMAND[2:]
            and rows[0]["pid"] == root
            and root in chains[rows[1]["pid"]],
            "wrong Cargo entry",
        )
    failures = [p for p, x in k["exits"].items() if x != (0, 0)]
    if variant == "cal":
        require(
            len(failures) == 1 and k["exits"][failures[0]] == (143, 15),
            "calibration signal",
        )
    else:
        require(not failures, ("failed task", failures))
    wild = [r for r in rows if r["name"] == "wild"]
    require(
        len(wild) == 2
        and len({r["pid"] for r in wild}) == 2
        and len(expected) == 2
        and len(set(expected.values())) == 2,
        "two unique outputs",
    )
    by_output = {v: k for k, v in expected.items()}
    result, used_native, branches = {}, set(), []
    for w in wild:
        p = w["pid"]
        o = arguments(w["argv"], "-o")
        require(
            o in by_output and by_output[o] not in result and Path(o).is_absolute(),
            "wrong Wild output",
        )
        tag = by_output[o]
        parents = [
            r
            for r in rows
            if r["seq"] < w["seq"]
            and r["pid"] in chains[p][1:]
            and r["name"] in ("rustc", "cc", "collect2")
        ]
        kinds = (
            ["cc", "collect2"] if variant == "native" else ["rustc", "cc", "collect2"]
        )
        require(
            [r["name"] for r in parents] == kinds,
            ("incorrect native lineage", [r["name"] for r in parents]),
        )
        for r in parents[-2:]:
            require(arguments(r["argv"], "-o") == o, "output differs between GNU tools")
        if variant == "ruff":
            a = parents[0]["argv"]
            cargo = rows[1]
            require(
                cargo["seq"] < parents[0]["seq"]
                and cargo["pid"] in chains[parents[0]["pid"]][1:],
                "compiler did not descend from the active Cargo frontend",
            )
            saved = [v for v in a if v.endswith(".rlink")]
            require(
                arguments(a, "--crate-name") == tag
                and len(saved) == 1
                and str(Path(saved[0]).with_suffix("")) == o
                and (
                    a.count("-Zlink-only")
                    + sum(pair == ("-Z", "link-only") for pair in zip(a, a[1:]))
                )
                == 1
                and (("--test" in a) == (tag == "integration_test")),
                "wrong saved-link compiler",
            )
            require(
                "-lgcc_s" in w["argv"]
                and all(
                    any(
                        Path(x).name.startswith("lib" + n + "-") and x.endswith(".rlib")
                        for x in w["argv"]
                    )
                    for n in ("zmij", "serde_json")
                ),
                "wrong native inputs",
            )
        ids = {r["seq"] for r in [*parents, w]}
        require(not used_native.intersection(ids), "nested or aliased sibling unit")
        used_native.update(ids)
        children = {q for q, c in chains.items() if p in c}
        require(sum(r["pid"] in children for r in rows) == 1, "exec below/after Wild")
        require(
            children.isdisjoint(set().union(*branches)), "overlapping Wild lifetimes"
        )
        branches.append(children)
        result[tag] = k["samples"][w["seq"]]
    require(
        set(result) == set(expected)
        and (k["whole"] == 0 or 0 < sum(result.values()) < k["whole"]),
        "impossible combined count",
    )
    return {"whole": k["whole"], "outputs": result}
