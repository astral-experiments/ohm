"""Independently reopen the signed inputs, captured process evidence and native oracles."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"


def read(name):
    p = EVIDENCE / name
    data = p.read_bytes()
    return json.loads(gzip.decompress(data) if p.suffix == ".gz" else data)


def check_manifest():
    paths = set()
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        path = HERE / name
        assert path.resolve().is_relative_to(HERE) and name not in paths
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
        paths.add(name)
    actual = {
        p.relative_to(HERE).as_posix()
        for p in HERE.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    assert actual == paths | {"SHA256SUMS"}


def read_role():
    inv = json.loads((HERE / "inputs/invocation.json").read_bytes())
    archive = HERE / "inputs/role-files.tar.zst"
    assert (
        hashlib.sha256(archive.read_bytes()).hexdigest() == inv["input_archive_sha256"]
    )
    raw = subprocess.check_output(["zstd", "-dcq", str(archive)])
    objects = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        for entry in tar:
            if entry.isdir():
                continue
            assert entry.isfile()
            data = tar.extractfile(entry).read()
            key = hashlib.sha256(data).hexdigest()
            assert key == Path(entry.name).name and key not in objects
            objects[key] = data
    expected = inv["member_sha256"]
    assert len(expected) == len(objects) == 36 and set(expected.values()) == set(
        objects
    )
    assert sum(n.endswith(".crate") for n in expected) == 11
    (core,) = [
        objects[k]
        for n, k in expected.items()
        if "/libserde_core-" in n and n.endswith(".rmeta")
    ]
    (macro,) = [
        objects[k]
        for n, k in expected.items()
        if "/libserde_derive-" in n and n.endswith(".so")
    ]
    mut = json.loads((HERE / "inputs/macro-mutation.json").read_bytes())
    assert hashlib.sha256(macro).hexdigest() == mut["normal"]
    altered = bytearray(macro)
    word = b"serialize_newtype_struct"
    for off in mut["offsets"]:
        assert altered[off : off + len(word)] == word
        altered[off + len(word) - 1] = ord("x")
    assert hashlib.sha256(altered).hexdigest() == mut["malformed"]
    (depinfo,) = [
        objects[k] for n, k in expected.items() if Path(n).name == "dep-lib-ron"
    ]
    return inv, core, depinfo


def check_cargo_depinfo(raw, expected, b3sum):
    assert hashlib.sha256(raw).hexdigest() == expected["sha256"]
    source = io.BytesIO(raw)
    assert source.read(6) == bytes.fromhex("01000000ff02")

    def u32():
        data = source.read(4)
        assert len(data) == 4
        return int.from_bytes(data, "little")

    names = []
    for _ in range(u32()):
        kind = source.read(1)
        assert len(kind) == 1
        names.append(source.read(u32()).decode())
        assert source.read(1) == b"\x00"
    assert len(names) == 20 and u32() == 0
    assert source.read(4) == b"OBS1"
    index = u32()
    assert index == expected["validated_OBS1_index"] == 3 and names[index].endswith(
        "/ohm-foreign-span-bytes"
    )
    assert source.read(1) == b"\x00"
    checksum = source.read()
    assert (
        len(checksum) == 32
        and subprocess.check_output([b3sum], input=raw[:-32]).decode().split()[0]
        == checksum.hex()
    )


def check_mapping(rows, physical, b3sum, field):
    malformed = b"R" + physical[1:]
    good_sha, bad_sha = [hashlib.sha256(b).hexdigest() for b in (physical, malformed)]
    good, bad = [
        subprocess.check_output([b3sum], input=b).decode().split()[0]
        for b in (physical, malformed)
    ]
    for mode in ("sham", "rename", "inplace", "inplace_restore"):
        r = rows[mode]
        assert r["rc"] == 0 and not r["errors"]
        assert (
            r["open_masks_before_intervention"] == [32] and "r--p" in r["original_map"]
        )
        assert r["original_sha256"] == good_sha and r["malformed_sha256"] == bad_sha
        assert r["size"] == len(physical) and r["same_mtime"]
        old_bytes, new_bytes = physical[:16].hex(), malformed[:16].hex()
        assert r["mapped_before"] == old_bytes
        assert r["mapped_after"] == (
            new_bytes if mode.startswith("inplace") else old_bytes
        )
        assert r["mapped_on_resume"] == (new_bytes if mode == "inplace" else old_bytes)
        assert r["path_after"] == (old_bytes if mode == "sham" else new_bytes)
        assert (r["inode_before"] != r["inode_after"]) == (mode == "rename")
        lines = r[field]
        expected = bad if mode in ("rename", "inplace") else good
        assert len(lines) == 1 and lines[0].startswith(
            f"# checksum:blake3={expected} file_len:{len(physical)} "
        )
    return good, bad


def main(b3sum):
    check_manifest()
    invocation, core, depinfo = read_role()
    census = read("census.json")
    observations = read("file-observations.json.gz")
    traces = read("syscalls.json.gz")
    assert {k: v["original_sha256"] for k, v in traces.items()} == census["traces"]
    lines = [l for v in traces.values() for l in v["rows"]]
    negative = [l for l in lines if " = -1 ENOENT" in l or " = -1 ENOTDIR" in l]
    assert (
        len(negative) == census["absent_calls"] == 100
        and len(observations["absent"]) == 77
    )
    assert len(census["ordinary_real_execs"]) == 2
    data = observations["positive_content"]
    assert not any(n.endswith(".crate") for n in data)
    assert (
        len(census["direct_externs"]) == 6
        and set(census["direct_externs"]) <= data.keys()
    )
    for group, (count, size) in {
        "ron-declared-source": (19, 272837),
        "explicit-extern-metadata": (5, 1289965),
        "explicit-proc-macro": (1, 4902736),
        "implicit-crate-artifact": (1, 4244611),
        "sdk-stdlib": (20, 88374044),
        "sdk-runtime": (2, 370815968),
        "host-native-loader": (9, 6056915),
    }.items():
        files = {n: r for n, r in data.items() if r["group"] == group}
        assert len(files) == count and sum(r["size"] for r in files.values()) == size
        assert len({tuple(r["physical"]) for r in files.values()}) == count
        assert census["data_by_group"][group]["unique_regular_bytes"] == size
        for n in files:
            assert any(
                n + ">" in l and ("read(" in l or "mmap(" in l or "pread64(" in l)
                for l in lines
            ), n
    assert census["enumerated_dirs"] == {
        "implicit-crate-artifact": 7,
        "output-or-temporary": 3,
        "sdk-stdlib": 1,
    }
    assert (
        sum(r["group"] == "ron-project-other" for r in observations["absent"].values())
        == 17
    )
    ordinary = census["plain_binary_cargo_depinfo"]
    check_cargo_depinfo(depinfo, ordinary, b3sum)
    assert (
        ordinary["files"],
        ordinary["checksum_count"],
        ordinary["environment_rows"],
    ) == (20, 0, 0)
    assert census["optional_binary_checksum_count"] == 45
    opt = read("emitted-depinfo.json.gz")["optional"]["text"].splitlines()
    checksums = [x for x in opt if x.startswith("# checksum:")]
    assert len(checksums) == 45
    std = {Path(n).name for n, v in data.items() if v["group"] == "sdk-stdlib"}
    in_d = {x.rsplit("/", 1)[-1] for x in checksums if "/lib/rustlib/" in x}
    assert std - in_d == {"libstd_detect-90b5259d92b4976a.rlib"} and not in_d - std
    joins = read("foreign-native-returns.json.gz")
    assert (
        joins["entry_counts"] == {"span_join": 68}
        and len(joins["actual_returns"]) == 3
        and joins["debugs"] == []
    )
    corruption = read("corruption.json")
    for name in ("private-bad", "unrelated-empty-bad"):
        r = corruption["phases"][name]["result"]
        assert r["rc"] != 0 and not r["files"] and "E0463" in str(r)
    for name in ("private-good", "private-repair", "unrelated-empty-good"):
        assert corruption["phases"][name]["result"]["rc"] == 0
    for row in read("normal-rmeta-table.json.gz").values():
        assert all(
            r["different"] == 0 and r["same_multiset"] for r in row["tables"].values()
        )
        assert row["tables"]["definitions"]["size"] == 3584
    matched = read("process-memory.json")
    check_mapping(matched, core, b3sum, "checksum")
    source = read("source-manifest.json")
    for role, excerpts in read("source-excerpts.json.gz").items():
        for file, proof in excerpts.items():
            assert proof["whole_file_sha256"] == source[role]["files"][file]["sha256"]
            assert proof["whole_git_blob"] == source[role]["files"][file]["blob"]
    assert source["signed"]["commit"] in invocation["signed"]["rustc"]
    upstream = read("upstream-optional.json")
    assert source["stock"]["commit"] in upstream["stock_rustc"]
    assert "E0786" in upstream["role_rows"]["independent-bad"]["errors"]
    assert upstream["role_rows"]["independent-repair"]["rc"] == 0
    check_mapping(
        upstream["role_rows"],
        (EVIDENCE / "official-fixture-leaf.rmeta").read_bytes(),
        b3sum,
        "checksums",
    )
    native = read("linked-consumer.json")
    assert native["invalid_E0308"] and len(native["physical_artifacts"]) == 11
    assert all(
        v["stdout"] == "valid=[8,13,21] roundtrip=3 malformed=1:5\n"
        for v in native["physical_artifacts"].values()
    )
    fresh = read("fresh-public-replay.json.gz")["contents"]
    pipe = read("jobserver-results.json")
    assert pipe["abi"] == [5, 7] and pipe["returned_tokens"] == 3
    assert pipe["rows"]["regular"][".rlib"] == pipe["rows"]["traced"][".rlib"]
    assert pipe["rows"]["regular"][".d"] == pipe["rows"]["traced"][".d"]
    assert (
        pipe["rows"]["regular"][".rlib"]
        == fresh["consumer"]["physical_artifacts"]["regular"]["rlib"]
    )
    assert fresh["native"]["same-argv-trace"]["rc"] == 0
    assert fresh["native"]["wrong-macro"]["errors"] == ["E0782", "E0782"]
    for key in ("static-transitive-malformed", "independent-empty-malformed"):
        assert (
            fresh["native"][key]["rc"] != 0
            and "E0463" in fresh["native"][key]["errors"]
        )
    assert (
        len({v["ELF"] for v in fresh["consumer"]["physical_artifacts"].values()}) == 1
        and fresh["consumer"]["invalid_E0308"]
    )
    for row in fresh["native"].values():
        if "open_masks_before_intervention" in row:
            assert row["open_masks_before_intervention"] == [32]
    check_mapping(
        fresh["official_reduced"]["role_rows"],
        (EVIDENCE / "fresh-official-fixture-leaf.rmeta").read_bytes(),
        b3sum,
        "checksums",
    )
    print(
        "Verified the 36 original inputs, 77 absent names, 45 optional checksums, four signed and four stock memory probes, 11 linked native readers, and the fresh end-to-end replay."
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--b3sum", default="b3sum")
    main(p.parse_args().b3sum)
