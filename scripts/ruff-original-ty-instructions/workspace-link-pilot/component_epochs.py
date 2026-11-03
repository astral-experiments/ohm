"""Independently partition the raw image-epoch PMU events in a real workspace replay."""

from collections import Counter, defaultdict
from pathlib import Path
import gzip
import hashlib
import json
import sys
from zipfile import ZipFile


def gather(z, tag):
    def read(name):
        return z.read(tag + "/" + name)

    census = json.loads(gzip.decompress(read("owner-census.json.gz")))
    counters = defaultdict(lambda: [0, 0, 0])
    images = {}
    parents = {}
    clocks = []
    for line in read("tasks/epochs.tsv").decode().splitlines():
        kind, *row = line.split()
        if kind == "W":
            clocks.append(list(map(int, row)))
        if kind == "I":
            idx, pid, tid, mono = map(int, row[:4])
            assert idx not in images and row[4] in ("exec", "first")
            images[idx] = (pid, tid, row[4])
        if kind == "F":
            src, caller, child, event = map(int, row)
            assert child not in parents
            parents[child] = src
        if kind == "C":
            idx, pid, tid, inst, en, run = map(int, row)
            assert min(inst, en, run) >= 0 and en >= run and images[idx][0] == pid
            for i, v in enumerate((inst, en, run)):
                counters[idx][i] += v
    assert (
        clocks == [census["outer"]]
        and clocks[0][0] > 0
        and clocks[0][1] == clocks[0][2] > 0
        and clocks[0][3] == 0
    )
    roster = {r["epoch"]: r for r in census["roles"]}
    assert set(roster) == set(images) and len(roster) == len(census["roles"])
    modes = defaultdict(list)
    targets = defaultdict(list)
    owners = defaultdict(list)
    signed_file = set()
    by_pid = defaultdict(list)
    for idx, r in sorted(roster.items()):
        assert (
            images[idx] == (r["pid"], r["tid"], r["trigger"])
            and r["counter"] == counters[idx]
        )
        raw = read("tasks/" + r["argv"])
        assert hashlib.sha256(raw).hexdigest() == r["argv_sha256"]
        fields = raw.split(b"\0")
        assert (
            fields[-1] == b""
            and list(map(int, fields[:3])) == [r["pid"], r["dev"], r["ino"]]
            and fields[3].decode() == r["path"]
        )
        args = tuple(x.decode() for x in fields[4:-1])
        path = Path(r["path"])
        mode = r["mode"]
        if mode == "Wild":
            mode = "StockWild" if not tag.startswith("C-") else "SourceWild"
        elif r["path"].endswith("/qa-diagnostic-build/original"):
            assert tag.startswith("C-") and r["mode"] == "other"
            mode = "FallbackStockWild"
            signed_file.add((r["dev"], r["ino"]))
        elif mode == "other" and path.name == "exec_count":
            assert r["trigger"] == "first" and args[0] == str(path)
            assert Path(args[1]).name == "tasks" and Path(args[1]).parent.name == tag
            mode = "ObserverStartup"
        elif (
            mode == "other"
            and len(args) >= 3
            and args[1] == "-IB"
            and args[2].endswith("/workspace-link-pilot/coordinator.py")
        ):
            assert path.name.startswith("python") and tag.startswith("C-")
            mode = "Coordinator"
        elif mode == "other" and path.name in ("cargo", "rustup"):
            mode = "Cargo/rustup"
        elif mode == "other" and path == Path("/usr/bin/x86_64-linux-gnu-gcc-13"):
            assert "-o" in args and any("wild-ld" in a for a in args)
            mode = "GNU/cc"
        elif mode in ("full", "test", "metadata", "config", "link-only"):
            mode = "rustc/" + mode
        elif mode == "native-driver":
            mode = "GNU/collect2" if path.name == "collect2" else "GNU/cc"
        record = {
            "epoch": idx,
            "pid": r["pid"],
            "parent_pid": parents.get(r["pid"]),
            "trigger": r["trigger"],
            "image": r["path"],
            "dev": r["dev"],
            "ino": r["ino"],
            "mode": mode,
            "clock": r["counter"],
            "argv_sha256": r["argv_sha256"],
        }
        if mode in ("rustc/full", "rustc/test", "rustc/metadata"):
            assert r["path"].endswith("/ohm-foreign-join/sdk/bin/rustc")
            assert args.count("--crate-name") == 1
            assert args[args.index("--crate-name") + 1] == r["crate"]
            assert (mode == "rustc/test") == ("--test" in args)
            owners[(r["crate"], mode)].append(record)
        modes[mode].append(record)
        if mode in ("SourceWild", "StockWild", "FallbackStockWild"):
            assert (
                fields[3] == fields[4] or mode == "FallbackStockWild"
            ) and "-o" in args
            dest = args[args.index("-o") + 1]
            assert dest.startswith("/") and "/target/" in dest
            if mode != "FallbackStockWild":
                assert dest == r["output"]
            targets[(Path(dest).name, mode)].append(record)
            if r["trigger"] == "first":
                p = parents[r["pid"]]
                assert any(
                    prev[1] == mode
                    and prev[2] == args
                    and prev[3:] == (r["dev"], r["ino"])
                    for prev in by_pid[p]
                )
            if mode == "FallbackStockWild" and r["trigger"] == "exec":
                assert any(
                    prev[1] == "SourceWild" and prev[2] == args
                    for prev in by_pid[r["pid"]]
                )
        by_pid[r["pid"]].append((idx, mode, args, r["dev"], r["ino"]))
    assert len(signed_file) <= 1 and not (set(counters) - set(roster))

    def summed(rows):
        return {
            "epochs": dict(Counter(r["trigger"] for r in rows)),
            "instructions_raw": sum(r["clock"][0] for r in rows),
            "enabled": sum(r["clock"][1] for r in rows),
            "running": sum(r["clock"][2] for r in rows),
            "unscaled_exact": all(r["clock"][1] == r["clock"][2] for r in rows),
        }

    domains = {k: summed(v) for k, v in sorted(modes.items())}
    return {
        "outer": clocks[0],
        "domain_clocks": domains,
        "all_counted": sum(r["instructions_raw"] for r in domains.values()),
        "all_unscaled_exact": all(r["unscaled_exact"] for r in domains.values()),
        "typed_compiler_owners": {
            k + " " + m: summed(v) for (k, m), v in sorted(owners.items())
        },
        "native_roles": {
            k + " " + m: summed(v) for (k, m), v in sorted(targets.items())
        },
        "unsigned_observer_gap": clocks[0][0]
        - sum(r["instructions_raw"] for r in domains.values()),
        "logical_forks": len(parents),
    }


if __name__ == "__main__":
    path, expected, *tags = sys.argv[1:]
    with open(path, "rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == expected
    with ZipFile(path) as z:
        data = {t: gather(z, t) for t in tags}
    print(json.dumps({"sha256": expected, "stages": data}, sort_keys=True, indent=2))
