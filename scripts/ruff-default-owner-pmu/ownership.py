"""Map kernel exec-stop counters to physical Cargo units without double-counting linkers."""

import json
from functools import partial
from pathlib import Path

import common as c


def optional_tag_probe(repo, work, products, inodes, trace, revision, exits, events, chains):
    """Recognize Git's one optional tag lookup underneath Ruff's successful version build script."""
    bad = [(pid, status) for pid, status in exits.items() if status != [0, 0]]
    if not bad:
        return
    c.need(len(bad) == 1, "multiple failing children in a successful build")
    pid, status = bad[0]
    chain = chains[pid]
    c.need(status == [128, 0] and len(chain) >= 4 and not any(pid in parents[1:] for parents in chains.values()),
           "failed child was not one ordinary Git leaf")
    leaf, parent, builder = chain[:3]
    rows = [[e for e in events if e["pid"] == expected] for expected in (leaf, parent, builder)]
    c.need(all(len(es) == 1 and es[0]["kind"] == 0 for es in rows), "failed probe has an unexpected exec or owner")
    git, log, build = (es[0] for es in rows)
    c.need(git["path"] == "/usr/lib/git-core/git" and git["argv"] == [git["path"], "describe", "--tags", revision]
           and log["path"] == "/usr/bin/git"
           and log["argv"] == ["git", "log", "-1", "--date=short", "--abbrev=9", "--format=%H %h %cd %(describe:tags)"],
           "failed child is not the registered Git metadata probe")
    scripts = [p["filenames"] for p in products if p["target"]["kind"] == ["custom-build"]
               and p["target"]["src_path"] == str(repo / "crates/ruff/build.rs")]
    c.need(scripts == [[build["path"]]] and build["argv"] == [build["path"]],
           "Git was not run by the actual Ruff build script")
    expected = inodes[str(Path(build["path"]).relative_to(work))][:2]
    raw = (trace / "exec.tsv").read_text().splitlines()[build["serial"] - 1].split("\t")
    c.need(raw[6] == build["path"] and [int(raw[4]), int(raw[5])] == expected, "foreign Ruff build script inode")


def read_attributed(topo, trace, selectors, repo, work, products, inodes):
    return topo.read(trace, selectors, "tree",
                     component=partial(classify, repo, work, products, inodes),
                     optional_exit=partial(optional_tag_probe, repo, work, products, inodes, trace, c.EXPECTED["A"]))


def option(argv, name):
    hits = [b for a, b in zip(argv, argv[1:]) if a == name]
    c.need(len(hits) == 1, ("single argument expected", name, hits))
    return hits[0]


def graph(rows):
    c.need(
        rows[-1] == {"reason": "build-finished", "success": True}
        and not any(m["reason"] == "compiler-message" and m["message"]["level"] == "error" for m in rows),
        "successful Cargo JSON terminal",
    )
    products = [r for r in rows if r["reason"] == "compiler-artifact"]

    def key(r):
        t = r["target"]
        return [
            r["package_id"],
            t["name"],
            t["kind"],
            t["crate_types"],
            t["src_path"],
            sorted(r["features"]),
            r["profile"],
            r["filenames"],
            r["executable"],
        ]

    inventory = sorted(json.dumps(key(r), sort_keys=True, separators=(",", ":")) for r in products)
    c.need(len(products) == len(set(inventory)) == 375, "complete unique 375-unit CLI graph")
    return inventory, products


def check_roots(rows, work):
    for r in rows:
        paths = []
        if r["reason"] == "compiler-artifact":
            paths = [*r["filenames"], *([r["executable"]] if r["executable"] else [])]
        elif r["reason"] == "build-script-executed":
            paths = [r["out_dir"]]
        c.need(
            all(
                Path(p).is_absolute()
                and ".." not in Path(p).parts
                and any(Path(p).is_relative_to(work / x) for x in ("target", "build"))
                for p in paths
            ),
            "output escaped registered roots",
        )


