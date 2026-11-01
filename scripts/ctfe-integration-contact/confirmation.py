"""Register six disjoint boots and replay the single paired whole-Cargo endpoint."""

from fractions import Fraction
import hashlib
import json
from math import comb
import re

import contract as q

POSITIONS = ("01", "02", "03", "04", "05", "06")
MODE = "six-host-test-fast-forward"
CONTACT = 41317769397
PLAN = "d435f1ec7c0a613d5ec8ccb19e937306a0530db08b8f8fa3348f229531cbfd28"
EXCLUSIONS = "f06744d5ca905d2dc1c85ba4c35eefc2c8bed223de0841db133def579cc73a60"
LABEL = "GNU E D integration fast-forward confirmation "
ARTIFACT = "gnu-donor-integration-fast-forward-"
REPO = "astral-experiments/ohm"


def order(position):
    q.need(position in POSITIONS, "unknown confirmation position")
    return q.ARMS if int(position) % 2 else tuple(reversed(q.ARMS))


def exclusions():
    path = q.HERE / "confirmation-exclusions.json"
    q.need(q.sha(path.read_bytes()) == EXCLUSIONS, "different prior registration")
    return json.loads(path.read_bytes())


def fresh(boot, runner):
    q.fresh_runner(boot, runner)
    prior = exclusions()
    q.need(
        boot not in prior["boots"] and runner not in prior["runners"],
        "prior confirmation host",
    )


def position_record(pos, meta):
    slot = meta["position"]
    q.need(
        (
            pos["mode"],
            pos["position"],
            pos["order"],
            pos["runner"],
            pos["run"],
            pos["head"],
            pos["command"],
            pos["plan"],
            pos["contact"],
            pos["exclusions"],
        )
        == (
            MODE,
            slot,
            list(order(slot)),
            meta["runner"],
            meta["run"],
            meta["head"],
            q.COMMAND,
            PLAN,
            CONTACT,
            EXCLUSIONS,
        ),
        "wrong source, slot, arm order or subject",
    )
    q.need(pos["boot"] == meta["boot"], "position boot differs from all-six admission")
    fresh(pos["boot"], pos["runner"])


def subjects(records, slot):
    """Use an actual monotonic clock boundary in each role to verify runtime order."""
    ref = json.loads((q.HERE / "contact-x-b-roster.json").read_bytes())
    q.need(set(records) == set(q.ARMS), "incorrect role inventory")
    intervals = []
    for arm in order(slot):
        row = records[arm]
        primary = row["physical/X-B"]
        q.need(
            primary["physical"] == ref
            and primary["typed"] == 390
            and primary["dirty"] == 21
            and primary["wild_outputs"]
            == ["integration_test::integration_test", "ruff::ruff"],
            "physical compiler and linker roster differs from the admitted contact",
        )
        for phase in ("Y-B", "X-A", "X-B"):
            clock = row["ordinary/" + phase]["clock"]
            intervals.append((clock["start"], clock["stop"]))
    q.need(
        all(0 < start < stop for start, stop in intervals)
        and all(a[1] < b[0] for a, b in zip(intervals, intervals[1:])),
        "actual PMU intervals violate enrolled arm order",
    )


