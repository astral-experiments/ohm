"""Enforce actual filesystem and memory reserves around a private native invocation."""

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

G = 1 << 30


def cgroup_room():
    unified = [x[3:] for x in Path("/proc/self/cgroup").read_text().splitlines() if x.startswith("0::")]
    mounts = [
        x.split(" - ")[0].split()[3:5]
        for x in Path("/proc/self/mountinfo").read_text().splitlines()
        if " - cgroup2 " in x
    ]
    if len(unified) != 1 or len(mounts) != 1:
        raise RuntimeError("cannot locate unique effective cgroup2 memory domain")
    root, mount = map(Path, mounts[0])
    # Cgroup namespaces may show / even when their mount root is the container subtree.
    location = Path(unified[0])
    relative = location.relative_to(root) if location.is_relative_to(root) else location.relative_to("/")
    at = mount / relative
    if not at.is_dir() or ".." in relative.parts:
        raise RuntimeError(("unresolved cgroup accounting path", at))
    consulted = []
    for path in (at, *at.parents):
        if not path.is_relative_to(mount):
            break
        maximum = path / "memory.max"
        if maximum.exists():
            val = maximum.read_text().strip()
            used = int((path / "memory.current").read_text())
            consulted.append((str(path), None if val == "max" else int(val) - used))
    # The real cgroup root has no memory.max by design; still require the memory controller.
    if not consulted and (at != mount or "memory" not in (at / "cgroup.controllers").read_text().split()):
        raise RuntimeError("no effective memory controller")
    return consulted


def resources(work, receipts):
    available = (
        int(
            next(
                l.split()[1]
                for l in Path("/proc/meminfo").read_text().splitlines()
                if l.startswith("MemAvailable:")
            )
        )
        * 1024
    )
    cg = cgroup_room()
    return {
        "work": shutil.disk_usage(work).free,
        "receipts": shutil.disk_usage(receipts).free,
        "physical": available,
        "effective": min([available, *(v for _, v in cg if v is not None)]),
        "cgroups": cg,
    }


def admit(state, *, entry=False, bootstrap=False):
    floor = (32 if bootstrap else (16 if entry else 8)) * G
    if (
        state["work"] < (32 if bootstrap else 4) * G
        or state["receipts"] < (32 if bootstrap else 6) * G
        or state["effective"] < floor
    ):
        raise RuntimeError(("resource floor", state, entry, bootstrap))


def run(command, cwd, env, where, work, receipts, *, timeout=2400):
    """Leave stdout, stderr, the literal invocation and the final guard state on every exit."""
    initial = resources(work, receipts)
    admit(initial)
    last = initial
    minimum = {k: initial[k] for k in ("work", "receipts", "physical", "effective")}
    begin = time.monotonic()
    refusal = None
    with (where / "outer.stdout").open("xb") as stdout, (where / "outer.stderr").open("xb") as stderr:
        child = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        try:
            while child.poll() is None:
                last = resources(work, receipts)
                for k in minimum:
                    minimum[k] = min(minimum[k], last[k])
                admit(last)
                if time.monotonic() - begin > timeout:
                    raise RuntimeError("scoped native command deadline")
                try:
                    child.wait(0.4)
                except subprocess.TimeoutExpired:
                    pass
        except BaseException as error:
            refusal = repr(error)
            raise
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
            (where / "resources.json").write_text(
                json.dumps(
                    dict(start=initial, end=last, minimum=minimum, refusal=refusal, exit=child.returncode)
                )
                + "\n"
            )
    return child.returncode


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if args[:1] == ["check"]:
        status = resources(Path(args[1]), Path(args[2]))
        admit(status, entry=True, bootstrap=True)
        print(json.dumps(status))
    elif args[:1] == ["watch"]:
        work, receipts, where = map(Path, args[1:4])
        where.mkdir()
        rc = run(args[4:], Path.cwd(), dict(os.environ), where, work, receipts, timeout=180 * 60)
        # Actions logs are useful, but keep original raw streams regardless of the exit.
        for name, target in (("outer.stdout", sys.stdout.buffer), ("outer.stderr", sys.stderr.buffer)):
            with (where / name).open("rb") as stream:
                shutil.copyfileobj(stream, target)
        sys.exit(rc)
    else:
        raise SystemExit("check WORK RECEIPTS or watch WORK RECEIPTS OUTPUT COMMAND...")
