"""Offline controls for the incoming graph, natural-Diesel roster and native result reader."""

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "darwin-pgo-diesel"))
from eager_header import scan
from graph_forensics import read, record
import native
import qualify
import release_smoke
import published


def refuse(call, message):
    try:
        call()
    except (ValueError, KeyError, FileNotFoundError, AssertionError):
        return
    raise AssertionError(message)


def cases():
    live = copy.deepcopy(published.REGISTER)
    live["draft"] = False
    for asset in live["assets"]:
        asset["state"] = "uploaded"
    tag = {"ref":"refs/tags/" + published.TAG,"object":{"type":"commit", "sha":qualify.BIND["release_coordinator"]}}
    for host in qualify.HOSTS.values():
        accepted = published.admit(live, tag, host)
        assert len(accepted) == 5 and accepted[published.TAG + "-" + host + ".tar.gz"]["size"] > 200_000_000
        bad = copy.deepcopy(live)
        next(a for a in bad["assets"] if a["name"].endswith(host + ".tar.gz"))["digest"] = "sha256:" + "0" * 64
        refuse(lambda: published.admit(bad, tag, host), "changed official distribution bytes")
        refuse(lambda: published.admit(live | {"draft":True}, tag, host), "draft release")
        refuse(lambda: published.admit(live, tag | {"object":{"type":"commit", "sha":qualify.CHILD}}, host), "different published tag")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        installed = root / "bin"
        installed.mkdir()
        for tool in ("rustup", "rustc", "cargo"):
            launcher = installed / tool
            launcher.write_text(f"#!/bin/sh\nprintf '%s\\n' '{tool}'\n")
            launcher.chmod(0o755)
        proxies = root / "proxies"
        got = release_smoke.named_proxies(proxies, installed / "rustup")
        for tool, row in got.items():
            assert subprocess.check_output([proxies / tool]).decode().strip() == tool
            assert row["sha256"] == qualify.checksum(installed / tool)
        old = root / "old-rustc"
        old.symlink_to(installed / "rustup")
        assert subprocess.check_output([old]).decode().strip() == "rustup"
        (installed / "cargo").unlink()
        refuse(lambda: release_smoke.named_proxies(root / "missing", installed / "rustup"), "missing Cargo entrypoint")

    env = qualify.BIND
    assert env["candidate"] == "6318c9795bf996860175bb3396be8673fb5952b5"
    assert env["worktree_native"]["rust"] == "494d4afc2e0b2e995000d345c8bfef4e2a4c6e3e"
    assert env["last_native"]["rust"] == "0c66092268115dc8cc72c6f2046bd7430ff45691"
    assert env["prior_native"]["rust"] == "dc70b47e9ff1926562626246bf996b824a456259"
    assert env["graph_candidate"] == "1686aef9877e0c95faddf6f9c313e451a9744f29"
    assert env["cargo_commits"][-1] == env["trees"]["src/tools/cargo"] == "fd98ecd186d2bb8d8e0455561c4257e90e1bff02"
    assert set(env["cargo_changed_blobs"]) == {"src/compiler/native_link/declared.rs", "src/compiler/native_link/mod.rs",
            "src/compiler/build_runner/compilation_files.rs", "src/compiler/mod.rs", "src/ops/cargo_worktree/mod.rs",
            "tests/testsuite/ohm_worktree.rs", "tests/testsuite/rustflags.rs", "src/ops/cargo_test/ready_test_process.rs",
            "src/ops/cargo_test/ready_tests.rs", "tests/testsuite/ohm_ready_tests.rs"}
    assert set(env["ready_changes"]) == set(env["cargo_commits"][-2:])
    assert set(env["worktree_changes"]) == set(env["cargo_commits"][-4:-2])
    assert env["parent"] == "008a21ac0d750dc9a1c18b7959d7e7984c03d887"
    assert env["previous_slot_candidate"] == "c0b318301965619c2cbd4b261ff3de84fac6831b"
    assert env["release_coordinator"] == "8c7d5b4500fdfa6e2234417340aa190e5787e513"
    assets = HERE / "release-22"
    for name, value in env["release_files"].items():
        b = (assets / name).read_bytes()
        assert [len(b), hashlib.sha256(b).hexdigest()] == value
    manifest = json.loads((assets / "22.json").read_bytes())
    assert manifest["sources"]["rust"]["revision"] == env["parent"]
    assert (
        manifest["sources"]["cargo"]["revision"]
        == env["shipped_cargo"]
        == "ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770"
    )
    candidate = json.loads((assets / "23.json").read_bytes())
    assert candidate["release"]["toolchain_name"] == env["candidate_toolchain"] == "ohm-1.99.0-23"
    assert manifest["release"]["toolchain_name"] == "ohm-1.99.0-22"
    assert env["candidate_packaging"] == {"commit":"99aaccb2f2eb778831a7522d5b8542d7ddac7f29", "manifest_blob":"fbfe9bf54e4bd366dfa6e6e6db30a2a9aaf40a86"}
    assert {k: v["revision"] for k,v in candidate["sources"].items()} == {
        **{k:v["revision"] for k,v in manifest["sources"].items()}, "rust":env["candidate"], "cargo":env["trees"]["src/tools/cargo"]}
    assert env["release_files"]["smoke-test-relink.sh"] == [
        6712,
        "e57b87041abe1f91c78c29bb26e276e7ccd41e8f33a360aec616fb260d7ec175",
    ]
    assert set(env["files"]) == {
        "compiler/rustc_incremental/src/persist/load.rs",
        "compiler/rustc_middle/src/dep_graph/serialized.rs",
        "tests/run-make/incremental-missing-query-cache/rmake.rs",
    }
    pack = (HERE / "source.pack").read_bytes()
    assert hashlib.sha256(pack).hexdigest() == env["pack"]["sha256"] and len(pack) == env["pack"]["bytes"]
    assert hashlib.sha1(pack[:-20]).digest() == pack[-20:]
    assert struct.unpack(">II", pack[4:12]) == (2, 3156)
    raw = gzip.decompress((HERE / "parent-graph.gz").read_bytes())
    assert (
        hashlib.sha256(raw).hexdigest()
        == "cb48adbfc616ceed962d29b17f2171aa6d22788c703a6bffbddeb2745ce18220"
        and read(raw)["accepted"]
    )
    start = 7 + raw[6] + 8
    # Move an entire variable-length physical record to the front. Both reserved IDs now
    # follow the injected row, and the next header is not at a fixed 38-byte stride.
    end = start
    for _ in range(100):
        row = record(raw, end, 362)
        if row["edges"] and row["index"] not in (0, 1):
            break
        end = row["end"]
    else:
        raise AssertionError("real variable-size row missing")
    relocated = raw[:start] + raw[end : row["end"]] + raw[start:end] + raw[row["end"] :]
    assert read(relocated)["accepted"] and scan(relocated)["all_node_headers_passed"]
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "dep-graph.bin"
        for incoming in [raw, relocated]:
            for kind, reason in [
                ("null", "incoming Null"),
                ("duplicate", "duplicate node index"),
                ("range", "destination index out of range"),
            ]:
                p.write_bytes(incoming)
                native.damage(p, kind)
                actual = scan(p.read_bytes())
                assert actual["failure"] == reason
                if kind == "duplicate":
                    assert actual["destination_previously_occupied"] and actual["ordinal"] > 0
        for invalid in [b"", b"RSIC" + bytes(90)]:
            p.write_bytes(invalid)
            refuse(lambda: native.damage(p, "duplicate"), "foreign file accepted")
    print(
        "Physical parent graph accepted before and after an arbitrary complete-row move; 6 directed slot faults and 2 negative headers distinguished."
    )


