"""Calibrate then account for each exec in strace's own sanitized child tree."""

from pathlib import Path
import gzip, hashlib, json, os, re, subprocess, sys

H = Path(__file__).resolve().parent
STRACE = "/usr/bin/strace"
PY = "/usr/bin/python3.12"
TRUE = "/usr/bin/true"
CARGO = "/tmp/uv-workflow-search/sdk/bin/cargo"
RUSTC = "/tmp/uv-workflow-search/sdk/bin/rustc"
CLEAN = {"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8"}
ARGS = json.loads((H / "reference.json").read_bytes())["argv"]
Q = r'"(?:\\x[0-9a-f]{2})*"'
ARGV = r"\[(?:" + Q + r"(?:, " + Q + r")*)?\]"
ENVP = r"(?:0x[0-9a-f]+|NULL)(?: /\* [0-9]+ vars? \*/)?"
EXEC = re.compile(r"^execve\((" + Q + r"), (" + ARGV + r"), " + ENVP + r"\)\s+=\s+(.*)$")
EXECAT = re.compile(
    r"^execveat\((?:AT_FDCWD|[0-9]+), ("
    + Q
    + r"), ("
    + ARGV
    + r"), "
    + ENVP
    + r", ([A-Z_0-9|]+)\)\s+=\s+(.*)$"
)
FORK = re.compile(r"^(?:clone3?|fork|vfork)\(.*\)\s+=\s+(-?[0-9]+)(?:\s+.*)?$")


def unquote(value):
    return bytes.fromhex(value[1:-1].replace("\\x", "")).decode("utf-8", "strict")


def key(v):
    return tuple(v)


def parse(logs, expected_root):
    pids = set(logs)
    edges = {}
    execs = []
    for pid, raw in sorted(logs.items()):
        assert raw.isascii() and len(raw) <= 64 << 20, "bad or excessive strace stream"
        for line in raw.splitlines():
            if not line:
                continue
            if line.startswith(("execve(", "execveat(")):
                m = EXEC.fullmatch(line)
                ext = False
                if not m:
                    m = EXECAT.fullmatch(line)
                    ext = True
                assert m, ("unreadable, truncated or environment-expanded exec", pid, line[:135])
                path, args = m.groups()[:2]
                rc = m.groups()[-1]
                if rc != "0":
                    assert re.match(r"^-1 [A-Z0-9_]+ \(", rc), ("unknown exec outcome", rc)
                    continue
                path = unquote(path)
                argv = list(map(unquote, re.findall(Q, args)))
                assert (
                    path and argv and (not ext or m.group(3) == "0")
                ), "unexpected anonymous or descriptor exec"
                assert not path.startswith("memfd:")
                execs.append({"pid": pid, "path": path, "argv": argv})
            elif line.startswith(("clone(", "clone3(", "fork(", "vfork(")):
                f = FORK.fullmatch(line)
                assert f, ("unclosed fork", line[:80])
                child = int(f.group(1))
                if child > 0:
                    assert child not in edges and child != pid, "ambiguous PID reuse"
                    edges[child] = pid
            elif line.startswith("+++ exited with ") and line.endswith(" +++"):
                pass
            else:
                raise ValueError(("unrecognized event in this process-only trace", line[:120]))
    roots = pids - set(edges)
    assert (
        len(roots) == 1 and set(edges) == pids - roots and set(edges.values()) <= pids
    ), "incomplete process tree"
    root = next(iter(roots))
    reached = {root}
    for _ in pids:
        reached |= {c for c, p in edges.items() if p in reached}
    assert reached == pids and [x["argv"] for x in execs if x["pid"] == root][:1] == [
        list(expected_root)
    ], "unexpected or disconnected trace root"
    return {"root": root, "parent": dict(sorted(edges.items())), "exec": execs}


def expected(tree, which):
    rows = tree["exec"]
    if which == "calibration":
        actual = [(r["path"], r["argv"]) for r in rows if r["path"] == TRUE]
        want = [[TRUE, "quick"], *[[TRUE, *v] for v in ARGS]]
        assert sorted(a for _, a in actual) == sorted(want), "missed short-lived, nested or long argv"
        assert any(len([r for r in rows if r["pid"] == pid]) == 2 for pid in tree["parent"]), "lost re-exec"
        assert any(tree["parent"].get(p) in tree["parent"] for p in tree["parent"]), "lost grandchild"
    else:
        found = [r for r in rows if Path(r["path"]).name == "rustc" or Path(r["argv"][0]).name == "rustc"]
        assert all(r["path"] == r["argv"][0] == RUSTC for r in found) and sorted(
            r["argv"] for r in found
        ) == sorted(ARGS), "actual scoped rustc exec roster/features/argv differed"
        assert len({r["pid"] for r in found}) == len(found) == 3
    return len(rows)


