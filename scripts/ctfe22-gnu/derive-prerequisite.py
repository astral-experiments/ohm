"""Check the source, four real-edit openings, eight cold counts and four ordinary build visits before the GNU build."""
from hashlib import sha256
import json
from pathlib import Path
import sys


PROTOCOL = "b2801bb8a8f30b4facd5cc4c1a7b0b9142a7841906f17fd241629504a9273ab2"
COMMITS = {"parent": "b9b3f6bba90145e25eb3b76864cfd0b5f4cbdc1f", "candidate": "bd03d5709719c5f0712f84573faa01b943f68cb8"}
UNITS = {"uv_cache", "uv_client", "uv_configuration", "uv_distribution_types", "uv_install_wheel", "uv_metadata", "uv_pypi_types", "uv_torch"}
ORDER = ["parent-1", "candidate-1", "candidate-2", "parent-2"]
CARGO = "3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871"


def verified(q, source):
    assert source["source"]["commit"] == q["production_candidate"] == "ac67101cb973e35ce8ff044cc8014c2c76bab69e"
    assert source["stage1_protocol"] == q["protocol"] == PROTOCOL and source["stage1_source"] == COMMITS["candidate"]
    assert source["format_versions"] == {"incremental": [43317, 43319], "metadata": [3, 43319]}
    assert source["pack_objects"] == 36 and source["pack_sha256"] == "b9b10f402d97b0a46cbafe79e72e467d0b034694e0eb41d40bfbe02e1167055b"
    assert q["order"] == ORDER and set(q["warm"]) == set(q["build_ns"]) == set(ORDER)
    assert set(q["cold"]) == {n + "-" + s for n in ORDER for s in ("A", "B")}
    samples, commands, slots = set(), {}, []
    for name in ORDER:
        w = q["warm"][name]
        role, hold = name.split("-")
        assert (w["role"], w["hold"], w["rustc"], w["cargo"], w["protocol"]) == (role, int(hold), COMMITS[role], CARGO, PROTOCOL)
        assert set(w["measurements"]) == UNITS
        assert w["sum"] == sum(i["Ir"] for i in w["measurements"].values())
        for unit, item in w["measurements"].items():
            assert item["Ir"] > 0 and item["raw_bytes"] > 1024 and item["raw_sha256"] not in samples
            assert len(bytes.fromhex(item["raw_sha256"])) == 32 and item["argc"] > 20
            samples.add(item["raw_sha256"])
            assert commands.setdefault(unit, item["argv_sha256"]) == item["argv_sha256"]
        if role == "candidate":
            si = w["six"]["slots"]
            assert len(si) == 6 and len({a for a,b in si.values() if a == b and a >= 2**31}) == 6
            slots.append(si)
        else:
            assert w["six"] is None
        assert type(q["build_ns"][name]) is int and q["build_ns"][name] > 0
        for state in ("A", "B"):
            c = q["cold"][name + "-" + state]
            assert (c["role"], c["hold"], c["state"], c["commit"]) == (role, int(hold), state, COMMITS[role])
            assert c["externs"] == 58 and c["sdk"] == w["sdk_receipt"] and c["Ir"] > 0
            assert len(c["native_outputs"]) == 2 and c["graph"] not in samples and len(bytes.fromhex(c["graph"])) == 32
            samples.add(c["graph"])
            assert commands.setdefault("cold", c["argv"]) == c["argv"]
    assert slots[0] == slots[1] and len(samples) == 40
    for hold in ("1", "2"):
        p, c = [q["warm"][r + "-" + hold] for r in ("parent", "candidate")]
        assert c["measurements"]["uv_client"]["Ir"] * 10 <= p["measurements"]["uv_client"]["Ir"] * 9 and c["sum"] < p["sum"]
    for state in ("A", "B"):
        pairs = [[q["cold"][r+"-"+i+"-"+state]["Ir"] for r in ("parent","candidate")] for i in ("1","2")]
        assert not all(c * 100 > p * 102 for p,c in pairs)
    assert not all(q["build_ns"]["candidate-"+i] * 10 >= q["build_ns"]["parent-"+i] * 11 for i in ("1","2"))
    assert len(set(q["build_admission"].values())) == 4 and all(len(bytes.fromhex(v)) == 32 for v in q["build_admission"].values())
    assert set(q["build_admission"]) == set(ORDER)
    for name in ("warm_originals", "two_history_lookups", "cold_originals", "build_original_panel", "build_final_oracle"):
        assert len(bytes.fromhex(q["evidence"][name])) == 32
    assert q["evidence"]["warm_originals"] == "79449070fe59baae71132e6e1855f3c1e393476b75b9591b747dd6318839e1cb"
    assert q["evidence"]["two_history_lookups"] == "462b68836c2f440388f8e01ff9d9df6e875037a86046a75b1cc96623cad39320"
    assert q["hardware_status"] == "unmeasured"


if __name__ == "__main__":
    packet = Path(sys.argv[1])
    source = json.loads((Path(__file__).parent / "derive-source.json").read_bytes())
    data = packet.read_bytes()
    assert sha256(data).hexdigest() == source["derive_screen_sha256"]
    verified(json.loads(data), source)
    print("Verified 32 edited compiler counts, eight cold terminal counts and four first-edit ordinary build visits.")
