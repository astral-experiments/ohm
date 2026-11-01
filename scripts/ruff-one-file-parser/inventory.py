"""Join a counter-free positive kernel exec ledger to Cargo's actual output inodes."""

from functools import cache, partial
from pathlib import Path
import re
import types

import protocol as p
import file_witness

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


def products(records, proc, repo, work, inodes):
    args = proc["argv"]
    name = o.option(args, "--crate-name")
    switches = [a for a in args if a.startswith("-Zlink-only") or a.startswith("link-only")]
    saved = [a for a in args if a.endswith(".rlink")]
    sources = [a for a in args if a.endswith(".rs")]
    f.require("-o" not in args and not any(a == "--print" or a.startswith("--print=") for a in args),
              "compiler output or query override")
    if not saved and not switches and name != "fixtures":
        return o.event_product(records, proc, repo, work, inodes)

    f.require(name in ("ruff", "fixtures") and "--emit=dep-info,link" in args and "--target" not in args,
              "unregistered saved-link or harness unit")
    test = name == "fixtures"
    kind = "test" if test else "bin"
    (unit,) = [r for r in records if r["target"]["kind"] == [kind] and r["target"]["name"] == name]
    expected_source = repo / ("crates/ruff_python_parser/tests/fixtures.rs" if test else "crates/ruff/src/main.rs")
    operand = saved or sources
    f.require(len(operand) == 1 and args.index(operand[0]) > 0
              and args[args.index(operand[0]) - 1] == "--edition=" + unit["target"]["edition"]
              and [a for a in args if a.startswith("--emit")] == ["--emit=dep-info,link"],
              "unregistered executable input or emission")
    f.require(unit["target"]["src_path"] == str(expected_source) and unit["target"]["crate_types"] == ["bin"]
              and unit["profile"]["test"] == test and args.count("--test") == int(test)
              and (("--crate-type" not in args) if test else (o.option(args, "--crate-type") == "bin")), "wrong executable target")
    flags = sorted(a[9:-1] for k, a in zip(args, args[1:]) if k == "--cfg" and a.startswith('feature="') and a.endswith('"'))
    f.require(flags == sorted(unit["features"]), "wrong executable features")
    suffixes = [a.split("=", 1)[1] for a in args if a.startswith("extra-filename=")]
    f.require(len(suffixes) <= 1 and all(re.fullmatch("-[0-9a-f]{16}", v) for v in suffixes)
              and (not test or len(suffixes) == 1), "unexpected executable suffix")
    out = Path(o.option(args, "--out-dir")) / (name + "".join(suffixes))
    public = Path(unit["executable"])
    f.require(unit["filenames"] == [str(public)] and inodes[file_witness.relative(out, work)] ==
              inodes[file_witness.relative(public, work)], "different actual executable inode")
    if switches or saved:
        f.require(len(switches) == 1 and switches[0] in ("-Zlink-only", "-Zlink-only=yes", "link-only", "link-only=yes")
                  and (switches[0].startswith("-Z") or ("-Z", switches[0]) in zip(args, args[1:]))
                  and not sources and saved == [str(out.with_suffix(".rlink"))], "wrong, mixed or missing saved-link operand")
        mode = "link-only"
    else:
        f.require([repo / a for a in sources] == [expected_source], "wrong ordinary test source")
        mode = "full"
    return unit, mode, [str(out)]


@cache
def signed_queries():
    fixture = c.read(c.HERE / "physical-fixture.json.gz")
    probes = fixture["source"]["signed_release_probe"]["selected"]
    return {tuple(a[1:]) for path, a in probes if path.endswith("/rustc")} | {("--version",)}


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
        all(e["serial"] in selected or
            (o.rustc_query(e["argv"]) and tuple(e["argv"][1:]) in signed_queries())
            for e in events if e["kind"] == 1)
        and all(e["kind"] == 1 for e in events if "--crate-name" in e["argv"]),
        "unaccounted compiler action",
    )
    used = []
    native = set()
    native_writers = set()
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
                native_writers.add(child["serial"])
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
            native_writers.update((cc["serial"], ld["serial"], w["serial"]))
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
    f.require(
        all(e["serial"] in native_writers for e in events if "-o" in e["argv"] and e["kind"] != 1),
        "foreign native output outside the enrolled writer chain",
    )
    dirty = {p.key(r) for r in records if not r["fresh"]}
    executed = set(used)
    missing = [r for r in records if p.key(r) in dirty - executed]
    eligible = {p.key(r) for r in file_witness.local_libraries(records, repo)}
    f.require(all(p.key(r) in eligible and r["executable"] is None and
                  sorted(Path(n).suffix for n in r["filenames"]) == [".rlib", ".rmeta"] for r in missing),
              "an unobserved dirty unit is not a two-output local library")
    f.require(
        len(executed) == len(used) and executed <= dirty and native | {e["serial"] for e in compilers} == set(selected),
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
        owners=owners, without_rustc=[dict(target=r["target"]["name"], outputs=r["filenames"]) for r in sorted(missing,key=p.key)], successful_execs=len(events), tasks=len(tasks), wild=len(wilds), whole_cargo=root
    )


def read(trace, topo, role, repo, work, rows, ins, sdk_rows, selectors):
    compiler = repo.parent / "home/.rustup/toolchains/ohm/bin/cargo"
    for line in (trace / "exec.tsv").read_text().splitlines():
        v = line.split("\t")
        args = (trace / f"args-{int(v[0]):04d}").read_bytes().split(b"\0")
        image, argv0 = v[6], Path(args[0].decode())
        for kind, role_name in ((1, "rustc"), (4, "wild")):
            dev, ino, path = selectors[role_name]
            if image == path or str(argv0) == path or (role_name == "rustc" and argv0.name == "rustc"):
                f.require(int(v[2]) == kind and image == path and list(map(int, v[4:6])) == [dev, ino],
                          "wrong physical " + role_name)
        if image == str(compiler) or argv0.name == "ohm-declared-cc":
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
