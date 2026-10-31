"""Verify that unchanged, repaired, malformed and lower-priority outcomes cannot be substituted."""

from copy import deepcopy
from pathlib import Path
import argparse
import json
import sys
import zipfile
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import confirm_binding as registration
import media
import physical as p


def refused(func, expected):
    try:
        func()
    except ValueError as error:
        if expected in str(error):
            return expected
        raise
    raise AssertionError("incorrect output accepted")


def exercise(path, ruff):
    case = json.loads((registration.INPUTS / "pilots.json").read_bytes())["runs"]["E"]["hosts"][
        "01"
    ]
    media.verify(path, case)
    _, parsers = p.corpus.source(ruff)
    with zipfile.ZipFile(path) as z:
        en = p.top(z, "enrollment.json")
        role = {"E": p.read(z, "sdk", "E.json")}
        env = p.active(z, "clean/Eon", "Eon", role, en["E"]["qualified"]["manifest"])
        args = ("Eon", "ordinary", "unchanged-B", "B", env, parsers)
        prefix = "ordinary/Eon/main/unchanged-B"
        baseline, _ = p.operation(z, "clean/Eon/B", "Eon", "clean", "cold-B", "B", env, parsers)
        p.operation(z, prefix, *args, baseline)
        found = {}
        for part in ("cli", "reader"):
            wrong = deepcopy(baseline)
            wrong["native"][part]["whole"] = "0" * 64
            found["incorrect_" + part] = refused(
                lambda: p.operation(z, prefix, *args, wrong), "does not match independent"
            )
        original = p.read

        def swapped(z_, at, name):
            row = original(z_, at, name)
            if at == "ordinary/Eon/main/invalid" and name == "diagnostics.json.gz":
                return []
            if at == "ordinary/Eon/same/same-edit" and name == "28233.json":
                row["case"]["exit"] = 1
            return row

        with patch.object(p, "read", swapped):
            found["discarded_real_error"] = refused(
                lambda: p.operation(
                    z,
                    "ordinary/Eon/main/invalid",
                    "Eon",
                    "ordinary",
                    "invalid",
                    "B",
                    env,
                    parsers,
                    baseline,
                ),
                "genuine bad edit missing",
            )
            found["old_parser_after_real_edit"] = refused(
                lambda: p.operation(
                    z,
                    "ordinary/Eon/same/same-edit",
                    "Eon",
                    "ordinary",
                    "same-edit",
                    "A-edit",
                    env,
                    parsers,
                ),
                "different real syntax-case",
            )
        original_read = p.replay_controls.read

        def wrong_provider(z_, at, name):
            row = original_read(z_, at, name)
            if at == "providers/Eon/provider-Eon" and name == "result.json":
                row["invalid"]["exit"] = 0
            return row

        with patch.object(p.replay_controls, "read", wrong_provider):
            found["using_old_native_result_on_malformed"] = refused(
                lambda: p.replay_controls.native_provider(z, "Eon"), "changed/corrupt native object"
            )
        return {
            "official_zip": case["sha256"],
            "rejected": found,
            "original_warm_clean_matched": True,
        }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("e_original", type=Path)
    cli.add_argument("ruff", type=Path)
    a = cli.parse_args()
    print(json.dumps(exercise(a.e_original, a.ruff), sort_keys=True, indent=2))
