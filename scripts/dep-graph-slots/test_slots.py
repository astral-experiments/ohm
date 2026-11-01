"""Offline controls for the incoming graph, natural-Diesel roster and native result reader."""

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "darwin-pgo-diesel"))
from eager_header import scan
from graph_forensics import read, record
import native
import qualify


def refuse(call, message):
    try:
        call()
    except (ValueError, KeyError, FileNotFoundError, AssertionError):
        return
    raise AssertionError(message)


def cases():
    env = qualify.BIND
    assert env["candidate"] == "c0b318301965619c2cbd4b261ff3de84fac6831b"
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
    if a.receipt:
        packet(a.receipt)
