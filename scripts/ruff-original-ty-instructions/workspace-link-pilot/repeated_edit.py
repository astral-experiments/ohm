"""Compare the genuine second edit's physical source decisions with both signed histories."""

import gzip, hashlib, json, sys
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
FORECAST_SHA = "053891f28aa18f5c90819fd65ea5cecf3b99358b8bc106e9a5c88f21e85c424d"


def reopen(archive, expected, release):
    seed = (
        HERE / "evidence/full-native-challenge/prospective-second-edit.json"
    ).read_bytes()
    assert hashlib.sha256(seed).hexdigest() == FORECAST_SHA
    proposed = json.loads(seed)["cases"][str(release)][
        "forecast_if_same_native_inputs_and_groups"
    ]
    assert len(proposed) == len(set(proposed)) == 32
    with archive.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == expected
    with ZipFile(archive) as z:

        def j(name):
            b = z.read(name)
            return json.loads(gzip.decompress(b) if name.endswith(".gz") else b)

        def brief(tag):
            return j(tag + "-receipt.json.gz")

        old = "C-ordinary-repeat-old"
        new = "C-ordinary-repeat-edit"
        oldreport = j(old + "/physical-decisions.json")
        newreport = j(new + "/physical-decisions.json")
        subset = set(j("admission.json")["roles"])
        assert len(subset) == 48
        decisions = {}
        now = newreport["actors"]
        prev = oldreport["actors"]
        assert set(now) | set(newreport["proof_refusals"]) == subset
        registered = (
            "P-ordinary-repeat-old",
            "P-ordinary-repeat-edit",
            "P-empty-new",
            "C-empty-new",
            old,
            new,
        )
        refs = {t: brief(t)["published"] for t in registered}
        assert len(refs["P-empty-new"]) == 50 and all(
            v.keys() == refs["P-empty-new"].keys() for v in refs.values()
        )
        for k in sorted(subset):
            c = now.get(k)
            p = prev.get(k)
            row = {
                "previous_source_action": p["action"] if p else "full-parse-refusal",
                "actual_source_action": c["action"] if c else "full-parse-refusal",
                "prospective": k in proposed,
                "complete_elf_sha256": {tag: r[k] for tag, r in refs.items()},
            }
            if c:
                row.update(
                    prior=c["prior"] and c["prior"]["key"],
                    key=c["key"],
                    allowed=c["allowed"],
                    response=c["response"],
                    reasons=c["reasons"],
                    direct_donor_stage=c.get("from_full_stage"),
                    changed_parts=(
                        sorted(n for n in c["parts"] if c["parts"][n] != p["parts"][n])
                        if p
                        else None
                    ),
                )
                if c["action"] == "fresh":
                    assert (
                        c["prior"]["key"] == c["key"]
                        and c["physical"]["output"] == c["prior"]["output"]
                    )
                    assert refs[new][k] == refs[old][k]
            decisions[k] = row
        hits = sorted(
            k for k, a in decisions.items() if a["actual_source_action"] == "fresh"
        )
        assert hits == sorted(brief(new)["fresh_roles"])

        def unequal(a, b):
            return sorted(k for k in refs[a] if refs[a][k] != refs[b][k])

        return {
            "release": release,
            "github_sha256": expected,
            "run": j("admission.json")["run"],
            "frozen_forecast_sha256": FORECAST_SHA,
            "actual_fresh_roles": hits,
            "forecast_only": sorted(set(proposed) - set(hits)),
            "unexpected_actual": sorted(set(hits) - set(proposed)),
            "hits_with_different_whole_elf_from_empty_signed": sorted(
                set(hits) & set(unequal(new, "P-empty-new"))
            ),
            "all50_source_second_vs_signed_second": unequal(
                new, "P-ordinary-repeat-edit"
            ),
            "all50_source_second_vs_signed_empty": unequal(new, "P-empty-new"),
            "all50_signed_second_vs_signed_empty": unequal(
                "P-ordinary-repeat-edit", "P-empty-new"
            ),
            "all50_source_empty_vs_signed_empty": unequal("C-empty-new", "P-empty-new"),
            "genuine_signed_native_changes": unequal(
                "P-ordinary-repeat-old", "P-ordinary-repeat-edit"
            ),
            "roles": decisions,
        }


if __name__ == "__main__":
    print(
        json.dumps(
            reopen(Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])),
            sort_keys=True,
            indent=2,
        )
    )
