"""Recheck the independently retained format, grammar and disk controls without rebuilding rustc."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import stat
import subprocess
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

here = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--collect", type=Path, metavar="BOARD", help="Collect once from the original study tree")
parser.add_argument("--run-native", action="store_true", help="Run the two retained Linux grammar executables")
args = parser.parse_args()
assert __debug__

def sha(b):
    return hashlib.sha256(b).hexdigest()

def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def serialized(obj):
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()

def measure(directory, target, shared):
    records = {}
    for name in (target, shared):
        base = directory / name
        assert base.is_dir()
        for parent, _, files in os.walk(base):
            for filename in sorted(files):
                path = Path(parent) / filename
                st = path.lstat()
                if not stat.S_ISREG(st.st_mode):
                    continue
                row = records.setdefault((st.st_dev, st.st_ino), [st.st_size, st.st_blocks * 512, []])
                assert row[:2] == [st.st_size, st.st_blocks * 512]
                row[2].append(str(path.relative_to(directory)))
    return [[dev, ino, size, blocks, sorted(names)] for (dev, ino), (size, blocks, names) in sorted(records.items())]

def disk_total(rows):
    assert len({(r[0], r[1]) for r in rows}) == len(rows)
    names = [n for r in rows for n in r[4]]
    assert len(names) == len(set(names))
    return {"files": len(rows), "logical": sum(r[2] for r in rows), "allocated": sum(r[3] for r in rows)}

def expected_native(tables, edited):
    rng = random.Random(20261104)
    results = []
    for i, (size, typ, _) in enumerate(tables):
        words = [rng.randrange(1 << int(typ[1:])) for _ in range(size)]
        if edited and i % 3 == 0:
            words[-1] ^= 1
        value = 1469598103934665603
        for word in words:
            value = ((value ^ word) * 1099511628211) & ((1 << 64) - 1)
        results.append(f"{i} {value:016x}\n")
    return "".join(results).encode()

packet = here / "local-controls.zip"
if args.collect:
    board = args.collect
    g = board / "uniform-grammar-entropy"
    f = board / "uniform-format-guard"
    stable = json.loads((board / "rand-holdout/uniform-storage.json").read_bytes())
    with ZipFile(packet, "x", ZIP_DEFLATED, compresslevel=9) as z:
        z.write(board / "uniform_grammar_entropy.py", "grammar/original-driver.py")
        z.write(board / "uniform_format_guard.py", "format/original-driver.py")
        z.write(board / "runmake-product/candidate/table.rs", "format/template.rs")
        z.write(g / "enrollment.json", "grammar/enrollment.json")
        z.write(g / "verified.json", "grammar/verdict.json")
        z.write(f / "verified.json", "format/verdict.json")
        for arm, role in (("P", "bulk"), ("C", "uniform")):
            work = board / "ordinary-ast-rehearsal" / (role + "-work")
            z.writestr(f"disk/{arm}/ast.json", serialized(measure(work, "target", "shared")))
            for stage in ("check-edited", "check-empty", "build-edited", "build-empty"):
                rows = measure(board / "rand-holdout" / role, stage + "-target", stage + "-shared")
                assert disk_total(rows) == stable[role][stage]["target_and_shared"]
                query = [r for r in rows if any(n.endswith("/query-cache.bin") and "/unicode_names2-" in n for n in r[4])]
                assert disk_total(query) == stable[role][stage]["query_cache"]
                z.writestr(f"disk/{arm}/{stage}.json", serialized(rows))
            for name in ("calls.json", "incorrect.stderr", "incorrect-again.stderr", "typed-hir.stdout", "table"):
                z.write(g / arm / name, f"grammar/{arm}/{name}")
            thir = g / arm / "thir.stdout"
            with thir.open("rb") as body:
                packed = sum(line.count(b"IntArrayLiteral(") for line in body)
            z.writestr(f"grammar/{arm}/thir.json", serialized(dict(bytes=thir.stat().st_size, sha256=digest(thir), packed=packed)))
        reopened = []
        for i, row in enumerate(json.loads((f / "verified.json").read_bytes())):
            work = f / f"empty-{i}"
            exe = work / "target/debug/uniform_guard"
            physical = work.rglob("dep-graph.bin")
            headers = []
            for path in physical:
                with path.open("rb") as src:
                    headers.append(src.read(6).hex())
            if row["empty"]["status"] == 0:
                assert digest(exe) == row["empty"]["elf"]
                p = subprocess.run([exe], capture_output=True, check=True)
                reopened.append({"elf": digest(exe), "stdout": p.stdout.decode(), "headers": sorted(set(headers))})
            else:
                assert not exe.exists()
                reopened.append({"empty_executable_present": False, "headers": sorted(set(headers))})
        z.writestr("format/empty-readback.json", serialized(reopened))

with ZipFile(packet) as z:
    read = lambda path: json.loads(z.read(path))
    assert z.testzip() is None and len(z.namelist()) == len(set(z.namelist()))
    results = read("grammar/verdict.json")
    enrollment = read("grammar/enrollment.json")
    tables = enrollment["tables"]
    assert enrollment["seed"] == 20261104
    assert tables == [[n, t, f] for n in (1023, 1024, 1025) for t in ("u8", "u16", "u32") for f in ("bare", "suffix", "expr", "attr")]
    expected = {stage: expected_native(tables, stage == "edit") for stage in ("old", "edit")}
    assert expected["old"] != expected["edit"]
    assert z.read("grammar/P/typed-hir.stdout") == z.read("grammar/C/typed-hir.stdout")
    for arm in "PC":
        res = results[arm]
        assert read(f"grammar/{arm}/calls.json") == [["old", 0], ["typed-hir", 0], ["thir", 0], ["edit", 0],
            ["incorrect", 1], ["incorrect-again", 1], ["repaired", 0], ["empty", 0]]
        assert res["typed_hir"] == sha(z.read(f"grammar/{arm}/typed-hir.stdout"))
        assert res["packed"] == read(f"grammar/{arm}/thir.json")["packed"] == 6
        for src, raw in expected.items():
            assert sha(raw) == res[src]["stdout"] == enrollment["sources"][src]["stdout"]
        assert res["edit"] == res["empty"] == res["repaired"]
        for name in ("incorrect", "incorrect-again"):
            errors = [json.loads(line) for line in z.read(f"grammar/{arm}/{name}.stderr").splitlines() if line.startswith(b"{")]
            error, = [e for e in errors if (e.get("code") or {}).get("code") == "overflowing_literals"]
            assert [error] == res[name] == results["P"]["incorrect"]
            span, = [s for s in error["spans"] if s["is_primary"]]
            assert [span["byte_start"], span["byte_end"]] == enrollment["sources"]["error"]["bad"] == [152344, 152347]
        native = z.read(f"grammar/{arm}/table")
        assert native.startswith(b"\x7fELF") and sha(native) == res["edit"]["elf"]
        if args.run_native:
            with tempfile.TemporaryDirectory() as work:
                exe = Path(work) / "table"
                exe.write_bytes(native)
                exe.chmod(0o700)
                assert subprocess.check_output([exe]) == expected["edit"]
    v = read("format/verdict.json")
    reopened = read("format/empty-readback.json")
    assert len(v) == len(reopened) == 11
    assert [(r["compiler"], r["type"], r["last"]) for r in v] == [
        ("P","u8","255"), ("C","u8","255"), ("C","u8","254"), ("P","u8","254"),
        ("C","u8","256"), ("P","u8","256"), ("P","u8","253"), ("C","u16","299"),
        ("P","u16","299"), ("C","u8","255"), ("P","u8","255")]
    for row, physical in zip(v, reopened):
        if row["last"] == "256":
            assert row["ordinary"] == row["empty"] == row["repeat"] == {"status":101,"diagnostic":"overflowing_literals","span":[2102,2105]}
            source = z.read("format/template.rs").replace(b"0,254]", b"0,256]")
            assert source[2102:2105] == b"256" and not physical["empty_executable_present"]
        else:
            assert physical["elf"] == row["ordinary"]["elf"] == row["repeat"]["elf"] == row["empty"]["elf"]
            assert row["ordinary"]["output"] == row["empty"]["output"] == row["repeat"]["output"] == row["last"]
            assert physical["stdout"].strip() == row["last"] and row["repeat"]["fresh"]
            epoch = int.from_bytes(bytes.fromhex(physical["headers"][0])[4:6], "little")
            assert len(physical["headers"]) == 1 and bytes.fromhex(physical["headers"][0])[:4] == b"RSIC"
            assert epoch == {"P": 57124, "C": 65135}[row["compiler"]]
    for stage in ("check-edited", "check-empty", "build-edited", "build-empty", "ast"):
        totals = {arm: disk_total(read(f"disk/{arm}/{stage}.json")) for arm in "PC"}
        if stage == "check-edited":
            assert totals["P"] == {"files": 723, "logical": 73123506, "allocated": 74825728}
            assert totals["C"] == {"files": 723, "logical": 69863203, "allocated": 71569408}
        if stage == "ast":
            assert totals["P"] == {"files": 407, "logical": 91663559, "allocated": 92807168}
            assert totals["C"] == {"files": 407, "logical": 91672883, "allocated": 92823552}
        print(stage, totals)
    print("Reopened 36 grammar cases in both compilers and all 11 cross-compiler cases.")
