"""Authenticate the physically mapped driver of actual Cargo descendant compilers without changing Cargo."""

import os, threading
from pathlib import Path

import driver_map


def watch(call, folder, code, sdk, driver, write, row):
    with driver_map.reference(driver, row) as proof:
        return _watch(call, folder, code, sdk, driver, write, row, proof)


def _watch(call, folder, code, sdk, driver, write, row, proof):
    stopped = threading.Event()
    found = {}
    base = os.getpid()
    exe = (sdk / "bin/rustc").stat()

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
                    lines = driver_map.mappings(proc, driver)
                    if lines:
                        namespace = os.readlink(proc / "ns/mnt")
                        visible = driver_map.file_stat((proc / "root" / driver.relative_to("/")).stat())
                        driver_map.check_process(proof, driver, row, namespace, visible, lines)
                        found[pid] = dict(
                            mount_namespace=namespace,
                            visible=visible,
                            pid=pid,
                            ancestry=parents,
                            argv=argv,
                            maps=lines,
                            dev=visible[0],
                            ino=visible[1],
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
        write(folder / "live-drivers.json.gz",
              dict(actual=found, refused=failure, worker_pid=base, reference=proof))
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
