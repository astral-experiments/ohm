"""Count guest instructions from actual Cargo entry through every registered Linux compiler process."""
import ast
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import tarfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ohm-aarch64-linux"))
import qualify as q
import runtime as rt
from study import digest, load, need, save, sha

VG = "/usr/bin/valgrind.bin"


def rows(data):
    success = []
    for path in sorted(data.glob("proc.*")):
        pid = int(path.suffix[1:])
        for line in path.read_text(errors="strict").splitlines():
            if not re.search(r"\)\s+= 0$", line):
                continue
            need(line.startswith("execve("), "unexpected successful execveat")
            expr = re.sub(r"\)\s+= 0$", ")", line.removeprefix("execve"))
            executable, argv, env = ast.literal_eval(expr)
            need(all(isinstance(s, str) for s in [executable, *argv, *env]) and all("=" in s for s in env),
                 "incomplete kernel argv/environment")
            env = dict(s.split("=", 1) for s in env)
            success.append((pid, Path(executable), argv, env))
    return success


def event_command(profile):
    with profile.open("rb") as body:
        hits = [line[4:].strip().decode() for line in body if line.startswith(b"cmd:")]
    need(len(hits) == 1, "no unique process command in profile")
    return hits[0]


def counted_command(argv, folder, cwd, env, expected, *, timeout=1800):
    """Sample the registered real Rust invocation and both kernel jobserver pipes under Callgrind."""
    if "cargo" not in expected:
        return rt.record(argv, folder, cwd, env), {}
    folder.mkdir()
    seen = {}
    stop = threading.Event()
    args = list(map(str, argv))
    by_args = {tuple(map(os.fsencode, av)): name for name, av in expected.items() if name != "cargo"}
    with subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
        def sample():
            while not stop.is_set():
                # Cargo launches its compiler children from worker threads. Match only their full
                # registered client argv, then validate pipes directly on the observed kernel PID.
                children = set()
                for task in Path(f"/proc/{child.pid}/task").glob("*/children"):
                    try:
                        children.update(int(v) for v in task.read_text().split())
                    except (OSError, ValueError):
                        continue
                for pid in children:
                    path = Path(f"/proc/{pid}")
                    try:
                        av = (path / "cmdline").read_bytes().split(b"\0")
                        if av and not av[-1]:
                            av.pop()
                        compiler = os.fsencode(rt.SDK / "bin/rustc")
                        if compiler not in av:
                            continue
                        name = by_args.get(tuple(av[av.index(compiler):]))
                        if not name or name in seen:
                            continue
                        inherited = dict(b.split(b"=",1) for b in (path / "environ").read_bytes().split(b"\0") if b and b"=" in b)
                        flags = inherited.get(b"CARGO_MAKEFLAGS", b"")
                        numbers = re.search(rb"--jobserver-(?:auth|fds)=(\d+),(\d+)", flags)
                        if not numbers:
                            continue
                        fds = [os.readlink(path / "fd" / fd.decode()) for fd in numbers.groups()]
                        image = os.readlink(path / "exe")
                        if fds[0] == fds[1] and re.fullmatch(r"pipe:\[\d+\]", fds[0]) and "callgrind-amd64-linux" in image:
                            seen[name] = {"pid": pid, "kernel_image": image, "descriptor_numbers": [int(x) for x in numbers.groups()],
                                          "pipe": fds[0], "jobserver": flags.decode()}
                    except (OSError, ValueError):
                        continue
                stop.wait(.025)
        monitor = threading.Thread(target=sample, daemon=True)
        monitor.start()
        try:
            out, err = child.communicate(timeout=timeout)
        finally:
            stop.set()
            monitor.join()
    for name, raw in (("stdout",out),("stderr",err)):
        (folder / (name+".gz")).write_bytes(gzip.compress(raw, compresslevel=2, mtime=0))
    save(folder / "command.json", {"argv":args,"exit":child.returncode,"stdout":digest(out),"stderr":digest(err)})
    save(folder / "physical-jobserver.json", seen)
    need(child.returncode == 0, f"instrumented Cargo returned {child.returncode}: {err[-1500:]!r}")
    return subprocess.CompletedProcess(args, child.returncode, out, err), seen