def event_product(rows, proc, repo, work, inodes):
    args = proc["argv"]
    name = option(args, "--crate-name")
    kind = option(args, "--crate-type")
    c.need(
        kind in ("lib", "bin") and "--test" not in args and "--target" not in args,
        ("unsupported Rust output", name),
    )
    (source,) = [str(repo / f) for f in args if f.endswith(".rs")]
    out = Path(option(args, "--out-dir"))
    extra = [arg.removeprefix("extra-filename=") for arg in args if arg.startswith("extra-filename=")]
    c.need(len(extra) <= 1 and out.is_absolute(), "named output directory")
    suffix = extra[0] if extra else ""
    candidates = [
        r
        for r in rows
        if r["target"]["name"].replace("-", "_") == name
        and r["target"]["src_path"] == source
        and (r["target"]["kind"] == [kind] or (kind == "bin" and r["target"]["kind"] == ["custom-build"]))
    ]
    flags = sorted(
        a[9:-1]
        for i, a in enumerate(args)
        if i and args[i - 1] == "--cfg" and a.startswith('feature="') and a.endswith('"')
    )
    candidates = [r for r in candidates if sorted(r["features"]) == flags]
    c.need(len(candidates) == 1, ("ambiguous physical Cargo target", name, source, flags))
    artifact = candidates[0]
    link_only = any(a in ("-Zlink-only", "-Zlink-only=yes") for a in args) or any(
        flag == "-Z" and value in ("link-only", "link-only=yes") for flag, value in zip(args, args[1:])
    )
    rlinks = [a for a in args if a.endswith(".rlink")]
    c.need((len(rlinks) == 1) == link_only and len(rlinks) <= 1, "inconsistent saved-link inputs")
    mode = "link-only" if link_only else "full"
    if kind == "lib":
        c.need(not link_only and "--emit=dep-info,metadata,link" in args, "unrecognized library command")
        expected = [out / ("lib" + name + suffix + "." + ext) for ext in ("rlib", "rmeta")]
    else:
        c.need("--emit=dep-info,link" in args, "unrecognized bin command")
        expected = [out / (name + suffix)]

    def inode(path):
        rel = str(Path(path).relative_to(work))
        c.need(rel in inodes and int(inodes[rel][3]) & 0o170000 == 0o100000, "expected regular product: " + rel)
        return tuple(inodes[rel])

    actual = artifact["filenames"]
    c.need(
        len(expected) == len(actual) and sorted(inode(p) for p in actual) == sorted(inode(p) for p in expected),
        ("actual Rust output does not match Cargo artifact", name),
    )
    return artifact, mode, [str(p) for p in expected]


def rustc_query(argv):
    if argv[1:] in (["-vV"], ["--version"]):
        return True
    probes = [a for a in argv if a.startswith("--print=")]
    return (
        bool(probes)
        and all(
            a.split("=", 1)[1] in {"sysroot", "file-names", "split-debuginfo", "crate-name", "cfg"} for a in probes
        )
        and "--out-dir" not in argv
        and "-o" not in argv
        and not any(a.endswith((".rs", ".rlink")) or a.startswith("--emit") for a in argv)
    )


def signed_cargo_images(trace, path, devino):
    actual_build = 0
    for line in (trace / "exec.tsv").read_text().splitlines():
        f = line.split("\t")
        data = (trace / f"args-{int(f[0]):04d}").read_bytes()
        c.need(data.endswith(b"\0"), "truncated argv")
        argv = data[:-1].decode().split("\0")
        if Path(argv[0]).name == "ohm-declared-cc" or f[6] == str(path):
            c.need(
                f[6] == str(path) and [int(f[4]), int(f[5])] == list(devino), "foreign installed Cargo/relay inode"
            )
        if f[6] == str(path) and argv[1:] == c.CMD[2:]:
            actual_build += 1
    c.need(actual_build == 1, "missing or duplicated actual signed Cargo build")


