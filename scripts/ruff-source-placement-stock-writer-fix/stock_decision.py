"""Report every registered count and both paired contrasts after the two independent native reopens."""

from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stock_scope as scope
import stock_artifacts as artifacts


def summarize(rows, study):
    need = scope.base.need
    scope.schedule(study)
    need(
        len(rows) == 2
        and [r["slot"] for r in rows] == [1, 2]
        and len({r["boot"] for r in rows}) == 2
        and len({r["raw"]["id"] for r in rows}) == 2
        and len({r["reader"]["id"] for r in rows}) == 2,
        "not two distinct physical acquisitions and independent readers",
    )
    excluded = set().union(*(v["forbidden_boots"] for v in rows))
    need(not {v["boot"] for v in rows} & excluded, "previously observed acquisition boot")
    source_hash = {
        r: {k: v["sha"] for k, v in record.items()} for r, record in rows[0]["kits"].items()
    }
    data = []
    for i, row in enumerate(rows):
        need(
            row["assignment"] == study["blocks"][i]
            and row["source"] == study["source"]
            and row["study"] == scope.base.sha(scope.HERE / "selected-study.json")
            and row["run"] == rows[0]["run"]
            and row["qa"] == rows[0]["qa"]
            and row["factory"] == rows[0]["factory"]
            and row["kit_products"] == rows[0]["kit_products"]
            and row["prior_native"] == rows[0]["prior_native"]
            and row["raw"]["job"] != row["reader"]["job"]
            and {r: {k: v["sha"] for k, v in rec.items()} for r, rec in row["kits"].items()}
            == source_hash,
            "different physical product, hardware registration or native eligibility",
        )
        for suite in row["assignment"]["suites"]:
            for phase in ("old", "new", "unchanged"):
                cells = {}
                for role in row["assignment"]["roles"]:
                    pm = row["counts"][suite][role][phase]
                    native = row["controls"][suite][role][phase]
                    rss = native["rss"]
                    disk = native["storage"]
                    need(
                        pm["phase"] == phase
                        and 0 < pm["instructions"]
                        and pm["status"] == 0
                        and pm["enabled"] == pm["running"] > 0,
                        "missing or multiplexed inherited hardware observation",
                    )
                    original = (
                        json.dumps(
                            {
                                k: pm[k]
                                for k in ("pid", "instructions", "enabled", "running", "status")
                            },
                            separators=(",", ":"),
                        )
                        + "\n"
                    ).encode()
                    need(
                        sha256(original).hexdigest() == pm["raw_sha256"],
                        "count differs from the actual physical counter bytes",
                    )
                    cells[role] = {
                        "instructions": pm["instructions"],
                        "raw": pm["raw_sha256"],
                        "kernel_maxrss_kib": rss["kernel_maxrss_kib"],
                        "allocated_bytes": disk["allocated"]["allocated"],
                        "optional_tail_bytes": disk["optional_tail_bytes"],
                        "optional_entries": disk["optional_entries"],
                        "storage_rows_sha256": disk["rows_sha256"],
                        "observed_roster": row["native_rosters"][suite][role][phase],
                    }
                ratios = {}
                for prior in ("P", "C3b"):
                    before = cells[prior]["instructions"]
                    after = cells["Stock4"]["instructions"]
                    ratios[prior] = {
                        "factor": float(Fraction(before, after)),
                        "instruction_reduction_percent": float(
                            100 * Fraction(before - after, before)
                        ),
                        "allocated_change": cells["Stock4"]["allocated_bytes"]
                        - cells[prior]["allocated_bytes"],
                        "kernel_maxrss_kib_change": cells["Stock4"]["kernel_maxrss_kib"]
                        - cells[prior]["kernel_maxrss_kib"],
                    }
                data.append(
                    {
                        "slot": i + 1,
                        "suite": suite,
                        "phase": phase,
                        "cells": cells,
                        "Stock4_vs": ratios,
                    }
                )
    need(
        len(data) == 12 and sum(len(v["cells"]) for v in data) == 36,
        "incomplete native hardware grid",
    )
    return {
        "schema": "two-independent-selected-source-boot-comparisons",
        "run": rows[0]["run"],
        "qa": rows[0]["qa"],
        "study": rows[0]["study"],
        "factories": rows[0]["factory"],
        "sources": study["source"],
        "physical_files": source_hash,
        "previous_gate": rows[0]["prior_native"],
        "measurements": data,
        "count": 36,
        "scored_with_prior_cohort": 0,
        "slots": [
            {k: v[k] for k in ("boot", "slot", "raw", "reader", "terminal_sha256", "assignment")}
            for v in rows
        ],
        "inference": "Two mirrored descriptive pairs. Each full source-built process tree is observed directly; no sampling interval or significance test.",
    }


def main(dest):
    study = scope.bind()
    run, head = int(os.environ["GITHUB_RUN_ID"]), os.environ["GITHUB_SHA"]
    rows = []
    with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as tmp:
        for slot in (1, 2):
            p = Path(tmp) / (str(slot) + ".zip")
            receipt = artifacts.receive(run, head, "three", slot, "verified", p, 4 << 20)
            with zipfile.ZipFile(p) as z:
                scope.base.need(
                    z.namelist() == ["reopened.json"]
                    and z.getinfo("reopened.json").file_size < 4 << 20,
                    "wrong independent source-writer projection",
                )
                v = json.loads(z.read("reopened.json"))
            v["reader"] = receipt
            rows.append(v)
    scope.base.save(dest, summarize(rows, study))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
