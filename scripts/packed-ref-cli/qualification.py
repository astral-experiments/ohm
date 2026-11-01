"""Reopen the source-qualified SDK, distinct small native contact and six excluded integration boots."""

import gzip
import hashlib
import json
from pathlib import Path

import packed_sdk as sdk

HERE = Path(__file__).resolve().parent
SIX = "eb7aa0c79de4d207bd6ceb334b275d069bc3a435832d5ce0a558c87efee39c86"
WITNESS = "042457d1e29a284f8caccffa0d426a0eb77810dd150f160262830533f741f920"
TERMINAL = "cc5f767869a8a12d1372a1fcfe94f9388ddff88fa82da9d9df866a5dab76b5f9"


def evidence(name, digest):
    raw = (HERE / "inputs" / name).read_bytes()
    if name.endswith(".gz"):
        raw = gzip.decompress(raw)
    sdk.need(
        hashlib.sha256(raw).hexdigest() == digest, "different prerequisite " + name
    )
    return raw


def native(v):
    d, q = v["D"], v["Q"]
    owners = {"pack_ref_app", "pack_ref_provider"}
    sdk.need(
        v["source"] == [sdk.D, sdk.Q]
        and v["Q_validated_visits"] == 13
        and q["unresolved_syscalls"] == 0
        and not d["opaque_cold"]
        and not d["opaque_return"]
        and list(q["per_tid_packed_bytes"].values())
        == list(d["completed_packed_reads"].values())
        == [65537] * 2
        and set(q["compilers"])
        == set(d["rustc_pids_at_X_B"])
        == set(q["selected"])
        == set(d["source_at_X_B"])
        == owners
        and len(set(q["wild"])) == len(set(d["wild_pids_at_X_B"])) == 1,
        "missing actual D/Q fixture source, compiler, linker or packed read",
    )
    for owner in owners:
        qtables, dtables = q["selected"][owner], d["source_at_X_B"][owner]
        sdk.need(
            set(qtables) == set(dtables) == {"dep-graph.bin", "query-cache.bin"}
            and all(
                qtables[k]["donor"] == "Y-B" and dtables[k]["from"] == "X-A"
                for k in dtables
            ),
            "small native contact failed to distinguish donors",
        )
    empty, warm = v["Q_independent_empty"], v["Q_warm_phases"]
    expected = {
        "01-Y-B": "B",
        "02-X-A": "A",
        "03-X-B": "B",
        "04-dirty": "dirty",
        "05-invalid": "invalid",
        "06-invalid-repeat": "invalid",
        "07-repair": "repair",
        "08-unchanged": "B",
    }
    sdk.need(
        set(warm) == set(expected)
        and set(empty) == {"cold-" + s for s in expected.values()}
        and all(warm[k] == empty["cold-" + s] for k, s in expected.items())
        and empty["cold-invalid"] == {"diagnostic": d["e0308"]},
        "warm/empty native verdict mismatch",
    )
    for state, value in (("A", 17), ("B", 29), ("dirty", 41), ("repair", 29)):
        rec = empty["cold-" + state]
        sdk.need(
            rec["elf"] == d["native"][str(value)]
            and rec["native"] == f"{value} {value}"
            and rec["bytes"] > 0,
            "did not retain the same correct native executable",
        )


def prereqs():
    terminal = json.loads(evidence("q-native-retry-terminal.json.gz", TERMINAL))
    sdk.need(
        terminal["bound_native_qualifier"] == WITNESS
        and [terminal["source_run"], terminal["source_job"]]
        == [sdk.SOURCE_RUN, sdk.SOURCE_JOB]
        and terminal["raw_archive"]
        == "a8f37b6b7812aca22f456db8ad9140b8b474ddd0b5dcdab7cd58db7539387bd4"
        and terminal["rejected_raw_sha"]
        == "c09a8186d8c56d16f54e8198189b98b64c29c7e3ff69edf356804e44da1caacd",
        "wrong accepted or refused native original",
    )
    native(json.loads(evidence("q-native-verified.json.gz", WITNESS)))
    refused = json.loads(
        evidence(
            "q-native-first-refused-forensics.json.gz",
            terminal["original_boundary_refusal_sha"],
        )
    )
    sdk.need(
        refused["qualified"] is False
        and refused["call_type_unrecoverable"]
        and len(refused["unknown"]) == 1,
        "earlier native refusal lost",
    )
    evidence("q-native-negatives.txt.gz", terminal["negative_results"])
    roster = json.loads(
        evidence(
            "qualified-q-sdk.json",
            "bc8520c850f51e05682e29582f4ce55b68dbd7e7e4d81ba5a4d0eab37393fb53",
        )
    )
    sdk.need(
        roster["source"] == [sdk.D, sdk.Q, sdk.Q_TREE]
        and roster["originals"] == sdk.enrolled()["artifacts"]
        and roster["identical_sdk_rows"] == 80
        and roster["drivers"] == sdk.enrolled()["source"]["drivers"],
        "wrong native SDK roster",
    )
    six = json.loads(evidence("integration-boots.json.gz", SIX))
    ex = sdk.read(HERE / "excluded-hosts.json")
    sdk.need(
        six["admitted"]
        and six["outcomes_opened"] == 0
        and len(six["hosts"]) == 6
        and (six["run"], six["head"], SIX)
        == (
            ex["concurrent"]["run"],
            ex["concurrent"]["head"],
            ex["concurrent"]["identity_only_sha256"],
        )
        and {b["job"] for b in six["hosts"].values()}
        == set(ex["concurrent"]["job_ids"]),
        "different six-host enrollment",
    )
    for k, old in (
        ("boot", "boots"),
        ("runner", "runners"),
        ("runner_id", "runner_ids"),
        ("job", "jobs"),
    ):
        vals = {r[k] for r in six["hosts"].values()}
        sdk.need(
            len(vals) == 6
            and vals <= set(ex[old])
            and all(row[k] in ex[old] for row in ex["source_attempts"]),
            "source or integration host not excluded",
        )
    return dict(
        native=WITNESS,
        terminal=TERMINAL,
        original=terminal["raw_archive"],
        earlier_refusal=terminal["rejected_raw_sha"],
        six_host_identity=SIX,
        source=roster["source_receipt_sha256"],
    )
