"""Project positive kernel image events onto the registered cold Cargo roles."""
import hashlib
from pathlib import Path
import re
import stat
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from history import need, shapes


def ns(value):
    sec, frac = value.split(".")
    need(re.fullmatch(r"-?\d+", sec) and re.fullmatch(r"\d{9}", frac), "invalid file timestamp")
    return int(sec) * 10**9 + int(frac)


def predecessors(ledger, sha):
    """Follow the image running in each parent at the instant that it creates a child."""
    current, before, interrupted = {}, {}, set()
    checksum = hashlib.sha256()
    with ledger.open("rb") as stream:
        for line in stream:
            checksum.update(line)
            f = line.split(b"\t", 5)
            if f[0] == b"R":
                current[int(f[1])] = 0
            elif f[0] == b"N":
                current[int(f[4])] = current[int(f[1])]
            elif f[0] == b"E":
                seq, life = int(f[1]), int(f[2])
                before[seq], current[life] = current[life], seq
            elif f[0] == b"L":
                interrupted.add(int(f[3]))
    need(checksum.hexdigest() == sha, "independent positive ledger changed during lineage read")
    return before, interrupted


def inventory(ledger, verified, catalog, expected, other_link):
    """Project only the independently closed kernel images, using physical identities."""
    identities = {}
    lookups = {}
    for role, row in catalog.items():
        digest, dev, ino, mode, size, mtime, ctime = row["identity"]
        identities[dev, ino] = (role, [digest, size, stat.S_IFREG | mode, mtime, ctime])
        lookups[role] = row["path"]
    need(len(identities) == len(catalog) == 5, "Cargo, rustc, Wild, proxy and system ld must be distinct")
    before, interrupted = predecessors(ledger, verified["sha256"])
    rustcs, cargos, cargo_queries, wilds, wild_queries, system = [], [], [], [], [], []
    for event in verified["execs"]:
        seq, life, pid = event["ordinal"], event["lifetime"], event["pid"]
        image, argv = event["image"], event["argv"]
        proc, cwd, requested = event["exe"], event["cwd"], event["execfn"]
        pinned = identities.get((image["dev"], image["ino"]))
        role = pinned[0] if pinned else None
        if pinned:
            need([image["sha256"], image["size"], image["mode"], ns(image["mtime"]), ns(image["ctime"])] == pinned[1],
                 ("enrolled executable changed", role, seq))
        leaves = {Path(p).name for p in (proc, requested, argv[0])}
        if "--crate-name" in argv and "rustc" in leaves:
            need(role in ("rustc", "proxy"), ("crate arguments to a foreign rustc", pid, proc))
        if any(re.fullmatch(r"(?:[\w.]+-)*ld(?:\.bfd|\.lld|\.gold)?|rust-lld|wild|mold", leaf) for leaf in leaves):
            need(role in ("wild", "sysld"), ("unexpected linker executable", pid, proc, requested))
        if role is None or role == "proxy":
            continue
        need(Path(proc).is_absolute() and Path(cwd).is_absolute(), ("nonabsolute kernel path", pid))
        need(seq not in interrupted and proc == catalog[role]["resolved"],
             ("enrolled image did not complete exec or has a different resolved path", seq, proc))
        row = {"pid": pid, "event": seq, "lifetime": life, "image": image["id"],
               "exe": requested, "physical_exe": proc, "cwd": cwd, "argv": argv}
        if role in ("rustc", "cargo", "wild"):
            need(requested == proc == lookups[role], ("unexpected enrolled executable spelling", role, proc, requested))
        if role == "rustc":
            if "--crate-name" not in argv or any(a.startswith("--print") for a in argv):
                continue
            crate = argv[argv.index("--crate-name") + 1]
            need(not any(a in ("link-only", "ohm-link-only") or a.startswith(("link-only=", "-Zlink-only")) for a in argv),
                 ("link-only on a true empty", crate))
            if crate in {"ruff", "ruff_python_ast", "ruff_python_parser"}:
                need("-Zohm-check-relink-inputs" in argv and not any("ohm-branch-cache" in a for a in argv),
                     ("unexpected Koff compiler flags", crate))
            rustcs.append({**row, "crate": crate, "mode": "full"})
        elif role == "cargo":
            (cargo_queries if argv[1:] in (["--version"], ["-V"], ["-Vv"]) else cargos).append(row)
        elif role == "sysld":
            need(requested == lookups["sysld"], ("different system ld path", requested))
            kind, output = other_link(requested, argv)
            system.append({**row, "kind": kind, "output": output})
        elif "-o" in argv:
            need(argv.count("-o") == 1, ("ambiguous Wild output", pid))
            wilds.append({**row, "output": argv[argv.index("-o") + 1]})
        else:
            need(bool(argv[1:]) and set(argv[1:]) <= {"-v", "--version", "--help", "--print-output-format"},
                 ("unknown default Wild output", argv[:8]))
            wild_queries.append(row)
    need(len(cargos) == 1, ("expected one physical Cargo command", len(cargos)))
    cargo_event = cargos[0]["event"]
    compiler_events = {r["event"]: r for r in rustcs}
    def ancestor(seq, choices):
        while seq:
            seq = before[seq]
            if seq in choices:
                return seq
        raise ValueError(("missing native ancestor", choices if len(choices) < 3 else "rustc", seq))
    for row in rustcs + system:
        ancestor(row["event"], {cargo_event})
    for row in wilds:
        owned = compiler_events[ancestor(row["event"], compiler_events)]
        row["rustc_event"], row["rustc_crate"] = owned["event"], owned["crate"]
    physical = {"real_cargo": 1, "cargos": cargos, "cargo_queries": cargo_queries, "rustcs": rustcs,
                "wild": len(wilds), "wild_processes": wilds, "wild_queries": wild_queries,
                "other_linkers": system, "successful_exec_count": len(verified["execs"])}
    need(shapes(physical) == expected["native"], "wrong complete historical cold compiler/link roster")
    return physical
