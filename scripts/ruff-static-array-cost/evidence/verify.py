"""Reopen each original measurement. Add --run-native to execute the retained Linux programs."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import statistics
import struct
import subprocess
import tempfile
from zipfile import ZipFile

here = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("packet", type=Path, nargs="?", default=here / "originals.zip")
parser.add_argument("--run-native", action="store_true")
parser.add_argument("--extract-originals", type=Path)
parser.add_argument("--gh-auto", type=Path, help="Also check each original artifact's digest on GitHub")
args = parser.parse_args()
assert __debug__
if args.extract_originals:
    args.extract_originals.mkdir(parents=True, exist_ok=False)

def sha(contents):
    return hashlib.sha256(contents).hexdigest()

with ZipFile(args.packet) as packet:
    assert set(packet.namelist()) == {"index.json", "bytes.bin"}
    index = json.loads(packet.read("index.json"))
    data = packet.read("bytes.bin")
chunks = {}
for checksum, (offset, length) in index["blobs"].items():
    chunk = memoryview(data)[offset:offset + length]
    assert len(chunk) == length and sha(chunk) == checksum
    chunks[checksum] = chunk

reg = json.loads((here.parent / "registration.json").read_bytes())
fixture = reg["cases"]["rand"]
aliases = (here / "NameAliases.txt").read_bytes()
assert sha(aliases) == fixture["name_aliases_sha"]
alias_rows = [(row.split(";")[1], int(row.split(";")[0], 16))
              for row in aliases.decode().splitlines() if row and not row.startswith("#")]
assert len(alias_rows) == 481
alias_rows.extend((name, 0xffffffff) for name in ("carriage_return", "Black_Star", "NO SUCH CODE POINT"))
stdin = ("\n".join(name for name, _ in alias_rows) + "\n").encode()

def verify_native_output(raw):
    assert len(raw) == fixture["native_bytes"] and sha(raw) == fixture["new_stdout"]
    pos = 0
    names = {}
    results = []
    while pos < len(raw):
        tag = raw[pos]
        pos += 1
        assert tag in (1, 2)
        if tag == 1:
            cp, = struct.unpack_from("<I", raw, pos)
            pos += 4
        length, = struct.unpack_from("<I", raw, pos)
        pos += 4
        name = raw[pos:pos + length].decode()
        pos += length
        got, = struct.unpack_from("<I", raw, pos)
        pos += 4
        if tag == 1:
            assert 0 <= cp <= 0x10ffff and got == cp and cp not in names
            names[cp] = name
        else:
            results.append((name, got))
    assert pos == len(raw) and len(names) == len(set(names.values())) == 153626
    assert results == alias_rows

def target_counter(z, prefix):
    images = {}
    found = []
    for line in z.read(prefix + "epochs.tsv").decode().splitlines():
        s = line.split()
        if s[0] == "I":
            index = int(s[1])
            argv = z.read(prefix + f"{index:05}.nul").split(b"\0")
            assert argv.pop() == b"" and int(argv[0]) == int(s[2])
            images[index] = (argv, s[-1])
        elif s[0] == "R":
            index, pid, instructions, enabled, running, status = map(int, s[1:])
            argv, origin = images[index]
            assert status == 0 and int(argv[0]) == pid and origin == "exec"
            assert enabled == running > 0 and instructions > 0
            if b"--crate-name" in argv and argv[argv.index(b"--crate-name") + 1] == b"unicode_names2":
                assert argv[3].endswith(b"/sdk/bin/rustc")
                assert b"crates/ruff_unicode_names2/src/lib.rs" in argv and b"-Zlink-only" not in argv
                found.append(instructions)
    target, = found
    return target

boots = set()
seen_native = set()
seen_streams = set()
def verify_job(z, head, label):
    read = lambda path: json.loads(z.read(path))
    host = read("host.json")
    assert host["head"] == head and host["case"] == "rand" and host["boot"] not in boots
    boots.add(host["boot"])
    block = label.split("-")[-1]
    assert host["order"] == (reg["confirmation_orders"][block] if block in reg["confirmation_orders"] else list(block))
    assert read("cargo-inputs.json") == reg["archives"]
    assert len(reg["archives"]) == 502
    calibration = [read(f"calibrate-{kind}.json") for kind in ("single", "fork")]
    assert all(c["status"] == 0 and c["enabled"] == c["running"] > 0 for c in calibration)
    assert 1.99 < calibration[1]["instructions"] / calibration[0]["instructions"] < 2.01
    out = {"P": {}, "C": {}}
    summary = read("result.json")
    for arm, name in (("P", "parent"), ("C", "candidate")):
        assert read(f"sdk-{arm}/source.json")["source"] == reg[name]
        for mode in ("check", "build"):
            counts = summary[arm][mode]
            path = f"{arm}/{mode}/"
            for stage, key in (("cold-old", "cold"), ("ordinary-edit", "whole_edit"),
                               ("unchanged", "unchanged"), ("observed-edit", "observed_whole"),
                               ("empty-new", "empty")):
                pmu = read(path + stage + "/hardware.json")
                assert pmu["status"] == 0 and pmu["enabled"] == pmu["running"] > 0
                assert pmu["instructions"] == counts[key] > 0
            for stage, key in (("observed-edit", "target_rustc"), ("observed-empty-new", "empty_target_rustc")):
                assert target_counter(z, path + stage + "/execs/") == counts[key]
            stages = ["cold-old", "ordinary-edit", "unchanged", "observed-edit", "empty-new", "observed-empty-new"]
            if mode == "build":
                stages.append("repaired")
            v = [read(path + stage + "/result.json") for stage in stages]
            assert v[0]["unit_count"] == len(v[0]["dirty"]) == fixture["old_units"]
            assert v[1]["dirty"] == v[3]["dirty"] == fixture["edit_dirty"] and not v[2]["dirty"]
            assert v[4]["dirty"] == v[5]["dirty"] and len(v[4]["dirty"]) == fixture["new_units"]
            assert v[0]["generated"] == fixture["old_generated"] != fixture["new_generated"]
            assert all(item["generated"] == fixture["new_generated"] for item in v[1:])
            if mode == "check":
                assert len({item["product_sha256"] for item in v[1:]}) == 1
            else:
                assert v[0]["native"]["elf"] != v[1]["native"]["elf"]
                for stage, item in zip(stages, v):
                    elf = z.read(path + stage + "/reader")
                    output = z.read(path + stage + "/native.bin")
                    assert sha(elf) == item["native"]["elf"] and sha(output) == item["native"]["stdout"]
                    if sha(output) not in seen_streams:
                        verify_native_output(output)
                        seen_streams.add(sha(output))
                    if args.run_native and sha(elf) not in seen_native:
                        with tempfile.TemporaryDirectory() as tmp:
                            program = Path(tmp) / "reader"
                            program.write_bytes(elf)
                            program.chmod(0o700)
                            assert subprocess.check_output([program], input=stdin) == output
                    seen_native.add(sha(elf))
                assert all(item["native"] == v[1]["native"] for item in v[1:])
                assert all(item["members"]["verified_renames"] == v[1]["members"]["verified_renames"] for item in v[1:])
                assert len(v[1]["members"]["verified_renames"]) == 15
                errors = read(path + "invalid/error.json")
                assert errors == read(path + "invalid-again/error.json") and any(e["code"]["code"] == "overflowing_literals" for e in errors)
            out[arm][mode] = counts
    return out

for study in index["runs"]:
    rows = []
    for record in study["records"]:
        raw = b"".join(chunks[key] for key in record["pieces"])
        digest = sha(raw)
        assert len(raw) == record["original_bytes"] and digest == record["original_sha256"]
        if args.gh_auto:
            gh = subprocess.check_output([args.gh_auto, "api", f"repos/astral-experiments/ohm/actions/artifacts/{record['artifact']}"])
            official = json.loads(gh)
            assert official["digest"] == "sha256:" + digest and official["workflow_run"]["id"] == study["run"]
        if args.extract_originals:
            (args.extract_originals / f"{study['run']}-{record['label']}.zip").write_bytes(raw)
        with ZipFile(io.BytesIO(raw)) as z:
            assert z.testzip() is None
            rows.append(verify_job(z, study["head"], record["label"]))
    save = lambda row, mode, key: 1 - row["C"][mode][key] / row["P"][mode][key]
    for mode in ("check", "build"):
        for key in ("target_rustc", "whole_edit", "empty_target_rustc", "cold", "empty", "unchanged"):
            changes = [save(row, mode, key) for row in rows]
            print(study["run"], mode, key, f"median {100*statistics.median(changes):.3f}% (range {100*min(changes):.3f}%..{100*max(changes):.3f}%)")
    primary = [save(r, "check", "target_rustc") for r in rows]
    if len(rows) == 2:
        assert min(primary) >= .20
    else:
        assert len(rows) == 6 and min(primary) > 0 and statistics.median(primary) >= .20
        print("Six favorable independent pairs. Exact two-sided sign p=0.03125.")
print("Original measurements verified on", len(boots), "boots;", len(seen_native), "distinct Linux executables.")
