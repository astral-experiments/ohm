"""Keep raw per-TID exec/child events and identify the actual compiler ancestor of each Ruff linker."""
from __future__ import annotations

import base64
import gzip
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from linux_common import CMD, RELEVANT, event, need

FLAGS = ["-ff", "-q", "--status=successful", "-s", "262144", "-e", "trace=execve,execveat,clone,clone3,fork,vfork"]

def retain(folder, dest):
    with gzip.open(dest, "xb", compresslevel=1) as stream:
        for path in sorted(folder.glob("exec.*")):
            pid = int(path.suffix[1:])
            stream.write(str(pid).encode() + b"\t" + base64.b64encode(path.read_bytes()) + b"\n")

def read(lines):
    parents, terminals, execs, tasks = {}, {}, [], set()
    for record in lines:
        pidraw, encoded = record.rstrip(b"\n").split(b"\t", 1)
        pid = int(pidraw)
        need(pid > 0 and pid not in tasks, "repeated task log")
        tasks.add(pid)
        trace = base64.b64decode(encoded, validate=True).splitlines()
        for line in trace:
            if line.startswith(b"--- ") and line.endswith(b" ---"):
                continue
            terminal = re.fullmatch(rb"\+\+\+ (?:exited with (\d+)|killed by (SIG[A-Z0-9]+)(?: \(core dumped\))?) \+\+\+", line)
            if terminal:
                need(pid not in terminals and line == trace[-1], "multiple or nonterminal task verdict")
                terminals[pid] = terminal[1].decode() if terminal[1] else terminal[2].decode()
                continue
            if line.startswith(b"execve("):
                literal, _ = event(line)
                if Path(literal).name in RELEVANT:
                    execs.append([pid, line.decode()])
                continue
            # Successful execveat or nonleader PID replacement needs different path/lifetime ownership.
            child = re.fullmatch(rb"(?:clone3?|fork|vfork)\(.*\)\s+= (\d+)", line)
            need(child is not None, "unrecognized or incomplete process event in " + str(pid) + ": " + repr(line[:110]))
            tid = int(child[1])
            need(tid > 0 and tid not in parents and b"CLONE_UNTRACED" not in line, "untracked or repeated child")
            parents[tid] = pid
        need(pid in terminals, "no kernel terminal for " + str(pid))
    roots = tasks - parents.keys()
    need(len(roots) == 1 and parents.keys() <= tasks, "missing task file or ambiguous process root")
    root = roots.pop()
    need(terminals[root] == "0", "observed Cargo launcher failed")
    for pid in tasks:
        ancestry(pid, parents, root)
    return execs, parents, root, terminals

def ancestry(pid, parents, root):
    seen = set()
    chain = []
    while pid != root:
        need(pid not in seen and pid in parents, "non-rooted process family")
        chain.append(pid)
        seen.add(pid)
        pid = parents[pid]
    return chain + [root]

def launch(rows, root, aliases, tools):
    def same(a, b):
        return a["sha256"] == b["sha256"] and a["dev_ino"] == b["dev_ino"]
    invocations = []
    rustcs = {}
    for pid, line in rows:
        path, argv = event(line.encode())
        image = aliases[path]
        if Path(path).name == "cargo" and argv[1:] != ["--version"]:
            invocations.append((pid, argv[1:], image))
        if Path(path).name == "rustc" and "--crate-name" in argv and not any(a.startswith("--print") for a in argv):
            rustcs.setdefault(pid, []).append((argv[1:], image))
    need(len(invocations) == 2 and
         [(p, argv) for p, argv, _ in invocations] == [(root, CMD[1:]), (root, CMD[2:])] and
         same(invocations[0][2], tools["rustup"]) and same(invocations[1][2], tools["cargo"]),
         "root was not the ordinary +ohm proxy followed by the authenticated Cargo")
    for chain in rustcs.values():
        args, compiler = chain[-1]
        need(same(compiler, tools["rustc"]) and (len(chain) == 1 or len(chain) == 2 and
             same(chain[0][1], tools["rustup"]) and chain[0][0] == args), "unregistered compiling rustc")
    return {"root": root, "rustc_pids": sorted(rustcs)}

def owners(tracked, parents, root, compilers, exits):
    answer = {}
    all_rust = {c["pid"] for c in compilers}
    for key, unit in tracked.items():
        own = {c["pid"] for c in unit["rustc"]}
        links = []
        for linker in unit["wild"]:
            pid = linker["pid"]
            chain = ancestry(pid, parents, root)
            hitting = [tid for tid in chain if tid in all_rust]
            need(len(hitting) == 1 and hitting[0] in own, "Wild has a foreign or ambiguous compiler ancestor")
            compiler = hitting[0]
            links.append({"wild": pid, "rustc": compiler, "chain": chain,
                          "wild_exit": exits[pid], "rustc_exit": exits[compiler]})
        if links:
            need(any(x["wild_exit"] == x["rustc_exit"] == "0" for x in links), "no successful native owner for " + key)
            answer[key] = links
    return answer
