"""Reopen the optional pre-LLVM modules and physical ELF members of each Cargo archive."""

import gzip
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from physical import CRATES, module, need


def members(body, owner):
    need(body.startswith(b"!<arch>\n"), "invalid ar magic")
    at, strings, objects, meta = 8, b"", {}, {}
    while at < len(body):
        head = body[at : at + 60]
        need(len(head) == 60 and head[58:] == b"`\n", "invalid ar header")
        name = head[:16].decode("ascii").rstrip()
        size = int(head[48:58].decode("ascii").strip())
        start = at + 60
        end = start + size
        need(0 <= size and end <= len(body), "invalid member extent")
        data = memoryview(body)[start:end]
        at = end + size % 2
        if name == "//":
            need(not strings, "multiple string tables")
            strings = bytes(data)
            continue
        if name in ("/", "/SYM64/"):
            continue
        if name.startswith("/") and name[1:].isdigit():
            off = int(name[1:])
            stop = strings.find(b"/\n", off)
            need(0 <= off < stop, ("unknown GNU member name", off))
            name = strings[off:stop].decode("ascii")
        elif name.startswith("#1/"):
            count = int(name[3:])
            need(0 < count < len(data), "invalid extended name")
            name = bytes(data[:count]).rstrip(b"\0").decode("ascii")
            data = data[count:]
        else:
            name = name.removesuffix("/")
        digest = hashlib.sha256(data).hexdigest()
        if name in ("lib.rmeta", "lib.rmeta-link"):
            need(name not in meta and data[:6] == b"\x7fELF\x02\x01", "invalid or duplicate metadata member")
            meta[name] = digest
            continue
        key = module(name, owner, "o")
        need(
            data[:6] == b"\x7fELF\x02\x01" and key not in objects, ("invalid or repeated native object", name)
        )
        objects[key] = digest
    need(at == len(body) and objects and "lib.rmeta" in meta, "incomplete native archive")
    return objects, meta


