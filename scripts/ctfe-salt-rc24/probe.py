"""Run the upstream PR's five direct cases and an independent Cargo pointer-identity fixture."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess as sp
import sys

out, src, rustup = map(Path, sys.argv[1:4])
role = sys.argv[4]
here = Path(__file__).resolve().parent
registration = json.loads((here / "registration.json").read_bytes())
sha = lambda body: hashlib.sha256(body).hexdigest()
out.mkdir(parents=True)
work = out / "fixture"
work.mkdir()
fixture = src / "tests/run-make/rdr-public-hash-ctfe-literal-identity"
for source in ("lib.rs", "main.rs", "right.rs"):
    shutil.copyfile(fixture / source, work / source)
shutil.copyfile(work / "right.rs", work / "left.rs")
env = dict(os.environ, RUSTUP_HOME=str(rustup))
records = []

def execute(argv):
    result = sp.run(argv, cwd=work, capture_output=True, env=env)
    if result.returncode:
        sys.stderr.buffer.write(result.stderr)
        raise RuntimeError((argv, result.returncode))
    return result.stdout

def observe(label, state, expected):
    # These are the original checked-in run-make compiler flags, outside the ordinary Cargo study.
    argv = ["rustc", "+ohm", "lib.rs", "--crate-name=dep", "--crate-type=rlib",
            "-Cincremental=cache", "-Copt-level=1", "-Zpublic-api-hash", "-Zassert-incr-state=" + state]
    execute(argv)
    execute(["rustc", "+ohm", "main.rs", "--extern", "dep=libdep.rlib"])
    verdict = execute([str(work / "main")]).decode()
    assert verdict == expected
    raw = execute(["rustc", "+ohm", "-Zls=public_hash", "libdep.rlib"])
    (out / (label + ".txt")).write_bytes(raw)
    public, = re.findall(rb"Public hash: ([0-9a-f]+)", raw)
    records.append(dict(label=label, public=public.decode(), native=verdict, elf=sha((work/"main").read_bytes()), argv=argv))
    (out / "direct.json").write_text(json.dumps(records, indent=2) + "\n")
    return raw

before = observe("original", "not-loaded", "Or Or true 17\n")
left = work / "left.rs"
left.write_text(left.read_text().replace("FloorDiv,", "FloorDiv, LShift,").replace("Operator::Or", "Operator::LShift"))
warm = observe("edited", "loaded", "LShift Or true 17\n")
shutil.rmtree(work / "cache")
empty = observe("empty", "not-loaded", "LShift Or true 17\n")
lib = work / "lib.rs"
lib.write_text(lib.read_text().replace("[&FIRST, &FIRST, &SECOND]", "[&FIRST, &SECOND, &SECOND]"))
changed = observe("pointer", "loaded", "LShift Or false 17\n")
shutil.rmtree(work / "cache")
assert changed == observe("pointer-empty", "not-loaded", "LShift Or false 17\n")
assert before != empty and empty != changed and (warm == empty) == (role == "candidate")

pointer = here / "public_pointer_guard.py"
assert sha(pointer.read_bytes()) == registration["pointer_guard_sha256"]
guard = out / "cargo"
guard.mkdir()
shutil.copyfile(pointer, guard / pointer.name)
sp.run([sys.executable, "-IB", guard / pointer.name, role, rustup], env=env, check=True)
result = guard / "public-pointer-guard" / role / "result.json"
shutil.copyfile(result, out / "pointer-result.json")
j = json.loads(result.read_bytes())
assert registration[role] in j["rustc"]
rows = j["records"]
assert len(rows) == 8
assert all(row["edit"]["elf"] == row["empty"]["elf"] for row in rows if "edit" in row)
assert all(row["edit"]["public_hash"] == row["empty"]["public_hash"] for row in rows if "edit" in row)
assert len({r["edit"]["public_hash"] for r in rows[:5]}) == 5
assert rows[5]["edit"]["public_hash"] != rows[0]["edit"]["public_hash"]
assert rows[-1]["edit"]["public_hash"] == rows[0]["edit"]["public_hash"]
assert all(c["status"] == 101 and "E0308" in c["codes"] for c in rows[-2]["attempts"])
print("Accepted original literal edit and independent pointer identities", role, flush=True)
