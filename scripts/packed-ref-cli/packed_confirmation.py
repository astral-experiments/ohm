"""Enforce the six-boot D/Q registration before reading any endpoint."""

import hashlib
import re
from fractions import Fraction
from math import comb
from pathlib import Path
from uuid import UUID

import endpoints
import packed_sdk as sdk

HERE = Path(__file__).resolve().parent
POSITIONS = ("01", "02", "03", "04", "05", "06")
BRANCH = "charlie/qa-ruff-sorted-packed-refs-six-20261101"
LABEL = "GNU sorted packed Ruff CLI confirmation "
ARTIFACT = "gnu-sorted-packed-ruff-cli-confirmation-"
MODE = "sorted-packed-ref-six"
CONTACT = 41331687491
CONTACT_HEAD = "abeafc0bb68267ac05d354fb2274fd5f5c03ae2a"
CONTACT_ORIGINAL = "c9c3bbde412be7ffe8016337792fcf6604cfa256dce9f673c332620ff1d747d2"
CONTACT_REPLAY = "dc8f0e433f78e47149ce8a5605a3e78d82805639b1bba7c21fc109725a7a2f21"
PLAN = "d5b173ef977a52702dcb10e8e0a41c20482fdfe9937bcdf033ccc114faf9f3b7"
EXCLUDED = "bfaccb27e513299beafc3496de44839a4ecf3e65d2020d72c96bab38654c20e8"
INVENTORY = "816746ced622667036a25d99754c90601e64489da0a4522f9a2663d78f092f3d"
LIVE = "612c929ed1d04e67a779bf08d35a0876b64adcd0b27f2ce173e87431cd58cc73"
EXTERNAL = "a8414df2952d55feed3e53347b8341512c4f3cf462ea103b68a1977291e370f7"
ENROLLMENT = {
    "contact": CONTACT,
    "contact_original": CONTACT_ORIGINAL,
    "contact_readback": CONTACT_REPLAY,
    "confirmation_plan": PLAN,
    "confirmation_exclusions": EXCLUDED,
    "confirmation_inventory": INVENTORY,
    "additional_live_jobs": LIVE,
    "additional_default_boots": EXTERNAL,
}
IDENTITIES = {
    "boot": "boots",
    "job": "jobs",
    "runner": "runners",
    "runner_id": "runner_ids",
}
LANES = (
    ("clean", "reference"),
    ("structural", "return"),
    ("structural", "dirty"),
    ("measured", "return"),
)
REQUIRED_STEPS = {
    "Verify the packed confirmation source",
    "Install the source-qualified D and Q SDKs",
    "Run the ordinary packed Ruff histories",
}
need = sdk.need


def order(position):
    need(position in POSITIONS, "unknown confirmation position")
    return sdk.ARMS if position in POSITIONS[::2] else tuple(reversed(sdk.ARMS))


def frozen():
    for name, digest in (
        ("plan.md", PLAN),
        ("excluded.json", EXCLUDED),
        ("inventory.md", INVENTORY),
        ("live-namespaces.json", LIVE),
        ("default-identities.json", EXTERNAL),
    ):
        raw = (HERE / "inputs" / ("six-" + name)).read_bytes()
        need(
            hashlib.sha256(raw).hexdigest() == digest,
            "wrong frozen confirmation " + name,
        )
    result = sdk.read(HERE / "inputs/six-excluded.json")["union"]
    live = sdk.read(HERE / "inputs/six-live-namespaces.json")["prior"]
    need(
        len(live) == 7 and len({r["job"] for r in live}) == 7,
        "different live worker set",
    )
    for key, field in (
        ("job", "jobs"),
        ("runner", "runners"),
        ("runner_id", "runner_ids"),
    ):
        result[field] = sorted(set(result[field]) | {r[key] for r in live})
    other = sdk.read(HERE / "inputs/six-default-identities.json")
    previous_hosts = other["positions"]
    need(
        other["outcome_members_opened"] == 0
        and other["attempt"] == 1
        and set(previous_hosts) == {"01", "02", "03", "04"}
        and other["run"] == 41334379753
        and other["head"] == "f2f627df09d4f37dc4e40a19760c3a9ae78e50b1"
        and other["member"] == "ctfe-default/host.json",
        "wrong independent defaults cohort",
    )
    for v in previous_hosts.values():
        (expected,) = [row for row in live if row["job"] == v["job"]]
        need(
            all(
                v[k] == expected[k]
                for k in ("run", "head", "job", "runner", "runner_id")
            )
            and v["member"] == other["member"]
            and v["bytes"] > 0
            and v["artifact"] > 0
            and all(
                re.fullmatch("[0-9a-f]{64}", v[k]) for k in ("sha256", "member_sha256")
            ),
            "unbound external original",
        )
    result["boots"] = sorted(
        set(result["boots"]) | {r["boot"] for r in previous_hosts.values()}
    )
    need(len(result["boots"]) == 147, "overlapping or missing excluded boot")
    return result