def provider_controls():
    digest = lambda tag: hashlib.sha256(str(tag).encode()).hexdigest()
    statuses = {
        "seed": 17,
        "unchanged": 17,
        "new": 29,
        "new-clean": 29,
        "bad": None,
        "bad-clean": None,
        "restored": 17,
        "old-clean": 17,
    }
    rows = {
        p: {
            "status": 0 if tag else 101,
            "links": 1,
            "closures": {},
            **({"elf": digest(tag), "value": tag} if tag else {}),
        }
        for p, tag in statuses.items()
    }
    depfiles = {
        "old": "libohm_private.a",
        "new": "libohm_private.so",
        "bad": "",
        "restored": "libohm_private.a",
    }
    native = {
        p: {"link": 0 if tag else 1, "exit": tag, "depfile": depfiles[p]}
        for p, tag in [("old", 17), ("new", 29), ("bad", None), ("restored", 17)]
    }
    fixture = {
        "wild": {"sha256": release_smoke.WILD},
        "cargo": rows,
        "direct": {tool: copy.deepcopy(native) for tool in ("gnu", "wild")},
        "commands": {
            "cargo-" + phase: {
                "argv": ["cargo", "+ohm", "build", "--offline", "--message-format=json"],
                "status": row["status"],
            }
            for phase, row in rows.items()
        },
    }
    assert release_smoke.assess_transitive(fixture)["qualified"]
    stale = copy.deepcopy(fixture)
    stale["cargo"]["new"].update(value=17, elf=digest(17), links=0)
    assert not release_smoke.assess_transitive(stale)["qualified"]
    stale["cargo"]["new"].update(value=29)
    assert not release_smoke.assess_transitive(stale)["qualified"]  # same tag, wrong ELF
    for edit in ["missing", "forged-command", "different-provider", "wrong-clean", "unbound-Wild"]:
        wrong = copy.deepcopy(fixture)
        if edit == "missing":
            del wrong["cargo"]["unchanged"]
        if edit == "forged-command":
            wrong["commands"]["cargo-new"]["argv"].append("--release")
        if edit == "different-provider":
            wrong["direct"]["wild"]["new"]["depfile"] = "libohm_private.a"
        if edit == "wrong-clean":
            wrong["cargo"]["new-clean"]["value"] = 17
        if edit == "unbound-Wild":
            wrong["wild"]["sha256"] = "0" * 64
        refuse(lambda: release_smoke.assess_transitive(wrong), edit)
    assert (
        release_smoke.checksum(HERE / "gnu_transitive.py")
        == "ed5166df83e6b6230e134e33b30be5bf398f0992312d3777d5c63fb64ae218d4"
    )
    print(
        "Transitive GNU qualification detects stale output, byte disagreement and five malformed registrations."
    )


