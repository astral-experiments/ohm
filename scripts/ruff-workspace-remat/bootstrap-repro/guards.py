import shutil
from pathlib import Path

G = 1 << 30


def cgroup_room():
    unified = [
        x[3:]
        for x in Path("/proc/self/cgroup").read_text().splitlines()
        if x.startswith("0::")
    ]
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
    relative = (
        location.relative_to(root)
        if location.is_relative_to(root)
        else location.relative_to("/")
    )
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
    if not consulted and (
        at != mount or "memory" not in (at / "cgroup.controllers").read_text().split()
    ):
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