def count(folder, command, env, expected, cwd):
    folder.mkdir()
    profiles = folder / "profiles"
    profiles.mkdir()
    args = [VG, "--tool=callgrind", "--trace-children=yes", "--separate-threads=no",
            "--cache-sim=no", "--branch-sim=no", "--collect-jumps=no",
            "--callgrind-out-file=" + str(profiles / "cg.%p"), "--log-file=" + str(profiles / "log.%p"), *command]
    result, descriptors = counted_command(args, folder / "command", cwd, env, expected)
    matched = {}
    for file in sorted(profiles.glob("cg.*")):
        pid = int(file.suffix[1:])
        actual = event_command(file)
        roles = [role for role, av in expected.items() if actual == " ".join(map(str, av))]
        need(len(roles) == 1 and roles[0] not in matched, f"unregistered or duplicate complete process: {actual}")
        role, = roles
        ir = q.instructions(file, pid)
        log = profiles / ("log." + str(pid))
        totals = re.findall(rb"^==" + str(pid).encode() + rb"== Collected\s+:\s+([\d,]+)\s*$", log.read_bytes(), re.M)
        need(len(totals) == 1 and int(totals[0].replace(b",", b"")) == ir, "mismatched independent Valgrind Ir")
        matched[role] = {"Ir": ir, "pid": pid, "argv": list(map(str, expected[role])), "profile": sha(file), "log": sha(log)}
        archive = file.with_suffix(file.suffix + ".gz")
        with file.open("rb") as inp, gzip.open(archive, "xb", compresslevel=2) as out:
            shutil.copyfileobj(inp, out)
        with gzip.open(archive, "rb") as inp:
            need(rt.hashlib.file_digest(inp, "sha256").hexdigest() == sha(file), "lost raw profile")
        file.unlink()
    need(matched.keys() == expected.keys(), "lost registered process")
    if "cargo" in expected:
        need(descriptors.keys() == expected.keys() - {"cargo"} and all(matched[n]["pid"] == d["pid"] for n,d in descriptors.items()),
             "actual counted rustc lacks the independently observed native jobserver pipe")
    logs = {int(p.suffix[1:]) for p in profiles.glob("log.*")}
    nonempty = {p for p in logs if (profiles / f"log.{p}").stat().st_size}
    need(nonempty == {r["pid"] for r in matched.values()}, "unaccounted subprocess logger")
    save(folder / "observed.json", {"Ir": sum(v["Ir"] for v in matched.values()), "processes": matched})
    return result, matched


def calibrate():
    root = rt.ROOT / "calibrant"
    root.mkdir()
    executable = root / "parent"
    env = rt.environment()
    rt.record(["cc", "-O2", "-pthread", "-o", executable, HERE / "calibrate.c"], rt.LOG / "calibration-cc", root, env)
    child = root / "child"
    shutil.copyfile(executable, child)
    child.chmod(0o755)
    cases = (("no-child", 150000, 0), ("ordinary", 150000, 150000), ("parent-thread", 1150000, 150000),
             ("child-only", 150000, 1150000), ("repeat", 150000, 150000))
    result = {}
    for name, n, m in cases:
        args = list(map(str, [executable, "parent", n, m, child]))
        expected = {"parent": args}
        if m:
            expected["child"] = list(map(str, [child, "child", m]))
        _, table = count(rt.LOG / ("cal-" + name), args, env, expected, root)
        result[name] = {r: d["Ir"] for r, d in table.items()}
    need(result["parent-thread"]["parent"] - result["ordinary"]["parent"] > 3_000_000 and
         result["child-only"]["child"] - result["ordinary"]["child"] > 3_000_000, "missed real kernel thread or child")
    for name, arm in (("child-only", "parent"), ("parent-thread", "child"), ("repeat", "parent"), ("repeat", "child")):
        need(abs(result[name][arm] / result["ordinary"][arm] - 1) < .01, "counts leaked into another subject")
    save(rt.LOG / "counter-calibrated.json", {"subjects": result, "valgrind": sha(Path(VG)), "source": sha(HERE / "calibrate.c")})


