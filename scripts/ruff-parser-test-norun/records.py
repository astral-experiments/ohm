"""Read ordinary Cargo protocol records, with only the checked-out Ruff root made relative."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, sort_keys=True, indent=2) + "\n")


def load(path):
    return json.loads(Path(path).read_bytes())


def rows(path):
    return [json.loads(line) for line in Path(path).read_bytes().splitlines()]


def fingerprint(items):
    rows = sorted(json.dumps(item, sort_keys=True, separators=(",", ":")) for item in items)
    encoded = "\n".join(rows).encode()
    return digest(encoded)


def roster(events, source):
    root = "path+" + Path(source).as_uri().rstrip("/") + "/"
    typed, dirty = [], []
    for row in events:
        if row["reason"] != "compiler-artifact":
            continue
        pid = row["package_id"]
        if pid.startswith("path+"):
            assert pid.startswith(root), pid
            pid = "ruff/" + pid[len(root):]
        else:
            assert pid.startswith("registry+https://github.com/rust-lang/crates.io-index#"), pid
        target = row["target"]
        identity = [pid, target["name"], target["kind"], target["crate_types"],
                    sorted(row["features"]), row["profile"]]
        typed.append(identity)
        if not row["fresh"]:
            dirty.append(identity)
    return {"total": len(typed), "dirty": len(dirty), "all_sha256": fingerprint(typed),
            "dirty_sha256": fingerprint(dirty), "dirty_names": sorted(row[1] for row in dirty)}


def test_executable(events):
    only, = [row for row in events if row["reason"] == "compiler-artifact"
             and row["target"]["name"] == "ruff_python_parser" and row["target"]["kind"] == ["lib"]
             and row["profile"]["test"] and row["executable"]]
    assert only["executable"] in only["filenames"]
    return Path(only["executable"])


def overflow(events):
    messages = [r["message"] for r in events if r["reason"] == "compiler-message"
                and r["message"]["level"] == "error"]
    error, = messages
    span, = [s for s in error["spans"] if s["is_primary"]]
    assert error["code"]["code"] == "overflowing_literals"
    assert span["file_name"] == "crates/ruff_unicode_names2/src/lib.rs"
    assert "256" in span["text"][0]["text"] and error["message"] == "literal out of range for `u8`"
    return [span["byte_start"], span["byte_end"]]


def native_checks(inventory, one, plan):
    assert digest(inventory) == plan["inventory_sha256"]
    lines = inventory.decode().splitlines()
    assert len(lines) == len(set(lines)) == 246 and all(s.endswith(": test") for s in lines)
    assert plan["native_test"] + ": test" in lines
    assert f"test {plan['native_test']} ... ok".encode() in one.splitlines()
    assert b"1 passed; 0 failed; 0 ignored; 0 measured; 245 filtered out" in one


def count(path):
    record = load(path)
    assert record["pid"] > 0 and record["status"] == 0
    assert record["enabled"] == record["running"] > 0 and record["instructions"] > 0
    return record["instructions"]