def verify_physical(root):
    def load(path):
        return json.loads((root / path).read_bytes())

    store = root / "cgu-originals"
    checked = {}
    archives = {}
    visits = {}
    sdk = load("sdk.json")["bin/rustc"]

    def original(desc, magic, owner=None):
        key = desc["sha256"]
        need(re.fullmatch("[0-9a-f]{64}", key), "invalid digest")
        if key not in checked:
            size = desc["stat"][2]
            need(0 < size <= 512 << 20, "unbounded original")
            with (store / (key + ".gz")).open("rb") as compressed, gzip.GzipFile(fileobj=compressed) as f:
                body = f.read(size + 1)
            need(len(body) == size, "incorrect uncompressed original size")
            need(body.startswith(magic) and hashlib.sha256(body).hexdigest() == key, "damaged original")
            checked[key] = (len(body), magic)
            if owner is not None:
                archives[key] = (owner, *members(body, owner))
        need(checked[key] == (desc["stat"][2], magic), "inconsistent physical extent")
        return key

    for lane, states in [
        ("reference", ("B", "A")),
        ("plain-1", ("B", "A")),
        ("ordinary-observed", ("B", "A")),
        ("green-reasons", ("B", "A")),
        ("diagnostic-empty", ("B", "A")),
        ("diagnostic", ("B", "A", "unchanged", "invalid", "repair")),
    ]:
        for state in states:
            rel = f"{lane}/{state}"
            visit = load(rel + "/visit.json")
            data = load(rel + "/cgus.json")
            raw = list(
                map(json.loads, gzip.decompress((root / rel / "cargo.stdout.gz").read_bytes()).splitlines())
            )
            need(
                raw[-1] == {"reason": "build-finished", "success": state != "invalid"}, ("Cargo verdict", rel)
            )
            if state == "invalid":
                need(
                    any(
                        (x["message"].get("code") or {}).get("code") == "E0308"
                        for x in raw
                        if x.get("reason") == "compiler-message"
                    ),
                    "missing real type error",
                )
                need(
                    not data,
                    "one of the two dependent crates produced an unexpected result during the parser error",
                )
                continue
            need(set(data) == set(CRATES), ("missing target owners", rel))
            for owner, row in data.items():
                (artifact,) = (
                    x
                    for x in raw
                    if x.get("reason") == "compiler-artifact"
                    and x["target"]["name"] == owner
                    and x["target"]["kind"] == ["lib"]
                )
                need(
                    row["archive_path"] in artifact["filenames"] and row["fresh"] == artifact["fresh"],
                    "wrong owner archive",
                )
                archive = original(row["archive"], b"!<arch>\n", owner)
                crate, objects, metadata = archives[archive]
                need(crate == owner, "native crate mismatch")
                bc = {}
                for k, desc in row["emitted"].items():
                    need(
                        k == module(desc["name"], owner, "no-opt.bc") and k in objects,
                        ("no owning object", k),
                    )
                    bc[k] = original(desc, b"BC\xc0\xde")
                if (call := row["call"]) is not None:
                    area = root / rel / "stage"
                    owned = area / owner

                    def args_at(path):
                        raw = path.read_bytes()
                        need(raw and raw[-1] == 0, "physical exec argv")
                        return [os.fsdecode(x) for x in raw[:-1].split(b"\0")]

                    process = json.loads((owned / "process.json").read_bytes())
                    original_argv = args_at(owned / "original.nul")
                    seen = args_at(owned / "observed.nul")
                    need(
                        process == call["process"]
                        and [process["compiler_dev"], process["compiler_ino"]] == sdk[1:3],
                        "unsigned observed process",
                    )
                    (actual,) = (
                        p
                        for p in map(json.loads, (area / "rustc.jsonl").read_bytes().splitlines())
                        if p["pid"] == process["pid"] and p["crate"] == owner
                    )
                    need(
                        actual["entry"] == f"rustc-{actual['seq']:05d}.nul"
                        and args_at(area / actual["entry"]) == original_argv,
                        "selected process absent from real execs",
                    )
                    need(
                        call["argv"]
                        == seen
                        == original_argv + (["-Csave-temps=yes"] if lane.startswith("diagnostic") else []),
                        "post-exec operand mismatch",
                    )
                    need(
                        original_argv[original_argv.index("--out-dir") + 1]
                        == call["outdir"]
                        == str(Path(row["archive_path"]).parent),
                        "unrelated codegen output root",
                    )
                    files = json.loads((owned / "emitted.json").read_bytes())
                    need(
                        len(files) == len(bc) and set(bc) == {x["unit"] for x in files},
                        "physical emission inventory",
                    )
                    for f in files:
                        saved = row["emitted"][f["unit"]]
                        need(
                            f["before"][:4] == f["after"][:4]
                            and f["after"] == saved["stat"]
                            and f["name"] == saved["name"],
                            "stale or replaced optional file",
                        )
                if lane.startswith("diagnostic") and state in ("B", "A"):
                    call = row["call"]
                    need(
                        call and call["argv"][-1] == "-Csave-temps=yes" and call["process"]["capture"],
                        "missing real LLVM invocation",
                    )
                elif not lane.startswith("diagnostic"):
                    call = row["call"]
                    need(
                        not bc and ((call is not None) == (lane in ("ordinary-observed","green-reasons"))),
                        "unexpected ordinary compiler observation",
                    )
                    if call:
                        need(
                            not call["process"]["capture"] and "-Csave-temps=yes" not in call["argv"],
                            "optional instrumentation in ordinary build",
                        )
                if state in ("A", "B"):
                    if lane != "reference":
                        ref = visits["reference", state, owner]
                        need(
                            visit["cli"] == ref["cli"] and visit["reader"] == ref["reader"],
                            ("different clean native output", rel, owner),
                        )
                else:
                    ref = visits["reference", "A", owner]
                    need(
                        visit["cli"] == ref["cli"] and visit["reader"] == ref["reader"],
                        ("different native repair", rel, owner),
                    )
                visits[lane, state, owner] = {
                    "obj": objects,
                    "bc": bc,
                    "metadata": metadata,
                    "cli": visit["cli"],
                    "reader": visit["reader"],
                }
    comparisons = {}
    for owner in CRATES:
        before = visits["diagnostic", "B", owner]
        after = visits["diagnostic", "A", owner]
        cold_b = visits["diagnostic-empty", "B", owner]
        cold_a = visits["diagnostic-empty", "A", owner]
        need(
            before["bc"] and cold_a["bc"] and cold_b["bc"] and before["bc"].keys() == cold_b["bc"].keys(),
            "cold LLVM coverage",
        )
        need(not visits["diagnostic", "unchanged", owner]["bc"], "new LLVM input on unchanged visit")
        emitted = after["bc"]
        shared = sorted(emitted.keys() & before["bc"].keys())
        same_pre = [k for k in shared if emitted[k] == before["bc"][k]]
        same_native = [k for k in shared if after["obj"][k] == before["obj"][k]]
        strict = [
            k
            for k in same_pre
            if k in same_native
            and before["bc"][k] == cold_b["bc"][k] == cold_a["bc"].get(k)
            and all(
                visits[lane, state, owner]["obj"].get(k) == before["obj"][k]
                for lane in ("reference", "plain-1", "ordinary-observed", "diagnostic-empty", "green-reasons")
                for state in ("B", "A")
            )
        ]
        history_parity = {}
        for reference, observed in [
            ("plain-1", "ordinary-observed"),
            ("ordinary-observed", "green-reasons"),
            ("ordinary-observed", "diagnostic"),
            ("reference", "diagnostic-empty"),
        ]:
            for state in ("B", "A"):
                left = visits[reference, state, owner]["obj"]
                right = visits[observed, state, owner]["obj"]
                if observed == "green-reasons":
                    need(left == right, ("probe changed native objects", owner, state))
                history_parity[f"{reference}/{observed}/{state}"] = {
                    "reference": len(left),
                    "observed": len(right),
                    "same": sum(left.get(k) == v for k, v in right.items()),
                }
        comparisons[owner] = {
            "old_modules": len(before["bc"]),
            "new_modules": len(cold_a["bc"]),
            "rebuilt": len(emitted),
            "rebuilt_shared_basenames": len(shared),
            "identical_preopt": same_pre,
            "identical_native": same_native,
            "identical_both": sorted(set(same_pre) & set(same_native)),
            "same_preopt_different_object": sorted(set(same_pre) - set(same_native)),
            "confirmed_against_both_empty_histories": strict,
            "warm_B_bitcode_different_from_clean": [
                k for k, v in before["bc"].items() if cold_b["bc"].get(k) != v
            ],
            "warm_A_bitcode_different_from_clean": [
                k for k, v in emitted.items() if cold_a["bc"].get(k) != v
            ],
            "native_history_parity": history_parity,
        }
    need(
        {p.name for p in store.iterdir()} == {k + ".gz" for k in checked}, "original-store inventory mismatch"
    )
    return {"original_files": len(checked), "comparisons": comparisons, "treatment_runs": 0}


def verify(root):
    result = verify_physical(root)
    plain = json.loads((root / "plain-1/A/clock.json").read_bytes())
    need(
        plain["code"] == plain["event_errno"] == 0
        and plain["instructions"] > 0
        and plain["running"] == plain["enabled"] > 0,
        "invalid whole hardware count",
    )
    return dict(whole_ordinary_instructions=plain["instructions"], **result)


if __name__ == "__main__":
    source = Path(sys.argv[1])
    if source.is_dir():
        result = verify(source)
    else:
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            need(len(names) == len(set(names)), "duplicate archive member")
            result = verify(zipfile.Path(archive))
    print(json.dumps(result, sort_keys=True, indent=2))
