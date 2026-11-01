"""Bind both possible Ruff sessions before X fast-forwards and reopen the actual selected file descriptors."""

import json
import re
from pathlib import Path, PurePath

import donor_witness as dw

A = "b5dba861cc38e3f7fb4524c9ceba3e01a474ea13"
B = dw.B
SIDE = {"D": "X", "Q": "Y"}
need = dw.need


def register(first, second, role, working):
    """Keep Y-B from the cold checkout and X-A finalized before the ordinary X-B invocation."""
    need(
        role in SIDE
        and first["source"]["revision"] == B
        and second["source"]["revision"] == A
        and first["source"]["ref"] == dw.Y
        and second["source"]["ref"] == dw.X,
        "wrong Y-B or X-A training",
    )
    need(
        set(first["sessions"]) <= second["sessions"].keys()
        and all(second["sessions"][k] == v for k, v in first["sessions"].items()),
        "original Y session disappeared",
    )
    need(
        {v["owner"] for v in second["sessions"].values()} == set(dw.OWN),
        "missing or foreign Ruff owner",
    )
    result = {}
    physical = set()
    for owner in dw.OWN:
        (old,) = [p for p, r in first["sessions"].items() if r["owner"] == owner]
        (new,) = [
            p for p, r in second["sessions"].items() if r["owner"] == owner and p != old
        ]
        y, x = first["sessions"][old], second["sessions"][new]
        need(
            x["branch"] != y["branch"]
            and int(x["time"], 36) > int(y["time"], 36)
            and x["directory"] != y["directory"]
            and PurePath(old).parent == PurePath(new).parent
            and x["revision"] == A[:16]
            and y["revision"] == (None if role == "D" else B[:16]),
            "unexpected prior revision, latest checkout or session namespace",
        )
        for path, row in [(old, y), (new, x)]:
            base = PurePath(path)
            match = dw.donors.PATTERN.fullmatch(base.name)
            need(
                match
                and match.groups()[:3] == (row["time"], row["branch"], row["revision"])
                and base.is_relative_to(working / "target/debug/incremental")
                and re.fullmatch(re.escape(owner) + "-[0-9a-z]+", base.parent.name)
                and set(row["tables"]) == set(dw.donors.TABLES),
                "wrong physical owner/table pair",
            )
            for kind, table in row["tables"].items():
                p = PurePath(table["path"])
                pair = (table["dev"], table["ino"])
                need(
                    p.parent == base
                    and p.name in (kind, "ohm-packed-" + kind)
                    and all(
                        type(table[k]) is int and table[k] > 0
                        for k in ("dev", "ino", "length", "blocks")
                    )
                    and re.fullmatch("[0-9a-f]{64}", table["sha256"])
                    and pair not in physical,
                    "ambiguous original table",
                )
                physical.add(pair)
        result[owner] = {"X": x, "Y": y, "X_path": new, "Y_path": old}
    return result


def bind_sources(registration, compiles):
    """The real owner compiled in precisely the incremental directory containing the observed pair."""
    for owner, rec in registration.items():
        (worker,) = [
            c for c in compiles if c["name"] == owner and c["mode"] == "compile"
        ]
        (inc,) = [
            v.split("=", 1)[1] for v in worker["argv"] if v.startswith("incremental=")
        ]
        need(
            "-Zohm-branch-cache=yes" in worker["argv"]
            and PurePath(inc)
            == PurePath(rec["Y_path"]).parent.parent
            == PurePath(rec["X_path"]).parent.parent,
            "other crate or branch cache did not use this registered directory",
        )


def capture(arm, where, env, observer):
    role = arm[0]

    def load(p):
        return json.loads(p.read_bytes())

    root = Path(env["CARGO_TARGET_DIR"]).parent
    first, second = [
        load(where.parent / k / "donor-state.json") for k in ("Y-B", "X-A")
    ]
    registered = register(first, second, role, root)
    need(
        dw.donors.snapshot(root / "target", role, packed_git=True)
        == second["sessions"],
        "donor changed before X-B",
    )
    dw.write(where / "donor-register.json", registered)
    record = load(root.parent / "logs/sdk" / (role + ".json"))
    answer = dw.capture(
        observer.invocation,
        where,
        env,
        arm,
        record,
        registered,
        expected_side=SIDE[role],
    )
    bind_sources(registered, dw.rows(answer[2]))
    return answer


def replay(z, top, arm, record, work, get):
    states = []
    for phase in ("Y-B", "X-A"):
        key = f"{top}/{phase}/"
        state = get(z, key + "donor-state.json")
        need(
            state["source"] == get(z, key + "source.json"), "different training source"
        )
        dw.check_ledger(state, get(z, key + "path-inodes.json.gz"), work.parent)
        states.append(state)
    where = f"{top}/X-B/"
    reg = register(*states, arm[0], work)
    need(
        reg == get(z, where + "donor-register.json"),
        "different registered physical sessions",
    )
    rows = dw.rows(get(z, where + "native-execs.json.gz"))
    bind_sources(reg, rows)
    cert = get(z, top + "/arm.json")
    proof = dw.check_processes(
        get(z, where + "live-drivers.json.gz"),
        (reg, get(z, where + "donor-opens.json"), arm[0]),
        Path(cert["sdk"]) / record["driver"],
        record["files"][record["driver"]],
        rows,
        expected_side=SIDE[arm[0]],
    )
    need(
        proof == get(z, where + "donor-selected.json")
        and all(
            set(v) == {SIDE[arm[0]] + "/" + k for k in dw.donors.TABLES}
            for v in proof.values()
        ),
        "kernel did not return both chosen tables for both installed owners",
    )
    return {
        owner: {
            "donor": SIDE[arm[0]],
            "files": reg[owner][SIDE[arm[0]]]["tables"],
            "opens": rows,
        }
        for owner, rows in proof.items()
    }