def positive(value):
    return type(value) is int and value > 0


def fresh(boot, runner):
    prior = frozen()
    need(
        str(UUID(boot)) == boot and boot not in prior["boots"], "wrong or repeated boot"
    )
    need(
        isinstance(runner, str) and runner and runner not in prior["runners"],
        "wrong or repeated runner",
    )


def position_record(record, meta):
    slot = meta["position"]
    expected = {
        "mode": MODE,
        "position": slot,
        "order": list(order(slot)),
        "run": meta["run"],
        "head": meta["head"],
        "boot": meta["boot"],
        "runner": meta["runner"],
        **ENROLLMENT,
    }
    need(
        all(record.get(k) == v for k, v in expected.items()),
        "substituted six-slot position",
    )
    fresh(record["boot"], record["runner"])


def check_hosts(hosts):
    need(set(hosts) == set(POSITIONS), "missing enrolled host")
    prior = frozen()
    for key in (*IDENTITIES, "artifact", "sha256", "position_sha256"):
        values = {hosts[p][key] for p in POSITIONS}
        need(
            len(values) == 6
            and (key not in IDENTITIES or values.isdisjoint(prior[IDENTITIES[key]])),
            "previous or repeated " + key,
        )
    need(
        len({r["head"] for r in hosts.values()})
        == len({r["run"] for r in hosts.values()})
        == 1
        and next(iter(hosts.values()))["run"] != CONTACT,
        "mixed or prior run",
    )
    for p, r in hosts.items():
        fresh(r["boot"], r["runner"])
        need(
            r["position"] == p
            and r["order"] == list(order(p))
            and all(
                positive(r[k]) for k in ("run", "job", "runner_id", "artifact", "bytes")
            )
            and re.fullmatch(r"[0-9a-f]{40}", r["head"])
            and all(
                re.fullmatch(r"[0-9a-f]{64}", r[k])
                for k in ("sha256", "position_sha256")
            ),
            "incomplete original identity",
        )


def official(directory, archive, head, slot):
    """Reopen the complete GitHub registration and the selected original media."""
    run, jobs, assets, early, boots = [
        sdk.read(directory / (k + ".json"))
        for k in ("run", "jobs", "artifacts", "pre-outcome", "boot-admission")
    ]
    need(slot in POSITIONS, "unknown original position")
    need(
        run["repository"]["full_name"]
        == run["head_repository"]["full_name"]
        == "astral-experiments/ohm"
        and (
            run["run_attempt"],
            run["head_sha"],
            run["head_branch"],
            run["event"],
            run["path"],
            run["status"],
        )
        == (
            1,
            head,
            BRANCH,
            "workflow_dispatch",
            ".github/workflows/ci.yml",
            "completed",
        ),
        "wrong official attempt",
    )
    rid = run["id"]
    need(
        early["run"] == boots["run"] == rid
        and early["head"] == boots["head"] == head
        and early["outcome_members_opened"] == 0
        and early["assets"] == 0
        and early["attempt"] == 1
        and set(early["positions"]) == set(POSITIONS)
        and boots["admitted"] is True
        and boots["outcomes_opened"] == 0
        and not boots["missing"]
        and boots["reason"] is None,
        "missing early roster or six source-only admissions",
    )
    hosts = boots["hosts"]
    check_hosts(hosts)
    need(
        jobs["total_count"]
        == len(jobs["jobs"])
        == assets["total_count"]
        == len(assets["artifacts"])
        == 6
        and {j["name"] for j in jobs["jobs"]} == {LABEL + p for p in POSITIONS}
        and {a["name"] for a in assets["artifacts"]}
        == {ARTIFACT + p for p in POSITIONS},
        "missing or duplicate official worker/original",
    )
    for p in POSITIONS:
        (j,) = [v for v in jobs["jobs"] if v["name"] == LABEL + p]
        (a,) = [v for v in assets["artifacts"] if v["name"] == ARTIFACT + p]
        x, o = hosts[p], a["workflow_run"]
        need(
            early["positions"][p] == {"job": j["id"], "order": list(order(p))}
            and (x["job"], x["run"], x["head"], x["runner"], x["runner_id"])
            == (j["id"], rid, head, j["runner_name"], j["runner_id"])
            and (
                j["run_id"],
                j["run_attempt"],
                j["head_sha"],
                j["head_branch"],
                j["status"],
                j["labels"],
            )
            == (
                rid,
                1,
                head,
                BRANCH,
                "completed",
                ["namespace-profile-ubuntu-24-04-16"],
            )
            and (o["id"], o["head_sha"], o["head_branch"]) == (rid, head, BRANCH)
            and o["repository_id"] == o["head_repository_id"] == run["repository"]["id"]
            and (a["id"], a["size_in_bytes"], a["digest"])
            == (x["artifact"], x["bytes"], "sha256:" + x["sha256"])
            and not a["expired"],
            "substitution in original GitHub roster",
        )
        if p == slot:
            need(
                j["conclusion"] == "success"
                and all(
                    s["status"] == "completed" and s["conclusion"] == "success"
                    for s in j["steps"]
                )
                and REQUIRED_STEPS <= {s["name"] for s in j["steps"]},
                "official worker refused a gate",
            )
    x = hosts[slot]
    with archive.open("rb") as f:
        need(
            archive.stat().st_size == x["bytes"]
            and hashlib.file_digest(f, "sha256").hexdigest() == x["sha256"],
            "wrong original GitHub archive bytes",
        )
    return dict(x, attempt=1)


