"""Attribute a successful native open or missing path to the actual image at that event."""

import ast
import gzip
import hashlib
import importlib.util
from pathlib import Path
import re
import subprocess
import tarfile

from records import need, save


TRACE = "execve,execveat,clone,clone3,fork,vfork,open,openat,openat2,stat,statx,newfstatat,access,faccessat,faccessat2"
BIRTH = re.compile(r"^(clone3?|fork|vfork)\(.*\)\s*=\s*([1-9][0-9]*)$")
FD = re.compile(r"^open(?:at2?)?\(.*\bO_RDONLY\b.*\)\s*=\s*([0-9]+)<([^>]*)>$")
IMAGE = re.compile(r'^execve(?:at\([^,]+, |\()("(?:[^"\\]|\\.)*"),')
QUOTED = re.compile(r'"([^"\\]*)"')
SYSCALL = re.compile(r"^(?:open(?:at2?)?|statx?|newfstatat|access|faccessat2?)\(")


def receiver(path):
    # The original source qualification exercised this exact split/resumed-syscall decoder.
    need(
        hashlib.sha256(path.read_bytes()).hexdigest()
        == "276bdcc0906ec07e21fee07ba7b46551a07053ffbf0ef1c981fa1d13359d1ce0",
        "wrong source-kit native_trace.py",
    )
    spec = importlib.util.spec_from_file_location("qualified_native_trace", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.original_calls


def read(raw, calls, catalog, side):
    parents, transitions, execs, opens, missing = {}, {}, [], [], []
    for pid, lines in raw:
        images = []
        transitions[pid] = images
        for idx, (kind, line) in enumerate(calls(lines)):
            if kind == "opaque":
                images.append((idx, None))
                continue
            if line.startswith(("execve(", "execveat(")):
                execs.append(f"{pid} {line}\n")
                if re.search(r"\)\s*= 0$", line):
                    image = IMAGE.match(line)
                    need(image, ("unparsed successful exec", pid, line[:100]))
                    images.append((idx, ast.literal_eval(image[1])))
            if m := BIRTH.match(line):
                child = int(m[2])
                need(pid != child and child not in parents, "ambiguous kernel birth")
                parents[child] = (pid, idx, "thread" if "CLONE_THREAD" in line else "process", m[1])
            if m := FD.match(line):
                path = m[2]
                if (
                    path in catalog
                    or path == str(side)
                    or Path(path).name.startswith("libgcc_s.so")
                ):
                    opens.append((pid, idx, path, line))
            elif SYSCALL.match(line) and "ENOENT" in line and str(side) in QUOTED.findall(line):
                missing.append((pid, idx, str(side), line))
    return parents, transitions, execs, opens, missing


def ownership(pid, event, parents, transitions):
    # Walk backwards through the kernel birth point, stopping at the first exec or opaque boundary.
    chain = []
    while pid is not None:
        need(not any(row["pid"] == pid for row in chain), "cyclic kernel birth")
        previous = next(
            ((i, image) for i, image in reversed(transitions.get(pid, [])) if i < event), None
        )
        if previous:
            idx, image = previous
            chain.append(dict(pid=pid, event=idx, image=image))
            return (pid, image), chain
        if pid not in parents:
            break
        parent, idx, kind, syscall = parents[pid]
        chain.append(dict(pid=pid, parent=parent, event=idx, kind=kind, syscall=syscall))
        pid, event = parent, idx
    return None, chain


def witnesses(parsed, cargo, wild, catalog, side):
    parents, transitions, _, opens, missing = parsed
    out = dict(cargo_records=[], wild_opens=[], wild_missing=[], wild_libgcc_reads=[], foreign=[])
    for label, rows in (("read", opens), ("absent", missing)):
        for pid, idx, path, line in rows:
            image, chain = ownership(pid, idx, parents, transitions)
            event = dict(pid=pid, event=idx, path=path, syscall=line, lineage=chain)
            if label == "read" and image == cargo and path in catalog:
                out["cargo_records"].append(event)
            elif image in wild:
                if label == "read" and Path(path).name.startswith("libgcc_s.so"):
                    out["wild_libgcc_reads"].append(event)
                if path == str(side):
                    out["wild_opens" if label == "read" else "wild_missing"].append(event)
            elif path == str(side):
                out["foreign"].append(event)
    return out


def record(where, cmd, env, cwd, processes, catalog, side, calls):
    raw = where / "raw-fds"
    raw.mkdir()
    argv = [
        "strace",
        "-ff",
        "-q",
        "-yy",
        "--seccomp-bpf",
        "-s",
        "262144",
        "-e",
        "trace=" + TRACE,
        "-o",
        str(raw / "pid"),
        *cmd,
    ]
    r = subprocess.run(argv, cwd=cwd, env=env, input=b"", capture_output=True, timeout=1200)
    for name, data in [("stdout", r.stdout), ("stderr", r.stderr)]:
        (where / ("cargo." + name + ".gz")).write_bytes(
            gzip.compress(data, compresslevel=3, mtime=0)
        )
    save(
        where / "command.json",
        dict(command=cmd, launch=argv, env=env, cwd=str(cwd), status=r.returncode),
    )
    # Preserve the original per-TID streams before deciding whether a witness is admissible.
    files = sorted(raw.glob("pid.*"))
    with tarfile.open(where / "syscalls.tar.gz", "x:gz", compresslevel=2) as tar:
        for f in files:
            tar.add(f, arcname=f.name, recursive=False)
    streams = (
        (int(f.suffix[1:]), f.read_text(errors="surrogateescape").splitlines()) for f in files
    )
    parsed = read(streams, calls, catalog, side)
    exe_target = where / "exec.raw"
    exe_target.write_text("".join(parsed[2]))
    native = processes.inventory(exe_target, "Foff")
    processes.compact(exe_target, where / "exec.raw.gz")
    cargo = native["cargos"][0]
    wild = {(a["pid"], a["exe"]) for a in native["wild_processes"]}
    proof = witnesses(parsed, (cargo["pid"], cargo["exe"]), wild, catalog, side)
    proof["captured_threads"] = len(files)
    save(where / "fd-witness.json", proof)
    save(where / "native.json", native)
    for f in files:
        f.unlink()
    raw.rmdir()
    return r, native, proof
