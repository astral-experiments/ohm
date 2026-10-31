"""Rebuild or reopen every original regular artifact member from a content-addressed byte stream."""

from pathlib import Path
import argparse
import io
import json
import lzma
import shutil
import struct
import subprocess
import sys

D = Path(__file__).resolve().parent
sys.path.insert(0, str(D))
import proof

ROWS = ("01", "02")
PACK = D / "observations.xz"
J = proof.J
sha = proof.h.sha


def records():
    run = J((D / "run.json").read_bytes())
    assert (
        run["id"],
        run["head_sha"],
        run["run_attempt"],
        run["event"],
        run["conclusion"],
    ) == (proof.RUN, proof.HEAD, 1, "workflow_dispatch", "success")
    jobs = J((D / "jobs.json").read_bytes())
    assert len(jobs) == len({j["runner_name"] for j in jobs}) == 2
    assert all(
        j["conclusion"] == "success" and j["status"] == "completed" for j in jobs
    )
    return {
        r: J((D / ("supported-linked-" + r + ".json")).read_bytes()) for r in ROWS
    }, jobs


def originals(source):
    meta, _ = records()
    return {
        r: proof.opened(
            (source / ("supported-linked-" + r + ".zip")).read_bytes(), meta[r], r
        )
        for r in ROWS
    }


def previous(row):
    local = D.parent / ("actual-compiler-loop-" + row)
    return proof.old.opened(
        local.with_suffix(".zip").read_bytes(),
        J(local.with_suffix(".json").read_bytes()),
        row,
    )


def encode(source):
    current = originals(source)
    available = {}
    for r in ROWS:
        for path, data in sorted(previous(r).items()):
            available.setdefault(sha(data), (r, path))
    parent, objects, paths, order = {}, {}, {}, []
    for r, bundle in current.items():
        paths[r] = {}
        for path, data in sorted(bundle.items()):
            assert path == str(Path(path)) and ".." not in Path(path).parts
            digest = sha(data)
            paths[r][path] = digest
            if digest in available:
                parent[digest] = available[digest]
            elif digest not in objects:
                objects[digest] = data
                order.append([path, digest, len(data)])
    order.sort()
    header = {
        "version": 1,
        "run": proof.RUN,
        "head": proof.HEAD,
        "current": paths,
        "ancestor": parent,
        "sizes": [[h, n] for _, h, n in order],
    }
    index = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    decoded = (
        struct.pack(">I", len(index))
        + index
        + b"".join(objects[h] for _, h, _ in order)
    )
    return lzma.compress(
        decoded, format=lzma.FORMAT_XZ, check=lzma.CHECK_SHA256, preset=5
    )


def decode(p):
    stream = io.BytesIO(lzma.decompress(p.read_bytes(), format=lzma.FORMAT_XZ))
    (n,) = struct.unpack(">I", stream.read(4))
    assert 0 < n < 4 * 2**20
    doc = J(stream.read(n))
    assert (doc["version"], doc["run"], doc["head"]) == (1, proof.RUN, proof.HEAD)
    objects = {}
    for digest, size in doc["sizes"]:
        assert 0 <= size < 100_000_000 and digest not in objects
        data = stream.read(size)
        assert len(data) == size and sha(data) == digest
        objects[digest] = data
    assert not stream.read(1)
    for row in sorted({r for r, _ in doc["ancestor"].values()}):
        donor = previous(row)
        for digest, (r, path) in doc["ancestor"].items():
            if r == row:
                assert digest not in objects and sha(donor[path]) == digest
                objects[digest] = donor[path]
    assert set(objects) == {
        k for paths in doc["current"].values() for k in paths.values()
    }
    assert set(doc["current"]) == set(ROWS)
    assert all(
        p == str(Path(p)) and not Path(p).is_absolute() and ".." not in Path(p).parts
        for paths in doc["current"].values()
        for p in paths
    )
    return {
        r: {p: objects[h] for p, h in paths.items()}
        for r, paths in doc["current"].items()
    }


def verify(current):
    meta, jobs = records()
    workers = {}
    for r in ROWS:
        result = proof.audit(current[r], r)
        (job,) = [j for j in jobs if j["name"] == f"pair ({r})"]
        assert "nsc-runner-" + result["host"] == job["runner_name"]
        workers[r] = {
            "archive": meta[r],
            "job": job["id"],
            "original_regular_members": len(current[r]),
            **result,
        }
    keys = ("first-unchanged", "edit-plus-repeat")
    both = lambda v: [
        k
        for k in keys
        if all(
            w["endpoints"][k]["parent_over_candidate"] >= v for w in workers.values()
        )
    ]
    return {
        "run": proof.RUN,
        "head": proof.HEAD,
        "workers": workers,
        "advance_same_named_endpoint": both(1.80),
        "at_least_two_same_named_endpoint": both(2.00),
        "registered_no_go": not both(1.80),
    }


def fetch(dest):
    meta, _ = records()
    dest.mkdir(parents=True, exist_ok=True)
    cli = shutil.which("gh-auto") or shutil.which("gh")
    if not cli:
        raise SystemExit(
            "Install gh-auto or gh with read access to astral-experiments/ohm"
        )
    for row, m in meta.items():
        destfile = dest / (m["name"] + ".zip")
        if not destfile.exists():
            value = subprocess.check_output(
                [
                    cli,
                    "api",
                    f"repos/astral-experiments/ohm/actions/artifacts/{m['id']}/zip",
                ]
            )
            proof.opened(value, m, row)
            with destfile.open("xb") as out:
                out.write(value)
        else:
            proof.opened(destfile.read_bytes(), m, row)
    return dest


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument(
        "--originals",
        type=Path,
        help="Independently verify both original GitHub ZIPs and every byte in this packet",
    )
    a.add_argument(
        "--download",
        type=Path,
        help="Retrieve and authenticate the two source ZIPs using gh-auto or gh",
    )
    a.add_argument(
        "--pack",
        type=Path,
        help="Write a deterministic pack to a new file from --originals",
    )
    a.add_argument(
        "--full", action="store_true", help="Print the complete per-worker receipt"
    )
    flags = a.parse_args()
    if flags.download:
        flags.originals = fetch(flags.download)
    if flags.pack:
        assert flags.originals
        packed = encode(flags.originals)
        if flags.pack.exists():
            assert flags.pack.read_bytes() == packed
        else:
            with flags.pack.open("xb") as out:
                out.write(packed)
    complete = decode(flags.pack or PACK)
    if flags.originals:
        assert complete == originals(flags.originals)
    v = verify(complete)
    if not flags.full:
        v = {
            "run": v["run"],
            "same_endpoint_over_1.80": v["advance_same_named_endpoint"],
            "same_endpoint_over_2": v["at_least_two_same_named_endpoint"],
            "registered_no_go": v["registered_no_go"],
            "rows": {
                key: {
                    "phases": r["endpoints"],
                    "native_provider_commands": r["provider"]["runs"],
                    "full_PMU_calibrations": r["reopened_calibrations"],
                    "original_regular_members": r["original_regular_members"],
                }
                for key, r in v["workers"].items()
            },
        }
    print(json.dumps(v, indent=2, sort_keys=True))
