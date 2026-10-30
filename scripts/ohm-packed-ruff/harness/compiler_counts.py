"""Count two complete Cargo-launched rustcs with the same Linux tracer as the paired study."""
from pathlib import Path
import gzip
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess

CRATES = ("ruff_python_ast", "ruff_python_parser")
WILD = "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"


def prepare(output):
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("Compiler counters require x86-64 Linux.")
    if not os.access("/usr/bin/valgrind.bin", os.X_OK):
        raise RuntimeError("Install Valgrind with Callgrind and /usr/bin/valgrind.bin.")
    tracer = output / "trace-compilers"
    subprocess.run(["cc", "-O2", "-o", tracer, Path(__file__).with_name("trace-compilers.c")], check=True)
    return tracer


def command(tracer, kit, directory, cargo):
    profile = directory / "callgrind"
    profile.mkdir(mode=0o700)
    return [tracer, profile, kit / "bin/rustc", kit / WILD, ",".join(CRATES), "--", *cargo]


def compress(path):
    target = path.with_name(path.name + ".gz")
    with path.open("rb") as source, target.open("xb") as sink:
        with gzip.GzipFile(fileobj=sink, mode="wb", compresslevel=2, mtime=0) as stream:
            shutil.copyfileobj(source, stream)
    # The per-invocation directory was created empty and the full profile is retained compressed.
    path.unlink()
    return target


def self_cost(path, pid=None):
    total = 0
    edge = False
    events, totals, processes = [], [], []
    with path.open("rb") as stream:
        for line in stream:
            if line.startswith(b"pid: "):
                processes.append(line.split()[1].decode())
            elif line.startswith(b"events: "):
                events.append(line.split()[1:])
            elif line.startswith(b"totals: "):
                totals.append(int(line.split()[1]))
            elif line.startswith(b"calls="):
                if edge:
                    raise ValueError("Unfinished call edge in profile.")
                edge = True
            elif line.strip() and line[:1] in b"0123456789+-*":
                if edge:
                    edge = False
                else:
                    total += int(line.split()[-1])
    if edge or events != [[b"Ir"]] or totals != [total] or total <= 0 or (pid is not None and processes != [pid]):
        raise ValueError("Incomplete or inconsistent compiler instruction stream.")
    return total


def read(directory, stderr, subcommand):
    root = directory / "callgrind"
    stock_links = int(subcommand == "test")
    if not re.search(fr"^cargo 0\nlinks {stock_links}$".encode(), stderr, re.M):
        raise RuntimeError("Cargo status or native linker count differs from the admitted workflow.")
    result = {}
    for match in re.finditer(rb"^compiler (\d+) (ruff_python_ast|ruff_python_parser) 1 0$", stderr, re.M):
        pid, name = match[1].decode(), match[2].decode()
        argv_file = root / f"rustc.{pid}.argv"
        argv = argv_file.read_bytes().split(b"\0")
        if argv[argv.index(b"--crate-name") + 1] != match[2] or not any(arg.startswith(b"--emit=") for arg in argv):
            raise RuntimeError("The native process does not match the selected full compiler.")
        profile = root / f"output.{pid}.{pid}"
        log = root / f"valgrind.{pid}.{pid}"
        if list(root.glob(f"output.{pid}.*")) != [profile]:
            raise ValueError("Expected exactly one full profile for the compiler PID.")
        forks = {}
        for other in sorted(root.glob(f"valgrind.{pid}.*")):
            if other == log:
                continue
            child = other.name.rsplit(".", 1)[-1]
            data = other.read_bytes()
            prefix = b"==" + child.encode() + b"== "
            lines = data.splitlines()
            allowed = (b"Callgrind,", b"Copyright ", b"Using Valgrind-", b"Command: ", b"Parent PID: ")
            if not (subcommand == "test" and name == "ruff_python_parser" and child.isdecimal()
                    and lines.count(prefix + b"Parent PID: " + pid.encode()) == 1
                    and sum(line.startswith(prefix + b"Command: ") for line in lines) == 1
                    and all(line == prefix or (line.startswith(prefix) and line[len(prefix):].startswith(allowed))
                            for line in lines)):
                raise ValueError("Unexpected child profile data for the compiler PID.")
            forks[other.name] = hashlib.sha256(data).hexdigest()
            compress(other)
        root_log = log.read_bytes()
        if re.findall(rb"^==(\d+)== Events\s*:\s+Ir\s*$", root_log, re.M) != [pid.encode()]:
            raise ValueError("The compiler log must report its own Ir event.")
        collected, = re.findall(rb"^==" + pid.encode() + rb"== Collected\s+:\s+([\d,]+)\s*$", root_log, re.M)
        count = self_cost(profile, pid)
        if count != int(collected.replace(b",", b"")) or name in result:
            raise ValueError("Final count, profile rows or compiler identity disagree.")
        gz = compress(profile)
        compress(log)
        with gz.open("rb") as f:
            digest = hashlib.file_digest(f, "sha256").hexdigest()
        result[name] = {"Ir": count, "profile": gz.name, "compressed_sha256": digest,
                        "argv_sha256": hashlib.sha256(argv_file.read_bytes()).hexdigest(), "fork_logs": forks}
    if set(result) != set(CRATES):
        raise RuntimeError("Both real compiler profiles are required.")
    (root / "counts.json").write_text(json.dumps({"crates": result, "wild_links": stock_links}, indent=2) + "\n")
    return {name: row["Ir"] for name, row in result.items()}
