"""Reconstruct the physical feature gate from original independently reopened native projections."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent


def original(path, size, digest):
    raw = path.read_bytes()
    assert len(raw) == size and "sha256:" + sha256(raw).hexdigest() == digest
    with zipfile.ZipFile(path) as z:
        assert z.namelist() == ["reopened.json"] and z.testzip() is None
        return json.loads(z.read("reopened.json"))


def evaluate(predecessor, rows, refs):
    result = {}
    boots = set()
    common = None
    protocol = "61f7cd62c90929d985e9943bfb74a1788bef3e348e032c0ba1afb09b7968e5d7"
    pred = predecessor["durable"]["round-trip"]
    assert predecessor["run"] == 41478151188 and predecessor["reader_run"] == 41484352206
    assert predecessor["source"]["C"]["revision"] == "4e546b27c311f29d99f9528e64420887f57c7538"
    for slot, (s, d) in enumerate(zip(("option", "e2e"), rows, strict=True), 1):
        assert (
            d["run"] == d["reader_run"] == 41495130889
            and d["slot"] == slot
            and d["stage"] == "admit"
        )
        assert d["qa"] == d["reader_qa"] == refs["qa"] == "4b73020e7799d43f448b6ac703d82bb8b923b96b"
        assert d["suites"] == [s] and d["boot"] not in boots and d["boot"] != predecessor["boot"]
        boots.add(d["boot"])
        assert d["source"]["P"]["revision"] == "531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5"
        assert d["source"]["C"]["revision"] == "ed0262f9bdc384576925229764971f23a141c95f"
        kits = {
            role: {k: v["sha"] for k, v in members.items()} for role, members in d["roles"].items()
        }
        assert common is None or common == kits
        common = kits
        assert (
            kits["P"]["driver"]
            == "cb6bd1e8074cfb4c092b270fa1450fcbf59941315615a5af48d537edeaf1933b"
        )
        assert (
            kits["C"]["driver"]
            == "e005172b9c7602695b50b697b7b7cf5b028a97d3de597f2c4a32745d47950674"
        )
        assert all(kits["P"][k] == kits["C"][k] for k in ("cargo", "llvm", "wild"))
        assert all(not x for suite in d["pmu"].values() for x in suite.values())
        gate = d["new_gate"]
        assert gate == refs["gates"][slot - 1] and gate["prospective"] == protocol
        assert gate["complete_original_native_and_clean"] is True and gate["eligible"] is True
        assert d["raw"]["job"] != refs["admissions"][slot - 1]["job"]
        data = d["verdicts"][s]
        native = d["native"][s]
        branches = {}
        for role in ("P", "C"):
            v = data[role]
            n = native[role]
            assert v["invalid"]["error"] == "E0308" and n["invalid"]["compilers"] >= 1
            assert v["old"]["elf"] != v["new"]["elf"] and v["old"]["verdict"] != v["new"]["verdict"]
            assert all(
                v[ph]["elf"] == v["new"]["elf"] and v[ph]["verdict"] == v["new"]["verdict"]
                for ph in ("unchanged", "repair", "clean-new")
            )
            assert all(
                v[ph]["elf"] in d["raw_consumer_bodies"]["native-bodies"]
                for ph in ("old", "new", "repair", "clean-new")
            )
            for ph in ("old", "new", "unchanged", "repair", "clean-new"):
                assert (
                    n[ph]["rss"]["kernel_maxrss_kib"] > 0
                    and n[ph]["disk"]["allocated"]["allocated"] > 0
                )
            api = v["new"]["raw_roster"]
            repeat = v["unchanged"]["raw_roster"]
            if s == "option":
                assert api == {
                    "rustc": [["full", "ruff_workspace", 1]],
                    "linkers": [],
                } and repeat == {"rustc": [], "linkers": []}
                assert set(d["check_handoff"][role]) == {
                    "empty-check-old",
                    "build-after-check-old",
                    "invalid-check-new",
                    "build-after-repair-new",
                    "repeat-build-new",
                }
            else:
                assert api == {
                    "rustc": [["full", "e2e", 1], ["full", "ty_server", 1]],
                    "linkers": [["signed-Wild", "e2e", 1]],
                }
                assert repeat == {
                    "rustc": [["link-only", "e2e", 1]],
                    "linkers": [["signed-Wild", "e2e", 1]],
                }
                assert (
                    v["restored-new"]["elf"] == v["new"]["elf"]
                    and v["old"]["verdict"]["count"] == 151
                    and v["new"]["verdict"]["count"] == 152
                )
                assert (
                    "Name `missing` used when not defined"
                    in v["negative"]["verdict"]["negative_left"]
                    and v["negative"]["elf"] != v["new"]["elf"]
                )
            branches[role] = {
                "old": v["old"]["elf"],
                "changed_and_clean": v["new"]["elf"],
                "edited": api,
                "unchanged": repeat,
            }
        assert branches["P"] == branches["C"]
        result[s] = branches["C"]
        if slot != 1:
            continue
        b = d["durable"]
        x = b["round-trip"]
        front = set(x["new"]["selected"])
        back = set(x["return-old"]["selected"])
        previous = set(pred["new"]["selected"])
        previous_back = set(pred["return-old"]["selected"])
        normal = set(gate["physical_ordinary"])
        assert (
            previous < front and previous_back < back and len(previous) == len(previous_back) == 13
        )
        assert front - previous == {"92ezh47i978bb5yfl2leg6c1y", "bj5a5qap5cgccauttckc1d8ev"}
        assert back - previous_back == {"9z2i9ar8n4enu9f18sb2ij12n"}
        assert (
            set(gate["physical_accepted"]) == front
            and len(front | normal) == 21
            and not front & normal
        )
        assert {"0wrsgo9esbuwdyfhrjd10085r", "6p30kgvj4lu40zowlel28tnn7"} <= normal
        for case, phases in b.items():
            for ph, t in phases.items():
                assert t["CGUs"] == 125 and t["hits"] == len(t["selected"])
                assert (
                    t["reader"]
                    == branches["C"]["old" if ph in ("old", "return-old") else "changed_and_clean"]
                )
        bad = b["object-corrupt"]["new"]
        footer = b["optional-corrupt"]["new"]
        assert set(bad["selected"]) < front and len(front) - len(bad["selected"]) == 1
        assert (
            bad["normal_writes"] == 7 and footer["normal_writes"] == 21 and footer["selected"] == []
        )
        assert x["new"]["normal_writes"] == 6 and x["return-old"]["normal_writes"] == 7
        result["codegen"] = {
            "edited_candidates": 21,
            "physical_placements": len(front),
            "reverse": len(back),
            "clean_objects_per_complete_reference": 125,
            "corrupt_object_placements": len(bad["selected"]),
            "malformed_footer_placements": footer["hits"],
            "forward_additions": sorted(front - previous),
            "reverse_additions": sorted(back - previous_back),
        }
    return result


if __name__ == "__main__":
    refs = json.loads((root / "receipts.json").read_bytes())
    old = refs["predecessor"]
    info = old["reader"]
    pred = original(root / old["file"], info["size_in_bytes"], info["digest"])
    rows = [original(root / r["file"], r["size_in_bytes"], r["digest"]) for r in refs["admissions"]]
    summary = evaluate(pred, rows, refs)
    for i in range(5):
        alter = deepcopy(rows)
        if i == 0:
            alter[0]["durable"]["optional-corrupt"]["new"]["hits"] = 1
        if i == 1:
            alter[0]["durable"]["round-trip"]["new"]["selected"].remove("92ezh47i978bb5yfl2leg6c1y")
        if i == 2:
            alter[1]["verdicts"]["e2e"]["C"]["repair"]["elf"] = "0" * 64
        if i == 3:
            alter[1]["roles"]["C"]["driver"]["sha"] = alter[1]["roles"]["P"]["driver"]["sha"]
        if i == 4:
            alter[1]["verdicts"]["e2e"]["C"]["unchanged"]["raw_roster"]["linkers"] = []
        try:
            evaluate(pred, alter, refs)
        except AssertionError:
            continue
        raise AssertionError("invalid genuine control was accepted")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("Five real-data mutation checks rejected.")
