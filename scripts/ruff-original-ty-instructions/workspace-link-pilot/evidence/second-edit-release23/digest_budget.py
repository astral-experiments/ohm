"""Reopen exact immutable hash operands and compare a separate hardware phase cutoff."""

import gzip, hashlib, json, sys
from pathlib import Path
from zipfile import ZipFile
from collections import Counter, defaultdict

sys.path[:0] = [
    str(Path(__file__).resolve().parent),
    str(Path(__file__).resolve().parents[2]),
]
import clock_coverage, component_epochs

BLOB = "941425ee53b9993f2337cf7d6a8f031ac2420e86e708751a0d3208b2af852713"
PHASE_SHA = "ab29199f24f47fb86d1ea05064d31e3f2a598946b839e1d4fd930e71a29bd190"
STAGE = "C-exec-warm-stable"


def reopen(archive, physical, previous):
    with archive.open("rb") as s:
        assert hashlib.file_digest(s, "sha256").hexdigest() == BLOB
    assert hashlib.sha256(previous).hexdigest() == PHASE_SHA
    phase = json.loads(previous)
    cuts = {r["name"]: r for r in phase["per_target"]}
    assert len(cuts) == 50 and phase["run"] == 41675206812
    d = json.loads(physical)
    c = d["component"]["C"]
    p = d["component"]["P"]
    assert d["github_artifact"]["digest"] == "sha256:" + BLOB
    assert all(a["all_unscaled"] and a["outer"][1] == a["outer"][2] for a in (c, p))
    with ZipFile(archive) as z:

        def j(n):
            b = z.read(n)
            return json.loads(gzip.decompress(b) if n.endswith(".gz") else b)

        measured = component_epochs.gather(z, STAGE)
        assert (
            measured["domain_clocks"] == c["domains"] and measured["all_unscaled_exact"]
        )
        candidate_coverage = clock_coverage.stage(z, STAGE)
        signed_coverage = clock_coverage.stage(z, "P-exec-warm-stable")
        assert candidate_coverage["complete_ancestry_and_counter_conservation"]
        assert not signed_coverage["complete_ancestry_and_counter_conservation"]
        perimage = measured["native_roles"]
        signed_measure = component_epochs.gather(z, "P-exec-warm-stable")
        assert (
            signed_measure["domain_clocks"] == p["domains"]
            and signed_measure["all_unscaled_exact"]
        )
        signed_elf = j("P-exec-warm-stable-receipt.json.gz")["published"]

        R = j(STAGE + "/physical-decisions.json")
        declared = j(STAGE + "-receipt.json.gz")
        counts = Counter()
        costs = Counter()
        unique = set()
        transients = []
        freq = Counter()
        keyed = defaultdict(set)
        rows = {}
        for role, a in sorted(R["actors"].items()):
            ops = Counter()
            frozen = []
            used = []
            accepted = []
            emitted = []
            lines = 0
            text_bytes = 0
            symbols = []
            with z.open(
                STAGE + "/actor-" + a["pid"] + ".tsv.gz"
            ) as handle, gzip.GzipFile(fileobj=handle) as src:
                for line in src:
                    lines += 1
                    text_bytes += len(line)
                    v = line.rstrip(b"\n").split(b"\t")
                    op = v[0]
                    ops[op] += 1
                    if op == b"FROZEN":
                        dev, ino, n = map(int, v[1:4])
                        h = v[4]
                        path = v[5]
                        value = (dev, ino, n, h)
                        frozen.append((n, h))
                        keyed[(dev, ino)].add((n, h))
                        if not path.endswith(b"/symbols.o"):
                            unique.add(value)
                        else:
                            transients.append(value)
                            symbols.append(n)
                    elif op == b"USED":
                        used.append((int(v[2]), v[3]))
                    elif op == b"ACCEPT":
                        accepted.append((int(v[3]), v[4]))
                    elif op == b"EMITTED":
                        emitted.append((int(v[3]), v[4]))
            assert (
                Counter(frozen) == Counter(used) and len(symbols) == len(emitted) == 1
            )
            assert (
                len(frozen) == a["inputs"]
                and sum(n for n, h in frozen) == a["input_bytes"]
            )
            if a["action"] == "fresh":
                assert (
                    accepted == emitted
                    and ops[b"FRESH-PUBLISH"] == 1
                    and ops[b"MISS"] == 0
                )
            else:
                assert (
                    a["response"] == "full"
                    and not accepted
                    and not ops[b"FRESH-PUBLISH"]
                )
            old = cuts[Path(role).name]
            delta = old["cuts"]["hash"] - old["cuts"]["paths"]
            assert delta > 0 and old["input_bytes"] > 0
            rate = delta / old["input_bytes"]
            inp = a["input_bytes"]
            out = emitted[0][0]
            donor = accepted[0][0] if accepted else 0
            counts.update(
                {
                    "frozen_inputs": len(frozen),
                    "frozen_input_bytes": inp,
                    "used_input_bytes": sum(n for n, h in used),
                    "emitted_output_bytes": out,
                    "accepted_previous_output_bytes": donor,
                    "fresh_copy_bytes": donor,
                    "actor_log_rows": lines,
                    "actor_log_bytes": text_bytes,
                    "frozen_current_bytes_equal_previous": int(
                        inp == old["input_bytes"]
                    ),
                    "input_count_equal_previous": int(
                        len(frozen) == old["input_count"]
                    ),
                    "output_bytes_equal_previous": int(out == old["output_bytes"]),
                }
            )
            costs.update(
                {
                    "original_lookup": old["cuts"]["paths"],
                    "original_look_and_hash": old["cuts"]["hash"],
                    "original_hash_increment": delta,
                    "original_input_bytes": old["input_bytes"],
                    "transfer_input_once": rate * inp,
                    "transfer_donor_output_once": rate * donor,
                    "transfer_emitted_once": rate * out,
                }
            )
            freq.update(ops)
            rows[role] = {
                "action": a["action"],
                "input_count": len(frozen),
                "native_bytes_per_pass": inp,
                "output_bytes_emitted": out,
                "output_bytes_accepted": donor,
                "prior_hardware_lookup": old["cuts"]["paths"],
                "prior_hardware_lookup_with_hash": old["cuts"]["hash"],
                "prior_hash_input_bytes": old["input_bytes"],
                "prior_hash_instructions_per_byte": rate,
                "signed_same_role_observed_image_subtotal_instructions": signed_measure[
                    "native_roles"
                ][Path(role).name + " StockWild"]["instructions_raw"],
                "same_state_signed_physical_elf_match": signed_elf[role]
                == declared["published"][role],
                "current_native_instructions": perimage[
                    Path(role).name + " SourceWild"
                ]["instructions_raw"],
                "estimated_current_hash_instructions": rate * (2 * inp + out + donor),
                "raw_actor_rows": lines,
                "raw_actor_bytes": text_bytes,
            }
        assert len(rows) == 48 and len(R["proof_refusals"]) == 0
        assert (
            counts["frozen_input_bytes"]
            == declared["native_bytes_consumed"]
            == counts["used_input_bytes"]
        )
        assert (
            sum(r["action"] == "fresh" for r in rows.values())
            == len(c["actual_fresh"])
            == 47
        )
        unique_bytes = sum(v[2] for v in unique) + sum(v[2] for v in transients)
        total = c["outer"][0]
        base = p["outer"][0]
        n = c["domains"]["SourceWild"]["instructions_raw"]
        coord = c["domains"]["Coordinator"]["instructions_raw"]
        threshold = base / 2
        need = total - threshold
        other = total - n - coord
        unit = costs["original_hash_increment"] / costs["original_input_bytes"]
        rates = sorted(v["prior_hash_instructions_per_byte"] for v in rows.values())
        duplicate = costs["transfer_input_once"] + costs["transfer_donor_output_once"]
        optimistic = unit * (counts["frozen_input_bytes"] - unique_bytes)
        native_hits = sum(
            row["current_native_instructions"]
            for row in rows.values()
            if row["action"] == "fresh"
        )
        native_fallback = sum(
            row["current_native_instructions"]
            for row in rows.values()
            if row["action"] != "fresh"
        )
        residuals = [
            row["current_native_instructions"]
            - row["estimated_current_hash_instructions"]
            for row in rows.values()
        ]
        outshape = {
            "source_native_fresh": native_hits,
            "source_native_full_fallback": native_fallback,
            "two_ineligible_dispatch_starts": n - native_hits - native_fallback,
            "roles_where_transfer_exceeds_measured_native": sum(
                r < 0 for r in residuals
            ),
            "smallest_estimated_residual": min(residuals),
            "largest_estimated_residual": max(residuals),
        }

        return {
            "original": BLOB,
            "prior_50_phase_reader": PHASE_SHA,
            "stage": STAGE,
            "run": 41741905666,
            "source_counts": counts,
            "raw_operation_counts": {k.decode(): v for k, v in sorted(freq.items())},
            "native_subtotal_coverage": {
                "P_complete": signed_coverage[
                    "complete_ancestry_and_counter_conservation"
                ],
                "C_complete": candidate_coverage[
                    "complete_ancestry_and_counter_conservation"
                ],
                "P_unaccounted_instructions": signed_coverage[
                    "unaccounted_whole_Cargo_instructions"
                ],
            },
            "observed_physical_domains": {
                which: {k: v["instructions_raw"] for k, v in arm["domains"].items()}
                for which, arm in (("P", p), ("C", c))
            },
            "source_native": n,
            "observed_native_by_action_and_transfer_sanity": outshape,
            "coordinator": coord,
            "other_whole": other,
            "signed": base,
            "candidate": total,
            "exact_2x_hurdle": threshold,
            "gross_savings_needed": need,
            "native_savings_needed_if_coordinator_free": need - coord,
            "two_to_one_ceiling_if_every_source_instruction_paired": n / 2,
            "shortfall_vs_this_ceiling_with_current_coordinator": need - n / 2,
            "cost_on_separate_real_phase_worker": costs,
            "prior_relative_rate_range": rates[:: len(rates) - 1],
            "projections": {
                "estimated_redundant_digest_work": duplicate,
                "estimated_current_large_hash_calls": costs["transfer_input_once"] * 2
                + costs["transfer_emitted_once"]
                + costs["transfer_donor_output_once"],
                "after_removing_duplicate_digests": total - duplicate,
                "without_coordinator_and_without_duplicate_digests": total
                - coord
                - duplicate,
                "gap_after_both": need - coord - duplicate,
                "original_phase_bytes_per_occurrence_beyond_unique": counts[
                    "frozen_input_bytes"
                ]
                - unique_bytes,
                "optimistic_shared_input_saving_on_remaining_single_digest": optimistic,
            },
            "cross_role_input_shape": {
                "distinct_stable_name_dev_ino_n_hash": len(unique),
                "private_symbols_generations": len(transients),
                "private_symbols_bytes": sum(v[2] for v in transients),
                "unique_bytes_counting_each_symbols_observation": unique_bytes,
                "inode_with_multiple_observed_payloads": sum(
                    len(v) > 1 for v in keyed.values()
                ),
            },
            "proposed_444_budget_only": {
                "external_P_approx": 124.22e9,
                "external_444_approx": 79.96e9,
                "half_parent": 62.11e9,
                "required_extra_cut": 17.85e9,
                "fraction_of_444": 17.85 / 79.96,
            },
            "limitations": "Old staged hash-minus-lookup measurements are from separate physical processes on another boot. No in-process hash PMU nor executing SIMD branch was recorded on this current boot. Hypothetical zero coordinator, unique-byte availability and transferred byte prices are not observations of another implementation. The two-to-one ceiling concerns only duplicate digest computation on equal byte strings, not log/parse removal and not full linking.",
            "roles": rows,
        }


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    prior = gzip.decompress(
        (
            root.parent / "e2e-wild-inputs/evidence/phase-price/reopened.json.gz"
        ).read_bytes()
    )
    # The toolkit retains the original prior readback in canonical compact JSON.
    print(
        json.dumps(
            reopen(
                Path(sys.argv[1]),
                gzip.decompress(Path(sys.argv[2]).read_bytes()),
                prior,
            ),
            indent=2,
            sort_keys=True,
        )
    )
