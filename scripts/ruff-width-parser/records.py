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



def overflow(events, controls):
    errors = [e["message"] for e in events if e["reason"] == "compiler-message" and e["message"]["level"] == "error"]
    error, = errors
    span, = [s for s in error["spans"] if s["is_primary"]]
    assert error["code"]["code"] == "overflowing_literals" and error["message"] == controls["message"]
    assert span["file_name"] == controls["path"] and [span["byte_start"], span["byte_end"]] == controls["span"]
    assert "65536" in span["text"][0]["text"]
    return {"source": span["file_name"], "message": error["message"], "span": controls["span"], "line": span["line_start"]}

def from_counter(data, expected_exit=0):
    assert data["status"] == expected_exit and data["pid"] > 0 and data["enabled"] == data["running"] > 0
    assert data["instructions"] > 0
    return data["instructions"]

def physical(read, installed, expected_version, edit):
    images = {}
    counted = []
    whole = []
    for line in read("epochs.tsv").decode().splitlines():
        col = line.split()
        if col[0] == "I":
            idx, pid = map(int, col[1:3])
            body = read(f"{idx:05}.nul").split(b"\0")
            assert idx not in images and body.pop() == b"" and int(body[0]) == pid
            images[idx] = pid, int(body[1]), int(body[2]), [a.decode() for a in body[4:]], col[-1]
        elif col[0] == "R":
            idx, pid, ins, en, ran, status = map(int, col[1:])
            seen, dev, ino, argv, start = images[idx]
            assert pid == seen and start == "exec" and en == ran > 0 and ins > 0 and status == 0
            tool, = [n for n in ("rustc", "Wild") if (dev, ino) == (installed[n]["device"], installed[n]["inode"])]
            name = argv[argv.index("--crate-name") + 1] if "--crate-name" in argv else None
            counted.append({"image": idx, "tool":tool, "pid":pid, "argv":argv, "name":name, "instructions":ins})
        elif col[0] == "W":
            ins, en, ran, status = map(int, col[1:])
            assert ins > 0 and en == ran > 0 and status == 0
            whole.append(ins)
    assert len(whole) == 1 and len({r["image"] for r in counted}) == len(counted)
    owner, = [r for r in counted if r["tool"] == "rustc" and r["name"] == "unicode_width"]
    args = owner["argv"]
    inputs = [s for s in args if s.endswith("/unicode-width-" + expected_version + "/src/lib.rs")]
    assert len(inputs) == 1 and "/registry/src/" in inputs[0]
    assert "--emit=dep-info,metadata" in args and "-Zlink-only" not in args
    for flag in ("-Zpublic-api-hash", "-Zthreads=8", "debuginfo=line-tables-only", "checksum-hash-algorithm=blake3"):
        assert flag in args, (flag, args)
    if edit:
        assert sorted(r["name"] for r in counted if r["name"]) == sorted(
            ["unicode_width", "ruff_formatter"])
        assert all(r["tool"] == "rustc" for r in counted)
    return {"all": counted, "owner":owner["instructions"], "owner_input":inputs[0], "whole_traced":whole[0]}

def calibrate_lifetime(read, ident, mode):
    episodes = {}
    selected = []
    whole = []
    for line in read("epochs.tsv").decode().splitlines():
        col = line.split()
        if col[0] == "I":
            idx, pid = map(int, col[1:3])
            fields = read(f"{idx:05}.nul").split(b"\0")
            assert fields.pop() == b"" and int(fields[0]) == pid
            episodes[idx] = (pid, int(fields[1]), int(fields[2]), fields[4:], col[-1])
        elif col[0] == "R":
            idx, pid, ins, en, ran, status = map(int, col[1:])
            orig, dev, ino, argv, origin = episodes[idx]
            assert origin == "exec" and orig == pid and [dev, ino] == ident and argv[-1] == mode.encode()
            assert en == ran > 0 and ins > 0 and status == 0
            selected.append(ins)
        elif col[0] == "W":
            ins, en, ran, status = map(int, col[1:])
            assert en == ran > 0 and ins > 0 and status == 0
            whole.append(ins)
    assert len(selected) == len(whole) == 1
    return selected[0]