def measure(folder, env, ordinary, leaf="ruff_python_ast"):
    base = load(ordinary / "native.json")
    expected = {"cargo": base["cargo"][0]["argv"]}
    for r in base["rustcs"]:
        need(r["crate"] not in expected and not r["link_only"], "unexpected native compiler sharing or mode")
        expected[r["crate"]] = r["argv"]
    need(not base["link_tools"] and not base["compiler_probes"], "unregistered instructions outside Cargo / full rustcs")
    folder.mkdir()
    trace = folder / "traced"
    trace.mkdir()
    cmd = ["strace", "-ff", "-qq", "-v", "-s", "262144", "-e", "trace=execve,execveat", "-o", trace / "proc", *q.COMMAND]
    cap = rt.record(cmd, folder / "capture", rt.RUFF, env)
    need(q.typed(cap.stdout, True)[1:3] ==
         q.typed(gzip.decompress((ordinary / "cargo/stdout.gz").read_bytes()), True)[1:3],
         "freshness changed while reacquiring the ordinary physical invocation")
    seen = {}
    cargo_env, root_pid = None, None
    proxy = Path(shutil.which("cargo", path=env["PATH"]))
    proxies = []
    for pid, path, argv, inherited in rows(trace):
        if path.samefile(rt.SDK / "bin/cargo"):
            role = "cargo"
            cargo_env, root_pid = inherited, pid
        elif path.samefile(rt.SDK / "bin/rustc"):
            need("--crate-name" in argv, "unexpected native version probe")
            role = argv[argv.index("--crate-name") + 1]
            need(re.search(r"--jobserver-(?:auth|fds)=\d+,\d+", inherited.get("CARGO_MAKEFLAGS", "")) and
                 not any(k in inherited for k in ("RUSTC_WRAPPER", "LD_PRELOAD")), "missing real native jobserver")
        elif path.samefile(proxy):
            need(argv[1:] == q.COMMAND[1:] and (argv[0] == "cargo" or Path(argv[0]).samefile(proxy)),
                 "unexpected rustup proxy selection")
            proxies.append(pid)
            continue
        else:
            raise AssertionError(f"unexpected ordinary executable: {path}")
        need(role not in seen and argv == expected[role], "literal arg mismatch in reacquired source invocation")
        seen[role] = {"pid": pid, "path": str(path), "executable": sha(path), "argv": argv,
                      "environment": digest(b"\0".join(os.fsencode(k + "=" + v) for k,v in sorted(inherited.items())))}
    need(seen.keys() == expected.keys() and proxies == [root_pid] and cargo_env and cargo_env["RUSTUP_TOOLCHAIN"] == "ohm",
         "physical Rustup / signed Cargo replacement incomplete")
    save(folder / "physical.json", {"roster": seen, "cwd": str(rt.RUFF), "environment_keys": sorted(cargo_env),
                                     "root_rustup_pid": root_pid, "rustup": sha(proxy)})
    # Only the explicitly allowlisted initial environment and authenticated Rustup's additions were passed.
    with tarfile.open(folder / "trace.tar.gz", "x:gz", compresslevel=2) as out:
        out.add(trace, arcname="exec")
    shutil.rmtree(trace)
    result, observed = count(folder / "whole", expected["cargo"], cargo_env, expected, rt.RUFF)
    need(q.typed(result.stdout, True)[1:3] == q.typed(cap.stdout, True)[1:3], "counter changed the genuine Cargo workload")
    va = load(ordinary / "verified.json")
    a, = [r for r in q.typed(result.stdout, True)[0] if r["target"]["name"] == leaf]
    rlib, = [Path(n) for n in a["filenames"] if n.endswith(".rlib")]
    after = q.archive(rlib.read_bytes())
    want = lambda j: [[k, size, h] for k, _, size, h in j["objects"]]
    need(want(after) == want(va["archive"]), "counter changed ordered AArch64 object payloads")
    save(folder / "verified.json", {"Ir": sum(v["Ir"] for v in observed.values()), "processes": observed,
                                     "compiler_subtotal": sum(v["Ir"] for k,v in observed.items() if k != "cargo"),
                                     "excludes": "Rustup proxy prefix, kernel CPU, and off-clock independent QEMU reader",
                                     "archive": after["raw"]})
    return observed


if __name__ == "__main__":
    calibrate()
