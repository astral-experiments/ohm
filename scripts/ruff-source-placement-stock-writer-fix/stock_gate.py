"""Bind the two genuine ordinary admissions and the independently reopened version crossover."""

import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stock_artifacts as artifacts
import stock_scope as scope

need = scope.base.need


def sealed(data, study, *, migration=True):
    ref = study["admissions"]["C3b_native"]
    need(
        data["protocol"] == scope.base.sha(scope.HERE / "selected-study.json")
        and set(data["admissions"]) == {"option", "e2e"}
        and set(data["kits"]) == {"P", "C"}
        and data["new_factory"] == scope.STOCK_FACTORY
        and data["old_factory"] == scope.GUARDED_FACTORY,
        "incomplete physical and native qualification",
    )
    rows = data["admissions"]
    for name, slot in (("option", 1), ("e2e", 2)):
        v = rows[name]
        need(
            v["baseline_and_empty"]
            and v["eligible"]
            and v["boot"] != rows["e2e" if name == "option" else "option"]["boot"]
            and v["raw"]["job"] != v["reader"]["job"]
            and v["raw"]["name"] == artifacts.ARTIFACTS["admit-raw"] + "-" + str(slot)
            and v["reader"]["name"] == artifacts.ARTIFACTS["admit-verified"] + "-" + str(slot),
            "original native and independent readers differ",
        )
    need(
        rows["option"]["forward"] == ref["hit"]["new"]
        and rows["option"]["inverse"] == ref["hit"]["return-old"],
        "selected compiled writer changed the admitted actual normal hit roster",
    )
    if migration:
        m = data["migration"]
        need(
            m["verified"]
            and m["boot"] not in {v["boot"] for v in rows.values()}
            and set(m["results"]) == {"C3b-to-Stock4", "Stock4-to-C3b"}
            and m["raw"]["job"] != m["reader"]["job"]
            and m["victim"] == ref["cross_victim"]
            and all(
                v["remaining_hits"] == 14
                and v["dirty"] == 21
                and v["native_objects"] == 125
                and v["prior_and_foreign_seals"]
                for v in m["results"].values()
            ),
            "missing either true migration",
        )
    return data


def check(run, head, dest, *, previous, migration):
    study = scope.bind()
    if previous:
        frozen = scope.read(scope.HERE / "native-enrollment.json")
        need(
            (run, head) == (frozen["run"], frozen["qa"])
            and frozen["protocol"] == scope.base.sha(scope.HERE / "selected-study.json")
            and frozen["factory_custody"] == scope.base.sha(scope.HERE / "physical-factory.json"),
            "different separately enrolled acceptance",
        )
    rows, kits = {}, {}
    with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as d:
        for group, slot, name in (
            ("admit", 1, "option"),
            ("admit", 2, "e2e"),
            *([("migration", 1, "migration")] if migration else []),
        ):
            path = Path(d) / (name + ".zip")
            receipt = artifacts.receive(
                run, head, group, slot, "verified", path, 4 << 20, previous=previous
            )
            with zipfile.ZipFile(path) as z:
                need(
                    z.namelist() == ["reopened.json"]
                    and z.getinfo("reopened.json").file_size < 4 << 20,
                    "not one bounded independent projection",
                )
                v = json.loads(z.read("reopened.json"))
            if name == "migration":
                need(
                    v["run"] == run
                    and v["qa"] == head
                    and v["source"] == study["source"]
                    and v["counter_samples"] == 0,
                    "different unscored migration",
                )
                cross = {
                    k: v[k]
                    for k in ("verified", "boot", "results", "victim", "raw", "terminal_sha256")
                }
                cross["reader"] = receipt
                continue
            ng = v["new_gate"]
            need(
                (v["run"], v["reader_run"], v["qa"], v["reader_qa"], v["stage"], v["slot"])
                == (run, run, head, head, "admit", slot)
                and v["suites"] == [name]
                and v["source"]["P"]["revision"] == scope.P
                and v["source"]["C"]["revision"] == scope.STOCK
                and not any(x for sw in v["pmu"].values() for x in sw.values())
                and ng["prospective"] == scope.base.sha(scope.HERE / "selected-study.json"),
                "unverified ordinary source, role, or unscored native admission",
            )
            current = {r: {k: x["sha"] for k, x in vals.items()} for r, vals in v["roles"].items()}
            need(not kits or kits == current, "physical SDKs changed between native controls")
            kits = current
            rows[name] = {
                "baseline_and_empty": ng["complete_original_native_and_clean"],
                "eligible": ng["eligible"],
                "boot": v["boot"],
                "raw": v["raw"],
                "reader": receipt,
                "terminal": v["terminal_sha256"],
            }
            if name == "option":
                rows[name].update(forward=ng["physical_accepted"], inverse=ng["physical_reverse"])
    data = {
        "run": run,
        "qa": head,
        "protocol": scope.base.sha(scope.HERE / "selected-study.json"),
        "new_factory": scope.STOCK_FACTORY,
        "old_factory": scope.GUARDED_FACTORY,
        "admissions": rows,
        "kits": kits,
    }
    if migration:
        data["migration"] = cross
    sealed(data, study, migration=migration)
    if dest is not None:
        scope.base.save(dest, data)
    return data


if __name__ == "__main__":
    frozen = scope.read(scope.HERE / "native-enrollment.json")
    check(
        int(os.environ["ADMISSION_RUN"]),
        frozen["qa"],
        Path(sys.argv[1]),
        previous=True,
        migration=True,
    )
