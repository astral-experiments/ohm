"""Physical typed/native, host, storage and full PMU reads shared with the two prior storage pilots."""

from collections import Counter
from contextlib import ExitStack
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SCREEN = HERE.parents[1] / "branch-first-session-e-screen"
sys.path[:0] = [str(HERE), str(SCREEN)]
import corpus
import hardware
import metrics
import replay_controls
import replay_elf
import replay_native
import same_branch
import tables
from replay_metrics import COMMAND, REVS, allocation, cargo_messages, measured_count, need, sha
from replay_native import raw, read

WILD = "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"


def active(z, slot, arm, inventory, source):
    rec = read(z, slot, "arm.json")
    p = inventory[arm[0]]
    roles = ["bin/cargo", "bin/rustc", "bin/rustdoc", WILD, p["driver"]]
    need(
        rec["arm"] == arm
        and rec["role"] == arm[0]
        and rec["source_manifest"] == source
        and rec["files"] == {n: p["files"][n] for n in roles},
        "reinstalled or mixed role",
    )
    env = rec["env"]
    need(
        env["CARGO_TARGET_DIR"] != env["CARGO_BUILD_BUILD_DIR"]
        and env["CARGO_NET_OFFLINE"] == "true"
        and env.get("CARGO_ENCODED_RUSTFLAGS")
        == ("-Zohm-branch-cache=yes" if arm.endswith("on") else None)
        and not ({"RUSTC", "RUSTFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER"} & env.keys()),
        "changed effective environment",
    )
    return env


EDITED = "7b40d968cd60dfabc8c36fc8437e7a583fff3fd1"
EDIT_TREE = "81d2fc20d496700e98c7efb86f4b036cd1a5f8c8"
# Previous implementation's exact 20 affected compiler-artifacts on both returns.
SWITCH = "051ce242f7e322de5461eb39ad55f6a52cd275b665490eb0c95afe678fb14d8c"
STATE = {
    "cold-A": "A",
    "first-B": "B",
    "return-A": "A",
    "return-B": "B",
    "unchanged-B": "B",
    "invalid": "B",
    "repair": "B",
    "same-cold-A": "A",
    "same-edit": "A-edit",
    "same-repeat": "A-edit",
    "same-first-B": "B",
}
SOURCE = {
    "F": "c6fe8ecda65452c105f85367a009af80cbb5efbc",
    "E": "c9a6a212d38d778ed0e9d2c7057a9dedb179fff2",
}


