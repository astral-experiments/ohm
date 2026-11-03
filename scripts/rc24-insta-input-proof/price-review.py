"""Reopen precisely one source-registered price cohort, keeping all ordinary controls."""

import argparse
import hashlib
import importlib.util
import json
import statistics
from pathlib import Path


def load(path, name):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def js(path):
    return json.loads(path.read_bytes())


def out(path, x):
    path.write_text(json.dumps(x, indent=2, sort_keys=True) + "\n")


def assess(d, base, source_archive, original, *, migration, archive_boots):
    p = js(d / "pricing.json")
    e = js(d / "expected.json")
    arts = js(d / "artifacts.json")["artifacts"]
    rp = base / "evidence/broad-pilot-41729274046/reopen.py"
    assert hashlib.sha256(rp.read_bytes()).hexdigest() == original["raw_reader"]
    core = load(rp, "original_price_reader")
    records = {}
    sums = {}
    for block, direction in p["orders"].items():
        (art,) = [a for a in arts if a["name"] == f"insta-price-{block}-{e['run']}"]
        assert sha_ok(art) and art["workflow_run"]["id"] == int(e["run"])
        records[block] = core.reopen(d / (block + ".zip"), art, p, e)
        sums[block] = art["digest"]
    boots = [v["boot"] for v in records.values()]
    assert len(set(boots)) == len(boots) and not set(boots).intersection(archive_boots)
    assert len({v["archive_set"] for v in records.values()}) == 1
    keys = list(next(iter(records.values()))["roles"]["parent"]["costs"])
    stages = {}
    for k in keys:
        rows = {}
        for label, v in records.items():
            r = v["roles"]
            pv = r["parent"]["costs"][k]
            cv = r["candidate"]["costs"][k]
            rows[label] = {
                "parent": pv,
                "candidate": cv,
                "ratio": pv / cv,
                "delta": cv - pv,
                "change_percent": 100 * (cv / pv - 1),
            }
        ratios = [x["ratio"] for x in rows.values()]
        stages[k] = {
            "blocks": rows,
            "min_ratio": min(ratios),
            "median_ratio": statistics.median(ratios),
            "max_ratio": max(ratios),
        }
    penalties = {}
    for k in ("check-unchanged", "build-unchanged"):
        bad = [
            label
            for label, x in stages[k]["blocks"].items()
            if x["delta"] > 10_000_000 and x["candidate"] * 100 > x["parent"] * 105
        ]
        # The same named common workflow must repeat the adverse guard in both orders.
        penalties[k] = {
            "adverse": bad,
            "both_orders": len({tuple(p["orders"][label]) for label in bad}) == 2,
        }
    mg = None
    if migration:
        name = f"insta-migration-PC-{e['run']}"
        (ma,) = [a for a in arts if a["name"] == name]
        z = d / "migration-PC.zip"
        assert (
            ma["workflow_run"]["id"] == int(e["run"])
            and ma["size_in_bytes"] == z.stat().st_size
        )
        with z.open("rb") as f:
            assert (
                "sha256:" + hashlib.file_digest(f, "sha256").hexdigest() == ma["digest"]
            )
        mm = load(base / "migration/review.py", "migration_reader")
        mg = mm.review(
            z,
            p,
            source_archive,
            base / "evidence/same-stamp-elf/originals.tar.gz",
            base / "migration/fixture",
        )
    primary = stages["first-unchanged"]
    hold = any(v["both_orders"] for v in penalties.values())
    dec = {
        "stage": p["stage"],
        "blocks": len(records),
        "migration": bool(mg),
        "hold": hold,
        "both_primary_minimum_two": primary["min_ratio"] >= 2,
        "all_primary_improve": primary["min_ratio"] > 1,
        "minimum_primary_ratio": primary["min_ratio"],
        "median_primary_ratio": primary["median_ratio"],
        "penalties": penalties,
    }
    return {
        "expected": e,
        "plan": p,
        "boots": boots,
        "archive_digests": sums,
        "raw": records,
        "stages": stages,
        "migration": mg,
        "gate": dec,
    }


def sha_ok(a):
    return a["digest"].startswith("sha256:") and len(a["digest"]) == 71


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("originals", type=Path)
    ap.add_argument("--suite", required=True, type=Path)
    ap.add_argument("--crate", required=True, type=Path)
    ap.add_argument("--prior-boots", required=True, type=Path)
    ap.add_argument("--migration", action="store_true")
    a = ap.parse_args()
    spec = js(a.suite / "reader-qualification.json")
    result = assess(
        a.originals,
        a.suite,
        a.crate,
        spec,
        migration=a.migration,
        archive_boots=js(a.prior_boots),
    )
    out(a.originals / "verified.json", result)
    print(json.dumps(result["gate"], sort_keys=True))
