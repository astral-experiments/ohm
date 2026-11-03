"""Reopen the scoped module/resolved-join experiment from the original bytes."""
import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def scoped_joins(arm, native):
    assert arm["entry_counts"] == {"span_join": 68}
    assert arm["events"] == {"join": 3}
    assert len(arm["returns"]) == len(arm["join_sources"]) == len(arm["selected_at_joins"]) == 3
    result = []
    for ret, src, selected in zip(arm["returns"], arm["join_sources"], arm["selected_at_joins"]):
        left, right = src["first"], src["second"]
        packed = [int(ret[key], 16) for key in ("first", "second", "returned")]
        for i, part in enumerate((left, right)):
            assert part["imported"] and part["packed"] == hex(packed[i])
            assert part["stable_id"] == "69754195d398d941cd88b96d81bd6a7d"
            assert part["ctx"] == (packed[i] >> 48) and part["ctx"] != 0xffff
            assert part["len"] == (packed[i] >> 32) & 0xffff < 0x8000
            assert part["relative_lo"] + part["global_start"] == packed[i] & 0xffffffff
        assert left["global_start"] == right["global_start"] and left["ctx"] == right["ctx"]
        assert (left["relative_lo"], left["len"], right["relative_lo"], right["len"]) == (549, 1, 602, 8)
        assert ret["some_tag"] == 1
        assert packed[2] == (left["ctx"] << 48 | 61 << 32 | left["global_start"] + 549)
        assert src["char_locs"] == [[17, 36, 36], [17, 89, 89]]
        for key, magic in (("OHM_SELECTED_CORE", b"rust"), ("OHM_SELECTED_MACRO", b"\x7fELF")):
            accepted = selected[key]
            assert accepted["path_sha256"] == native[key]
            assert accepted["maps"] and all(
                row["flags"] == "r--p" and bytes.fromhex(row["memory_prefix"]).startswith(magic)
                for row in accepted["maps"]
            )
        result.append((left["stable_id"], 549, 550, 602, 610, 549, 610, (17, 36), (17, 89)))
    return result


