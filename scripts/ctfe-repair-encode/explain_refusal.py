"""Reopen physical source, map and immutable-registry placement from the two refused originals."""

import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evidence as ev


def digest(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def original(root, mode):
    group = root / ("return-" + mode)
    base = group / "repair"
    calls = base / "calls"
    sdk = json.loads((root / "sdk/C.json").read_bytes())
    reg = json.loads((HERE / "owners.json").read_bytes())
    tool = json.loads((root / "tools/tool.json").read_bytes())
    before = json.load(gzip.open(base / "before.json.gz"))
    selection = [before["owners"][o] for o in reg["selected"]]
    ds = sdk["files"][ev.DRIVER]
    assert ds[0] == "481e8cf9c46278874b40a129f44a3825d64bc050de5f0b3ff34c0986cb4d177c"
    counts = collections.Counter()
    images = collections.Counter()
    aliases = set()
    inputs = []
    rustcs = 0
    wild = []
    for m in sorted(calls.glob("*.image")):
        role = m.name.split("-")[0]
        images[role] += 1
        device, inode, size, path = m.read_text().strip().split("\t")
        actual_path = Path(path)
        f = sdk["files"][{"cargo": "bin/cargo", "rustc": "bin/rustc", "wild": ev.WILD}[role]]
        assert list(map(int, (device, inode, size))) == [f[1], f[2], f[4]]
        if role == "rustc":
            sdkpath = actual_path.parent.parent
            rows = [l.split(maxsplit=5) for l in m.with_suffix(".maps").read_text().splitlines()]
            for wanted, name, ino, dev in [
                (sdkpath / ev.DRIVER, "driver", ds[2], ds[1]),
                (Path(tool["argv"][-1]), "interceptor", tool["file"]["ino"], tool["file"]["dev"]),
            ]:
                selected = [v for v in rows if len(v) == 6 and v[1] == "r-xp" and Path(v[5]) == wanted]
                assert len(selected) == 1
                backing = os.makedev(*(int(n, 16) for n in selected[0][3].split(":")))
                assert int(selected[0][4]) == ino and backing != dev
                aliases.add((name, backing, dev, ino, str(wanted)))
            argv = m.with_suffix(".cmdline").read_bytes().rstrip(b"\0").split(b"\0")
            rustcs += int(b"--crate-name" in argv)
        if role == "wild":
            a = m.with_suffix(".cmdline").read_bytes().rstrip(b"\0").split(b"\0")
            if b"-o" in a:
                wild.append(os.fsdecode(a[a.index(b"-o") + 1]))
    assert images == {"cargo": 1, "rustc": 397, "wild": 64} and len(wild) == 64 and rustcs == 371
    assert len(aliases) == 2
    try:
        ev.physical(calls, sdkpath, selection, inventory=sdk["files"])
    except ValueError as exc:
        assert str(exc) == "wrong mapped driver"
    else:
        raise ValueError("admitted original without positive mmap FD evidence")
    prior = set()
    cur = set()
    ns = set()
    example = {}
    environment = {}
    emitted = {}
    for phase in ("Y-B", "X-B", "comment", "unchanged", "invalid", "repair"):
        msgs = [
            m
            for line in gzip.open(group / phase / "cargo.stdout.gz")
            if (m := json.loads(line)).get("reason") == "compiler-artifact"
        ]
        env = json.load(gzip.open(group / phase / "cargo.json.gz"))["env"]
        environment[phase] = env
        regs = [m for m in msgs if m["package_id"].startswith("registry+")]
        sides = collections.Counter()
        keys = {}
        fresh = 0
        for r in regs:
            filenames = [str(Path(p).relative_to(sdkpath.parents[3] / "work")) for p in r["filenames"]]
            key = digest([r["package_id"], r["target"], r["features"], r["profile"]])
            assert key not in keys
            keys[key] = filenames
            for path in filenames:
                parts = Path(path).parts
                for c in parts:
                    if c.startswith("v2-"):
                        ns.add(c)
            sides[filenames[0].split("/")[0]] += 1
            fresh += r["fresh"]
            if r["target"]["name"] == "itoa":
                example[phase] = filenames[0]
        if phase == "unchanged":
            prior = keys
        if phase == "repair":
            cur = keys
        emitted[phase] = {
            "total": len(msgs),
            "dirty": sum(not m["fresh"] for m in msgs),
            "registry": len(regs),
            "registry_dirty": len(regs) - fresh,
            "registry_roots": dict(sides),
        }
    assert len(ns) == 1 and len(cur) == len(prior) == 337 and cur.keys() == prior.keys()
    changes = sum(prior[k] != cur[k] for k in prior)
    assert changes == 282
    assert (
        emitted["unchanged"]["registry_dirty"] == 0
        and emitted["repair"]["dirty"] == 367
        and emitted["repair"]["registry_dirty"] == 331
    )
    delta = {k: v for k, v in environment["repair"].items() if environment["unchanged"].get(k) != v}
    assert set(delta) == {
        "LD_PRELOAD",
        "OHM_QA_PACK_CARGO",
        "OHM_QA_PACK_CONTROL",
        "OHM_QA_PACK_RUSTC",
        "OHM_QA_PACK_WILD",
    }
    return dict(
        mode=mode,
        source=sdk["source"],
        images=dict(images),
        real_crate_commands=rustcs,
        actual_wild_outputs=len(wild),
        raw_aliases=sorted(aliases),
        unresolved_reference=True,
        namespace=ns.pop(),
        changed_registry_file_sets=changes,
        visits=emitted,
        itoa=example,
        repair_environment_additions=delta,
    )


if __name__ == "__main__":
    print(
        json.dumps(
            [original(Path(sys.argv[1]) / pos, mode) for pos, mode in [("01", "P"), ("02", "B")]],
            indent=2,
            sort_keys=True,
        )
    )
