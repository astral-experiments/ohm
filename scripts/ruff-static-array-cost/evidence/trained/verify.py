"""Replay every original and bind the six independent pairs to the two trained compilers."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile

here = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run-native", action="store_true")
parser.add_argument("--gh-auto", type=Path, help="Check the original artifact digests on GitHub")
args = parser.parse_args()
assert __debug__

def sha(data):
    return hashlib.sha256(data).hexdigest()

def previous_boots():
    """Read the eight original stage 1 machine identities from their preserved ZIP bytes."""
    with ZipFile(here.parent / "originals.zip") as z:
        index = json.loads(z.read("index.json"))
        data = memoryview(z.read("bytes.bin"))
    result = set()
    for study in index["runs"]:
        for record in study["records"]:
            parts = []
            for digest in record["pieces"]:
                offset, size = index["blobs"][digest]
                parts.append(data[offset:offset + size])
            raw = b"".join(parts)
            assert len(raw) == record["original_bytes"] and sha(raw) == record["original_sha256"]
            with ZipFile(io.BytesIO(raw)) as z:
                result.add(json.loads(z.read("host.json"))["boot"])
    assert len(result) == 8
    return result

def verify_compiler(z, role):
    """Match a worker's actual inputs and training records to the signed-file identities."""
    path = "sdk-" + role + "/"
    read = lambda name: json.loads(z.read(path + name + ".json"))
    name = {"P": "parent", "C": "candidate"}[role]
    source = read("source")
    sdk = read("sdk")
    training = read("training")
    bound = transports[role]
    proof = physical[role]
    assert source["role"] == name and source["source"] == reg[name] == proof["source"]
    assert source["tree"] == reg[name + "_tree"] and source["factory"] == bound["qa"]
    assert str(source["run"]) == str(bound["run"])
    assert sdk["driver"] == bound["driver"] == proof["driver"]
    assert proof["cargo"] == sdk["release_cargo"] == reg["release_members"]["bin/cargo"]["sha256"]
    linker = "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
    assert proof["wild"] == sdk["wild"] == reg["release_members"][linker]["sha256"]
    assert z.read(path + "sdk-sha256").decode().strip() == bound["tar"] == proof["tar"]
    config = z.read(path + "bootstrap.toml")
    assert sha(config) == training["config"] == bound["config"]
    assert b'lto = "thin"' in config and b"codegen-units = 1" in config
    assert training["script"] == bound["script"] and training["profiles"] == proof["training_profiles"]
    assert set(training["profiles"]) == {"rustc", "rustdoc", "rustfmt", "clippy"}
    assert all(len(digest) == 64 and size > 0 for digest, size in training["profiles"].values())
    note = bytes.fromhex(proof["bolt_note_hex"])
    assert note and sha(note) == proof["bolt_note_sha256"]
    assert read("probes/verdict")["marked_arrays"] == (4 if role == "C" else 0)

reg_data = (here / "registration.json").read_bytes()
trans_data = (here / "transports.json").read_bytes()
reg = json.loads(reg_data)
transports = json.loads(trans_data)
physical = json.loads((here / "physical.json").read_bytes())
assert transports["P"]["driver"] != transports["C"]["driver"]
assert transports["P"]["config"] == transports["C"]["config"]
assert transports["P"]["script"] == transports["C"]["script"]
seen = previous_boots()
with tempfile.TemporaryDirectory() as temp:
    originals = Path(temp) / "originals"
    cmd = [sys.executable, "-IB", here.parent / "verify.py", here / "originals.zip",
           "--extract-originals", originals]
    if args.run_native:
        cmd.append("--run-native")
    if args.gh_auto:
        cmd.extend(["--gh-auto", args.gh_auto])
    subprocess.run(cmd, check=True)
    paths = sorted(originals.glob("41751693389-rand-B*.zip"))
    assert len(paths) == 6
    for path in paths:
        with ZipFile(path) as z:
            host = json.loads(z.read("host.json"))
            assert host["head"] == "71ee962005d6518812457ef1122712d7f93b196e"
            assert host["registration_sha256"] == sha(reg_data)
            assert host["transports_sha256"] == sha(trans_data)
            assert host["boot"] not in seen
            seen.add(host["boot"])
            for role in ("P", "C"):
                verify_compiler(z, role)
assert len(seen) == 14
print("Verified six trained-compiler pairs on fresh machines and the original eight stage 1 identities.")
