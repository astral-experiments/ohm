"""Read evidence from corresponding physical compiler visits at the two source revisions."""

import gzip
import hashlib
import json
import re


def read(path):
    return json.loads(path.read_bytes())


NATIVE = re.compile(r"([a-z][a-z0-9_]*-[0-9a-f]{16}\.[a-z0-9]{25})(?:\.[a-z0-9]{7})?\.rcgu\.o")


def key(member):
    match = NATIVE.fullmatch(member)
    if not match:
        raise ValueError(("unknown projected object name", member))
    return match[1]


def inventory(path):
    objects = {}
    for archive, rows in read(path).items():
        for member, sha in rows.items():
            if not NATIVE.fullmatch(member):
                continue
            ref = key(member)
            if ref in objects and objects[ref]["hash"] != sha:
                raise ValueError(("ambiguous object identity", archive, member))
            objects[ref] = {"archive": archive, "member": member, "hash": sha}
    return objects


def decide(out, reports):
    result = {}
    for role, history in reports.items():
        warm, clean = out/f"{role}-edit", out/f"{role}-clean"
        phases = {**{p.name: p for p in warm.iterdir() if p.is_dir()},
                  **{p.name: p for p in clean.iterdir() if p.is_dir()}}
        for label, row in history.items():
            assert row == read(phases[label]/"case.json")
            assert row["kernel"] == hashlib.sha256((phases[label]/"kernel.json").read_bytes()).hexdigest()
        inventories = {v["verdict"]["test_list"] for v in history.values() if "verdict" in v}
        assert len(inventories) == 1 and history["negative"]["verdict"]["exit"] == 101
        assert all(v["verdict"]["exit"] == 0 for k,v in history.items() if k != "negative" and "verdict" in v)
        old = inventory(warm/"empty_old/objects.json")
        new = inventory(warm/"edit/objects.json")
        fresh = inventory(clean/"empty_new/objects.json")
        observed = {}
        for name in history["edit"]["admitted"]:
            k = key(name)
            assert k in old and k in new and k in fresh, ("missing physical archive member", k)
            assert new[k]["hash"] == fresh[k]["hash"], ("incorrect warm CGU", name, new[k], fresh[k])
            witness = out/"native-witnesses"/(new[k]["hash"]+".o.gz")
            assert hashlib.sha256(gzip.decompress(witness.read_bytes())).hexdigest() == fresh[k]["hash"]
            observed[name] = {"old": old[k], "warm": new[k], "clean": fresh[k]}
        if role == "P":
            assert not observed and not history["return_old"]["admitted"]
        assert history["edit"]["sites"] == history["empty_new"]["sites"], "different debugger output for the warm edit"
        assert history["return_old"]["sites"] == history["empty_old"]["sites"], "different debugger output for reverse edit"
        shifted = []
        for before, after in zip(history["empty_old"]["sites"], history["empty_new"]["sites"], strict=True):
            for a in before["records"]:
                for b in after["records"]:
                    if b[0] - a[0] == 246 and a[1:3] == b[1:3] and a[2] is not None:
                        shifted.append([a, b])
        pm = read(clean/"score_new/pmu.json")
        assert pm["enabled"] == pm["running"] > 0 and pm["instructions"] > 0 and pm["status"] == 0
        result[role] = {"admitted": observed, "shifted_sites": shifted,
                        "same_full_test_executable": history["edit"]["verdict"]["binary"] == history["empty_new"]["verdict"]["binary"],
                        "same_inventory": inventories.pop(), "instructions": pm["instructions"],
                        "edited_roster": history["edit"]["calls"], "repeat_roster": history["unchanged"]["calls"],
                        "storage": read(warm/"edit/storage.json")["allocated"],
                        "optional_bytes": history["edit"]["placement_bytes"]}
    assert result["P"]["same_inventory"] == result["C"]["same_inventory"]
    return {"roles": result, "qualified_for_replication": bool(result["C"]["admitted"]) and all(
        r["same_full_test_executable"] and r["shifted_sites"] for r in result.values()),
        "scope": "One prospective P then C diagnostic pair. No significance claim."}
