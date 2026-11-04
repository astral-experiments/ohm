"""Reopen the two immutable originals, their hardware clocks and the failed admission."""

from pathlib import Path
import gzip, json, sys
from zipfile import ZipFile

E = Path(__file__).resolve().parent
P = E.parent.parent
sys.path[:0] = [str(P), str(E)]
import clock_coverage, component_epochs, digest_budget, read_pilot, repeated_edit, sections_and_fallbacks, native_lease_boundary


def saved(name):
    return json.loads(gzip.decompress((E / (name + ".json.gz")).read_bytes()))


def verify(archive, phase):
    head = "d68c5ce147ce6089d48f2524836ab663737c175f"
    run = 41741905666
    h = digest_budget.BLOB
    r = read_pilot.intake(archive, h, head, run, 23)
    assert (
        r["stage_count"] == r["registered_stages"] == 37
        and r["complete"]
        and not r["qualified"]
    )
    expected = saved("hardware-and-native")
    assert expected["comparison_refusals"] == r["refusal"] and len(r["refusal"]) == 5
    with ZipFile(archive) as z:
        for phase_name, row in expected["ordinary"].items():
            for arm in ("P", "C"):
                tag = arm + "-" + phase_name
                meter = json.loads(z.read(tag + "/hardware.json"))
                receipt = json.loads(gzip.decompress(z.read(tag + "-receipt.json.gz")))
                assert meter == receipt["meter"] and meter["status"] == 0
                assert meter["running"] == meter["enabled"] > 0
                fields = {
                    "elapsed_ns",
                    "instructions",
                    "user_us",
                    "system_us",
                    "rchar",
                    "wchar",
                    "read_bytes",
                    "write_bytes",
                    "inblock",
                    "outblock",
                }
                assert set(row[arm]) == fields and row[arm] == {
                    k: meter[k] for k in fields
                }
            assert sorted(row["accepted"]) == sorted(
                r["native"]["C-" + phase_name]["fresh"]
            )
        coverage = saved("physical-image-coverage")["23"]["stages"]
        for tag, original_coverage in coverage.items():
            assert clock_coverage.stage(z, tag) == original_coverage
        for arm in ("P", "C"):
            obs = component_epochs.gather(z, arm + "-exec-warm-stable")
            original = expected["component"][arm]
            assert (
                obs["outer"] == original["outer"]
                and obs["domain_clocks"] == original["domains"]
            )
            assert obs["all_unscaled_exact"] and original["all_unscaled"]
        assert (
            r["guarded_native_outputs"]["C-native-four"]
            == expected["negative_controls"]["C-native-four"]
        )
    actual = repeated_edit.reopen(archive, h, 23)
    assert actual == saved("physical-second-edit")
    assert sections_and_fallbacks.reopen(archive, h) == saved("sections-and-fallbacks")
    prior = gzip.decompress(
        (
            P.parent / "e2e-wild-inputs/evidence/phase-price/reopened.json.gz"
        ).read_bytes()
    )
    original = gzip.decompress((E / "hardware-and-native.json.gz").read_bytes())
    assert digest_budget.reopen(archive, original, prior) == saved("digest-attribution")
    assert native_lease_boundary.run(phase, archive) == saved("prior-lease-overlap")
    return {
        "qualified": False,
        "completed_phases": 37,
        "second_edit": {
            "hits": len(actual["actual_fresh_roles"]),
            "signed_and_candidate_whole_elf_differences_on_same_second_edit": actual[
                "all50_source_second_vs_signed_second"
            ],
            "P_instructions": expected["ordinary"]["ordinary-repeat-edit"]["P"][
                "instructions"
            ],
            "C_instructions": expected["ordinary"]["ordinary-repeat-edit"]["C"][
                "instructions"
            ],
        },
        "four_byte_exit": expected["negative_controls"]["C-native-four-verdict.json"][
            "exit"
        ],
        "strict_refusals": r["refusal"],
    }


if __name__ == "__main__":
    print(json.dumps(verify(*map(Path, sys.argv[1:])), indent=2, sort_keys=True))