def official(folder, raw, head, slot):
    load = lambda filename: json.loads((folder / filename).read_bytes())
    run, jobs, assets, early, boots = (
        load(k + ".json")
        for k in ("run", "jobs", "artifacts", "pre-outcome", "boot-admission")
    )
    registered = early["positions"]
    q.need(
        early["run"] == run["id"] == boots["run"]
        and early["assets"] == 0
        and run["conclusion"] == "success"
        and early["head"] == boots["head"] == head
        and early["attempt"] == 1
        and set(registered) == set(POSITIONS),
        "incorrect initial six-position registration",
    )
    rid = run["id"]
    q.need(
        run["repository"]["full_name"] == run["head_repository"]["full_name"] == REPO
        and (
            run["head_sha"],
            run["head_branch"],
            run["event"],
            run["run_attempt"],
            run["path"],
            run["status"],
        )
        == (
            head,
            q.BRANCH,
            "workflow_dispatch",
            1,
            ".github/workflows/ci.yml",
            "completed",
        ),
        "wrong official run",
    )
    q.need(
        jobs["total_count"]
        == len(jobs["jobs"])
        == assets["total_count"]
        == len(assets["artifacts"])
        == 6
        and {j["name"] for j in jobs["jobs"]} == {LABEL + p for p in POSITIONS}
        and {a["name"] for a in assets["artifacts"]}
        == {ARTIFACT + p for p in POSITIONS},
        "incomplete official inventory",
    )
    q.need(
        boots["outcomes_opened"] == 0 and boots["admitted"] is True,
        "prior complete identity-only admission missing",
    )
    check_hosts(boots["hosts"])
    for p in POSITIONS:
        (j,) = [j for j in jobs["jobs"] if j["name"] == LABEL + p]
        (a,) = [a for a in assets["artifacts"] if a["name"] == ARTIFACT + p]
        x = boots["hosts"][p]
        q.need(
            registered[p] == {"job": j["id"], "order": list(order(p))}
            and (
                j["run_id"],
                j["head_sha"],
                j["run_attempt"],
                j["labels"],
                j["status"],
                j["runner_name"],
                j["runner_id"],
            )
            == (
                rid,
                head,
                1,
                ["namespace-profile-ubuntu-24-04-16"],
                "completed",
                x["runner"],
                x["runner_id"],
            )
            and (
                a["workflow_run"]["id"],
                a["workflow_run"]["head_sha"],
                a["id"],
                a["size_in_bytes"],
                a["digest"],
            )
            == (rid, head, x["artifact"], x["bytes"], "sha256:" + x["sha256"])
            and x["run"] == rid
            and x["head"] == head
            and x["job"] == j["id"]
            and not a["expired"],
            "substitution in the official six-job inventory",
        )
        if p == slot:
            q.need(
                j["conclusion"] == "success"
                and all(v["conclusion"] == "success" for v in j["steps"]),
                "official position refused a gate",
            )
    selected = boots["hosts"][slot]
    with raw.open("rb") as f:
        q.need(
            raw.stat().st_size == selected["bytes"]
            and hashlib.file_digest(f, "sha256").hexdigest() == selected["sha256"],
            "different original archive",
        )
    return {**selected, "position": slot, "attempt": 1}


def check_hosts(hosts):
    prior = exclusions()
    q.need(set(hosts) == set(POSITIONS), "missing enrolled host")
    for field, prior_field in (
        ("boot", "boots"),
        ("runner", "runners"),
        ("runner_id", "runner_ids"),
        ("job", "jobs"),
        ("artifact", None),
    ):
        values = [hosts[pos][field] for pos in POSITIONS]
        q.need(
            len(set(values)) == 6
            and (not prior_field or set(values).isdisjoint(prior[prior_field])),
            "previous or repeated " + field,
        )
    q.need(
        {v["run"] for v in hosts.values()}.isdisjoint(prior["runs"])
        and len({v["run"] for v in hosts.values()}) == 1
        and len({v["head"] for v in hosts.values()}) == 1,
        "mixed workflow runs or heads",
    )
    for pos, h in hosts.items():
        fresh(h["boot"], h["runner"])
        q.need(
            h["position"] == pos
            and h["order"] == list(order(pos))
            and h["bytes"] > 0
            and re.fullmatch("[a-f0-9]{64}", h["sha256"])
            and re.fullmatch("[a-f0-9]{64}", h["position_sha256"])
            and re.fullmatch("[a-f0-9]{40}", h["head"])
            and all(
                type(h[k]) is int and h[k] > 0
                for k in ("run", "job", "runner_id", "artifact", "bytes")
            ),
            "missing original identity or enrollment",
        )


def evaluate(reports, hosts):
    """Return the registered all-six decision from the complete independent replay."""
    check_hosts(hosts)
    q.need(set(reports) == set(POSITIONS), "incomplete report set")
    values = []
    rows = {}
    for pos in POSITIONS:
        report = reports[pos]
        q.need(
            report["qualified"] is True
            and report["complete_suites"] == 24
            and report["boot"] == hosts[pos]["boot"]
            and report["official"] == {**hosts[pos], "position": pos, "attempt": 1},
            "unbound complete independent replay",
        )
        records = report["records"]
        subjects(records, pos)
        e, d = (records[a]["ordinary/X-B"]["clock"]["instructions"] for a in q.ARMS)
        q.need(
            type(e) is int and type(d) is int and min(e, d) > 0,
            "nonpositive or noninteger primary",
        )
        ratio = Fraction(e, d)
        values.append(ratio)
        rows[pos] = dict(
            E=e, D=d, ratio=float(ratio), order=list(order(pos)), passes=e > 2 * d
        )
    v = sorted(values)
    exact = lambda f: [f.numerator, f.denominator]
    wins = sum(r["passes"] for r in rows.values())
    return dict(
        complete_positions=6,
        primary="ordinary/X-B",
        pairs=rows,
        wins=wins,
        accepted=wins == 6,
        median=exact((v[2] + v[3]) / 2),
        interval=[exact(v[0]), exact(v[-1])],
        coverage=[31, 32],
        one_sided_sign_tail=[sum(comb(6, k) for k in range(wins, 7)), 64],
    )
