"""The accepted original native contact, two prospectively ordered boots and the complete Cargo counter contract."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract as q

BRANCH = "charlie/qa-ctfe-integration-hardware-20261101"
CONTACT = "6bb98896980d427001e7a4ec7a687aaf730774ba"
REGISTERED = {
    "run": 41296525800,
    "job": 124818429492,
    "artifact": 13080217225,
    "head": CONTACT,
    "attempt": 1,
    "sha256": "04bff62d505eb417d0494188db5c1d96bf92f4107fdc581b942c649cbe5b3f0f",
    "bytes": 360940419,
    "boot": "c69b6a00-118b-4d4e-bc44-f62b8fc8913d",
    "independent_sha256": "8319290a740374d368a225a99c767321df4bf9a02fc1400e34549e18f32d2fb1",
}
ORDER = {"01": ("Eon", "Con"), "02": ("Con", "Eon")}
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


def enrolled(original):
    o = original["official"]
    q.need(
        all(
            o[k] == REGISTERED[k]
            for k in ("attempt", "run", "job", "artifact", "head", "bytes", "sha256")
        )
        and original["boot"] == REGISTERED["boot"]
        and original["contact_only"] is True
        and [
            original[k]
            for k in (
                "commands",
                "complete_96_case_suites",
                "expected_E0308",
                "semantic_commands",
                "scored",
            )
        ]
        == [24, 18, 2, 4, 0]
        and original["continuation"]["eligible"] is True,
        "unqualified genuine native antecedent",
    )
    rows = original["records"]
    for arm, full in (("Eon", 21), ("Con", 4)):
        native = rows[arm]["comment"]["physical"]
        q.need(
            not native["link_only"]
            and len(native["full"]) == full
            and len(native["wild"]) == 2
            and rows[arm]["comment"]["wild_outputs"]
            == ["integration_test::integration_test", "ruff::ruff"]
            and rows[arm]["comment"]["suite_count"] == 96
            and rows[arm]["invalid"]["status"] == 101,
            "wrong native branch edit or link outcome",
        )
    return {
        "registered": REGISTERED,
        "comment_full": {k: len(v["comment"]["physical"]["full"]) for k, v in rows.items()},
        "comment_wild_outputs": {k: v["comment"]["wild_outputs"] for k, v in rows.items()},
    }


def raw_contact(d, upstream, ruff, kernel):
    """Execute the untouched contact checker against the one authenticated public original."""
    media = d / "original.zip"
    q.need(
        q.git(upstream, "rev-parse", "HEAD") == CONTACT
        and not q.git(
            upstream,
            "status",
            "--porcelain",
            "--",
            "scripts/ctfe-integration-contact",
            ".github/workflows/ci.yml",
        ),
        "unregistered original checker or workflow",
    )
    reader = upstream / "scripts/ctfe-integration-contact/reopen_contact.py"
    cmd = [
        sys.executable,
        "-IB",
        str(reader),
        str(media),
        str(d),
        "--run",
        str(REGISTERED["run"]),
        "--head",
        CONTACT,
        "--kernel",
        str(kernel),
        "--ruff",
        str(ruff),
    ]
    raw = subprocess.check_output(cmd)
    q.need(
        hashlib.sha256(raw).hexdigest() == REGISTERED["independent_sha256"], "foreign native certificate"
    )
    head = enrolled(json.loads(raw))
    hashes = {}
    with zipfile.ZipFile(media) as z:
        for arm in q.ARMS:
            hashes[arm] = {}
            for phase in (*q.PHASES, "semantic-edit", "semantic-empty"):
                data = json.loads(gzip.decompress(z.read(f"{arm}/{phase}/roster.json.gz")))
                hashes[arm][phase] = {k: q.sha(canonical(data[k])) for k in ("units", "dirty")}
    return {**head, "roster": hashes}


def get_original(dest):
    q.need(
        dest.is_absolute()
        and not dest.exists()
        and dest.parent == dest.parent.resolve()
        and os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
        and os.environ["GITHUB_ACTIONS"] == "true",
        "incorrect contact intake",
    )
    dest.mkdir()
    repo = "repos/astral-experiments/ohm"
    r = REGISTERED
    for name, s in (
        ("run", f"actions/runs/{r['run']}"),
        ("jobs", f"actions/runs/{r['run']}/attempts/1/jobs?per_page=100"),
        ("artifacts", f"actions/runs/{r['run']}/artifacts?per_page=100"),
    ):
        b = subprocess.check_output(["gh", "api", f"{repo}/{s}"])
        q.need(0 < len(b) < 1 << 20, "unexpected metadata extent")
        (dest / (name + ".json")).write_bytes(b)
    sender = json.loads((dest / "artifacts.json").read_bytes())
    (a,) = sender["artifacts"]
    q.need(
        a["id"] == r["artifact"]
        and a["name"] == "ctfe-integration-contact-original"
        and not a["expired"]
        and a["size_in_bytes"] == r["bytes"]
        and a["digest"] == "sha256:" + r["sha256"]
        and a["workflow_run"]["id"] == r["run"]
        and a["workflow_run"]["head_sha"] == r["head"],
        "unbound original",
    )
    with subprocess.Popen(
        ["gh", "api", f"{repo}/actions/artifacts/{a['id']}/zip"], stdout=subprocess.PIPE
    ) as p, (dest / "original.zip").open("xb") as f:
        n = 0
        h = hashlib.sha256()
        while chunk := p.stdout.read(1 << 20):
            n += len(chunk)
            q.need(n <= r["bytes"], "oversize original")
            h.update(chunk)
            f.write(chunk)
        q.need(
            p.wait() == 0 and n == r["bytes"] and h.hexdigest() == r["sha256"],
            "incomplete official original",
        )


def fresh_boot(boot):
    q.excluded_boot(boot)
    exclusions = json.loads((HERE / "additional-boots.json").read_bytes())
    q.need(boot != REGISTERED["boot"] and boot not in exclusions, "kernel boot already used")


def reference_owners(owners):
    q.need(
        set(owners) == {"cli", "harness"}
        and all(
            type(v["pid"]) is int and v["pid"] > 0 and len(v["linked_by"]) == 1 for v in owners.values()
        ),
        "missing physical clean linkage",
    )
    return {role: {"pid": None, "linked_by": [], "externs": v["externs"]} for role, v in owners.items()}


def rosters_admit(reference, arm, phase, whole, dirty):
    q.need(
        arm in q.ARMS and phase in q.PHASES + ("semantic-edit", "semantic-empty"), "unregistered phase"
    )
    if phase != "invalid":
        value = {k: q.sha(canonical(v)) for k, v in (("units", whole), ("dirty", dirty))}
        q.need(
            value == reference["roster"][arm][phase] and len(whole) == 390,
            ("changed authenticated typed graph or dirty units", arm, phase, value),
        )


def outcomes(records):
    all_counts = {}
    for arm in q.ARMS:
        q.need(set(records[arm]) == set(q.PHASES), "missing source visits")
        all_counts[arm] = {phase: timed(records[arm][phase]["clock"], phase) for phase in q.HISTORY}
    e, c = all_counts["Eon"], all_counts["Con"]
    return {
        "instructions": all_counts,
        "primary_comment_ratio": [e["comment"], c["comment"]],
        "strictly_over_two": e["comment"] > 2 * c["comment"],
        "individual_ratios": {ph: [e[ph], c[ph]] for ph in q.HISTORY},
        "sum_comment_and_unchanged": [a["comment"] + a["unchanged"] for a in (e, c)],
        "sum_seven_command_counts": [sum(a.values()) for a in (e, c)],
    }


def pair(rows):
    q.need(set(rows) == set(ORDER), "two independent qualified boots required")
    q.need(
        len({r["boot"] for r in rows.values()})
        == len({r["runner"] for r in rows.values()})
        == len({r["job"] for r in rows.values()})
        == 2
        and len({r["head"] for r in rows.values()}) == len({r["run"] for r in rows.values()}) == 1,
        "repeated workers or mixed study",
    )
    for pos, r in rows.items():
        q.need(
            r["position"] == pos
            and list(ORDER[pos]) == r["order"]
            and r["prerequisite"] == REGISTERED
            and r["qualified"] is True
            and r["complete_96_case_suites"] == 18
            and r["semantic_commands"] == 4
            and r["boot"]
            not in set(json.loads((HERE / "additional-boots.json").read_bytes())) | {REGISTERED["boot"]},
            "wrong product, source, position or host",
        )
        q.excluded_boot(r["boot"])
        stop = 0
        for arm in ORDER[pos]:
            for phase in q.HISTORY:
                clk = r["records"][arm][phase]["clock"]
                timed(clk, phase)
                q.need(clk["start"] > stop, "counter windows overlap or role order differs")
                stop = clk["stop"]
        q.need(r["observed"] == outcomes(r["records"]), "unverified results")
    return {
        "positions": {k: r["observed"] for k, r in rows.items()},
        "both_strictly_over_two": all(r["observed"]["strictly_over_two"] for r in rows.values()),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("work", type=Path)
    get_original(p.parse_args().work)
