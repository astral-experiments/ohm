"""Verify the compact record; pass the original archive and signed LLVM to repeat the IR experiment."""

import argparse
from collections import Counter
from contextlib import contextmanager
import ctypes
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from llvm_inputs import FILE, SignedLLVM, debug_key, sha
from native_objects import elf, iter_archive
from ordinal_controls import ordinal_mutations

RECEIPT_NAMES = (
    "receipts.json.gz",
    "ordinal-tables.json.gz",
    "ordinal-file-signatures.json.gz",
)


def read(name):
    with gzip.open(HERE / name, "rt") as f:
        return json.load(f)


def check_sums():
    for record in (HERE / "SHA256SUMS").read_text().splitlines():
        digest, name = record.split(maxsplit=1)
        with (HERE / name).open("rb") as f:
            assert hashlib.file_digest(f, "sha256").hexdigest() == digest, name


def verify_records(rec, coordinates, signatures):
    rows = rec["per_module"]
    tables = coordinates["modules"]
    file_records = signatures["modules"]
    assert set(rows) == set(tables) == set(file_records) and len(rows) == 21
    assert signatures["ordinal_tables"] == sha(
        (HERE / "ordinal-tables.json.gz").read_bytes()
    )
    quantities = rec["quantities"]
    groups = {}
    groups["all"] = set(rows)
    groups["allocated_and_relocation_equal"] = {
        k for k, r in rows.items() if r["allocated_and_link_equal"]
    }
    groups["genuine_changed_allocated"] = (
        set(rows) - groups["allocated_and_relocation_equal"]
    )
    groups["untouched_stripped_bitcode_equal"] = {
        k for k, r in rows.items() if r["untouched_stripped_equal"]
    }
    groups["changed_runtime_literals_with_unused_formal"] = (
        groups["allocated_and_relocation_equal"]
        - groups["untouched_stripped_bitcode_equal"]
    )
    groups["raw_bc_equal"] = {
        k for k, r in rows.items() if r["input_bc"]["old"] == r["input_bc"]["new"]
    }
    groups["raw_object_equal"] = {
        k for k, r in rows.items() if r["native"]["old"] == r["native"]["new"]
    }
    changes = Counter()
    sites = 0
    for k, r in rows.items():
        t = tables[k]
        assert (
            r["native"]["new"] == r["native"]["clean"]
            and r["all_function_bodies_equal"]
        )
        eq = r["allocated_and_link_equal"]
        assert eq == t["admitted"] == t["allocated_and_relocations_equal"]
        assert (
            eq
            == (r["input_key"]["old"] == r["input_key"]["new"])
            == (r["input_dense_text"]["old"] == r["input_dense_text"]["new"])
        )
        assert (
            r["cost"]["total"]
            == r["cost"]["ir_pipeline"]
            + r["cost"]["machine_emission"]
            + r["cost"]["actor"]
        )
        assert r["cost"]["new_preopt"] == r["input_bc"]["new"] == r["post_O1"]["input"]
        assert not r["post_O1"]["still_named_after_O1"] and r["post_O1"][
            "also_old"
        ] == (k in groups["raw_bc_equal"])
        for role in ("old", "new"):
            q = t[role]
            fs = q["files"]
            assert (
                q["input_bc"] == r["input_bc"][role]
                and q["comparison_key"] == r["input_key"][role]
            )
            assert q["tables_sha256"] == sha(json.dumps(fs, sort_keys=True).encode())
            assert fs.keys() <= file_records[k][role].keys() and all(
                vals == sorted(set(vals)) and all(x > 0 for x in vals)
                for vals in fs.values()
            )
        if eq:
            assert (
                r["whole_symbol_table_equal"] and not r["relocation_sections_changed"]
            )
            assert set(r["changed_sections"]) <= {".debug_info", ".debug_line"}
            changes[tuple(r["changed_sections"])] += 1
            sites += sum(x[4] for x in r["conditional_locations"])
        if "stock_deadargelim_globaldce" in r:
            z = r["stock_deadargelim_globaldce"]
            assert (
                eq
                == (z["old"]["post_stripped"] == z["new"]["post_stripped"])
                == (z["old"]["post_dense"] == z["new"]["post_dense"])
            )
    expect = quantities["subsets"]
    for group, keys in groups.items():
        assert len(keys) == expect[group]["modules"]
        for field in ("total", "ir_pipeline", "machine_emission", "actor"):
            assert sum(rows[k]["cost"][field] for k in keys) == expect[group][field]
    assert changes == {
        (): 4,
        (".debug_info",): 3,
        (".debug_line",): 1,
        (".debug_info", ".debug_line"): 11,
    }
    assert sum(r["defined_functions"] for r in rows.values()) == 14167
    assert sites == sum(quantities["callsites"].values()) == 3022
    assert sum(r["debug_rows"].get("4", 0) for r in rows.values()) == 16560
    assert (
        sum(r["debug_die_attributes"].get("call+4", 0) for r in rows.values()) == 11474
    )
    assert (
        sum(
            r["with_source_checksum"]["old"] == r["with_source_checksum"]["new"]
            for r in rows.values()
        )
        == 2
    )
    assert (
        len(groups["allocated_and_relocation_equal"]) == 19
        and len(groups["untouched_stripped_bitcode_equal"]) == 8
    )
    return groups


