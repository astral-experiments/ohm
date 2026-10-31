"""A baseline-only envelope for the real Ruff #29308 edit."""

from fractions import Fraction
from pathlib import Path
import json
import hashlib

RUFF = "93526150df078af7dd8fc4226cdcc469539d2001"
CHILD = "4d6a7db787130c5a4a95bd835369babd78e4a1f6"
PATCH = "f5a3c6085bb0e90335c5f1686a0eb9c61e1456aa5d5808381a2deea304b3650d"
FEATURELESS = "69c21b3ecf8510871c346f751c60866e302708d5"
COLLECTOR = "8a659140df8ab27fd6a8cc61f5eb38717b3f8bbc"
RUST = "c79998a5cd143c445a4b2528f20953b176a65c5d"
CARGO = "761ea115605c34f11a1cd29afd68812c1e1359dd"
CLI = "cargo +ohm test --no-run -p ty_server --test e2e --locked --offline -j8 --message-format=json".split()
EIGHT = {
    "ruff_db": 252,
    "ruff_ranged_value": 8,
    "ty_vendored": 3,
    "ty_site_packages": 30,
    "ty_module_resolver": 102,
    "ty_combine": 1,
    "ty_project": 243,
    "ty_ide": 171,
}
REPEAT = {"build_script_build", "unicode_names2", "e2e"}
EDIT = set(EIGHT) | REPEAT | {"ty_python_core", "ty_python_semantic", "ruff_notebook", "ty_server"}
STATES = {
    "prior-repeat": "original",
    "edited": "reversed",
    "edit-repeat": "reversed",
    "restored": "original",
    "restore-repeat": "original",
}
CASES = {
    "original": {"notebook::cells_after_cell_magic", "notebook::inlay_hints_range_past_end_of_cell"},
    "reversed": {"notebook::inlay_hints_range_past_end_of_cell"},
}
GUARD_FILE = "crates/ruff_db/src/lib.rs"
GUARD = b'\nconst _: u8 = "OHM_NOTEBOOK_29308_E0308";\n'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def signed_closure(rows):
    projection = {n: [r["sha256"], r["size"], r["mode"], r["link"]] for n, r in rows.items()}
    digest = hashlib.sha256(
        json.dumps(projection, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    require(
        len(rows) == 149
        and digest == "b0700ca4a4ec446f8c4ce9c4e63ffa02b1352d96429942718095777a95bf2140",
        "different signed -21 SDK image",
    )
    return digest


def option(args, name):
    vals = [args[i + 1] for i, a in enumerate(args[:-1]) if a == name]
    require(len(vals) == 1, (name, vals))
    return vals[0]


def relative_source(name):
    return {
        "build_script_build": "crates/ruff_unicode_names2/build.rs",
        "unicode_names2": "crates/ruff_unicode_names2/src/lib.rs",
        "e2e": "crates/ty_server/tests/e2e/main.rs",
    }.get(name, f"crates/{name}/src/lib.rs")


def compiler(args, root):
    name = option(args, "--crate-name")
    require(
        name in EDIT and [s for s in args if s.endswith(".rs")] == [relative_source(name)],
        (name, "source"),
    )
    require(
        "--target" not in args and not any("link-only" in a for a in args), (name, "compilation mode")
    )
    dest = Path(option(args, "--out-dir"))
    extra = [v.split("=", 1)[1] for v in args if v.startswith("extra-filename=")]
    increments = [Path(v.split("=", 1)[1]) for v in args if v.startswith("incremental=")]
    require(
        dest.name == "out"
        and dest.is_relative_to(root / "slot/target/debug/build/workspaces")
        and len(increments) == 1
        and increments[0].parent == root / "slot/target/debug/incremental",
        (name, dest, increments),
    )
    if name == "e2e":
        require(
            "--test" in args
            and "--crate-type" not in args
            and "--emit=dep-info,link" in args
            and len(extra) == 1,
            "test mode",
        )
        return name, str(dest / ("e2e" + extra[0]))
    if name == "build_script_build":
        require(
            option(args, "--crate-type") == "bin" and "--emit=dep-info,link" in args and not extra,
            "generator mode",
        )
        return name, str(dest / name)
    require(
        option(args, "--crate-type") == "lib"
        and "--emit=dep-info,metadata,link" in args
        and len(extra) == 1
        and "-Zpublic-api-hash" in args
        and "-Zpublic-api-hash=no" not in args,
        (name, "full library"),
    )
    return name, str(dest / ("lib" + name + extra[0] + ".rmeta"))


def typed(raw, root):
    rows = [json.loads(v) for v in raw.splitlines()]
    require(
        rows
        and rows[-1] == {"reason": "build-finished", "success": True}
        and not any(
            r["reason"] == "compiler-message" and r["message"]["level"] == "error" for r in rows
        ),
        "Cargo success",
    )
    inventory = []
    products = {}
    for row in rows:
        if row["reason"] != "compiler-artifact":
            continue
        target = row["target"]
        key = json.dumps(
            [
                row["package_id"],
                target["name"],
                target["kind"],
                row["features"],
                row["profile"]["test"],
            ],
            separators=(",", ":"),
        )
        inventory.append(key)
        name = target["name"]
        if name == "build-script-build" and Path(
            target["src_path"]
        ) == root / "ruff" / relative_source("build_script_build"):
            name = "build_script_build"
        if name not in EDIT or Path(target["src_path"]) != root / "ruff" / relative_source(name):
            continue
        require(name not in products, ("duplicate returned unit", name))
        if name == "build_script_build":
            require(
                target["kind"] == ["custom-build"] and len(row["filenames"]) == 1,
                "missing generator binary",
            )
            products[name] = row["filenames"][0]
        elif name == "e2e":
            require(
                target["kind"] == ["test"] and row["profile"]["test"] and bool(row["executable"]),
                "missing native e2e",
            )
            products[name] = row["executable"]
        else:
            meta = [p for p in row["filenames"] if p.endswith(".rmeta")]
            require(len(meta) == 1 and target["kind"] == ["lib"], (name, "typed metadata"))
            products[name] = meta[0]
    require(
        len(inventory) == 300 and len(set(inventory)) == 277 and set(products) == EDIT,
        "feature-free 277-unit graph",
    )
    require(
        all(Path(f).is_relative_to(root / "slot") for f in products.values()),
        "product outside active roots",
    )
    return sorted(inventory), products


def classify(rootdir, typed_paths, changed, root, events, selected, samples, tasks, chains):
    """Map exec-stop counters to the exact product, prove disjointness, leave both real links outside U."""
    compilers = [e for e in selected.values() if e["kind"] == 1]
    roots = {e["pid"] for e in compilers}
    require(len(roots) == len(compilers), "same task re-executed a selected compiler")
    roster = {}
    native = {}
    accounted = set()
    for e in compilers:
        idx, pid = e["serial"], e["pid"]
        name, output = compiler(e["argv"], rootdir)
        require(
            name not in roster and not (roots & set(chains[pid][1:])),
            (name, "overlapping compiler event"),
        )
        require(typed_paths[name] == output, (name, typed_paths[name], output))
        require(
            all(x["serial"] > idx for x in events if x["pid"] != pid and pid in chains[x["pid"]]),
            (name, "a descendant predates the selected exec boundary"),
        )
        below = [x for x in events if pid in chains[x["pid"]] and x["serial"] > idx]
        require(all(x["pid"] != pid for x in below), "compiler image changed")
        roster[name] = {
            "pid": pid,
            "serial": idx,
            "instructions": samples[idx],
            "output": output,
            "tasks": sum(pid in c for c in chains.values()),
        }
        accounted.add(idx)
        if name not in ("e2e", "build_script_build"):
            require(not below, (name, "unexpected external child executable"))
            continue
        require(sorted(x["kind"] for x in below) == [2, 3, 4], (name, "unexpected linker descendants"))
        by_role = {x["kind"]: x for x in below}
        cc, collect, wild = [by_role[i] for i in (2, 3, 4)]
        require(
            cc["pid"] in chains[collect["pid"]][1:]
            and collect["pid"] in chains[wild["pid"]][1:]
            and all(option(x["argv"], "-o") == output for x in below),
            (name, "native ancestry/actual output"),
        )
        require(
            samples[wild["serial"]] <= samples[cc["serial"]] <= samples[idx], "invalid nested counters"
        )
        require(
            not any(wild["pid"] in chains[x["pid"]][1:] for x in events),
            "native linker execed another image",
        )
        accounted.update([cc["serial"], wild["serial"]])
        native[name] = {
            "output": output,
            "pids": [cc["pid"], collect["pid"], wild["pid"]],
            "cc_including_wild": samples[cc["serial"]],
            "wild_including_workers": samples[wild["serial"]],
        }
    require(
        set(roster) == (EDIT if changed else REPEAT)
        and set(native) == {"e2e", "build_script_build"}
        and accounted == set(selected)
        and sum(v["instructions"] for v in roster.values()) <= samples[0],
        ("unexpected physical roster or overlapping counters", list(roster)),
    )
    real_gen = [e for e in events if e["path"] == typed_paths["build_script_build"]]
    require(
        len(real_gen) == 1
        and real_gen[0]["pid"] not in roots
        and not (roots & set(chains[real_gen[0]["pid"]])),
        "generator execution not separate",
    )
    u = sum(roster[k]["instructions"] for k in EIGHT) if changed else 0
    return {
        "whole": samples[0],
        "eight_inclusive": u,
        "root": root,
        "tasks": len(tasks),
        "events": len(events),
        "compilers": roster,
        "native": native,
        "generator_pid": real_gen[0]["pid"],
    }


def activation_boundaries(trace, scopes):
    # An inherited event covers tasks forked after the selected exec stop. Refuse
    # any compiler with a preexisting direct child at that stop, even if later reaped.
    lines = [v.split("\t") for v in (trace / "tasks.tsv").read_text().splitlines()]
    at = {int(v[2]): i for i, v in enumerate(lines) if v[0] == "exec"}
    for key, record in scopes["compilers"].items():
        early = [
            (int(v[2]), i)
            for i, v in enumerate(lines)
            if v[0] == "spawn" and int(v[1]) == record["pid"] and i < at[record["serial"]]
        ]
        require(not early, (key, "child already existed before event activation", early))


def ceiling(whole, first, last, u):
    require(
        all(type(n) is int and n > 0 for n in (whole, first, last, u)) and u < whole,
        "invalid instruction counts",
    )
    low, high = min(first, whole, last), max(first, whole, last)
    require(20 * (high - low) <= low, ("greater than 5% whole-instruction spread", first, whole, last))
    require(u < low, "removal exceeds smallest whole-command cost")
    verdict = (
        "below-2x" if 2 * u < low else ("room-for-investigation" if 2 * u > high else "unresolved")
    )

    def fraction(x):
        f = Fraction(x, x - u)
        return [f.numerator, f.denominator]

    return {
        "whole_traced": whole,
        "whole_untraced": [first, last],
        "eight_inclusive": u,
        "optimistic_envelope": [fraction(high), fraction(low)],
        "headroom_over_half_of_larger_whole": [2 * u - high, 2],
        "outcome": verdict,
    }
