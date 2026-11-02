"""Allow only the signed build script's documented random autocfg crate-name field."""

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

NAME = re.compile(r"autocfg_([0-9a-f]{16})_([01])")
READ = re.compile(r"^read(?:v)?\(0,.*\)\s+= (0x[0-9a-f]+|[0-9]+)$")
HEX = re.compile(r"^\s*\|\s*([0-9a-f]+)  (.*)$")
CHILD = re.compile(r"^clone3?\(.*\bCLONE_THREAD\b.* = ([0-9]+)$")


def require(condition, context):
    if not condition:
        raise ValueError(context)


def read_stdin(path):
    data = bytearray()
    eof = False
    left = offset = 0
    with path.open() as stream:
        for text in stream:
            line = text.rstrip("\n")
            if left:
                row = HEX.match(line)
                require(row and int(row[1], 16) == offset, ("incomplete stdin hexdump", path.name))
                count = min(left, 16)
                words = row[2].split()[:count]
                require(len(words) == count and all(re.fullmatch(r"[0-9a-f]{2}", w) for w in words),
                        ("bad physical stdin bytes", path.name))
                data.extend(bytes.fromhex(" ".join(words)))
                offset += count
                left -= count
            else:
                got = READ.fullmatch(line)
                if got:
                    left = int(got[1], 0)
                    require(not left or not eof, ("stdin read after EOF", path.name))
                    require(len(data) + left <= 8192, ("unbounded probe", path.name))
                    eof |= left == 0
                    offset = 0
    require(not left, ("truncated stdin", path.name))
    return bytes(data), eof


def capture(where, rusts, tree, roster, cold, *, expected_shape=True):
    probes = [r for r in rusts if r["name"].startswith("autocfg_")]
    if not cold:
        require(not probes, "an unregistered capability probe ran during a settled edit")
        return roster, []
    # A rustc compiler thread may read fd 0. The stderr relay forks a process
    # with a different thread group and cannot supply the sampled input.
    traced = where / "trace"
    threads = defaultdict(list)
    for f in traced.glob("exec.[0-9]*"):
        tid = int(f.suffix[1:])
        with f.open() as lines:
            for line in lines:
                got = CHILD.match(line.rstrip("\n"))
                if got:
                    threads[tid].append(int(got[1]))
    execs = defaultdict(list)
    for exe in tree["processes"]:
        execs[exe["pid"]].append(exe["path"])
    parents = {int(k): int(v) for k, v in tree["parents"].items()}
    projected = []
    uuids = defaultdict(list)
    seen = set()
    for r in probes:
        m = NAME.fullmatch(r["name"])
        if not expected_shape:
            m = re.fullmatch(r"autocfg_([0-9a-f]{16})_([0-2])", r["name"])
        require(m and r["kind"] == "full", ("different probe shape", r["name"]))
        uuids[m[1]].append(m[2])
        pid = r["pid"]
        tids, pending = [], [pid]
        while pending:
            tid = pending.pop()
            require(tid not in tids, "cyclic thread genealogy")
            tids.append(tid)
            pending += threads[tid]
        bodies = []
        for tid in tids:
            data, eof = read_stdin(traced / f"exec.{tid}")
            if data or eof:
                require(eof, ("probe stdin did not reach EOF", tid))
                bodies.append(data)
        require(len(bodies) == 1, ("missing or ambiguous real stdin reader", pid, len(bodies)))
        body = bodies[0]
        source = body.decode("utf-8")
        # AutoCfg::with_dir deliberately compiles the zero-byte library first.
        # A non-observation is never evidence of empty input: the reader above
        # must have performed a successful physical read returning EOF.
        require(bool(source) == (m[2] != "0"), ("different detected probe source", m[2], source))
        # Follow the actual exec genealogy to the build script. Output dirs and
        # executable paths remain literal. Save its bytes as an extra witness.
        ancestor = pid
        chain = []
        while ancestor in parents:
            ancestor = parents[ancestor]
            chain += list(reversed(execs[ancestor]))
        owners = [p for p in chain if re.search(r"(?:/build-script-build|/out/build_script_build|/build_script_build-[0-9a-f]+)$", p)]
        require(owners and Path(owners[0]).is_file(), ("no physical build-script ancestry", pid, chain[:8]))
        args = list(r["argv"])
        i = args.index("--crate-name") + 1
        require(args[i] == r["name"] and sum(arg.count(r["name"]) for arg in args) == 1 and "-" in args,
                ("nonce outside its named field", r["name"]))
        args[i] = "autocfg_<independently-random>_" + m[2]
        with Path(owners[0]).open("rb") as owner_file:
            owner_sha = hashlib.file_digest(owner_file, "sha256").hexdigest()
        row = {"suffix": m[2], "argv": args, "stdin_utf8": source, "stdin_sha256": hashlib.sha256(body).hexdigest(),
               "owner": owners[0], "owner_sha256": owner_sha}
        key = json.dumps(row, sort_keys=True, separators=(",", ":"))
        require(key not in seen, ("two indistinguishable probe parents", key))
        seen.add(key)
        projected.append({"pid": pid, "actual_crate": r["name"], "equivalence": row})
    if expected_shape:
        require(sorted(sorted(v) for v in uuids.values()) == [["0"], ["0", "1"]],
                ("unexpected Ruff probe multiplicities", dict(uuids)))
    expected = Counter((r["kind"], r["name"]) for r in probes)
    raw = Counter({(kind, name): n for kind, name, n in roster["rustc"]})
    require(not (expected - raw), "actual probes missing from native roster")
    physical = [[kind, name, n] for (kind, name), n in sorted((raw - expected).items())]
    comparison = {"rustc": physical, "linkers": roster["linkers"],
                  "autocfg": sorted((r["equivalence"] for r in projected),
                                    key=lambda item: json.dumps(item, sort_keys=True))}
    return comparison, projected