@contextmanager
def module(a, raw):
    cx = a.ContextCreate()
    buf = a.CreateMemoryBufferWithMemoryRangeCopy(raw, len(raw), b"input.bc")
    m = ctypes.c_void_p()
    try:
        assert a.ParseBitcodeInContext2(cx, buf, ctypes.byref(m)) == 0
        yield m
    finally:
        if m:
            a.DisposeModule(m)
        a.DisposeMemoryBuffer(buf)
        a.ContextDispose(cx)


def stock_dae_contact(a, raw, source):
    with module(a, raw) as m:
        options = a.CreatePassBuilderOptions()
        try:
            err = a.RunPasses(m, b"deadargelim,globaldce", None, options)
            if err:
                msg = a.GetErrorMessage(err)
                try:
                    raise ValueError(ctypes.string_at(msg).decode())
                finally:
                    a.DisposeErrorMessage(msg)
        finally:
            a.DisposePassBuilderOptions(options)
        msg = ctypes.c_void_p()
        rc = a.VerifyModule(m, 2, ctypes.byref(msg))
        try:
            assert rc == 0
        finally:
            if msg:
                a.DisposeMessage(msg)
        dense, _ = debug_key(a.textmod(m), source)
        a.StripModuleDebugInfo(m)
        return {"post_stripped": a.serialize(m), "post_dense": a.wire(dense)}


def reopen(args, rec, tabs):
    a = SignedLLVM(args.llvm)
    if args.source_old and args.source_new:
        sources = {
            "old": args.source_old.read_bytes(),
            "new": args.source_new.read_bytes(),
        }
    elif args.ruff_checkout:
        sources = {
            r: subprocess.check_output(
                [
                    "git",
                    "--no-lazy-fetch",
                    "-C",
                    str(args.ruff_checkout),
                    "show",
                    rec["roles"]["Ruff_" + r] + ":" + FILE,
                ]
            )
            for r in ("old", "new")
        }
    else:
        raise ValueError(
            "supply both source files, or an existing Ruff checkout containing the two commits"
        )
    for role, src in sources.items():
        assert sha(src) == tabs["source_roles"][role]["physical_sha256"]
    with args.capture.open("rb") as f:
        assert (
            hashlib.file_digest(f, "sha256").hexdigest()
            == rec["roles"]["archive_sha256"]
        )
    with zipfile.ZipFile(args.capture) as z:

        def payload(d):
            key = d["sha256"]
            b = gzip.decompress(z.read("cgu-originals/" + key + ".gz"))
            assert sha(b) == key and len(b) == d["stat"][2]
            return b

        stages = {
            r: json.loads(z.read(p + "/cgus.json"))["ruff_workspace"]
            for r, p in [
                ("old", "capture/old"),
                ("new", "capture/new"),
                ("clean", "capture-empty/new"),
            ]
        }
        selected = set(stages["new"]["emitted"])
        assert selected == rec["per_module"].keys()
        objects = {
            r: {
                k: bytes(part)
                for k, part in iter_archive(payload(stage["archive"]), "ruff_workspace")
                if k in selected
            }
            for r, stage in stages.items()
        }
        for k in sorted(selected):
            row = rec["per_module"][k]
            before = []
            for role in ["old", "new", "clean"]:
                assert sha(objects[role][k]) == row["native"][role]
                if role == "clean":
                    continue
                b = payload(stages[role]["emitted"][k])
                assert sha(b) == row["input_bc"][role]
                result, _ = a.independent(b, sources[role])
                assert (
                    result["whole_llvm_bitcode"] == row["input_key"][role]
                    and result["whole_llvm_text"] == row["input_dense_text"][role]
                )
                assert (
                    result["debug"]["with_real_checksum"]
                    == row["with_source_checksum"][role]
                    and result["debug"]["tables_sha256"]
                    == tabs["modules"][k][role]["tables_sha256"]
                )
                with module(a, b) as m:
                    a.StripModuleDebugInfo(m)
                    before.append(a.serialize(m))
                if "stock_deadargelim_globaldce" in row:
                    assert (
                        stock_dae_contact(a, b, sources[role])
                        == row["stock_deadargelim_globaldce"][role]
                    )
            assert (before[0] == before[1]) == row["untouched_stripped_equal"]
            x, y = [elf(objects[r][k]) for r in ("old", "new")]
            changed = sorted(
                n for n in set(x[0]) | set(y[0]) if x[0].get(n) != y[0].get(n)
            )
            assert (
                changed == sorted(row["changed_sections"])
                and (x[1] == y[1]) == row["whole_symbol_table_equal"]
            )
            assert (
                sorted(
                    n
                    for n in set(x[2]) | set(y[2])
                    if x[2].get(n, []) != y[2].get(n, [])
                )
                == row["relocation_sections_changed"]
            )
    print(
        "Reopened all 21 old/edited/independent-clean objects, 42 untouched pre-optimization modules, and six stock DAE module transformations."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for opt in ("capture", "llvm", "source-old", "source-new", "ruff-checkout"):
        parser.add_argument("--" + opt, type=Path)
    args = parser.parse_args()
    if bool(args.capture) != bool(args.llvm):
        parser.error("--capture and --llvm are required together")
    check_sums()
    rec, tables, sigs = map(read, RECEIPT_NAMES)
    assert ordinal_mutations() == rec["ordinal_negative_controls"]
    groups = verify_records(rec, tables, sigs)
    print(
        f"{len(groups['allocated_and_relocation_equal'])}/21 complete comparison keys match; both native data changes miss."
    )
    if args.capture:
        reopen(args, rec, tables)


if __name__ == "__main__":
    main()
