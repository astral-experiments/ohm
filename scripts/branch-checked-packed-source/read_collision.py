"""Reopen whole programs, original Cargo verdicts, source-session evidence and actual driver mappings."""

from contextlib import contextmanager
import gzip
import io
import os
import json
from pathlib import Path
import re
import stat

from objects import digest, need, unpack
from physical import native_lines

CARGO = [
    "cargo",
    "+ohm",
    "build",
    "--locked",
    "--offline",
    "-p",
    "shadow_app",
    "-j1",
    "--message-format=json",
    "-vv",
]
STATES = {
    "honest": (29, True),
    "matching-raw": (29, False),
    "conflicting-raw": (29, False),
    "bad-zlib": (29, False),
    "bad-digest-no-raw": (29, False),
    "bad-digest-with-raw": (29, False),
    "bad-digest-name": (29, False),
    "bad-both": (29, False),
    "nonregular-raw-symlink": (29, False),
    "nonregular-raw-fifo": (29, False),
    "locked": (29, False),
    "raw-only-old": (17, True),
    "malformed-raw": (29, False),
}


@contextmanager
def from_directory(root):
    def get(name):
        need(not Path(name).is_absolute() and ".." not in Path(name).parts, "invalid evidence path")
        full = root / name
        need(
            not full.is_symlink() and full.is_file() and full.stat().st_size <= 12 << 20,
            "missing/oversize " + name,
        )
        return full.read_bytes()

    yield get


def group_correspondence(ids, legacy, C, F):
    need(
        set(ids) == {"old", "F", "corrected"}
        and ids["old"] == legacy
        and ids["F"] == F
        and ids["corrected"] == C
        and len({r["driver"] for r in ids.values()}) == 3,
        "incorrect three physical sources or Rust drivers",
    )


def bounded_gzip(compressed):
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        data = stream.read((32 << 20) + 1)
    need(len(data) <= 32 << 20, "oversized compressed native evidence")
    return data


def scan(get, folder, ids):
    def read(n):
        return get(folder + "/" + n)

    def data(n):
        return json.loads(read(n + ".json"))

    def raw(n):
        return bounded_gzip(read(n + ".gz"))

    def elf(h):
        need(isinstance(h, str) and re.fullmatch("[0-9a-f]{64}", h), "invalid ELF identifier")
        image = raw("elf/" + h)
        need(
            re.fullmatch("[0-9a-f]{64}", h)
            and digest(image) == h
            and image[:7] == b"\x7fELF\x02\x01\x01"
            and image[16:18] in (b"\x02\x00", b"\x03\x00")
            and image[18:20] == b"\x3e\x00",
            "unbound whole ELF",
        )

    def driver(label, role, code):
        actual = data(label + "-physical")
        rec = ids[role]
        need(
            actual["source"] == rec["source"]
            and actual["sha256"] == rec["driver"]
            and actual["status"] == code
            and Path(actual["driver"]).name.startswith("librustc_driver-")
            and Path(actual["driver"]).is_absolute(),
            "incorrect image/role/status " + label,
        )
        witnessed = []
        crate_execs = []
        sdk = Path(actual["driver"]).parent.parent
        candidates = {
            os.fsencode(p) for p in (sdk / "bin/rustc", sdk.parent / "rustup/toolchains/ohm/bin/rustc")
        }
        seen = set()
        for p in actual["positive_traces"]:
            name = p["name"]
            need(
                re.fullmatch(re.escape(label) + r"-pid-[1-9][0-9]*\.kernel\.gz", name)
                and name not in seen,
                "wrong or duplicate kernel record",
            )
            seen.add(name)
            kernel = bounded_gzip(read(name))
            op, mm = native_lines(kernel, actual["driver"])
            need(
                p == {"name": name, "opened": op, "mapped_exec": mm, "raw_sha256": digest(kernel)}
                and (op or mm),
                "inconsistent positive driver evidence",
            )
            if op and mm:
                witnessed.append(name)
                for line in kernel.splitlines():
                    m = re.match(rb'^execve\("([^"\\]+)", \[', line)
                    if m is None or m[1] not in candidates or re.search(rb"\)\s+=\s+0$", line) is None:
                        continue
                    c = re.search(rb'"--crate-name", "([a-z0-9_]+)"', line)
                    if c is not None:
                        if c[1] == b"___" and b'"--print' in line:
                            continue
                        crate_execs.append(c[1].decode("ascii"))
        if folder.startswith("cargo-"):
            expected = ["shadow_app", "shadow_leaf"]
        elif folder.startswith("natural-"):
            expected = ["shadow_legacy"]
        else:
            expected = ["branch_tables"]
        need(
            witnessed and sorted(crate_execs) == expected,
            "different mapped native compiler unit roster: " + repr(crate_execs),
        )
        return actual

    return read, data, raw, elf, driver