def packet(source):
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "receipt"
        shutil.copytree(source, dest)

        def run():
            qualify.validate_native(dest, "parent", False, allow_proxy=True)

        run()
        archived = list(dest.glob("*.native"))
        assert archived
        for binary in archived:
            binary.chmod(0o644)
        run()
        assert all(binary.stat().st_mode & 0o777 == 0o644 for binary in archived)
        receipt = dest / "native.json"
        original = receipt.read_bytes()
        for mode in [
            "gone",
            "extra",
            "unchecked",
            "wrong-native",
            "lost-diagnostic",
            "wrong-driver",
            "wrong-graph",
            "wrong-verdict",
        ]:
            j = json.loads(original)
            steps = j["steps"]
            row = next(x for x in steps if x["name"] == "range-parent")
            if mode == "gone":
                steps.pop()
            if mode == "extra":
                steps.append(copy.deepcopy(steps[-1]))
            if mode == "unchecked":
                row["argv"].remove("-Zincremental-verify-ich")
            if mode == "wrong-native":
                next(x for x in steps if x["name"] == "both-repair-B")["elf"] = steps[0]["elf"]
            if mode == "lost-diagnostic":
                row["stderr_sha256"] = "0" * 64
            if mode == "wrong-driver":
                j["consumer"]["driver_sha256"] = "0" * 64
            if mode == "wrong-graph":
                j["ordinary"]["range"]["mutations"][0]["after"] = j["ordinary"]["null"]["mutations"][0][
                    "after"
                ]
            if mode == "wrong-verdict":
                row["code"] = 0
            receipt.write_text(json.dumps(j))
            refuse(run, mode)
        receipt.write_bytes(original)
        body = next((dest / "bodies").glob("*.gz"))
        backup = body.read_bytes()
        body.unlink()
        refuse(run, "missing input bytes")
        body.write_bytes(backup)
        run()
    print("Authenticated 19-source-compiler parent outcome and nine independent raw/evidence mutations.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--receipt", type=Path)
    a = p.parse_args()
    cases()
    provider_controls()
    if a.receipt:
        packet(a.receipt)
