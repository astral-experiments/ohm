"""Corroborate strace's inherited syscall reports with the kernel's process events."""

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re

# Ubuntu Noble's installed amd64 6.8-0ubuntu2, verified on the original hosted VM.
STRACE_SHA = "28f957c227012de0b18d1bd7fff2d396cb693ea60ed8013be68de071e84b5001"
SOURCE_SHA = "50eea3d2d3b46fbfc754615d17f4029b96f444121fd1dcaad9474755941589dc"
EXPECTED_OPTS = 0x10009E  # EXITKILL, TRACESECCOMP, TRACEEXEC, TRACECLONE, TRACEVFORK, TRACEFORK
WAIT = re.compile(rb"^/usr/bin/strace: \[wait\(0x([0-9a-f]+)\) = ([1-9][0-9]*)\] (.+)$")
EXIT = re.compile(r"\+\+\+ exited with ([0-9]{1,3}) \+\+\+")
FIXTURE = b"""    # Reproduce the linker's concurrent thread-group teardown without invoking a compiler.
    child = os.fork()
    if not child:
        import threading
        started = threading.Barrier(13)
        done = threading.Event()
        def worker():
            started.wait()
            done.wait()
        for _ in range(12):
            threading.Thread(target=worker, daemon=True).start()
        started.wait()
        os._exit(0)
    assert os.waitpid(child, 0) == (child, 0)
"""


def source(raw, count):
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA and 1 <= count <= 256
    pid_guard = b'len({r["pid"] for r in found}) == len(found) == 3'
    quick = b'    subprocess.run([TRUE, "quick"], env=CLEAN, check=True)\n'
    for old, new in [
        (pid_guard, pid_guard[:-1] + str(count).encode()),
        (b'        "-qq",\n', b'        "-q",\n        "-d",\n        "--seccomp-bpf",\n'),
        (quick, quick + FIXTURE),
    ]:
        assert raw.count(old) == 1
        raw = raw.replace(old, new)
    return raw


def kernel(debug, logs, tree):
    opts = re.findall(rb"^/usr/bin/strace: ptrace_setoptions = 0x([0-9a-f]+)$", debug, re.M)
    assert len(opts) == 1 and int(opts[0], 16) & EXPECTED_OPTS == EXPECTED_OPTS, "kernel syscall filtering or process tracing disabled"
    assert b"Stray PTRACE_EVENT_EXEC" not in debug
    execs, forks, exits, seccomp, waits = Counter(), Counter(), {}, 0, set()
    for line in debug.splitlines():
        if not line.startswith(b"/usr/bin/strace: [wait("):
            continue
        m = WAIT.fullmatch(line)
        assert m, "malformed kernel wait record"
        status, pid, detail = int(m[1], 16), int(m[2]), m[3]
        waits.add(pid)
        if (status & 0x7f) == 0:
            rc = status >> 8
            assert 0 <= rc <= 255 and detail == f"WIFEXITED,exitcode={rc}".encode() and pid not in exits, "duplicate or malformed kernel exit"
            exits[pid] = rc
        else:
            assert (status & 0xff) == 0x7f and detail.startswith(b"WIFSTOPPED,"), "tracee killed or unknown wait status"
            event = status >> 16
            if event in (1, 2, 3, 4, 7):
                name = {1:"FORK", 2:"VFORK", 3:"CLONE", 4:"EXEC", 7:"SECCOMP"}[event]
                assert detail == f"WIFSTOPPED,sig=SIGTRAP,EVENT_{name} ({event})".encode(), "kernel event status/text disagreement"
                if event == 4:
                    execs[pid] += 1
                elif event == 7:
                    seccomp += 1
                else:
                    forks[pid] += 1
    assert seccomp > 0 and waits == set(logs) == set(exits), "kernel/filter/terminal process roster differs"
    assert execs == Counter(row["pid"] for row in tree["exec"]), "kernel successful execs differ (PID and multiplicity)"
    assert forks == Counter(tree["parent"].values()), "kernel child births differ (parent PID and multiplicity)"
    for pid, raw in logs.items():
        lines = raw.splitlines()
        match = EXIT.fullmatch(lines[-1]) if lines else None
        assert match and int(match[1]) == exits[pid] and sum(bool(EXIT.fullmatch(s)) for s in lines) == 1, "missing or mismatched terminal exit"
    assert exits[tree["root"]] == 0 and all(exits[r["pid"]] == 0 for r in tree["exec"] if Path(r["path"]).name == "rustc"), "Cargo or rustc failed"
    return {"kernel_events": {"exec":sum(execs.values()),"birth":sum(forks.values()),"exit":len(exits),"seccomp":seccomp},
            "options":int(opts[0],16),"strace_sha256":STRACE_SHA,"debug_sha256":hashlib.sha256(debug).hexdigest()}


def inputs(path):
    p = path / "stderr"
    assert p.stat().st_size < 64 << 20, "kernel observer over budget"
    return p.read_bytes(), {int(f.name.split(".")[1]):gzip.decompress(f.read_bytes()).decode("ascii") for f in path.glob("proc.*.gz")}


def attach(tr):
    execute, replay, mutations = tr.execute, tr.replay, tr.mutations
    def live(path, *args):
        assert hashlib.sha256(Path(tr.STRACE).read_bytes()).hexdigest() == STRACE_SHA, "unexpected installed strace"
        tree = execute(path, *args)
        checked = kernel(*inputs(path), tree)
        with (path / "kernel.json").open("x") as f:
            json.dump(checked, f, sort_keys=True)
        return tree
    def review(path):
        tree = replay(path)
        assert kernel(*inputs(path), tree) == json.loads((path / "kernel.json").read_bytes()), "raw kernel event replay disagrees"
        return tree
    def hostile(path):
        original = mutations(path)
        tree = review(path)
        debug, logs = inputs(path)
        threads = [tr.FORK.fullmatch(line) for raw in logs.values() for line in raw.splitlines() if "CLONE_THREAD" in line]
        assert sum(bool(match) and int(match[1]) > 0 for match in threads) >= 12, "rapid thread-group teardown missing"
        row = next(r for r in debug.splitlines() if r.endswith(b"EVENT_EXEC (4)"))
        pid = next(p for p in logs if p != tree["root"])
        def without_exit():
            changed = dict(logs)
            changed[pid] = "\n".join(changed[pid].splitlines()[:-1])
            kernel(debug, changed, tree)
        def unknown():
            changed = dict(logs)
            changed[pid] = "???( <detached ...>\n" + changed[pid]
            tr.parse(changed, json.loads((path / "parsed.json").read_bytes())["command"])
        def bad_parent():
            changed = dict(tree, parent=dict(tree["parent"]))
            k = next(iter(changed["parent"]))
            changed["parent"][k] = 0
            kernel(debug, logs, changed)
        for label, call in [
            ("kernel omitted genuine successful exec", lambda: kernel(debug.replace(row + b"\n", b"", 1), logs, tree)),
            ("kernel manufactured extra successful exec", lambda: kernel(debug + row + b"\n", logs, tree)),
            ("kernel seccomp unavailable", lambda: kernel(re.sub(rb"ptrace_setoptions = 0x[0-9a-f]+", b"ptrace_setoptions = 0x5f", debug), logs, tree)),
            ("missing terminal TID", without_exit), ("unreadable or detached", unknown), ("wrong fork parent", bad_parent),
        ]:
            try:
                call()
            except (AssertionError, ValueError):
                continue
            raise AssertionError("did not reject " + label)
        return original
    tr.execute, tr.replay, tr.mutations = live, review, hostile
    return tr
