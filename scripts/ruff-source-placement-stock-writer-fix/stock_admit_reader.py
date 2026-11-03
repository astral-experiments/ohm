"""Independently reopen the complete physical C3b source, native, consumer and refusal proofs."""

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stock_artifacts as artifacts
import stock_footer as footer
import stock_scope as scope
import readback as original


def extra(z, result, slot, study):
    proof = original.read(z, "physical/selected-native-gate.json")
    scope.base.need(
        proof
        == {
            "schema": "Stock4-native-v1",
            "slot": slot,
            "previous_operator": scope.base.sha(scope.ORIGINAL / "protocol.json"),
            "prospective": scope.base.sha(scope.HERE / "selected-study.json"),
            "packet": scope.base.sha(scope.HERE / "source-packet.json"),
            "complete": result["terminal_sha256"],
            "actual_factory": scope.STOCK_FACTORY,
            "source": result["source"],
            "boot": result["boot"],
        },
        "different independently registered native eligibility",
    )
    reach = {
        "complete_original_native_and_clean": True,
        "prospective": proof["prospective"],
        "eligible": True,
    }
    if slot == 1:
        folder = "physical/option/C-edit/new"
        traces = [
            p for p in z.namelist() if re.fullmatch(re.escape(folder) + r"/trace/exec\.\d+", p)
        ]
        sdk = original.read(z, "physical/physical-roles.json")["sdk"]
        placed, emitted = original.selection_read(z, folder, traces, sdk)
        take = lambda rows: {v["cgu"] for v in rows if v["owner"] == "ruff_workspace"}
        hits, misses = take(placed), take(emitted)
        ref = study["admissions"]["C3b_native"]
        controls = result["durable"]
        reverse = controls["round-trip"]["return-old"]
        chosen = ref["cross_victim"]
        ok = (
            not (hits & misses)
            and len(hits | misses) == ref["dirty_total"]
            and set(ref["hit"]["new"]) == hits == set(controls["round-trip"]["new"]["selected"])
            and set(ref["hit"]["return-old"]) == set(reverse["selected"])
            and all(
                controls["round-trip"][ph]["CGUs"] == ref["total_owner_CGUs"]
                for ph in ("old", "new", "return-old")
            )
            and controls["optional-corrupt"]["new"]["hits"] == 0
            and set(controls["object-corrupt"]["new"]["selected"]) == hits - {chosen}
        )
        reach.update(
            eligible=ok,
            physical_accepted=sorted(hits),
            physical_ordinary=sorted(misses),
            physical_reverse=sorted(reverse["selected"]),
            cross_victim=chosen,
        )
    return reach


def reopen(slot, path):
    study = scope.bind()
    run = int(os.environ["GITHUB_RUN_ID"])
    head = os.environ["GITHUB_SHA"]
    with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as d:
        p = Path(d) / "original.zip"
        r = artifacts.receive(run, head, "admit", slot, "raw", p, 6 << 30)
        with zipfile.ZipFile(p) as z, scope.product("Stock4") as reg, ExitStack() as stack:
            stack.enter_context(patch.object(original, "enrollment", lambda: reg))
            stack.enter_context(patch.object(original.receiver, "FACTORY", scope.STOCK_FACTORY))
            stack.enter_context(patch.object(original.receiver, "FACTORY_QA", scope.STOCK_QA))
            stack.enter_context(patch.object(original.storage, "parse_footer", footer.parse))
            result = original.scan(z, run, head, "admit", slot)
            result["new_gate"] = extra(z, result, slot, study)
        result["raw"] = r
        result["reader_run"] = run
        result["reader_qa"] = head
        scope.base.save(path, result)
        print(
            "Complete independent selected native verdict:",
            slot,
            result["new_gate"]["eligible"],
            flush=True,
        )


if __name__ == "__main__":
    reopen(int(sys.argv[1]), Path(sys.argv[2]))
