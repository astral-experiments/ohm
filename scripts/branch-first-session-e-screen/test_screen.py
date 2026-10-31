"""Offline fixture and historical native checks. This entrypoint reads no new performance samples."""

import argparse
import collections
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
import zlib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import same_branch as sb
import history
import tables
import peak


def digest_bytes(b):
    return hashlib.sha256(b).hexdigest()


def digest_file(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def reject(f):
    try:
        f()
    except (ValueError, OSError, zlib.error, subprocess.CalledProcessError):
        return
    raise AssertionError("accepted invalid or incomplete case")


def table_fixture(t):
    root = t / "store"
    root.mkdir()
    data = b"RSIC" + bytes(range(243)) * 400
    tag = "3372b4745d5226e8"
    names = tables.ROSTER["cold_roster"]
    expected = set()
    for name, count in names.items():
        for i in range(count):
            rel = Path("target/debug/incremental/namespace") / (name + "-" + str(i))
            dir_ = root / rel / f"s-aaa-_{tag}_abc-ccc"
            dir_.mkdir(parents=True)
            (dir_ / "work-products.bin").write_bytes(b"1")
            for k, base in tables.KINDS.items():
                small = name in {"ruff_memory_usage", "ty_static"}
                if small:
                    p = dir_ / (base + ".bin")
                    p.write_bytes(data if k == "G" else data[:31000])
                    os.link(p, dir_ / ("ohm-build-" + base + ".bin"))
                else:
                    head = (
                        bytes([1, ord(k), 3])
                        + len(data).to_bytes(8, "little")
                        + dir_.name.rsplit("-", 1)[0].encode()
                        + b"\0"
                    )
                    (dir_ / ("ohm-packed-" + base + ".bin")).write_bytes(zlib.compress(head + data))
            expected.add(str(rel))

    def make_ledger():
        return {str(p.relative_to(root)): tables.geometry(p.lstat()) for p in root.rglob("*")}

    def run(n):
        out = t / n
        out.mkdir()
        (out / "path-inodes.json.gz").write_bytes(gzip.compress(json.dumps(make_ledger()).encode()))
        return tables.scan(root, out, cold=True, arm="Eon")

    qualifying = run("positive")
    assert set(qualifying["sessions"]) == expected
    classifications = collections.Counter(
        s["classification"] for a in qualifying["sessions"].values() for s in a.values()
    )
    assert classifications == {"native-packed": 36, "outside-codec-size": 2}
    q = next(root.rglob("ohm-packed-query-cache.bin"))
    q.rename(q.with_name("saved.Q"))
    reject(lambda: run("partial-pair"))
    q.with_name("saved.Q").rename(q)
    raw = q.with_name("query-cache.bin")
    raw.write_bytes(data)
    reject(lambda: run("hybrid"))
    raw.unlink()
    old = q.read_bytes()
    q.write_bytes(old + b"!")
    reject(lambda: run("trailing-zlib"))
    q.write_bytes(old)
    q.write_bytes(old[:-2])
    reject(lambda: run("missing-zlib-checksum"))
    q.write_bytes(old)
    plain = zlib.decompress(old)
    for label, n, v in (("tag", 1, ord("G")), ("mask", 2, 8), ("prefix", 12, ord("!"))):
        body = bytearray(plain)
        body[n] = v
        q.write_bytes(zlib.compress(body))
        reject(lambda: run("bad-" + label))
        q.write_bytes(old)
    alias = root / "other-physical-name"
    os.link(q, alias)
    reject(lambda: run("hardlink-to-packed"))
    alias.unlink()
    return {
        "cold_units": len(expected),
        "classifications": classifications,
        "refused_table_mutations": 8,
    }


def git_fixture(ruff, t):
    # A private non-cone sparse checkout uses three genuine blobs from the immutable donor.
    repo = t / "public"
    subprocess.run(["git", "init", "-q", "--template=", repo], check=True)
    obj = (
        history.command(ruff, ["rev-parse", "--path-format=absolute", "--git-path", "objects"])
        .decode()
        .strip()
    )
    (repo / ".git/objects/info/alternates").write_text(obj + "\n")
    history.command(repo, ["config", "core.sparseCheckout", "true"])
    (repo / ".git/info").mkdir(exist_ok=True)
    (repo / ".git/info/sparse-checkout").write_text("".join("/" + s + "\n" for s in sb.PATHS))
    for key, rev in (("historical-parent", sb.A), ("historical-feature", sb.B)):
        history.command(repo, ["branch", key, rev])
    names = {"A": "historical-parent", "B": "historical-feature"}
    patch = (HERE / "inputs/ruff-28233.patch").read_bytes()
    assert sb.source_check(ruff)["complete_patch_sha256"] == sb.CHANGE_SHA
    edited, tree = history.construct(repo, patch)
    reject(lambda: history.construct(repo, patch + b"x"))
    out = t / "phases"
    out.mkdir()
    for p, state in (
        ("same-cold-A", "A"),
        ("same-edit", "A-edit"),
        ("same-repeat", "A-edit"),
        ("same-first-B", "B"),
    ):
        dest = out / p
        dest.mkdir()
        identity = history.select(repo, names, state, p, dest)
        (dest / "source.json").write_text(json.dumps(identity))
        if p == "same-edit":
            reject(lambda: history.reset_inactive(repo, names))
        if p == "same-repeat":
            assert (
                identity["watched"]
                == json.loads((out / "same-edit/source.json").read_bytes())["watched"]
            )
    history.reset_inactive(repo, names)
    assert (
        history.command(repo, ["rev-parse", "refs/heads/historical-parent"]).decode().strip()
        == sb.A
    )
    return {
        "synthetic_commit": edited,
        "source_tree": tree,
        "four_actual_checkouts": True,
        "patch_tamper_refused": True,
        "active_ref_restore_refused": True,
        "repeat_watched_stat_and_bytes_identical": True,
    }


def execution_media(first, second):
    assert (
        digest_file(first) == sb.ARCHIVE_SHA
        and digest_file(second)
        == "e7da14cca976ffe617031773132c0189ee2101f4068131e58be4fd29eda08269"
    )
    with zipfile.ZipFile(first) as previous, zipfile.ZipFile(second) as source:
        streams = json.loads(source.read("streams.json"))
        rows = json.loads(previous.read("tables.json"))
        cold = json.loads(gzip.decompress(previous.read("cold-A/path-inodes.json.gz")))
        first_b = json.loads(gzip.decompress(previous.read("first-B/path-inodes.json.gz")))
        assert len(tables.units(cold)) == len(tables.units(first_b)) == 38 and all(
            len(x) == 1 for x in tables.units(cold).values()
        )
        assert len(rows) == 20 and len(streams) == 80
        observations = []
        for unit, row in rows.items():
            for kind, s in row["streams"].items():
                for branch in ("A", "B"):
                    name = f"{branch}/{Path(unit).name}/{kind}.zlib"
                    prefix = Path(row[branch]).name.rsplit("-", 1)[0]
                    with source.open(name) as f:
                        read = tables.digest_body(f, kind, prefix, True)
                    assert streams[name] == [read["stored_bytes"], read["stored_sha256"]]
                    expected = (
                        [s["raw"]["bytes"], s["raw"]["sha256"]]
                        if branch == "A"
                        else s["native_B"]["decoded"]
                    )
                    assert [read["raw_bytes"], read["raw_sha256"]] == expected and read[
                        "alias_mask"
                    ] == 3
                    observations.append(read["stored_sha256"])
        out = {
            "run": 41221390896,
            "cold_units": 38,
            "displaced": 20,
            "actual_native_B_streams": 40,
            "independent_native_old_A_encodes": 40,
            "all_streams_digest": digest_bytes(json.dumps(sorted(observations)).encode()),
            "all_76_cold_raw_inodes_allocated": sum(
                {
                    tuple(row[:2]): row[4] * 512
                    for name, row in cold.items()
                    if "/incremental/" in name
                    and Path(name).name in ("dep-graph.bin", "query-cache.bin")
                }.values()
            ),
        }
        assert out["all_76_cold_raw_inodes_allocated"] == 807190528
        return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ruff", type=Path)
    ap.add_argument("--original", nargs=2, type=Path)
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as root:
        t = Path(root)
        observed = {"synthetic": table_fixture(t)}
        fixture = t / "shared-runner"
        fixture.mkdir()
        (fixture / "logs").mkdir()
        (fixture / "work").mkdir()
        assert not peak.calibrate(fixture, fixture / "work", fixture / "logs/peak-capability.json")[
            "available"
        ]
        with peak.command(fixture, fixture / "work", fixture / "logs"):
            pass
        assert (
            json.loads((fixture / "logs/sampled-filesystem.json").read_text())["available"] is False
        )
        observed["shared_mount_sample_refused"] = True
        if a.ruff:
            observed["historical_git"] = git_fixture(a.ruff, t)
        if a.original:
            observed["original_native"] = execution_media(*a.original)
        print(json.dumps(observed, indent=2, sort_keys=True))
