"""Read disjoint compiler subtrees from the calibrated, unchanged kernel observer."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

PRODUCER = "annotate_snippets"
DIRECT = {"ruff_db", "ty_site_packages"}
CMD = ["cargo", "+ohm", "check", "-p", "ty_server", "--lib", "--locked", "--offline", "--message-format=json"]
SHARD = re.compile(r"/v2-[0-9a-f]{16}/")


def need(value, why):
    if not value:
        raise ValueError(why)


def read(path):
    return json.loads(Path(path).read_bytes())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(argv):
    """Only the SDK shard may change across independent hosted images."""
    canonical = []
    namespaces = set()
    for i, item in enumerate(argv):
        shards = SHARD.findall(item)
        if shards:
            need(i and argv[i-1] in ("--out-dir", "--extern", "-L", "-C"), ("nonpath namespace", item))
            if argv[i-1] == "-C":
                need(item.startswith("incremental="), ("codegen option", item))
            namespaces.update(shards)
            item = SHARD.sub("/v2-<sdk>/", item)
        canonical.append(item)
    need(len(namespaces) == 1, ("SDK namespace", namespaces))
    return digest(json.dumps(canonical, separators=(",", ":")).encode())


def inspect(table, trace, selectors, process, cargo_stdout):
    """Charge the inclusive timer at each physical compiler exec exactly once."""
    def component(root, events, selected, samples, tasks, chains):
        identities = {int(row[0]): [int(row[4]), int(row[5]), row[6]]
                      for row in table.lines(trace, "exec.tsv")}
        need(events and events[0]["pid"] == root and events[0]["argv"] == CMD
             and identities[events[0]["serial"]] == process["proxy"], "actual rustup root argv or image")
        cargo, = [e for e in events if identities[e["serial"]] == process["cargo"] and e["argv"][1:] == CMD[2:]]
        need(root in chains[cargo["pid"]], "physical source-bound Cargo ancestry")
        need(all(e["kind"] == 1 for e in selected.values()), "unexpected real C driver or native linker")
        for e in events:
            if e["kind"] == 1 and e["serial"] not in selected:
                a = e["argv"][1:]
                need("--out-dir" not in a and "-o" not in a and not any(v.startswith("--emit") for v in a)
                     and (a in (["-vV"], ["--version"]) or any(v.startswith("--print") for v in a)),
                     ("unattributed active rustc", a))
        roots = {e["pid"] for e in selected.values()}
        need(len(roots) == len(selected), "multiple counted images per PID")
        typed = [json.loads(line) for line in cargo_stdout.splitlines()]
        dirty = Counter(row["target"]["name"] for row in typed if row["reason"] == "compiler-artifact" and not row["fresh"])
        need(typed[-1] == {"reason": "build-finished", "success": True}, "Cargo completion")
        rows = table.lines(trace, "tasks.tsv")
        result = []
        raw = []
        for serial, e in selected.items():
            pid, argv = e["pid"], e["argv"]
            need(not (roots & set(chains[pid][1:])) and cargo["pid"] in chains[pid][1:], "nested or orphan rustc")
            stop, = [i for i, row in enumerate(rows) if row == ["exec", str(pid), str(serial)]]
            need(not any(row[:2] == ["spawn", str(pid)] for row in rows[:stop])
                 and not any(row[:2] == ["exec", str(pid)] for row in rows[stop+1:]),
                 "compiler child before measurement or subsequent re-exec")
            name = table.option(argv, "--crate-name")
            need(table.option(argv, "--out-dir") and name, "physical output or owner missing")
            need([v for v in argv if v.startswith("--emit=")] == ["--emit=dep-info,metadata"]
                 and table.option(argv, "--crate-type") == "lib", "unexpected compiler work")
            deps = [argv[i+1].split("=",1)[0] for i,v in enumerate(argv[:-1]) if v == "--extern"]
            need((PRODUCER in deps) == (name in DIRECT), ("direct dependency", name))
            need(not any(a["pid"] != pid and pid in chains[a["pid"]] for a in events), "unexpected non-thread compiler descendant exec")
            raw.append({"crate": name, "pid": pid, "argv": argv})
            result.append({"crate": name, "pid": pid, "serial": serial, "instructions": samples[serial],
                           "group": "producer" if name == PRODUCER else "direct" if name in DIRECT else "indirect",
                           "argv_sha256": digest(json.dumps(argv,separators=(",", ":")).encode()), "tasks": sum(pid in chain for chain in chains.values())})
        need(Counter(x["crate"] for x in result) == dirty, ("typed and physical roster", dirty))
        total = samples[0]
        by_group = {k:sum(v["instructions"] for v in result if v["group"] == k) for k in ("producer","direct","indirect")}
        residual = total - sum(by_group.values())
        need(residual > 0, "overlapping or incomplete whole count")
        return {"whole": total, "residual": residual, "group": by_group, "owners": sorted(result,key=lambda r:r["crate"]),
                "root": root, "cargo": cargo["pid"], "execs": len(events), "tasks": len(tasks)}, raw
    return table.read(trace, selectors, "tree", component=component)
