"""Recount Cargo product events, settled linker processes, and archive members."""
import collections
import hashlib
import json
from pathlib import Path
import re
import tarfile

ARCHIVE = Path(__file__).with_name("originals.tar.gz")
assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() == "371e998bd0ba166b36b3fe7e2fad7bd89993a8b631ae15ca974acd9a72d579ad"
with tarfile.open(ARCHIVE) as archive:
    originals = {entry.name: archive.extractfile(entry).read() for entry in archive}
assert hashlib.sha256(originals["cases.json"]).hexdigest() == "3b8f6c8e4d740987e6df023b8a8cef59b215c5bcc322f8a7443fff537399f62a"
cases = json.loads(originals["cases.json"])
assert len(cases) == 6
ids = {
    "signed": "2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c",
    "classic": "735e1528ed741015c57676dccf05dbdc0ff7bed1",
    "aware": "c18e91b514b2c4e4966c9ab03232c804af3e1b57",
}
expected_dirty = {("build-script-build", ("custom-build",)), ("unicode_names2", ("lib",))}


def rows(stream):
    records = [json.loads(line) for line in stream.splitlines()]
    assert records[-1] == {"reason": "build-finished", "success": True}
    return [row for row in records if row["reason"] == "compiler-artifact"]


def normalized(members):
    # rustc's third .rcgu.o component is a per-session disambiguator.
    return {
        ".".join(name.split(".")[:2] + name.split(".")[3:]) if name.endswith(".rcgu.o") else name: digest
        for name, digest in members.items()
    }


seen = set()
for case in cases:
    role = case["reader"]
    explicit = "--target" in case["command"]
    assert case["git"] == ids[role] and (role, explicit) not in seen
    seen.add((role, explicit))
    arm = role + ("-explicit-host" if explicit else "-plain")
    cold, first, settled = case["observations"]
    for step, observation in zip(("cold", "first", "settled"), (cold, first, settled)):
        units = rows(originals[f"{arm}/{step}/stdout"])
        assert len(units) == observation["units"] == 17
        dirty = [(r["target"]["name"], tuple(r["target"]["kind"])) for r in units if not r["fresh"]]
        assert dirty == [(n, tuple(kinds)) for n, kinds in observation["dirty"]]
        if step == "cold":
            assert len(dirty) == 17
        else:
            assert set(dirty) == (set() if role == "signed" else expected_dirty)
        assert len(observation["generated"]) == 3 and observation["generated"] == cold["generated"]
    a, b = normalized(first["members"]), normalized(settled["members"])
    assert len(a) == len(b) == 15 and a.keys() == b.keys()
    assert {key for key in a if a[key] != b[key]} == (set() if role == "signed" else {"lib.rmeta-link"})
    print(arm, "17 units; unchanged dirty count", len(dirty))

for role in ("signed", "aware"):
    events = collections.Counter()
    compiles = []
    for name, data in originals.items():
        if not name.startswith(f"kernel/{role}/") or not name.rsplit("/", 1)[1].isdigit():
            continue
        for line in data.decode().splitlines():
            path = re.match(r'execve\("([^"]+)",', line)
            if not path or not line.endswith(" = 0"):
                continue
            exe = Path(path[1]).name
            events[exe] += 1
            if exe == "rustc":
                compiles.append(re.search(r'"--crate-name", "([^"]+)"', line)[1])
    assert events["cargo"] == 2 # rustup proxy and Cargo itself
    assert sorted(compiles) == ([] if role == "signed" else ["build_script_build", "unicode_names2"])
    assert events["ld.bfd"] == (0 if role == "signed" else 1)
    assert len(rows(originals[f"kernel/{role}/jsonl"])) == 17
    print(role, "settled native execve", dict(events))