def classify(repo, work, products, inodes, root, events, selected, samples, tasks, chains):
    compilers = [v for v in selected.values() if v["kind"] == 1]
    roots = {v["pid"] for v in compilers}
    c.need(
        len(roots) == len(compilers) > 0 and not any(roots.intersection(chains[p][1:]) for p in roots),
        "overlapping compiler owners",
    )
    for e in events:
        if e["kind"] == 1 and e["serial"] not in selected:
            c.need(rustc_query(e["argv"]), "unmetered rustc action")
    accounted = set()
    owners = []
    consumed = set()
    for compiler in compilers:
        pid = compiler["pid"]
        serial = compiler["serial"]
        artifact, mode, expected = event_product(products, compiler, repo, work, inodes)
        key = json.dumps(
            [artifact["package_id"], artifact["target"], artifact["features"], artifact["profile"]], sort_keys=True
        )
        c.need(key not in consumed and not artifact["fresh"], "duplicate owner or no matching Cargo work")
        consumed.add(key)
        accounted.add(serial)
        descendants = [e for e in events if e["serial"] != serial and pid in chains[e["pid"]]]
        c.need(
            all(e["serial"] > serial and e["pid"] != pid for e in descendants),
            "existing descendant or re-exec at compiler boundary",
        )
        cc = [e for e in descendants if e["kind"] == 2 and e["serial"] in selected]
        wild = [e for e in descendants if e["kind"] == 4 and e["serial"] in selected]
        c.need(not any(a["pid"] in chains[b["pid"]][1:] for a in cc for b in cc if a is not b), "nested C drivers")
        c.need(not any(a["pid"] in chains[b["pid"]][1:] for a in wild for b in wild if a is not b), "nested Wild")
        c.need(len(cc) == len(wild), "unclassified native link")
        links = []
        for driver in cc:
            (w,) = [e for e in wild if driver["pid"] in chains[e["pid"]][1:]]
            collect = [
                e
                for e in descendants
                if e["kind"] == 3 and e["pid"] in chains[w["pid"]][1:] and driver["pid"] in chains[e["pid"]][1:]
            ]
            c.need(
                len(collect) == 1 and not any(w["pid"] in chains[e["pid"]][1:] for e in events),
                "foreign link or child image under stock Wild",
            )
            dest = option(w["argv"], "-o")
            c.need(
                option(driver["argv"], "-o") == option(collect[0]["argv"], "-o") == dest and dest in expected,
                "native output ownership",
            )
            cv = samples[driver["serial"]]
            wv = samples[w["serial"]]
            c.need(0 < wv <= cv, "invalid nested counter values")
            links.append(
                {
                    "output": dest,
                    "cc_serial": driver["serial"],
                    "collect2_serial": collect[0]["serial"],
                    "wild_serial": w["serial"],
                    "cc": cv,
                    "wild": wv,
                }
            )
            accounted.update((driver["serial"], w["serial"]))
        for e in descendants:
            if e["kind"] in (2, 4) and e["serial"] not in selected:
                c.need(
                    "-o" not in e["argv"]
                    and any(a.startswith(("-print-", "-dump")) or a == "--version" for a in e["argv"]),
                    "unknown unmetered native driver",
                )
            elif e["kind"] == 0:
                # A shipped Cargo relay or GCC subprogram may delegate. Count its work with its
                # enclosing rustc/cc. Never classify an unknown native writer as the signed linker.
                if "-o" in e["argv"]:
                    c.need(
                        e["path"] == str(repo.parent / "home/.rustup/toolchains/ohm/bin/cargo")
                        and Path(e["argv"][0]).name == "ohm-declared-cc"
                        and option(e["argv"], "-o") in expected
                        and any(e["pid"] in chains[w["pid"]][1:] for w in wild),
                        "unclassified child writer",
                    )
        total = samples[serial]
        cc_total = sum(v["cc"] for v in links)
        wild_total = sum(v["wild"] for v in links)
        c.need(0 <= wild_total <= cc_total <= total, "overdrawn parent counter")
        owners.append(
            {
                "package": artifact["package_id"],
                "target": artifact["target"]["name"],
                "kind": artifact["target"]["kind"],
                "features": artifact["features"],
                "profile": artifact["profile"],
                "src": artifact["target"]["src_path"],
                "outputs": expected,
                "mode": mode,
                "pid": pid,
                "serial": serial,
                "tasks": sum(pid in chain for chain in chains.values()),
                "instructions": total,
                "outside_cc": total - cc_total,
                "cc_outside_wild": cc_total - wild_total,
                "wild": wild_total,
                "links": links,
            }
        )
    dirty = {
        json.dumps([r["package_id"], r["target"], r["features"], r["profile"]], sort_keys=True)
        for r in products
        if not r["fresh"]
    }
    c.need(consumed == dirty and accounted == set(selected), "unmatched actual Cargo work or selected exec")
    c.need(
        any(o["target"] == "ruff" and o["kind"] == ["bin"] and len(o["links"]) == 1 for o in owners),
        "no physical final Ruff ELF link",
    )
    whole = samples[0]
    residual = whole - sum(r["instructions"] for r in owners)
    c.need(
        residual >= 0
        and whole == residual + sum(r["outside_cc"] + r["cc_outside_wild"] + r["wild"] for r in owners),
        "non-disjoint charge",
    )
    return {
        "whole": whole,
        "outside_rustcs": residual,
        "owners": sorted(owners, key=lambda r: -r["instructions"]),
        "tasks": len(tasks),
        "execs": len(events),
    }


def early_children(trace, result):
    events = [line.split("\t") for line in (trace / "tasks.tsv").read_text().splitlines()]
    selected = {o["serial"] for o in result["owners"]}
    for o in result["owners"]:
        for link in o["links"]:
            selected.update((link["cc_serial"], link["wild_serial"]))
    for serial in selected:
        at, pid = next((i, v[1]) for i, v in enumerate(events) if v[0] == "exec" and v[2] == str(serial))
        c.need(not any(v[0] == "spawn" and v[1] == pid for v in events[:at]), "child born before selected counter")
        c.need(
            not any(v[0] == "exec" and v[1] == pid for v in events[at + 1 :]),
            "enrolled process subsequently execed another image",
        )


def typed(rows, bad):
    errors = [m for m in rows if m.get("reason") == "compiler-message" and m["message"]["level"] == "error"]
    if not bad:
        c.need(not errors, "successful compile with an error")
        return []
    c.need(rows[-1] == {"reason": "build-finished", "success": False}, "Cargo failed completion")
    result = []
    for m in errors:
        v = m["message"]
        if not v["code"]:
            c.need(
                not v["spans"] and v["message"].startswith("aborting due to 1 previous error"),
                "extra compiler error",
            )
            continue
        (primary,) = [s for s in v["spans"] if s["is_primary"]]
        c.need(
            m["target"]["name"] == "ruff_python_parser"
            and v["code"]["code"] == "E0308"
            and primary["file_name"] == c.PARSER
            and any(c.INVALID.strip().decode() in t["text"] for t in primary["text"]),
            "incorrect Ruff parser diagnostic or span",
        )
        result.append(
            [v["code"]["code"], v["message"], primary["file_name"], primary["line_start"], primary["column_start"]]
        )
    c.need(len(result) == 1, "expected exactly one source E0308")
    return result