def history_order(slot, history, clocks):
    """Check acquisition order in all histories and the actual watch.c clock boundaries."""
    expected = [(lane, line, arm) for lane, line in LANES for arm in order(slot)]
    need(len(history) == len(expected), "missing history boundary")
    previous_stop = 0
    for row, (lane, line, arm) in zip(history, expected, strict=True):
        start, stop = row["start_ns"], row["stop_ns"]
        need(
            (row["lane"], row["line"], row["arm"]) == (lane, line, arm)
            and positive(start)
            and positive(stop)
            and previous_stop < start < stop,
            "invalid history order or boundary",
        )
        previous_stop = stop
        if lane == "measured":
            for phase in endpoints.PHASES:
                clock = clocks[arm]["phases"][phase]
                need(
                    start < clock["start"] < clock["stop"] < stop,
                    "clock outside enrolled arm history",
                )


def check_clocks(raw, summaries):
    """Retain the literal counters and independently recalculate each seven-visit summary."""
    need(set(raw) == set(summaries) == set(sdk.ARMS), "missing clock role")
    for arm in sdk.ARMS:
        need(
            set(raw[arm]) == set(endpoints.PHASES),
            "missing or unregistered ordinary clock",
        )
        ordered = {p: raw[arm][p] for p in endpoints.PHASES}
        for row in ordered.values():
            need(
                set(row)
                == {
                    "start",
                    "stop",
                    "user_us",
                    "system_us",
                    "instructions",
                    "enabled",
                    "running",
                    "event_errno",
                    "code",
                }
                and all(type(v) is int for v in row.values())
                and row["user_us"] >= 0
                and row["system_us"] >= 0,
                "wrong native PMU/CPU ABI",
            )
        need(
            endpoints.count(ordered) == summaries[arm],
            "summary differs from raw seven clocks",
        )


def evaluate(reports, hosts):
    check_hosts(hosts)
    need(
        set(reports) == set(POSITIONS),
        "six independently complete raw reports required",
    )
    ratios, pairs = [], {}
    for p in POSITIONS:
        r = reports[p]
        need(
            r["qualified"] is True
            and r["official"] == dict(hosts[p], attempt=1)
            and r["boot"] == hosts[p]["boot"]
            and r["visits"] == 46
            and r["metered"] == 14
            and r["traced"] == 16
            and r["source"]["source"]["source"][:2] == [sdk.D, sdk.Q],
            "report belongs to another source/host",
        )
        rows = r["measured"]
        check_clocks(r["raw_clocks"], rows)
        history_order(p, r["histories"], rows)
        d, q = (rows[role]["phases"]["X-B"]["instructions"] for role in sdk.ARMS)
        need(
            positive(d) and positive(q) and r["primary"] == {"Don": d, "Qon": q},
            "wrong whole primary",
        )
        value = Fraction(d, q)
        ratios.append(value)
        pairs[p] = {
            "D": d,
            "Q": q,
            "order": list(order(p)),
            "ratio": [value.numerator, value.denominator],
            "passes": d > 2 * q,
        }
    ratios.sort()
    wins = sum(r["passes"] for r in pairs.values())
    median = (ratios[2] + ratios[3]) / 2
    return {
        "complete_positions": 6,
        "primary": "measured/return/X-B",
        "pairs": pairs,
        "wins": wins,
        "accepted": wins == 6,
        "median": [median.numerator, median.denominator],
        "interval": [[r.numerator, r.denominator] for r in (ratios[0], ratios[-1])],
        "coverage": [31, 32],
        "one_sided_sign_tail": [sum(comb(6, k) for k in range(wins, 7)), 64],
    }
