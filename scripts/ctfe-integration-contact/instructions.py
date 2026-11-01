"""Single-host diagnostic with distinct ordinary PMU and kernel-observed acquisitions."""

import json
import contract as q

ORDER = ("Eon", "Don")
BRANCH = q.BRANCH
LAYOUT = {
    "empty": q.EMPTY,
    "physical": ("Y-B", "X-A", "X-B"),
    "ordinary": (
        "Y-B",
        "X-A",
        "X-B",
        "dirty-X-B",
        "comment",
        "unchanged",
        "invalid",
        "repair",
    ),
}
PLAIN = LAYOUT["ordinary"][:3]
ACTIONS = [(lane, phase) for lane, phases in LAYOUT.items() for phase in phases]


def plan(lane, phase):
    q.need((lane, phase) in ACTIONS, ("not an enrolled visit", lane, phase))
    if phase == "dirty-X-B":
        return "clean-semantic", "X-B", "dirty"
    return (
        phase,
        phase,
        "dirty"
        if lane == "ordinary" and phase in ("comment", "unchanged", "invalid", "repair")
        else "return",
    )


def is_counter(lane, phase):
    return lane == "ordinary" and phase in PLAIN


def outcomes(rows):
    primary = {a: rows[a]["ordinary/X-B"]["clock"]["instructions"] for a in ORDER}
    for arm in ORDER:
        m = rows[arm]
        q.need(set(m) == {l + "/" + p for l, p in ACTIONS}, "incomplete role")
        for phase in PLAIN:
            nat, pmu = (m[l + "/" + phase] for l in ("physical", "ordinary"))
            q.need(
                nat["physical"]
                and pmu["physical"] is None
                and nat["products"] == pmu["products"]
                and nat["dirty"] == pmu["dirty"]
                and nat["typed"] == pmu["typed"] == 390,
                "physical and ordinary siblings disagree",
            )
        q.need(
            all(
                m["physical/X-A"]["products"][k] != m["physical/X-B"]["products"][k]
                for k in ("harness", "cli", "reader")
            )
            and m["physical/X-B"]["wild_outputs"]
            == ["integration_test::integration_test", "ruff::ruff"],
            "no historical cross-revision change/link",
        )
        q.need(
            m["ordinary/dirty-X-B"]["products"]["cli"]
            != m["ordinary/X-B"]["products"]["cli"]
            and m["ordinary/comment"]["products"] == m["empty/clean-edited"]["products"]
            and m["ordinary/invalid"]["status"] == 101
            and m["ordinary/repair"]["status"] == 0,
            "dirty donor or repair did not exercise the expected native change",
        )
    return dict(
        whole_x_b=primary,
        above_two=primary["Eon"] > 2 * primary["Don"],
        independent_hosts=1,
        confidence_inference=False,
    )


C_FIELDS = {
    "start",
    "stop",
    "enabled",
    "running",
    "instructions",
    "event_errno",
    "code",
    "system_us",
    "user_us",
}


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def timed(clock, phase):
    code = 101 if phase == "invalid" else 0
    q.need(
        phase in q.HISTORY
        and set(clock) == C_FIELDS
        and all(type(v) is int for v in clock.values())
        and clock["instructions"] > 0
        and clock["code"] == code
        and clock["event_errno"] == 0
        and clock["enabled"] == clock["running"] > 0
        and 0 < clock["start"] < clock["stop"]
        and min(clock["user_us"], clock["system_us"]) >= 0
        and clock["user_us"] + clock["system_us"] > 0,
        "unqualified complete Cargo user event",
    )
    return clock["instructions"]


def reference_owners(owners):
    q.need(
        set(owners) == {"cli", "harness"}
        and all(
            type(v["pid"]) is int and v["pid"] > 0 and len(v["linked_by"]) == 1
            for v in owners.values()
        ),
        "missing physical clean linkage",
    )
    return {
        role: {"pid": None, "linked_by": [], "externs": v["externs"]}
        for role, v in owners.items()
    }
