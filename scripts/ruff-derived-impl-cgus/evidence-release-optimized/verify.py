"""Reopen the complete original reader packet and independently compute each whole and rustc price."""
from pathlib import Path
import hashlib
import io
import json
import subprocess
import sys
import zipfile

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent))
import reopen

def digest(data):
    return hashlib.sha256(data).hexdigest()

def result():
    packet = here / "checked-originals.zip"
    assert digest(packet.read_bytes()) == "c1ee299603a9e867f5919bfb07519189c4d47e40666ef41c1149ce3c6be34045"
    roles = json.loads((here.parent / "release-transports.json").read_bytes())
    bindings = {"28392": (13284693124, "75828e493eba33904de6a3c997aa0f6f4c015070565292c08a2dc23fa2cd1692"), "26372": (13285456011, "ceee343b2be7ad2ecfeea52986c0ff9878e3154c4d5424a99e6f3b74c36a85fd")}
    cases = {}
    with zipfile.ZipFile(packet) as full, zipfile.ZipFile(io.BytesIO(full.read("raw-hardware-and-controls.zip"))) as raw:
        for case, binding in bindings.items():
            observed = json.loads(full.read(case + ".json"))
            source = json.loads(full.read(case + "-binding.json"))
            assert source["run"] == 41746716369 and source["head"] == "c688d2d522196f3b7c6e9fc386dce3c25598c600"
            assert (source["original"], source["sha256"]) == binding and observed["sha256"] == binding[1]
            prices = {}
            for role in "PC":
                prefix = case + "/" + role + "/"
                measured = observed["roles"][role]
                assert measured["driver"] == roles[role]["driver"]
                whole = {}
                for stage, expected in measured["ordinary"].items():
                    event = json.loads(raw.read(prefix + stage + "/hardware.json"))
                    assert event["enabled"] == event["running"] > 0 and event["status"] == 0 and event["instructions"] == expected > 0
                    whole[stage] = event["instructions"]
                clocks = reopen.lifetimes(raw, prefix + "observed-edit/kernel-execs")
                clocks = json.loads(json.dumps(clocks))
                assert all(clocks[key] == measured["lifetime"][key] for key in ("whole", "rustcs", "wild"))
                lib, = [row[2] for row in clocks["rustcs"] if row[:2] == ["ruff", "lib"]]
                assert lib == measured["lifetime"]["lib"]
                for stage in ("old-unchanged", "edited-unchanged"):
                    quiet = reopen.lifetimes(raw, prefix + stage + "/kernel-execs")
                    assert quiet["rustcs"] == quiet["wild"] == []
                typed = json.loads(full.read(case + "-typed-metadata.json"))[role]["edit vs empty-new"]
                prices[role] = {"whole": whole, "library_rustc": lib, "allocated_edit": measured["storage"]["edit"]["allocated_unique"],
                                "native_elf": measured["elf"], "changed_clean_public_rows": typed["changed_public_rows"],
                                "changed_clean_required_crates": typed["changed_required"], "changed_native_ruff": measured["transitions"]["lib"]}
            for rows in json.loads(full.read(case + "-changed-object-bindings.json")).values():
                for name, size, sha in rows:
                    assert name.endswith(".o") and 0 < size < 2**24
                    object_bytes = subprocess.check_output(["zstd", "-qdc"], input=full.read("changed-object-originals/" + sha + ".o.zst"))
                    assert object_bytes[:4] == b"\x7fELF" and len(object_bytes) == size and digest(object_bytes) == sha
            p, c = prices["P"], prices["C"]
            saves = {stage: 100 * (1 - c["whole"][stage] / old) for stage, old in p["whole"].items()}
            library = 100 * (1 - c["library_rustc"] / p["library_rustc"])
            assert saves == observed["whole_reduction_pct"] and library == observed["library_rustc_reduction_pct"]
            cases[case] = {"order": observed["order"], "boot": observed["boot"], "whole_reductions_percent": saves,
                           "library_rustc_reduction_percent": library, "roles": prices,
                           "additional_edit_allocation_bytes": c["allocated_edit"] - p["allocated_edit"]}
    return cases

if __name__ == "__main__":
    print(json.dumps(result(), sort_keys=True, indent=1))
