"""Bind the three accepted native gates and all prior source-study boots without using any clocks."""

from hashlib import sha256
import json
from pathlib import Path
import sys
import uuid
from zipfile import ZipFile


def digest(file):
    return sha256(file.read_bytes()).hexdigest()


def projection(file, name="reopened.json"):
    with ZipFile(file) as z:
        return json.loads(z.read(name))


def build(native_run, original_six, qa, out):
    result = json.loads((native_run / "recomputed.json").read_bytes())
    study = json.loads((qa / "selected-study.json").read_bytes())
    admissions = result["admissions"]
    assert result["protocol"] == digest(qa / "selected-study.json")
    assert study["source"]["Stock4"] == "fba2663650927209e3589fdc807194f66271bd5a"
    assert result["new_factory"] == 41510486074 and result["old_factory"] == 41492092582
    assert result["run"] == 41556515852 and result["qa"] == "fb2ea0a339a9dcef0011b2f1828b5b7c7531795d"
    assert all(v["eligible"] and v["baseline_and_empty"] for v in admissions.values())
    assert result["migration"]["verified"]
    boots = {}

    def add(boot, label, run=None):
        key = str(uuid.UUID(boot))
        assert key == boot
        item = boots.setdefault(key, dict(boot=key, studies=[]))
        entry = dict(study=label, acquisition=run)
        if entry not in item["studies"]:
            item["studies"].append(entry)

    for k in ("option", "e2e"):
        add(admissions[k]["boot"], "corrected-source-native-" + k, result["run"])
    add(result["migration"]["boot"], "corrected-source-live-migration", result["run"])
    for history, run in (("refused-first-stage", 41505848219), ("constructor-fba26636", 41510486074)):
        add(projection(qa / "evidence" / history / "original.zip", "entry.json")["boot"], history, run)

    original_forbid = None
    for slot in range(1, 7):
        f = original_six / ("placement-three-verified-" + str(slot) + ".zip")
        actual = projection(f)
        assert (actual["run"], actual["qa"], actual["slot"]) == (
            41501796384, "ece4528e7e0e2d35a8fb4072fcb54ec7a245f5a8", slot)
        assert original_forbid is None or original_forbid == actual["forbidden_boots"]
        original_forbid = actual["forbidden_boots"]
        add(actual["boot"], f"earlier P/C2/C3b slot {slot}", actual["run"])
    for boot in original_forbid:
        add(boot, "excluded by all six earlier source-workflow blocks")
    assert len(boots) == 19
    external = json.loads((native_run / "published.json").read_bytes())["external_reader"]
    assert external["run"] != result["run"] and external["archive"] == result["migration"]["reader"]
    fields = {"schema": "separate-fixed-source-hardware-admission",
              "run": result["run"], "qa": result["qa"], "protocol": result["protocol"],
              "factory_custody": digest(qa / "physical-factory.json"),
              "reopened_native_decision": digest(native_run / "recomputed.json"),
              "original_archive_metadata": digest(native_run / "published.json"),
              "source": study["source"], "previous_excluded": [boots[b] for b in sorted(boots)],
              "independent_migration_reader": external,
              "previous_observations_admitted": 0}
    data = (json.dumps(fields, indent=2, sort_keys=True) + "\n").encode()
    if out.exists():
        assert out.read_bytes() == data
    else:
        with out.open("xb") as f:
            f.write(data)


if __name__ == "__main__":
    build(*(Path(p).resolve() for p in sys.argv[1:]))
