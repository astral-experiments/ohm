"""Reduce the resident compiler fixture report to portable reviewable evidence."""

import argparse
import json
from pathlib import Path


def compact(raw):
    if "uv_revision" in raw:
        return compact_uv(raw)
    result = {}
    for name, suite in raw.items():
        providers = {}
        for _, _, owner, _, typeck, borrowck, pointer in suite["checks"]:
            observation = providers.setdefault(
                owner, {"typeck": [], "borrowck": [], "same_type_result": True}
            )
            observation["typeck"].append(int(typeck))
            observation["borrowck"].append(int(borrowck))
            initial_pointer = observation.setdefault("initial_pointer", pointer)
            observation["same_type_result"] &= initial_pointer == pointer
        for observation in providers.values():
            del observation["initial_pointer"]
        result[name] = {
            "success": suite["success"],
            "required_callers_remained_cached": suite["selectivity_success"],
            "auxiliary_helpers_remained_cached": suite["auxiliary_selectivity_success"],
            "diagnostic_codes": suite["error_codes"],
            "diagnostic_owners": suite["primary_owners"],
            "providers": providers,
        }
    return {
        "kind": "exact patched compiler, one process per fixture",
        "fixtures": result,
    }


def compact_uv(raw):
    constants = {}
    for revision, owner, success, evaluated, allocated in raw["constants"]:
        constants.setdefault(owner, []).append(
            {
                "revision": revision,
                "success": success == "true",
                "evaluation_provider_runs": int(evaluated),
                "allocation_provider_runs": int(allocated),
            }
        )
    cached = {}
    for _, owner, value in raw["unaffected_cached"]:
        cached[owner] = cached.get(owner, True) and value == "true"
    parsers = {}
    if raw.get("checked_parser_borrow"):
        for revision, owner, success, typeck, borrowck, pointer in raw["functions"]:
            if owner not in {"parse_pre", "parse_post"}:
                continue
            parser = parsers.setdefault(
                owner, {"revisions": [], "same_type_result": True}
            )
            initial_pointer = parser.setdefault("initial_pointer", pointer)
            parser["same_type_result"] &= initial_pointer == pointer
            parser["revisions"].append(
                {
                    "revision": revision,
                    "success": success == "true",
                    "type_provider_runs": int(typeck),
                    "borrow_provider_runs": int(borrowck),
                }
            )
        for parser in parsers.values():
            del parser["initial_pointer"]
    fresh = {
        revision: {
            "success": item["success"],
            "diagnostics": [diagnostic["code"] for diagnostic in item["diagnostics"]],
        }
        for revision, item in raw["fresh"].items()
    }
    return {
        "kind": "whole production uv-pep440 library; exact patched compiler",
        "uv_revision": raw["uv_revision"],
        "single_resident_context": len(raw["context"]) == 1,
        "error_counts": {
            revision: int(count) for revision, count in raw["error_counts"]
        },
        "constants": constants,
        "enclosing_parsers": parsers,
        "unaffected_providers_and_pointers_stable": cached,
        "fresh": fresh,
        "raw_diagnostic_snippet_updated": raw.get(
            "diagnostic_excerpt_limitation", {}
        ).get("raw_diagnostic_snippet_updated"),
        "failures": raw["failures"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(compact(json.loads(args.source.read_text())), indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