def verify(root):
    report = read(root / "history/ordinary.json")
    assert report["plan"] == sha(root / "registration.json")
    live = root / "history/input"
    installed = {str(p.relative_to(live)): sha(p) for p in live.rglob("*") if p.is_file()}
    assert len(installed) == 555 and installed == report["previous_input_sha256"]
    first = root / "history/closed-first-input"
    assert {str(p.relative_to(first)): sha(p) for p in first.rglob("*") if p.is_file()} == installed
    selected = {
        key: next(sha(p) for p in live.rglob(glob))
        for key, glob in (("OHM_SELECTED_CORE", "libserde_core-*.rmeta"), ("OHM_SELECTED_MACRO", "libserde_derive-*.so"))
    }
    bs, = live.rglob("bitflags-*/src/public.rs")
    bm, = live.rglob("libbitflags-*.rmeta")
    data = bs.read_bytes()
    assert data[549:610] == b"<$PublicBitFlags as $crate::__private::PublicFlags>::Internal"
    assert (data[:549].count(b"\n") + 1, len(data[:549].split(b"\n")[-1])) == (17, 36)
    meta = bm.read_bytes()
    file_id = bytes.fromhex("69754195d398d941cd88b96d81bd6a7d")
    digest = hashlib.md5(data).digest()
    assert meta.count(file_id) == meta.count(digest) == 1
    reg = read(root / "registration.json")
    arms = report["arms"]
    assert sorted(reg["control_order"]) == sorted(arms)
    bad = ["new-zero-length-src-util-rs", "independent-empty-util"]
    good = sorted(set(arms).difference(bad))
    assert len(good) == 6
    for name, val in arms.items():
        record = root / "history/events" / name
        assert read(record / "result.json") == val
        assert {f.suffix: sha(f) for f in record.iterdir() if f.suffix in (".d", ".rlib", ".rmeta")} == val["outputs"]
        assert val["previous_file_count"] == 555
        ds = [json.loads(line) for line in (record / "stderr").read_bytes().splitlines() if line.startswith(b"{")]
        primary = [(o.get("code") or {}).get("code") for o in ds if o.get("$message_type") == "diagnostic" and o.get("code")]
        if name in bad:
            assert primary == ["E0761"] and val["rc"] == 1 and set(val["outputs"]) == {".d"}
            actual = next(o for o in ds if (o.get("code") or {}).get("code") == "E0761")
            assert actual["message"].startswith("file for module `util` found at both")
            assert any(sp["is_primary"] and sp["line_start"] == 36 for sp in actual["spans"])
        else:
            assert primary == [] and val["rc"] == 0 and set(val["outputs"]) == {".d", ".rlib", ".rmeta"}
    assert arms[bad[0]]["diag"] == arms[bad[1]]["diag"]
    types = {k: sorted({arms[n]["outputs"][k] for n in good}) for k in (".rlib", ".rmeta", ".d")}
    assert len(types[".d"]) == len(types[".rlib"]) == 1
    bodies = report["consumer"]["physical_artifacts"]
    assert set(bodies) == set(good)
    assert all(row["stdout"] == "valid=[8,13,21] roundtrip=3 malformed=1:5\n" for row in bodies.values())
    elves = {row["ELF"] for row in bodies.values()}
    assert elves == {report["consumer"]["repair_elf"]} and report["consumer"]["invalid_E0308"]
    bridge = read(root / "debugger-01/readback.json")
    classes = []
    for name, arm in bridge.items():
        prefix = root / "debugger-01" / name
        physical = read(prefix / "observations/hits.json")
        assert sha(prefix / "observations/hits.json") == arm["hits_sha"]
        assert (physical["actual_returns"], physical["join_sources"], physical["events"], physical["entry_counts"]) == (
            arm["returns"], arm["join_sources"], arm["events"], arm["entry_counts"]
        )
        assert physical["exit_codes"] == [int(name == "zero-byte-module")] == [arm["rc"]]
        assert read(prefix / "observations/selected-at-joins.json") == arm["selected_at_joins"]
        if arm["rc"]:
            assert b"E0761" in (prefix / "stderr").read_bytes() and ".rlib" not in arm["products"]
        else:
            assert arm["products"][".rlib"] in types[".rlib"]
        classes.append(scoped_joins(arm, selected))
    assert len(classes) == 2 and classes[0] == classes[1]
    sm = read(root / "source.json")
    for f, entry in sm.items():
        blob = (root / "source" / f).read_bytes()
        assert sha(root / "source" / f) == entry["sha256"]
        assert hashlib.sha1(b"blob " + str(len(blob)).encode() + b"\0" + blob).hexdigest() == entry["oid"]
    unchanged = ["compiler/rustc_expand/src/proc_macro_server.rs", "compiler/rustc_expand/src/module.rs",
                 "compiler/rustc_metadata/src/locator.rs", "compiler/rustc_span/src/span_encoding.rs", "compiler/rustc_span/src/lib.rs"]
    assert all(sm["rust-23/" + f]["oid"] == sm["rust-24/" + f]["oid"] for f in unchanged)
    metadata = read(root / "history/metadata-comparison.json")
    assert sorted(metadata) == types[".rmeta"]
    for row in metadata.values():
        assert all(not t["different"] and t["same_multiset"] for t in row["tables"].values())
        assert set(row["hash_fields"]) <= {"full"}
        if "full" in row["hash_fields"]:
            assert set(row["hash_fields"]["full"]) == set(types[".rmeta"])
        assert all("'_" in str(x) and "opaque#" in str(x) for x in row["different_physical_indices"].values())
    return dict(registered=report["plan"], compiler_sources=reg["native_role"], positive_files=len(installed),
                producer_rows={n:arms[n]["rc"] for n in reg["control_order"]}, typed_refusal="E0761",
                previous_compiler_outputs=types, complete_consumer_elf=sorted(elves), consumers=len(bodies),
                consumer_invalid="E0308", input_ids=selected, rust24=reg["rust_rc24"], cargo24=reg["cargo_rc24"],
                immutable_rust_paths=unchanged, bridge_returns_each=classes[0], bridge_entries_each=68,
                foreign_debug_each=0, bitflags_source_sha256=sha(bs), bitflags_rmeta_sha256=sha(bm),
                selected_in_rmeta=dict(file_id_offset=meta.index(file_id), source_md5_offset=meta.index(digest)),
                decoded_standalone={k:dict(bytes_changed=v["diff_offsets"],different_def_indices=v["different_physical_indices"],
                                           tables=v["tables"]) for k,v in metadata.items()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    print(json.dumps(verify(parser.parse_args().directory), indent=2, sort_keys=True))