def cargo(get, role, ids):
    read, data, raw, elf, driver = scan(get, "cargo-" + role, ids)
    rec = data("complete")
    sub = data("subject")
    old = role == "old"
    want = dict(STATES)
    if old:
        want.update(
            {
                "matching-raw": (29, True),
                "conflicting-raw": (17, True),
                "bad-digest-with-raw": (17, True),
                "bad-both": (17, True),
                "malformed-raw": (None, False),
            }
        )
    need(
        set(rec["cases"]) == set(want)
        and rec["expected_policy"] == ("original" if old else "reject")
        and sub["source"] == rec["producer"] == rec["consumer"] == ids[role]["source"]
        and sub["driver"][0] == ids[role]["driver"]
        and sub["members"] == 81
        and rec["original_raw_absent"] is True,
        "unverified cargo history",
    )
    obj, payload = unpack(raw("inputs/packed-B"), rec["packed_filename"], rec["session"])
    a = raw("inputs/raw-A")
    b = raw("inputs/raw-B")
    need(
        a != b == payload
        and b"\x11" * 8192 in a
        and b"\x1d" * 8192 in b
        and len(a) == len(b)
        and (digest(a), digest(b), digest(raw("inputs/packed-B")))
        == (rec["raw_A"], rec["raw_B"], rec["packed_B"]),
        "different native collision operands",
    )
    elfs = {v: data(n)["program"] for n, v in (("A17", 17), ("B29", 29))}
    need(elfs[17] != elfs[29], "identical old and new program")
    for h in elfs.values():
        elf(h)
    expected = {
        "A17": (17, False),
        "B29": (29, False),
        "B-independent-empty": (29, False),
        **{"B-" + k: v for k, v in want.items()},
    }
    for label, (v, mark) in expected.items():
        code = 101 if v is None else 0
        row = data(label)
        c = driver(label, role, code)
        messages = [json.loads(x) for x in raw(label + ".stdout").splitlines()]
        units = {x["target"]["name"]: x["fresh"] for x in messages if x["reason"] == "compiler-artifact"}
        stderr = raw(label + ".stderr").decode()
        rustcs = [x for x in stderr.splitlines() if "Running `" in x and "--crate-name " in x]
        need(
            c["argv"] == row["cargo"] == CARGO
            and messages[-1] == {"reason": "build-finished", "success": code == 0}
            and [re.search(r"--crate-name (shadow_leaf|shadow_app) ", l)[1] for l in rustcs]
            == ["shadow_leaf", "shadow_app"]
            and units
            == ({"shadow_leaf": False} if v is None else {"shadow_leaf": False, "shadow_app": False}),
            "wrong actual Cargo units",
        )
        if v is None:
            need(
                row["status"] == 101
                and row["panic_or_ice"] is False
                and "program" not in row
                and any(
                    "linking with `cc` failed" in m.get("message", {}).get("message", "")
                    for m in messages
                ),
                "missing real malformed failure",
            )
        else:
            need(
                row["status"] == 0
                and row["runtime"] == v
                and read(label + ".runtime") == f"{v}\n".encode()
                and row["marker"] is mark
                and row["program"] == elfs[v],
                "incorrect settled native CLI or reuse",
            )
        if label.startswith("B-") and label != "B-independent-empty":
            key = label[2:]
            hold = data(key + "-source-unchanged")
            need(
                hold["before"] == hold["after"]
                and hold["mode"] == ("EX" if key == "locked" else "SH")
                and rec["cases"][key]
                == {k: row.get(k) for k in ("runtime", "status", "marker", "program", "panic_or_ice")},
                "source session changed during guarded read",
            )
            files = hold["before"]
            entry = files.get(obj)
            if key in {"matching-raw", "conflicting-raw", "locked", "raw-only-old"}:
                need(
                    entry[5] == (digest(b) if key == "matching-raw" else digest(a))
                    and entry[2] == len(a),
                    "wrong injected regular object",
                )
            if key in {
                "honest",
                "matching-raw",
                "conflicting-raw",
                "locked",
                "malformed-raw",
                "nonregular-raw-symlink",
                "nonregular-raw-fifo",
            }:
                need(
                    files[rec["packed_filename"]][5] == rec["packed_B"], "original good sidecar missing"
                )
            if key == "raw-only-old":
                need(rec["packed_filename"] not in files, "raw-only case still had a packed copy")
            if key == "nonregular-raw-symlink":
                need(entry[5].endswith("/outside-object"), "missing symlink sentinel")
            if key == "nonregular-raw-fifo":
                need(entry[5] == str(stat.S_IFIFO), "not a FIFO")
    return {"comparisons": len(expected), "raw_only_old": elfs[17], "clean_29": elfs[29]}