def execute(path, child, env, cwd):
    cfg = json.loads((H / "case.json").read_bytes())
    is_root = child[0] == CARGO
    assert (
        env == (cfg["workload_environment"] if is_root else CLEAN)
        and path.is_absolute()
        and not path.exists()
    )
    assert (
        (child == cfg["unscored_argv"])
        if is_root
        else (child == [PY, "-ISB", str(Path(__file__).resolve()), "fixture"])
    )
    path.mkdir()
    prefix = path / "proc"
    args = [
        STRACE,
        "-ff",
        "-qq",
        "-s",
        "131072",
        "-xx",
        "-e",
        "trace=execve,execveat,clone,clone3,fork,vfork",
        "-e",
        "signal=none",
        "-o",
        str(prefix),
        "--",
        *child,
    ]
    with (path / "stdout").open("xb") as so, (path / "stderr").open("xb") as se:
        run = subprocess.run(args, cwd=cwd, env=env, stdout=so, stderr=se, timeout=600)
    assert run.returncode == 0, (
        "scoped child tracing unavailable or command failed",
        run.returncode,
        (path / "stderr").read_bytes()[-1500:],
    )
    files = sorted(path.glob("proc.*"))
    assert 1 <= len(files) < 4096 and sum(f.stat().st_size for f in files) < 128 << 20, "trace over budget"
    logs = {int(f.name.split(".")[1]): f.read_text("ascii") for f in files}
    tree = parse(logs, child)
    n = expected(tree, "calibration" if child[0] != CARGO else "root")
    (path / "parsed.json").write_text(
        json.dumps(
            {
                "command": child,
                "env_keys": sorted(env),
                "processes": len(logs),
                "execs": n,
                "tree": tree,
                "score": False,
            },
            indent=2,
        )
        + "\n"
    )
    for f in files:
        with gzip.open(str(f) + ".gz", "xb", compresslevel=3) as z:
            z.write(f.read_bytes())
        f.unlink()
    return tree


def replay(path):
    q = json.loads((path / "parsed.json").read_bytes())
    ps = list(path.glob("proc.*.gz"))
    cfg = json.loads((H / "case.json").read_bytes())
    cmd = q["command"]
    if cmd[0] == CARGO:
        assert cmd == cfg["unscored_argv"] and q["env_keys"] == sorted(cfg["workload_environment"])
    else:
        assert (
            len(cmd) == 4
            and cmd[:2] == [PY, "-ISB"]
            and Path(cmd[2]).is_absolute()
            and Path(cmd[2]).name == "trace.py"
            and cmd[3] == "fixture"
            and q["env_keys"] == sorted(CLEAN)
        )
    tree = parse(
        {int(p.name.split(".")[1]): gzip.decompress(p.read_bytes()).decode("ascii") for p in ps},
        q["command"],
    )
    # JSON object keys are strings after serialization.
    assert json.loads(json.dumps(tree)) == q["tree"] and q["score"] is False
    assert q["execs"] == expected(tree, "calibration" if q["command"][0] != CARGO else "root") and q[
        "processes"
    ] == len(ps)
    return tree


def mutations(path):
    q = json.loads((path / "parsed.json").read_bytes())
    source = {
        int(p.name.split(".")[1]): gzip.decompress(p.read_bytes()).decode("ascii")
        for p in path.glob("proc.*.gz")
    }
    root = q["tree"]["root"]
    child = next(p for p in source if p != root)

    def reject(label, fn):
        try:
            fn()
        except (AssertionError, ValueError):
            return label
        raise AssertionError("did not reject " + label)

    # Each negative changes exactly one genuine captured property. Do not execute any new child.
    longpid = max(source, key=lambda p: len(source[p]))
    assert len(source[longpid]) > 200000
    shortened = dict(source)
    shortened[longpid] = re.sub(r', ("(?:\\x[0-9a-f]{2})*")\],', ", ...],", shortened[longpid], count=1)
    assert shortened[longpid] != source[longpid]
    leaked = dict(source)
    leaked[root] = re.sub(r"0x[0-9a-f]+ /\* [0-9]+ vars? \*/", r'["forbidden"]', leaked[root], count=1)
    assert leaked[root] != source[root]
    drop = dict(source)
    del drop[child]
    cases = [
        reject("truncated or abbreviated argv", lambda: parse(shortened, q["command"])),
        reject("expanded environment instead of pointer/count", lambda: parse(leaked, q["command"])),
        reject("missing nested child trace", lambda: parse(drop, q["command"])),
    ]
    tamper = json.loads(json.dumps(q["tree"]))
    candidate = next(e for e in tamper["exec"] if len(e["argv"]) > 1000)
    candidate["argv"][-1] += "-wrong"
    cases.append(reject("one changed long argv value", lambda: expected(tamper, "calibration")))
    return cases


def fixture():
    for i in range(len(ARGS)):
        first = os.fork()
        if not first:
            nested = os.fork()
            if not nested:
                os.execl(PY, PY, "-ISB", str(Path(__file__).resolve()), "relay", str(i))
            _, s = os.waitpid(nested, 0)
            os._exit(os.waitstatus_to_exitcode(s))
        _, s = os.waitpid(first, 0)
        assert os.waitstatus_to_exitcode(s) == 0
    subprocess.run([TRUE, "quick"], env=CLEAN, check=True)


def calibrate(folder):
    execute(folder, [PY, "-ISB", str(Path(__file__).resolve()), "fixture"], CLEAN, H)
    replay(folder)


if __name__ == "__main__":
    if sys.argv[1:] == ["fixture"]:
        fixture()
    elif len(sys.argv) == 3 and sys.argv[1] == "relay":
        os.execve(TRUE, [TRUE, *ARGS[int(sys.argv[2])]], CLEAN)
    elif len(sys.argv) == 3 and sys.argv[1] == "calibrate":
        calibrate(Path(sys.argv[2]))
    else:
        raise SystemExit("trace.py calibrate OUTPUT")
