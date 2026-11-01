"""Join a counter-free positive kernel exec ledger to Cargo's actual output inodes."""

from functools import partial
from pathlib import Path
import types

import protocol as p

f, o, c = p.f, p.ownership, p.c


def decoder(topo):
    # The historical callback is after its complete native lineage/sample checks. Select the
    # topology-only mode at that same point; actual observer/watch sources are byte-identical.
    src = Path(topo.__file__)
    body = src.read_bytes()
    old = b'assert mode == "tree" and not synthetic'
    f.require(
        f.sha(body) == "4a9342275c6b5d1efd04881e8fb310291ffd7e284993dabd015aee4a6db3ce04"
        and body.count(old) == 1,
        "unregistered ledger seam",
    )
    mod = types.ModuleType("topology_without_counters")
    exec(
        compile(body.replace(old, b'assert mode == "topology" and not synthetic'), str(src), "exec"),
        mod.__dict__,
    )
    return mod


def products(row, proc, repo, work, inodes):
    args = proc["argv"]
    if o.option(args, "--crate-name") != "fixtures":
        return o.event_product(row, proc, repo, work, inodes)
    (test,) = [r for r in row if r["target"]["kind"] == ["test"] and r["target"]["name"] == "fixtures"]
    (source,) = [str(repo / a) for a in args if a.endswith(".rs")]
    f.require(
        source == test["target"]["src_path"] == str(repo / "crates/ruff_python_parser/tests/fixtures.rs")
        and test["target"]["crate_types"] == ["bin"]
        and test["profile"]["test"]
        and "--emit=dep-info,link" in args
        and "--target" not in args,
        "wrong physical parser test rustc",
    )
    (suffix,) = [a.split("=", 1)[1] for a in args if a.startswith("extra-filename=")]
    f.require(suffix.startswith("-") and len(suffix) == 17, "unexpected native fixture suffix")
    output = Path(o.option(args, "--out-dir")) / ("fixtures" + suffix)
    (name,) = test["filenames"]
    f.require(name == test["executable"], "different parser executable")
    f.require(
        inodes[str(output.relative_to(work))] == inodes[str(Path(name).relative_to(work))],
        "different actual parser output inode",
    )
    saved = [a for a in args if a.endswith(".rlink")]
    relink = any(a in ("-Zlink-only", "-Zlink-only=yes") for a in args) or any(
        k == "-Z" and v in ("link-only", "link-only=yes") for k, v in zip(args, args[1:])
    )
    f.require(len(saved) == int(relink), "inconsistent saved-link inputs on fixtures")
    return test, ("link-only" if relink else "full"), [str(output)]


def classify(
    role, repo, work, records, ins, sdk, command, root, events, selected, samples, tasks, chains
):
    f.require(not any(samples.values()), "counter on structural Cargo visit")
    cargo = repo.parent / "home/.rustup/toolchains/ohm/bin/cargo"
    build = [e for e in events if e["path"] == str(cargo) and e["argv"][1:] == command[2:]]
    f.require(len(build) == 1, "wrong physical signed Cargo invocation")
    compilers = [e for e in selected.values() if e["kind"] == 1]
    wilds = [e for e in selected.values() if e["kind"] == 4]
    f.require(
        len({e["pid"] for e in compilers}) == len(compilers)
        and all(not any(a["pid"] in chains[b["pid"]][1:] for a in compilers) for b in compilers),
        "nested or repeated rustc owners",
    )
    f.require(
        all(e["serial"] in selected or o.rustc_query(e["argv"]) for e in events if e["kind"] == 1),
        "unaccounted compiler action",
    )
    used = []
    native = set()
    owners = []
    for e in compilers:
        f.require(
            build[0]["pid"] in chains[e["pid"]] and build[0]["serial"] < e["serial"],
            "compiler not started by real Cargo",
        )
        art, mode, paths = products(records, e, repo, work, ins)
        used.append(p.key(art))
        links = []
        descendants = [v for v in events if e["pid"] in chains[v["pid"]][1:]]
        for child in descendants:
            args = child["argv"]
            if child["kind"] in (2, 4) and child["serial"] not in selected:
                f.require(
                    "-o" not in args
                    and any(a.startswith(("-print-", "-dump")) or a == "--version" for a in args),
                    "unclassified native driver",
                )
            elif child["kind"] == 0 and "-o" in args:
                f.require(
                    child["path"] == str(cargo)
                    and Path(args[0]).name == "ohm-declared-cc"
                    and o.option(args, "-o") in paths
                    and any(child["pid"] in chains[w["pid"]][1:] for w in wilds),
                    "foreign child output writer",
                )
        for w in [v for v in wilds if v in descendants]:
            dest = o.option(w["argv"], "-o")
            (cc,) = [
                v
                for v in descendants
                if v["kind"] == 2 and v["serial"] in selected and v["pid"] in chains[w["pid"]][1:]
            ]
            (ld,) = [
                v
                for v in descendants
                if v["kind"] == 3
                and cc["pid"] in chains[v["pid"]][1:]
                and v["pid"] in chains[w["pid"]][1:]
            ]
            f.require(
                e["serial"] < cc["serial"] < ld["serial"] < w["serial"]
                and o.option(cc["argv"], "-o") == o.option(ld["argv"], "-o") == dest
                and dest in paths,
                "native writer output or physical lineage",
            )
            native.update((cc["serial"], w["serial"]))
            links.append(
                dict(
                    wild_serial=w["serial"],
                    cc_serial=cc["serial"],
                    collect2_serial=ld["serial"],
                    output=dest,
                )
            )
        f.require(
            art["target"]["kind"] in (["bin"], ["test"]) or not links,
            "unexpected native linker under library",
        )
        owners.append(
            dict(
                serial=e["serial"],
                pid=e["pid"],
                target=art["target"]["name"],
                kind=art["target"]["kind"],
                mode=mode,
                outputs=paths,
                links=links,
            )
        )
    dirty = sorted(p.key(r) for r in records if not r["fresh"])
    f.require(
        sorted(used) == dirty and native | {e["serial"] for e in compilers} == set(selected),
        "unmatched cargo unit or native exec",
    )
    _, _, name, kind = p.ROLES[role]
    f.require(
        sum(v["target"] == name and v["kind"] == [kind] and len(v["links"]) == 1 for v in owners) == 1
        and sum(
            v["target"] == "ruff_python_parser" and v["kind"] == ["lib"] and v["mode"] == "full"
            for v in owners
        )
        == 1,
        "real edited parser library or final Wild output missing",
    )
    return dict(
        owners=owners, successful_execs=len(events), tasks=len(tasks), wild=len(wilds), whole_cargo=root
    )


def read(trace, topo, role, repo, work, rows, ins, sdk_rows, selectors):
    compiler = repo.parent / "home/.rustup/toolchains/ohm/bin/cargo"
    for line in (trace / "exec.tsv").read_text().splitlines():
        v = line.split("\t")
        args = (trace / f"args-{int(v[0]):04d}").read_bytes().split(b"\0")
        if v[6] == str(compiler) or Path(args[0].decode()).name == "ohm-declared-cc":
            f.require(
                v[6] == str(compiler) and list(map(int, v[4:6])) == sdk_rows["bin/cargo"][1:3],
                "wrong physical Cargo/relay",
            )
    result = topo.read(
        trace,
        selectors,
        "topology",
        component=partial(classify, role, repo, work, rows, ins, sdk_rows, p.command(role)),
    )
    o.early_children(trace, result)
    return result
