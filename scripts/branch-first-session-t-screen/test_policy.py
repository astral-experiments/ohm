"""Validate shared thresholds and check that these table-only arms cannot hide residual storage."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
COMMON = HERE.parent / "branch-first-session-e-screen"
sys.path[:0] = [str(HERE), str(COMMON)]
from metrics import evaluate, TABLE_ONLY, MIB
from test_metrics import fixture


def table_rows():
    old = fixture()
    return {
        right: old[left] for left, right in zip(("Eoff", "Kon", "Eon"), TABLE_ONLY, strict=True)
    }


class DirectPolicy(unittest.TestCase):
    def test_equal_threshold_and_actual_role_names(self):
        r = evaluate(table_rows(), TABLE_ONLY)
        self.assertTrue(r["meets_numeric_margins"])
        self.assertTrue(r["incremental_table_storage_and_instructions_only"])
        for phase, row in r["instructions"].items():
            self.assertEqual(set(row["instructions_over_Fon"]), set(TABLE_ONLY))
            self.assertEqual(row["instructions_over_Fon"]["Fon"]["decimal"], 1)
        self.assertNotIn("Kon", json.dumps(r))
        self.assertNotIn("Eon", json.dumps(r))

    def test_250_mib_alone_does_not_hide_baseline_excess(self):
        x = table_rows()
        for p in ("first-B", "same-first-B"):
            for lane in ("allocated", "unmetered_allocated"):
                x["Fon"][p][lane] = 2990 * MIB
                x["Ton"][p][lane] = 2640 * MIB
        r = evaluate(x, TABLE_ONLY)
        self.assertFalse(r["meets_numeric_margins"])
        self.assertTrue(r["incremental_table_storage_and_instructions_only"])
        self.assertEqual(
            r["storage"]["unmetered_allocated"]["visits"]["first-B"]["bytes_above_Foff"]["Ton"],
            140 * MIB,
        )

    def test_same_branch_must_qualify_on_every_arm(self):
        x = table_rows()
        x["Ton"]["same-first-B"]["allocated"] = (
            x["Fon"]["same-first-B"]["allocated"] - 250 * MIB + 1
        )
        r = evaluate(x, TABLE_ONLY)
        self.assertFalse(r["incremental_table_storage_and_instructions_only"])

    def test_cold_cost_matters_to_table_comparison(self):
        x = table_rows()
        x["Ton"]["cold-A"]["instructions"] = x["Fon"]["cold-A"]["instructions"] * 2
        r = evaluate(x, TABLE_ONLY)
        self.assertFalse(r["meets_numeric_margins"])
        self.assertFalse(r["incremental_table_storage_and_instructions_only"])

    def test_measured_and_unmeasured_sources_disjoint(self):
        x = table_rows()
        x["Ton"]["same-repeat"]["running"] = 994
        with self.assertRaises(ValueError):
            evaluate(x, TABLE_ONLY)
        with self.assertRaises(ValueError):
            evaluate(table_rows())

    def test_registration_requires_both_source_and_distinct_prior_hosts(self):
        import policy as p

        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp)
            fixtures = fake / "inputs"
            fixtures.mkdir()
            config = fixtures / "t-source.json"
            proof = fixtures / "source-replay.json"
            e_history = fixtures / "e-boots.json"
            excluded = fixtures / "excluded-boots.json"
            extras = json.loads(p.OTHER_BOOTS.read_bytes())
            q = {
                "source": p.T,
                "members": 81,
                "manifest": "e" * 64,
                "cargo": [p.b.CARGO_ELF, 1234, 493],
                "wild": [p.b.WILD_ELF, 3434, 493],
            }
            rec = {
                "head": p.SOURCE_HEAD,
                "attempt": 1,
                "run": 1,
                "job": 2,
                "artifacts": {p.DRIVER: {}, p.OBS: {}},
                "qualified": q,
            }
            native = {
                "official": rec,
                "restored": q,
                "original_F": p.BASE,
                "mixed": list(sorted(p.HISTORIES)),
                "in_tree_tests": [8, 7],
                "ordinary_provider_visits": [6, 16],
                "native_values": [17, 29],
                "cargo_sha256": p.b.CARGO_ELF,
                "wild_sha256": p.b.WILD_ELF,
            }
            boots = ["11111111-2222-3333-4444-111111111111", "11111111-2222-3333-4444-222222222222"]
            eb = {
                "run": 41228642029,
                "head": "a6967b95ca4222e755e859ee1fb6e7839c3f8a30",
                "hosts": {
                    pos: {"job": job, "boot": boot, "archive_sha256": "c" * 64}
                    for pos, job, boot in zip(
                        ("01", "02"), (124617991858, 124617991520), boots, strict=True
                    )
                },
            }
            original = set(json.loads(p.sdk.EXCLUDED.read_bytes()))
            with (
                patch.object(p, "HERE", fake),
                patch.object(p, "RUNTIME", config),
                patch.object(p, "EXCLUDED", excluded),
                patch.object(p, "BOOT_WITNESS", e_history),
            ):

                def bind(n, e, deny):
                    proof.write_text(json.dumps(n))
                    config.write_text(
                        json.dumps(
                            {"schema": 1, "source": rec, "reviewer": {"sha256": p.b.sha(proof)}}
                        )
                    )
                    e_history.write_text(json.dumps(e))
                    excluded.write_text(json.dumps(sorted(deny)))

                deny = original | set(extras) | set(boots)
                bind(native, eb, deny)
                self.assertEqual(p.enrollment(), rec)
                for kind in (
                    "wrong-native-case",
                    "missing-older-boot",
                    "missing-E-boot",
                    "same-worker",
                    "different-Cargo",
                ):
                    n, e, ex = deepcopy((native, eb, deny))
                    if kind == "wrong-native-case":
                        n["mixed"].pop()
                    elif kind == "missing-older-boot":
                        ex.remove(next(iter(extras)))
                    elif kind == "missing-E-boot":
                        ex.remove(boots[1])
                    elif kind == "same-worker":
                        e["hosts"]["01"]["boot"] = boots[1]
                    else:
                        n["cargo_sha256"] = "0" * 64
                    bind(n, e, ex)
                    with self.subTest(kind=kind), self.assertRaises(ValueError):
                        p.enrollment()

    def test_source_native_gate(self):
        import policy as p

        official = {
            name: {"id": i + 11, "size_in_bytes": 12345, "digest": "sha256:" + "a" * 64}
            for i, name in enumerate((p.DRIVER, p.OBS))
        }
        r = {"run": 23, "job": 24, "artifacts": official}
        run = {
            "id": 23,
            "head_sha": p.SOURCE_HEAD,
            "run_attempt": 1,
            "head_branch": p.SOURCE_REF,
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "path": ".github/workflows/ci.yml",
        }
        j = {
            "total_count": 1,
            "jobs": [
                {
                    "id": 24,
                    "name": p.JOB_NAME,
                    "conclusion": "success",
                    "head_sha": p.SOURCE_HEAD,
                    "run_id": 23,
                    "steps": [{"name": name, "conclusion": "success"} for name in p.JOB_STEPS],
                }
            ],
        }
        a = {
            "total_count": 2,
            "artifacts": [
                {
                    "name": name,
                    **rec,
                    "expired": False,
                    "workflow_run": {"id": 23, "head_sha": p.SOURCE_HEAD},
                }
                for name, rec in official.items()
            ],
        }
        p.check_live(r, run, j, a)
        for mutant in (
            "wrong-head",
            "wrong-parent",
            "missing-step",
            "expired",
            "changed-digest",
            "bad-job",
        ):
            run2, j2, a2 = deepcopy((run, j, a))
            if mutant == "wrong-head":
                run2["head_sha"] = "a" * 40
            elif mutant == "wrong-parent":
                a2["artifacts"][0]["workflow_run"]["id"] = 25
            elif mutant == "missing-step":
                j2["jobs"][0]["steps"].pop()
            elif mutant == "expired":
                a2["artifacts"][0]["expired"] = True
            elif mutant == "changed-digest":
                a2["artifacts"][1]["digest"] = "sha256:" + "c" * 64
            else:
                j2["jobs"][0]["id"] = 25
            with self.subTest(mutant=mutant), self.assertRaises(ValueError):
                p.check_live(r, run2, j2, a2)

    def test_actual_safety_and_eligible_arms(self):
        import policy

        self.assertEqual(policy.ORDERS, {"01": TABLE_ONLY, "02": TABLE_ONLY[::-1]})
        self.assertEqual(policy.PACKED_OBJECTS, set())
        self.assertEqual(policy.COLD_TABLE_ARM, "Ton")
        for a in TABLE_ONLY:
            env = policy.b.environment(a, permitted=TABLE_ONLY)
            self.assertEqual(
                env.get("CARGO_ENCODED_RUSTFLAGS"),
                None if a == "Foff" else "-Zohm-branch-cache=yes",
            )
            self.assertFalse(
                any(x in env for x in ("RUSTC_WRAPPER", "CI", "TF_BUILD", "CARGO_INCREMENTAL"))
            )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as t:
        os.environ.setdefault("RUNNER_TEMP", t)
        unittest.main()
