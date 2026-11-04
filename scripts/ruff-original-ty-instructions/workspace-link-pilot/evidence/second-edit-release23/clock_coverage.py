"""Bind every kernel-reported child to its final per-TID clock before using image prices."""

import collections
import gzip
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
PILOT = HERE.parent.parent
sys.path.insert(0, str(PILOT))
import component_epochs


W23 = "941425ee53b9993f2337cf7d6a8f031ac2420e86e708751a0d3208b2af852713"
W24 = "7bae04f05025e8866aca064beb9ccb492dccb28fcb119853bae4989d0427900f"


def stage(z, tag):
    census = json.loads(gzip.decompress(z.read(tag + "/owner-census.json.gz")))
    roles = {r["epoch"]: r for r in census["roles"]}
    active = {}
    last_image = {}
    last_count = {}
    children = {}
    counts = collections.Counter()
    monitor = None
    root = None
    first = None
    whole = None
    for ordinal, raw in enumerate(z.read(tag + "/tasks/epochs.tsv").splitlines()):
        a = raw.split()
        kind = a[0]
        if kind == b"M":
            assert monitor is None
            monitor = int(a[1])
        elif kind == b"I":
            image, group, tid = map(int, a[1:4])
            r = roles[image]
            assert (group, tid, a[5].decode()) == (r["pid"], r["tid"], r["trigger"])
            active[group] = image
            last_image[tid] = ordinal
            if first is None:
                assert (
                    image == 1
                    and a[5] == b"first"
                    and group == tid
                    and group != monitor
                )
                first = image
                root = group
        elif kind == b"F":
            group, caller, child, event = map(int, a[1:])
            assert child not in children and event in (1, 2, 3)
            children[child] = (group, caller, active[group], event)
        elif kind == b"C":
            image, group, tid, value, enabled, running = map(int, a[1:])
            assert roles[image]["pid"] == group and enabled == running
            counts[image] += value
            last_count[tid] = ordinal
        elif kind == b"W":
            assert whole is None
            whole = list(map(int, a[1:]))
        else:
            raise AssertionError(raw)
    assert first is not None and whole == census["outer"]
    assert whole[0] > 0 and whole[1] == whole[2] > 0 and whole[3] == 0
    assert all(counts[i] == r["counter"][0] for i, r in roles.items())
    assert set(last_count) <= {root, *children}
    missed = {}
    for child, (group, caller, image, event) in children.items():
        if last_count.get(child, -1) <= last_image.get(child, -1):
            parent = roles[image]
            missed[str(child)] = {
                "group": group,
                "caller": caller,
                "image_epoch": image,
                "ptrace_event": event,
                "mode": parent["mode"],
                "output": parent.get("output"),
            }
    assert last_count[root] > last_image[root]
    subtotal = sum(counts.values())
    startup = counts[first]
    gap = whole[0] - subtotal + startup
    return {
        "stage": tag,
        "root_pid": root,
        "fork_events": len(children),
        "missing_terminal_children": missed,
        "whole": whole,
        "all_image_epoch_instructions": subtotal,
        "root_before_first_exec_instructions": startup,
        "raw_outer_minus_all_images": whole[0] - subtotal,
        "unaccounted_whole_Cargo_instructions": gap,
        "complete_ancestry_and_counter_conservation": not missed and gap == 0,
    }


def reopen(archive, expected):
    with archive.open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == expected
    with ZipFile(archive) as z:
        if expected == W23:
            tags = [
                "P-exec-warm",
                "P-exec-warm-stable",
                "C-exec-warm",
                "C-exec-warm-stable",
            ]
        else:
            assert expected == W24
            tags = ["P-exec-warm", "P-exec-warm-stable"]
        records = {tag: stage(z, tag) for tag in tags}
        complete = {
            k
            for k, r in records.items()
            if r["complete_ancestry_and_counter_conservation"]
        }
        if expected == W23:
            assert complete == {"C-exec-warm", "C-exec-warm-stable"}
        else:
            assert complete == {"P-exec-warm"}
        result = {"original_archive_sha256": expected, "stages": records}
        if expected == W24:
            r = component_epochs.gather(z, "P-exec-warm")
            selected = {
                Path(s).name
                for s in json.loads((PILOT / "accepted-48.json").read_bytes())
            }
            prices = {
                k.removesuffix(" StockWild"): v["instructions_raw"]
                for k, v in r["native_roles"].items()
            }
            assert (
                r["all_unscaled_exact"]
                and len(prices) == 50
                and len(selected) == 48
                and selected <= prices.keys()
            )
            n = sum(prices[name] for name in selected)
            result["eligible_48_signed_native"] = n
            result["all_50_native_process_clocks"] = prices
            result["outer_less_all_eligible"] = r["outer"][0] - n
            result["excluded_native"] = {
                k: v for k, v in prices.items() if k not in selected
            }
        return result


if __name__ == "__main__":
    r = {
        str(n): reopen(Path(p), h)
        for p, n, h in zip(sys.argv[1:], [23, 24], [W23, W24], strict=True)
    }
    print(json.dumps(r, indent=2, sort_keys=True))
