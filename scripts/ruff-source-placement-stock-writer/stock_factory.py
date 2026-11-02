"""Run the proven #337 constructor with one extra, fully checked Git successor."""

import importlib.util
import gzip
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stock_source as source

# The old module imports the preceding normal source-placement factory itself.
spec = importlib.util.spec_from_file_location(
    "guarded_native_factory", source.GUARDED_DIR / "factory.py"
)
guarded = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guarded)
base = guarded.common
matched = guarded.matched


def materialize(rust, reg):
    before = json.loads((source.GUARDED_DIR / "registration.json").read_bytes())
    guarded.verified_sources(rust, before)
    base.need(
        source.oid(rust, "FETCH_HEAD") == source.GUARDED,
        "original guarded commit was not physically reconstructed",
    )
    packet, expected = source.binding(HERE)
    base.need(
        expected == reg and before["bundle"] == reg["guarded_bundle"],
        "different role or predecessor",
    )
    candidate = packet["subject"]
    path = HERE / "candidate.bundle"
    bundle = source.bundle_header(path.read_bytes(), candidate)
    base.need(reg["bundle"] == bundle, "delivered source transport changed")
    base.need(
        base.git(rust, "bundle", "list-heads", str(path)) == candidate + " " + bundle["branch"],
        "different advertised compiler",
    )
    base.git(rust, "bundle", "verify", str(path))
    base.git(rust, "fetch", "--no-tags", "--no-recurse-submodules", str(path), bundle["branch"])
    base.need(
        source.oid(rust, "FETCH_HEAD") == candidate
        and source.shape(rust, candidate, packet["reviewed_sha256"]) == packet,
        "fresh complete source does not reproduce the independently reviewed compiler",
    )
    attested = json.loads((HERE / "root-source-attestation.json").read_bytes())
    paths = [r.split("\t", 1)[1] for r in attested["unchanged_gitlinks"]]
    base.need(
        len(set(paths)) == 12
        and all(
            sorted(base.git(rust, "ls-tree", rev, "--", *paths).splitlines())
            == sorted(attested["unchanged_gitlinks"])
            for rev in (source.GUARDED, candidate)
        ),
        "one of the twelve real Rust source gitlinks changed",
    )
    changed = reg["changed_sources"]
    base.need(
        base.git(
            rust, "diff", "--name-status", "--no-renames", source.PARENT, candidate
        ).splitlines()
        == [("M" if row["P"] else "A") + "\t" + p for p, row in sorted(changed.items())],
        "extra, removed or missing compiler file",
    )
    for role, row in reg["roles"].items():
        rev = row["revision"]
        base.need(
            [source.oid(rust, rev + "^{tree}"), source.oid(rust, rev + ":compiler")]
            == [row["tree"], row["compiler"]],
            "different materialized full product or compiler",
        )
        for p, entries in changed.items():
            oid = entries[role]
            base.need(
                base.git(rust, "ls-tree", rev, "--", p)
                == ("100644 blob " + oid + "\t" + p if oid else ""),
                "wrong participating source " + p,
            )
        base.need(
            all(source.oid(rust, rev + ":" + p) == oid for p, oid in reg["unchanged"].items()),
            "mismatched real source factory or source-built tools",
        )
    root = Path(os.environ["RUNNER_TEMP"]) / "ohm-branch-object-qa"
    base.save(root / "logs/selected-actual-source.json", packet)


def main(command):
    base.HERE, base.BRANCH = HERE, source.BRANCH
    reg = base.enrollment()
    source.binding(HERE)
    matched.HERE = HERE
    matched.verified_sources = materialize
    ws = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    root = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "ohm-branch-object-qa"
    if command == "preflight":
        matched.setup(ws, root, reg)
    elif command == "build":
        matched.source_build(ws, root, reg)
        for role in ("P", "C"):
            data = json.loads((root / "logs" / (role + "-constructed.json")).read_bytes())
            rows = data["cxx"]["OhmSourcePlacement.cpp"]
            base.need(
                bool(rows) == (role == "C")
                and all(row["sha256"] == source.SELECTED for row in rows)
                and all(data["rustc_crates"].get(name) for name in base.CRATES)
                and data["cxx"]["OhmRegisterCoalescer.cpp"],
                "real native source constructors did not match the selected trial",
            )
            if role == "C":
                with gzip.open(root / "logs/C-constructors.jsonl.gz", "rt") as f:
                    actual = [
                        rec
                        for line in f
                        if (rec := json.loads(line)).get("cpp") == "OhmSourcePlacement.cpp"
                    ]
                base.need(
                    actual
                    and all(
                        r["sha256"] == source.SELECTED
                        and "-fno-exceptions" in r["argv"]
                        and "-fexceptions" not in r["argv"]
                        and any(
                            v in ("-DRUSTC_LLVM_NO_EXCEPTIONS", "-DRUSTC_LLVM_NO_EXCEPTIONS=1")
                            for v in r["argv"]
                        )
                        for r in actual
                    ),
                    "the actual native C++ constructor did not enable the guarded, non-throwing explicit writer",
                )
    else:
        raise ValueError("unknown factory phase")


if __name__ == "__main__":
    main(sys.argv[1])
