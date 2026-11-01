"""Authenticate the physically mapped driver of actual Cargo descendant compilers without changing Cargo."""

import os, re, threading, time
from pathlib import Path


def watch(call, folder, code, sdk, driver, write, read):
    stopped = threading.Event()
    found = {}
    base = os.getpid()
    exe = (sdk / "bin/rustc").stat()
    ds = driver.stat()

    def sample():
        todo = [(base, [])]
        seen = set()
        while todo:
            pid, parents = todo.pop()
            if pid in seen:
                continue
            seen.add(pid)
            proc = Path("/proc") / str(pid)
            try:
                physical = (proc / "exe").stat()
                if (physical.st_dev, physical.st_ino) == (exe.st_dev, exe.st_ino):
                    if pid in found:
                        continue
                    argv = [
                        os.fsdecode(a) for a in (proc / "cmdline").read_bytes().split(b"\0") if a
                    ]
                    if "--crate-name" not in argv:
                        continue
                    lines = []
                    for line in (proc / "maps").read_text().splitlines():
                        bits = line.split(maxsplit=5)
                        if len(bits) == 6 and "x" in bits[1] and Path(bits[5]).name == driver.name:
                            maj, minor = (int(a, 16) for a in bits[3].split(":"))
                            if (
                                os.makedev(maj, minor) != ds.st_dev
                                or int(bits[4]) != ds.st_ino
                                or bits[5] != str(driver)
                            ):
                                raise RuntimeError(("foreign mapped driver", line))
                            lines.append(line)
                    if lines:
                        found[pid] = dict(
                            pid=pid,
                            ancestry=parents,
                            argv=argv,
                            maps=lines,
                            dev=ds.st_dev,
                            ino=ds.st_ino,
                        )
                    continue
                for t in (proc / "task").iterdir():
                    try:
                        children = (t / "children").read_text().split()
                    except OSError:
                        continue
                    todo.extend((int(c), parents + [pid]) for c in children)
            except (FileNotFoundError, ProcessLookupError, NotADirectoryError, PermissionError):
                continue

    failure = []

    def loop():
        try:
            while not stopped.is_set():
                sample()
                stopped.wait(0.007)
        except BaseException as ex:
            failure.append(repr(ex))

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    try:
        result = call(folder, code)
    finally:
        stopped.set()
        thread.join()
        write(folder / "live-drivers.json.gz", dict(actual=found, refused=failure, worker_pid=base))
    if failure:
        raise ValueError(failure)
    for c in result[2]:
        if c["name"] in ("ruff_python_ast", "ruff_python_edits") and c["mode"] == "compile":
            v = found.get(c["pid"])
            assert v and v["argv"][1:] == c["argv"][1:] and base == v["ancestry"][0], (
                "no authenticated mapped workload driver",
                c["name"],
                c["pid"],
            )
    return result