def compact(value):
    return sha((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())


def top(z, n):
    return json.loads(z.read(n))


def physical(z, name, desc, state, checked):
    h = desc["whole"]
    k = (h, name)
    if k not in checked:
        zip_name = f"native-bodies/{h}.zst"
        rec = replay_elf.verify(z, zip_name, desc, "ruff" if name == "cli" else None)
        fd = os.memfd_create("native-ruff-cold-control", os.MFD_CLOEXEC)
        try:
            with (
                z.open(zip_name) as packed,
                subprocess.Popen(
                    ["zstd", "-dq", "--stdout"], stdin=subprocess.PIPE, stdout=fd
                ) as inflate,
            ):
                import shutil

                with inflate.stdin:
                    shutil.copyfileobj(packed, inflate.stdin, 1 << 20)
                need(inflate.wait() == 0, "incomplete archived ELF stream")
            os.lseek(fd, 0, os.SEEK_SET)
            with os.fdopen(os.dup(fd), "rb") as body:
                need(
                    os.fstat(fd).st_size == desc["size"]
                    and hashlib.file_digest(body, "sha256").hexdigest() == h,
                    "wrong physical complete ELF",
                )
            os.fchmod(fd, 0o500)
            program = "/proc/self/fd/" + str(fd)
            with tempfile.TemporaryDirectory() as d:
                if name == "cli":
                    outcome = same_branch.oracle(program, d, state == "A-edit", pass_fds=(fd,))
                    rec["parser"] = {tag: r["exit"] for tag, r in outcome.items()}
                else:
                    p = subprocess.run(
                        [program],
                        cwd=d,
                        env={"PATH": "/usr/bin:/bin", "LANG": "C", "HOME": d},
                        capture_output=True,
                        pass_fds=(fd,),
                    )
                    want = f"Expr={56 if state=='B' else 64} valid=1 rejected"
                    need(
                        p.returncode == 0 and p.stdout.decode().strip() == want and not p.stderr,
                        "native typed AST behavior",
                    )
                    rec["typed"] = want
        finally:
            os.close(fd)
        checked[k] = rec
    if name == "cli":
        need(
            checked[k]["parser"]["case"] == int(state != "A-edit"),
            "old and repaired parser confused",
        )
    return checked[k]


def inspect_tables(z, prefix, arm, phase, ledger, previous):
    record = read(z, prefix, "table-bodies.json.gz")
    expected = tables.units(ledger)
    rs = record["sessions"]
    need(
        record["arm"] == arm and record["unit_count"] == 38 and set(rs) == set(expected),
        "incomplete table roster",
    )
    counts = Counter()
    unique = {}
    for unit, sessions in rs.items():
        need(set(sessions) == set(expected[unit]), "inconsistent finalized session inventory")
        for sess, item in sessions.items():
            if record["cold"]:
                need(len(sessions) == 1, "multiple cold sessions")
            vals = item["streams"]
            need(
                set(vals) == {"G", "Q"} and vals["G"]["mode"] == vals["Q"]["mode"],
                "partial table pair",
            )
            counts[item["classification"]] += 1
            for kind, s in vals.items():
                shape = ledger[s["path"]]
                need(
                    shape == s["stat"]
                    and s["stored_bytes"] == shape[5]
                    and s["allocated"] == shape[4] * 512
                    and s["mount_id"] > 0
                    and 0 < s["raw_bytes"] <= tables.LIMIT
                    and len(s["raw_sha256"]) == len(s["stored_sha256"]) == 64,
                    "unattested body or allocation",
                )
                if s["mode"] == "raw":
                    need(
                        (s["stored_bytes"], s["stored_sha256"])
                        == (s["raw_bytes"], s["raw_sha256"]),
                        "raw table mismatch",
                    )
                else:
                    need(
                        s["mode"] == "packed"
                        and shape[2] == 1
                        and s["path"].startswith(sess + "/ohm-packed-"),
                        "foreign packed body",
                    )
                need(
                    sorted(s["all_visible_aliases"])
                    == sorted(n for n in s["all_visible_aliases"] if ledger[n][:2] == shape[:2]),
                    "wrong table aliases",
                )
                unique[tuple(shape[:2])] = s["allocated"]
    if record["cold"] and arm != "Eon":
        need(
            set(counts) <= {"raw-in-size-range", "outside-codec-size", "additional-hardlink"},
            "unexpected prior cold compaction",
        )
    if previous is not None:
        need(
            tables.relate(previous, record, phase) == read(z, prefix, "table-transitions.json"),
            "false table transition",
        )
    return record, {
        "owners": len(rs),
        "classifications": dict(counts),
        "allocated": sum(unique.values()),
    }


def operation(z, prefix, arm, lane, phase, state, env, parsers, ref=None):
    failed = phase == "invalid"
    code = 101 if failed else 0
    expected_commit = EDITED if state == "A-edit" else REVS[state]
    src = read(z, prefix, "source.json")
    need(
        src["commit"] == expected_commit
        and src["tree"] == (EDIT_TREE if state == "A-edit" else corpus.TREES[state]),
        "different source tree",
    )
    if "watched" not in src:
        need(
            src["registry_lock"] == corpus.LOCK
            and (src["parser_sha256"] == parsers[state]) == (not failed)
            and src["status"] == ("M " + corpus.FILE if failed else ""),
            "source dirty state",
        )
    process = read(z, prefix, "cargo.json.gz")
    need(
        process["env"] == env
        and process["expected"] == code
        and process["stdin_sha256"] == sha(b""),
        "different Cargo environment",
    )
    if lane != "measured":
        need(
            process["observer_argv"] is None and prefix + "/clock.json" not in z.NameToInfo,
            "instrumented native control",
        )
    else:
        need(
            process["observer_argv"][-len(COMMAND) :] == COMMAND
            and len(process["observer_argv"]) == 2 + len(COMMAND)
            and process["observer_argv"][0].endswith("/observers/plain")
            and process["observer_argv"][1].endswith("/" + prefix + "/clock.json"),
            "wrapped hardware workload",
        )
    roster = cargo_messages(
        raw(z, prefix, "cargo.stdout.gz"),
        raw(z, prefix, "cargo.stderr.gz"),
        process,
        code,
        process["cwd"],
    )
    ledger = read(z, prefix, "path-inodes.json.gz")
    disk = read(z, prefix, "storage.json")
    value = allocation(ledger, disk, read(z, prefix, "allocation-readers.json"))
    if arm != "Eon" or phase in (
        "cold-A",
        "same-cold-A",
        "same-empty-edit",
        "cold-B",
        "same-edit",
        "same-repeat",
    ):
        need(
            disk["packed_files"] == disk["packed_bytes"] == 0,
            "unexpected compressed native codegen",
        )
    elif phase in ("first-B", "return-A", "return-B", "unchanged-B", "same-first-B"):
        need(
            disk["packed_files"] > 0 and disk["packed_bytes"] > 0,
            "E did not preserve any packed native codegen on the real switch",
        )
    v = read(z, prefix, "visit.json")
    need(
        (v["status"], v["arm"], v["phase"], v["branch"], v["source"], v["allocated"])
        == (code, arm, phase, state, expected_commit, value),
        "bad stored visit",
    )
    if failed:
        need(
            sorted(read(z, prefix, "working.json")) == disk["failed_sessions"],
            "failure session attribution",
        )
        diags = read(z, prefix, "diagnostics.json.gz")
        cargo_raw = raw(z, prefix, "cargo.stdout.gz")
        all_errors = [
            e
            for e in map(json.loads, cargo_raw.splitlines())
            if e["reason"] == "compiler-message" and e["message"].get("level") == "error"
        ]
        tagged = [e for e in all_errors if e["message"].get("code")]
        need(
            diags == all_errors
            and tagged
            and all(
                e["target"]["name"] == "ruff_python_parser"
                and e["message"]["code"]["code"] == "E0308"
                and any(
                    "ohm_branch_switch_invalid" in t["text"]
                    for span in e["message"]["spans"]
                    for t in span["text"]
                )
                for e in tagged
            ),
            "genuine bad edit missing",
        )
        return {"record": v, "allocated": value}, ledger
    need(
        not disk["failed_sessions"]
        and roster == read(z, prefix, "roster.json.gz")
        and v["dirty"] == len(roster["dirty"])
        and v["artifact_count"] == 375
        and v["graph"] == compact(roster["members"])
        and v["dirty_digest"] == compact(roster["dirty"]),
        "typed graph/dirty mismatch",
    )
    if lane == "clean" or phase in ("cold-A", "same-cold-A"):
        need(len(roster["dirty"]) == 375, "not independently cold")
    if phase in ("first-B", "return-A", "return-B"):
        need(
            len(roster["dirty"]) == 20 and compact(roster["dirty"]) == SWITCH,
            "different edited workload",
        )
    if phase in ("unchanged-B", "same-repeat"):
        need(
            [(q["name"], q["kind"]) for q in roster["dirty"]] == [("ruff", ["bin"])],
            "different true repeat",
        )
    with patch.dict(replay_native.REVS, {"A": EDITED}) if state == "A-edit" else ExitStack():
        native = replay_native.native_verdict(z, prefix, "B" if state == "B" else "A")
    need(
        v["cli"] == native["cli"]["whole"] and v["reader"] == native["reader"]["whole"],
        "wrong native product",
    )
    if "watched" in src:
        parsed = read(z, prefix, "28233.json")
        for tag, raw_input in (("case", same_branch.BAD), ("neighbor", same_branch.GOOD)):
            line = parsed[tag]
            expected_bad = tag == "case" and state != "A-edit"
            need(
                line["exit"] == int(expected_bad)
                and line["stdin"].encode() == raw_input
                and line["stderr"].encode() == same_branch.WARNING,
                "different real syntax-case command verdict",
            )
            messages = json.loads(line["stdout"])
            if expected_bad:
                need(
                    len(messages) == 1
                    and messages[0]["code"] == "invalid-syntax"
                    and messages[0]["message"] == "Expected a numeric literal after unary operator"
                    and messages[0]["location"] == {"row": 2, "column": 11}
                    and messages[0]["end_location"] == {"row": 2, "column": 15},
                    "different actual parser rejection",
                )
            else:
                need(messages == [], "false neighboring syntax-case success")
    if ref is not None:
        need(
            roster["members"] == ref["members"]
            and native == ref["native"]
            and v["native_output"] == ref["record"]["native_output"],
            "native or typed output does not match independent same-placement clean",
        )
    return {"record": v, "allocated": value, "native": native, "members": roster["members"]}, ledger


def peak_rows(z, order):
    cap = top(z, "peak-capability.json")
    mode = z.read("storage-mode.txt").decode().strip()
    results = {}
    need(
        mode in ("private-ext4", "runner-filesystem") and isinstance(cap["available"], bool),
        "no authenticated storage backend",
    )
    if cap["available"]:
        need(
            mode == "private-ext4"
            and cap["before"] == cap["after"]
            and cap["held"] - cap["before"] >= 4 << 20
            and cap["allocated_inode"] == 4 << 20
            and cap["mount"]["findmnt"]["fstype"] == "ext4",
            "uncalibrated sampled filesystem high water",
        )
    fn = "sampled-filesystem.json"
    for arm in order:
        limits = {}
        for study, ps in (
            ("main", ("cold-A", "first-B")),
            ("same", ("same-cold-A", "same-edit", "same-first-B")),
        ):
            for ph in ps:
                v = read(z, f"ordinary/{arm}/{study}/{ph}", fn)
                if not v["available"]:
                    need(
                        isinstance(v.get("reason"), str),
                        "unexplained missing transient observation",
                    )
                    limits[ph] = {"available": False, "reason": v["reason"]}
                    continue
                sam = v["samples"]
                idle = v["idle"]
                need(
                    cap["available"]
                    and v["mount"] == cap["mount"]
                    and len(sam) >= 2
                    and len(idle) == 5
                    and len({(x[1], x[2]) for x in idle}) == 1
                    and sam[0] == idle[-1]
                    and all(t[1] == sam[0][1] for t in sam)
                    and all(b[0] > a[0] for a, b in zip(sam, sam[1:]))
                    and v["max_gap_ns"] == max(b[0] - a[0] for a, b in zip(sam, sam[1:]))
                    and v["maximum_observed_allocated_bytes"] == max(t[1] * t[2] for t in sam),
                    "nonreproducible transient sample",
                )
                limits[ph] = {
                    k: v[k]
                    for k in (
                        "available",
                        "scope",
                        "max_gap_ns",
                        "maximum_observed_allocated_bytes",
                    )
                }
        results[arm] = limits
    need(
        not any(n.startswith("measured/") and n.endswith("/" + fn) for n in z.namelist()),
        "transient observer in instruction lane",
    )
    return {"capability": cap, "backend": mode, "phases": results}


def unmetered(z, en, inputs, parsers, source_media):
    order = en["order"]
    boot = en["boot"]
    n = top(z, "complete.json")
    need(
        n["host_complete"]
        and n["order"] == order
        and n["main"] == list(metrics.PHASES)
        and n["same"] == list(metrics.SAME)
        and n["scheduled_counts_unscaled"],
        "incomplete source histories",
    )
    need(top(z, "ruff-inputs.json") == inputs, "different historical inputs")
    ready = top(z, "meter-ready.json")
    need(ready["boot"] == boot, "wrong calibrated boot")
    c = replay_controls.calibration(z, boot)
    hw = hardware.verify(z, c, ready)
    need(
        c["affinity"] == list(range(8))
        and c["cpu"]
        == {
            "vendor_id": "AuthenticAMD",
            "cpu family": "26",
            "model": "68",
            "model name": "AMD EPYC",
            "stepping": "0",
        }
        and c["platform"]["machine"] == "x86_64"
        and c["platform"]["system"] == "Linux",
        "different qualified CPU or scope",
    )
    hw["host"] = c
    roles = {r: read(z, "sdk", r + ".json") for r in SOURCE}
    native_paths = {
        "E": (source_media["E"], en["E"]["qualified"]["manifest"]),
        "F": (source_media["F"], en["F"]["manifest"]),
    }
    for role, s in roles.items():
        source = s["source"]
        path, digest = native_paths[role]
        with zipfile.ZipFile(path) as immutable:
            mb = immutable.read("manifest.json")
            manifest = json.loads(mb)
        expected = manifest["source"] if role == "E" else manifest["roles"][role]
        files = manifest["files"] if role == "E" else manifest["files"][role]
        need(
            sha(mb) == digest
            and source == expected
            and (source["role"] if role == "E" else source)["commit"] == SOURCE[role]
            and s["role"] == role
            and s["driver"] == manifest["driver"]
            and len(files) == 81
            and {k: [v[0], v[4], v[3]] for k, v in s["files"].items()} == files,
            "wrong physical SDK or role manifest",
        )

    roles_equal = set(roles["F"]["files"]) == set(roles["E"]["files"])
    changed = {
        k for k in roles["E"]["files"] if roles["E"]["files"][k][0] != roles["F"]["files"][k][0]
    }
    need(
        roles_equal and changed == {roles["F"]["driver"], "bin/rustdoc"}, "uncontrolled SDK members"
    )
    terminal = read(z, "sdk", "terminal.json")
    need(
        terminal["both_complete_byte_and_inode_inventories_unchanged"]
        and terminal["registry"] == compact(inputs["archives"]),
        "terminal compilation input",
    )
    reps = {}
    refs = {}
    envs = {}
    controls = {}
    per_arm = {}
    tables_by_arm = {}
    for arm in order:
        digest = en["F"]["manifest"] if arm[0] == "F" else en["E"]["qualified"]["manifest"]
        env = active(z, "clean/" + arm, arm, roles, digest)
        envs[arm] = env
        for state, ph in (("A", "cold-A"), ("B", "cold-B"), ("A-edit", "same-empty-edit")):
            p = f"clean/{arm}/{state}"
            v, _ = operation(z, p, arm, "clean", ph, state, env, parsers)
            refs[arm, state] = v
            for kind in ("cli", "reader"):
                physical(z, kind, v["native"][kind], state, reps)
        controls[arm] = replay_controls.native_provider(z, arm)
        per_arm[arm] = {}
        tables_by_arm[arm] = {}
        for study, phases in (("main", metrics.PHASES), ("same", metrics.SAME)):
            slot = f"ordinary/{arm}/{study}"
            need(active(z, slot, arm, roles, digest) == env, "native lane variant")
            last = None
            for ph in phases:
                state = STATE[ph]
                prefix = slot + "/" + ph
                v, ledger = operation(
                    z, prefix, arm, "ordinary", ph, state, env, parsers, refs[arm, state]
                )
                per_arm[arm][ph] = v["record"]
                if ph in (
                    "cold-A",
                    "first-B",
                    "same-cold-A",
                    "same-edit",
                    "same-repeat",
                    "same-first-B",
                ):
                    last, summary = inspect_tables(z, prefix, arm, ph, ledger, last)
                    tables_by_arm[arm][ph] = summary
                if ph == "same-repeat":
                    need(
                        read(z, prefix, "source.json")["watched"]
                        == read(z, slot + "/same-edit", "source.json")["watched"],
                        "repeated ref mutation",
                    )
    for state in ("A", "B", "A-edit"):
        left = refs[order[0], state]
        for arm in order[1:]:
            right = refs[arm, state]
            need(left["members"] == right["members"], "cross-arm typed graph difference")
            for kind in ("cli", "reader"):
                for key in ("loads", "executable"):
                    need(
                        left["native"][kind][key] == right["native"][kind][key],
                        "different executable/load section payload",
                    )
            need(
                all(
                    left["native"][k] == right["native"][k]
                    for k in ("typed", "cli_cases", "fstring_cases")
                ),
                "different native verdict",
            )
    return {
        "roles": roles,
        "refs": refs,
        "envs": envs,
        "visits": per_arm,
        "native": list(reps.values()),
        "providers": controls,
        "tables": tables_by_arm,
        "calibration": hw,
        "transient": peak_rows(z, order),
    }
