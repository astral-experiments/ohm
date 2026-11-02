"""Complete the original physical P build and an independently empty one-file-repaired native C."""

import gzip
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fix_source as fix
import stock_factory as old

base, matched = old.base, old.matched


def materialize(rust, reg):
    _, reg_a9 = fix.prev.binding(fix.ORIGINAL)
    old.materialize(rust, reg_a9)
    packet, expected = fix.binding()
    base.need(
        expected == reg
        and fix.oid(rust, "FETCH_HEAD") == fix.A9
        and reg["refused_explicit_bundle"] == reg_a9["bundle"],
        "failed to reconstruct original actual compiler",
    )
    path = HERE / "candidate.bundle"
    head = packet["subject"]
    ref = reg["bundle"]["branch"]
    base.need(
        base.git(rust, "bundle", "list-heads", str(path)) == head + " " + ref,
        "wrong child in source transport",
    )
    base.git(rust, "bundle", "verify", str(path))
    base.git(rust, "fetch", "--no-tags", "--no-recurse-submodules", str(path), ref)
    base.need(
        fix.oid(rust, "FETCH_HEAD") == head and fix.shape(rust, head) == packet,
        "unpacked complete native compiler no longer matches reviewed source",
    )
    source_files = reg["changed_sources"]
    base.need(
        base.git(rust, "diff", "--name-status", "--no-renames", fix.prev.PARENT, head).splitlines()
        == [("M" if r["P"] else "A") + "\t" + p for p, r in sorted(source_files.items())],
        "unregistered compiler source",
    )
    for role, r in reg["roles"].items():
        rev = r["revision"]
        base.need(
            [fix.oid(rust, rev + "^{tree}"), fix.oid(rust, rev + ":compiler")]
            == [r["tree"], r["compiler"]]
            and all(
                base.git(rust, "ls-tree", rev, "--", p)
                == ("100644 blob " + v[role] + "\t" + p if v[role] else "")
                for p, v in source_files.items()
            )
            and all(fix.oid(rust, rev + ":" + p) == blob for p, blob in reg["unchanged"].items()),
            "incomplete physical source, tools or native files",
        )
    refs = fix.loaded(fix.ORIGINAL / "root-source-attestation.json")["unchanged_gitlinks"]
    paths = [r.split("\t", 1)[1] for r in refs]
    base.need(
        len(set(paths)) == 12
        and sorted(base.git(rust, "ls-tree", head, "--", *paths).splitlines()) == sorted(refs),
        "one of the twelve pinned submodules changed",
    )
    root = Path(os.environ["RUNNER_TEMP"]) / "ohm-branch-object-qa"
    # The original selected-actual-source.json remains the complete root-attested failed A9 source.
    base.save(root / "logs/fixed-actual-source.json", packet)


def main(command):
    base.HERE, base.BRANCH = HERE, fix.prev.BRANCH
    reg = base.enrollment()
    fix.binding()
    matched.HERE = HERE
    matched.verified_sources = materialize
    ws = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    root = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "ohm-branch-object-qa"
    if command == "preflight":
        matched.setup(ws, root, reg)
    elif command == "build":
        matched.source_build(ws, root, reg)
        for role in ("P", "C"):
            data = fix.loaded(root / "logs" / (role + "-constructed.json"))
            cpp = data["cxx"]["OhmSourcePlacement.cpp"]
            base.need(
                bool(cpp) == (role == "C")
                and all(r["sha256"] == fix.prev.SELECTED for r in cpp)
                and all(data["rustc_crates"].get(name) for name in base.CRATES)
                and data["cxx"]["OhmRegisterCoalescer.cpp"],
                "physical native, Rust or #337 source producer missing",
            )
            if role == "C":
                with gzip.open(root / "logs/C-constructors.jsonl.gz", "rt") as f:
                    rows = [
                        r
                        for line in f
                        if (r := json.loads(line)).get("cpp") == "OhmSourcePlacement.cpp"
                    ]
                base.need(
                    rows
                    and all(
                        r["sha256"] == fix.prev.SELECTED
                        and "-fno-exceptions" in r["argv"]
                        and "-fexceptions" not in r["argv"]
                        and any(
                            arg in ("-DRUSTC_LLVM_NO_EXCEPTIONS", "-DRUSTC_LLVM_NO_EXCEPTIONS=1")
                            for arg in r["argv"]
                        )
                        for r in rows
                    ),
                    "real native translation unit fallback or unqualified exception mode",
                )
    else:
        raise ValueError(command)


if __name__ == "__main__":
    main(sys.argv[1])