def direct(get, role, ids):
    read, data, raw, elf, driver = scan(get, "writer-old-reader-" + role, ids)
    r = data("complete")
    ref = data("empty-B")
    need(
        r["producer"] == "old"
        and r["consumer"] == role
        and r["empty_B"] == ref["elf"]
        and set(r["cases"]) == {"honest", "identical", "conflict", "corrupt"},
        "wrong raw collision history",
    )

    def visit(label, who, want):
        row = data(label)
        c = driver(label, who, 0)
        need(
            row["role"] == who
            and row["driver"] == ids[who]["driver"]
            and row["source"] == ids[who]["source"]
            and c["argv"][:4] == ["rustc", "+ohm", "checkout/main.rs", "--crate-name"]
            and row["output"] == want
            and read(label + ".runtime") == f"{want}\n".encode(),
            "wrong run-make native participant",
        )
        elf(row["elf"])
        return row

    fresh = visit("empty-B", role, 29)
    for mode, case in r["cases"].items():
        a = visit(mode + "-old-A", "old", 17)
        b = visit(mode + "-old-B", "old", 29)
        again = visit(mode + "-return-A", "old", 17)
        stale = role == "old" and mode == "conflict"
        v = 17 if stale else 29
        actual = visit(mode + "-read-B", role, v)
        name, body = unpack(raw("inputs/" + mode + "-side"), case["packed"], case["session"])
        aa = raw("inputs/" + mode + "-A")
        bb = raw("inputs/" + mode + "-B")
        need(
            (case["A"], case["B"], case["returned"], case["output"])
            == (a["elf"], b["elf"], actual["elf"], v)
            and case["marker"]
            is (mode == "honest" or role == "old" and mode in {"identical", "conflict"})
            and [digest(aa), digest(bb), digest(raw("inputs/" + mode + "-side"))]
            == [case["raw_A"], case["raw_B"], case["sidecar"]]
            and aa != bb == body
            and len(aa) == len(bb)
            and b"\x11" * 8192 in aa
            and b"\x1d" * 8192 in bb
            and fresh["elf"] == b["elf"]
            and again["elf"] == a["elf"] != b["elf"]
            and actual["elf"] == (a if stale else fresh)["elf"]
            and actual["source_body"] == fresh["source_body"],
            "independent mixed collision produced stale bytes",
        )
    return {"visits": 17, "clean": fresh["elf"]}


def natural(get, role, ids):
    read, data, raw, elf, driver = scan(get, "natural-" + role, ids)
    r = data("complete")
    need(
        (r["producer"], r["bridge"], r["consumer"], r["source_drivers"]) == ("old", "F", role, ids)
        and r["compiler_created_both"] is True
        and r["marker"] is (role == "old"),
        "incorrect F writer or discard",
    )
    rows = []
    for label, who, v in (
        ("old-A17", "old", 17),
        ("old-B29", "old", 29),
        ("F-B83", "F", 83),
        ("read-B83", role, 83),
        ("empty-B83", role, 83),
    ):
        c = driver(label, who, 0)
        x = data(label)
        elf(x["elf"])
        need(
            x["role"] == who
            and x["source"] == ids[who]["source"]
            and x["driver"] == ids[who]["driver"]
            and x["expected"] == v
            and read(label + ".runtime") == f"{v}\n".encode()
            and c["argv"][:4] == ["rustc", "+ohm", "main.rs", "--crate-name"],
            "natural writer identity/verdict",
        )
        rows.append(x)
    a, b, f, new, clean = rows
    key = r["packed_name"]
    name, body = unpack(raw("inputs/packed-29"), key, b["session"])
    fresh = raw("inputs/raw-83")
    need(
        name == r["object"]
        and fresh != body == raw("inputs/decoded-29")
        and digest(body) == r["decoded_29"]
        and digest(fresh) == r["raw_83"]
        and b"\x53" * 8192 in fresh
        and b"\x1d" * 8192 in body
        and name not in b["files"]
        and r["carried"] == b["files"][key] == f["files"][key]
        and f["files"][name][3] == digest(fresh)
        and b["files"][key][3] == digest(raw("inputs/packed-29"))
        and new["elf"] == clean["elf"] == r["clean"] == f["elf"]
        and len({a["elf"], b["elf"], f["elf"]}) == 3
        and f["source_body"] == new["source_body"] == clean["source_body"]
        and ("mixed-source-marker" in new["files"]) is (role == "old")
        and "mixed-source-marker" not in clean["files"],
        "natural carried packed inode and new raw contents/own independent ELF mismatch",
    )
    return {
        "visits": 5,
        "native_clean_B83": r["clean"],
        "packed29": digest(body),
        "raw83": digest(fresh),
    }


def verify(get, ids):
    return {
        "roles": ids,
        "checks": {
            role: {
                "normal_cargo": cargo(get, role, ids),
                "old_writer": direct(get, role, ids),
                "F_bridge": natural(get, role, ids),
            }
            for role in ("old", "corrected")
        },
    }
