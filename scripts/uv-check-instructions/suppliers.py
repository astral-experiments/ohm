"""Check ordered external trait suppliers against fresh lookup across dependency edits."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import tempfile

CONTRACTS = """
pub trait Pick<Tag> { fn pick(&self) -> u32; }
pub struct Item;
pub struct Other;
"""
CONSUMER = """
use contracts::{Item, Pick};
extern crate bridge;
pub fn pick(item: &Item) -> u32 { item.pick() }
"""
# A successful transition seeds the history before each negative transition.
# Left and right use local trait arguments to implement Pick for a foreign receiver.
CASES = [
    ("initial", "Item", "", False, False, ""),
    ("new supplier", "Item", "Item", False, False, "E0283"),
    ("different receiver", "Item", "Other", False, False, ""),
    ("same supplier and receiver kind", "Item", "Item", False, False, "E0283"),
    ("swap the matching supplier", "Other", "Item", False, False, ""),
    ("remove the matching row", "Other", "Other", False, False, "E0599"),
    ("remove the first supplier", "", "Item", False, False, ""),
    ("restore both in reverse order", "Item", "Item", True, False, "E0283"),
    ("keep one in reverse order", "Item", "Other", True, False, ""),
    ("change order only", "Item", "Other", False, False, ""),
    ("change supplier identity", "Item", "Other", False, True, ""),
    ("ambiguity under new supplier identity", "Item", "Item", False, True, "E0283"),
    ("restore initial", "Item", "", False, False, ""),
]

def sha(data):
    return hashlib.sha256(data).hexdigest()

def exercise(rustc, path, public, rotate):
    env = dict(os.environ, RUSTC_BOOTSTRAP="1", CARGO_PKG_VERSION="1.0.0")

    def compile_crate(name, source, deps=(), salt="fixed", extra=()):
        (path / (name + ".rs")).write_text(source)
        cmd = [rustc, name + ".rs", "--crate-type=lib", "--emit=metadata", "--edition=2024",
               "-Zohm-shared-stages", "-Zincremental-verify-ich", "-Cmetadata=" + salt,
               "-Zpublic-api-hash=" + ("yes" if public else "no"), "-Ldependency=.", *extra]
        for dep in deps:
            cmd.extend(["--extern", f"{dep}=lib{dep}.rmeta"])
        proc = subprocess.run(cmd, env=dict(env, CARGO_PKG_NAME=name), cwd=path, capture_output=True)
        if name != "consumer":
            assert proc.returncode == 0, proc.stderr.decode()
        return proc

    compile_crate("contracts", CONTRACTS)
    for i, (change, left, right, reverse, new_id, expected) in enumerate(CASES):
        for label, receiver in [("left", left), ("right", right)]:
            source = "pub struct Tag;\n"
            if receiver:
                source += f"impl contracts::Pick<Tag> for contracts::{receiver} {{ fn pick(&self) -> u32 {{ 1 }} }}"
            salt = "new" if new_id and label == "left" else "fixed"
            compile_crate(label, source, ["contracts"], salt)

        order = ["right", "left"] if reverse else ["left", "right"]
        compile_crate("bridge", "\n".join(f"pub extern crate {x};" for x in order), order)
        observations = []
        for warm in (True, False):
            history = "warm" if warm else f"fresh-{i}"
            state = "loaded" if warm and i else "not-loaded"
            salt = str(i) if rotate else "fixed"
            proc = compile_crate("consumer", CONSUMER, ["contracts", "bridge"], salt, [
                "-Cincremental=" + history, "-Zassert-incr-state=" + state,
            ])
            text = proc.stderr.decode()
            assert proc.returncode == int(bool(expected)), (change, warm, text)
            assert expected in text, (change, expected, text)
            obs = {"exit": proc.returncode, "diagnostics": sha(proc.stderr)}
            if proc.returncode == 0:
                meta = (path / "libconsumer.rmeta").read_bytes()
                obs.update(private=meta[24:40].hex(), public=meta[40:56].hex(), metadata=sha(meta))
            observations.append(obs)
        assert observations[0] == observations[1], (public, rotate, change, observations)
        yield {"case": change, "public_hash": public, "salt_changed": rotate,
               "expected_error": expected, "warm": observations[0], "fresh": observations[1]}

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("rustc", type=Path)
parser.add_argument("--rotate", action="store_true", help="also check a new consumer salt on each edit")
args = parser.parse_args()
result = []
for public in (True, False):
    for rotate in ([False, True] if args.rotate else [False]):
        with tempfile.TemporaryDirectory() as tmp:
            result.extend(exercise(args.rustc.resolve(), Path(tmp), public, rotate))
print(json.dumps(result, indent=2))
