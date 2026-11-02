"""Close the predeclared triplet using all six separately reopened native archives."""

import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artifacts
import exact_stats
import scope


def decide(rows, study):
    schedule = exact_stats.registered(study)
    need = scope.base.need
    need(
        len(rows) == 6
        and [v["slot"] for v in rows] == list(range(1, 7))
        and len({v["boot"] for v in rows}) == 6,
        "all six independent actual fresh boots in chronological order are required",
    )
    first = rows[0]
    boots = {v["boot"] for v in rows}
    need(
        not boots.intersection(set().union(*(set(v["forbidden_boots"]) for v in rows)))
        and all(
            v["study"] == scope.base.sha(scope.HERE / "three-arm-protocol.json")
            and v["assignment"] == study["blocks"][i]
            and v["source"] == study["source"]
            and v["factory"] == first["factory"]
            and v["kit_products"] == first["kit_products"]
            and v["prior_native"] == first["prior_native"]
            and v["qa"] == first["qa"]
            and v["run"] == first["run"]
            for i, v in enumerate(rows)
        ),
        "study, qualification, physical source or boot repeated or changed",
    )
    sources = {r: {k: x["sha"] for k, x in first["kits"][r].items()} for r in exact_stats.ROLES}
    need(
        all(
            {r: {k: x["sha"] for k, x in v["kits"][r].items()} for r in exact_stats.ROLES}
            == sources
            for v in rows
        )
        and len({v["reader"]["id"] for v in rows}) == len({v["raw"]["id"] for v in rows}) == 6,
        "different physical tools, original or readbacks",
    )
    bounds = {}
    primary = {}
    detail = {}
    for suite in ("option", "e2e"):
        bounds[suite] = {}
        detail[suite] = {}
        for ph in ("old", "new", "unchanged"):
            vals = []
            exposure = []
            for v in rows:
                cell = {}
                native = {}
                for r in exact_stats.ROLES:
                    pm = v["counts"][suite][r][ph]
                    need(
                        pm["status"] == 0
                        and pm["phase"] == ph
                        and pm["enabled"] == pm["running"] > 0
                        and pm["instructions"] > 0
                        and len(pm["raw_sha256"]) == 64,
                        "missing or multiplexed true native hardware count",
                    )
                    n = v["controls"][suite][r][ph]
                    cell[r] = pm["instructions"]
                    native[r] = {
                        "kernel_maxrss_kib": n["rss"]["kernel_maxrss_kib"],
                        "allocated": n["storage"]["allocated"]["allocated"],
                        "optional_tail_bytes": n["storage"]["optional_tail_bytes"],
                        "optional_entries": n["storage"]["optional_entries"],
                        "rows_sha256": n["storage"]["rows_sha256"],
                        "raw_counter_sha256": pm["raw_sha256"],
                        "native_roster": v["native_rosters"][suite][r][ph],
                    }
                vals.append(cell)
                exposure.append(
                    {"slot": v["slot"], "absolute_instructions": cell, "all_roles": native}
                )
            bounds[suite][ph] = exact_stats.endpoint(vals, schedule)
            detail[suite][ph] = exposure
            if suite == "option" and ph == "new":
                primary = {
                    r: bounds[suite][ph]["contrasts"]["P_" + r]["all_over_10_percent"]
                    for r in ("C2", "C3b")
                }
    return {
        "name": study["schema"],
        "source": study["source"],
        "study_sha256": first["study"],
        "qa": first["qa"],
        "run": first["run"],
        "primary_over_10_percent_each_of_6": primary,
        "old_C2_two_pair_2x_screen": False,
        "inference_limits": study["inference"],
        "absolute_and_controls": detail,
        "all_endpoint_estimates": bounds,
        "native_admission": first["prior_native"],
        "roles": sources,
        "slots": [
            {
                "slot": v["slot"],
                "boot": v["boot"],
                "raw": v["raw"],
                "reader": v["reader"],
                "terminal": v["terminal_sha256"],
                "roles": v["assignment"]["roles"],
                "suites": v["assignment"]["suites"],
            }
            for v in rows
        ],
    }


def main():
    study = scope.bind()
    run = int(os.environ["GITHUB_RUN_ID"])
    head = os.environ["GITHUB_SHA"]
    rows = []
    with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as tmp:
        for i in range(1, 7):
            p = Path(tmp) / f"{i}.zip"
            receipt = artifacts.receive(run, head, "three", i, "verified", p, 8 << 20)
            with zipfile.ZipFile(p) as z:
                scope.base.need(
                    z.namelist() == ["reopened.json"] and z.testzip() is None,
                    "extra or corrupt bounded projection",
                )
                v = json.loads(z.read("reopened.json"))
            scope.base.need(
                (v["run"], v["qa"], v["slot"]) == (run, head, i)
                and v["raw"]["job"] != receipt["job"],
                "different original worker or run",
            )
            v["reader"] = receipt
            rows.append(v)
    result = decide(rows, study)
    scope.base.save(Path(sys.argv[1]), result)
    print(
        "All six original boots reopened. Ten-percent option edit tests:",
        result["primary_over_10_percent_each_of_6"],
        flush=True,
    )
    for suite, phases in result["all_endpoint_estimates"].items():
        for ph, value in phases.items():
            print(
                suite,
                ph,
                {n: d["median_savings"] for n, d in value["contrasts"].items()},
                flush=True,
            )


if __name__ == "__main__":
    main()
