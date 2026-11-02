"""Check the four original ordinary Cargo clocks, their logs and the admission receipts."""
from pathlib import Path
import hashlib
import json
import tarfile

here = Path(__file__).resolve().parent
origin = json.loads((here / "build-origin.json").read_bytes())
digest = lambda raw: hashlib.sha256(raw).hexdigest()
archive = here / origin["archive"]["file"]
assert archive.stat().st_size == origin["archive"]["bytes"] and digest(archive.read_bytes()) == origin["archive"]["sha256"]
with tarfile.open(archive, "r:xz") as tar:
    assert len(tar.getmembers()) == len(origin["files"]) == 20 and set(tar.getnames()) == set(origin["files"])
    evidence = {}
    for name, rec in origin["files"].items():
        member = tar.getmember(name)
        assert member.isfile() and member.size == rec["bytes"]
        raw = tar.extractfile(member).read()
        assert digest(raw) == rec["sha256"]
        evidence[name] = raw
q = json.loads(evidence["promotion-input.json"])
assert q["role_order"] == ["parent-1", "candidate-1", "candidate-2", "parent-2"] and len(q["visits"]) == 4
assert len({visit["source_A_seed_sha256"] for visit in q["visits"].values()}) == 4
def read(rec):
    raw = evidence[rec["relative_path"]]
    assert digest(raw) == rec["sha256"]
    return raw
for rec in q.values():
    if isinstance(rec,dict) and "relative_path" in rec:
        read(rec)
clocks = {}
for index, role in enumerate(q["role_order"], 1):
    visit = q["visits"][role]
    raw = evidence[visit["receipt_relative_path"]]
    assert digest(raw) == visit["sha256"]
    clock = json.loads(raw)
    stderr = read(visit["raw_cargo_log"])
    native = json.loads(read(visit["native_admission"]))
    assert clock["exit"] == 0 and clock["argv"][1:] == ["build","--locked","--offline","-j8","-p","uv-cli"]
    assert clock["log_bytes"] == len(stderr) and clock["log_sha256"] == digest(stderr) == native["original_stderr"]
    assert clock["elapsed_ns"] == clock["end_monotonic_ns"] - clock["start_monotonic_ns"] == visit["wall_ns"] == native["first_B_ns"]
    assert native["clock"] == visit["sha256"] and native["ordinal"] == index and native["all_native_products"] == 1794
    assert len(native["all_four_A"]) == 4 and native["original_registration"] == q["registration"]["sha256"]
    clocks[role] = clock["elapsed_ns"]
ratios = [clocks[f"candidate-{i}"] / clocks[f"parent-{i}"] for i in (1,2)]
assert q["ratios_candidate_over_parent"] == ratios and json.loads(read(q["raw_panel"]))["ratios_candidate_over_parent"] == ratios
assert q["repeat_10pct_regression_veto"] == all(r >= 1.10 for r in ratios)
for i, ratio in enumerate(ratios, 1):
    print(f"Build hold {i}: {clocks[f'parent-{i}']/1e9:.6f} -> {clocks[f'candidate-{i}']/1e9:.6f} s ({(ratio-1)*100:+.3f}%)")
