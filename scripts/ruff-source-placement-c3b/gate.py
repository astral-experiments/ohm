"""Read the original native controls from their own Actions run before admitting any PMU job."""

import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artifacts
import scope


def check(run, head, dest):
    study = scope.bind()
    binding = json.loads((scope.HERE / "native-enrollment.json").read_bytes())
    # The scoring checkout may be shallow. Fetch the tiny exact Git blob at the
    # original unscored source; never synthesize a prior local commit or event.
    blob = scope.c2_receiver.api(
        f"repos/{scope.base.REPO}/contents/scripts/ruff-source-placement-c3b/three-arm-protocol.json?ref={head}"
    )
    old = base64.b64decode(blob["content"])
    scope.base.need(
        blob["encoding"] == "base64"
        and blob["type"] == "file"
        and 0 < len(old) == blob["size"] < 65536
        and hashlib.sha256(old).hexdigest() == binding["protocol"]
        and old == (scope.HERE / "three-arm-protocol.json").read_bytes(),
        "different native and scored registrations",
    )
    scope.base.need(
        [run, head] == [binding["run"], binding["qa"]]
        and scope.base.sha(scope.HERE / "three-arm-protocol.json") == binding["protocol"]
        and scope.base.sha(scope.HERE / "physical-factory.json") == binding["factory_custody"],
        "not the independently enrolled native study",
    )
    rows = {}
    boots = set()
    kits = {}
    with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as tmp:
        for slot, name in ((1, "option"), (2, "e2e")):
            p = Path(tmp) / f"{slot}.zip"
            receipt = artifacts.receive(
                run, head, "admit", slot, "verified", p, 4 << 20, previous=True
            )
            with zipfile.ZipFile(p) as z:
                scope.base.need(
                    z.namelist() == ["reopened.json"] and z.testzip() is None,
                    "unexpected native projection",
                )
                v = json.loads(z.read("reopened.json"))
            scope.base.need(
                v["new_gate"]["eligible"] is True
                and v["new_gate"]["complete_original_native_and_clean"]
                and v["new_gate"]["prospective"] == binding["protocol"]
                and (v["run"], v["reader_run"], v["qa"], v["reader_qa"], v["stage"], v["slot"])
                == (run, run, head, head, "admit", slot)
                and v["suites"] == [name]
                and v["source"]["C"]["revision"] == scope.C3
                and not any(counts for suite in v["pmu"].values() for counts in suite.values())
                and v["boot"] not in boots
                and v["raw"]["job"] != receipt["job"],
                "native score or actual registration mismatch",
            )
            if slot == 1:
                gate = v["new_gate"]
                scope.base.need(
                    set(study["native"]["C2_native_reference"]["forward"])
                    < set(gate["physical_accepted"])
                    and gate["required_new"] in gate["physical_accepted"]
                    and set(gate["required_ordinary"]) <= set(gate["physical_ordinary"]),
                    "candidate did not improve the registered normal codegen",
                )
            current = {r: {k: x["sha"] for k, x in b.items()} for r, b in v["roles"].items()}
            scope.base.need(
                not kits or kits == current,
                "different physical compilers used by the native admissions",
            )
            kits = current
            boots.add(v["boot"])
            rows[name] = {
                "raw": v["raw"],
                "reader": receipt,
                "boot": v["boot"],
                "gate": v["new_gate"],
                "native_terminal": v["terminal_sha256"],
            }
    scope.base.need(len(boots) == 2, "native boots repeated")
    result = {
        "run": run,
        "qa": head,
        "admissions": rows,
        "kits": kits,
        "protocol": binding["protocol"],
        "new_factory": scope.C3_FACTORY,
        "old_factory": scope.OLD_FACTORY,
    }
    scope.base.save(dest, result)
    return result


if __name__ == "__main__":
    binding = json.loads((scope.HERE / "native-enrollment.json").read_bytes())
    check(int(os.environ["ADMISSION_RUN"]), binding["qa"], Path(sys.argv[1]))
