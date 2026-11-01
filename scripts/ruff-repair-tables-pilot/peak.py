"""Quiescent reachable allocation and process PSS on an unscored command inside its own PID namespace."""

import argparse
import errno
import gzip
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time

PROC = Path("/proc")
STOPPED = {"T", "t", "Z", "X"}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def process_ns():
    return os.readlink(PROC / "self/ns/pid")


def pids():
    return sorted(int(p.name) for p in PROC.iterdir() if p.name.isdecimal() and p.name != "1")


def state(pid):
    proc = PROC / str(pid)
    info = (proc / "stat").read_text().rsplit(")", 1)[1].split()
    tasks = {t.name: (t / "stat").read_text().rsplit(")", 1)[1].split()[0] for t in (proc / "task").iterdir()}
    return [int(info[19]), tasks]


def census():
    rows = {}
    for pid in pids():
        try:
            rows[pid] = state(pid)
        except (FileNotFoundError, ProcessLookupError):
            continue
    return rows


def send(pid, signum):
    # The namespace admission below prohibits host processes even when a child changes process group.
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    try:
        signal.pidfd_send_signal(fd, signum)
    except ProcessLookupError:
        pass
    finally:
        os.close(fd)


def quiesce():
    until = time.monotonic() + 12
    while time.monotonic() < until:
        seen = census()
        for pid, (_, tasks) in seen.items():
            if any(st not in STOPPED for st in tasks.values()):
                send(pid, signal.SIGSTOP)
        if all(st in STOPPED for _, tasks in seen.values() for st in tasks.values()) and seen == census():
            return seen
        time.sleep(0.001)
    raise RuntimeError("unscored namespace would not fully stop")


def working_session(path, root):
    rel = path.relative_to(root).parts
    return (
        len(rel) >= 3
        and re.fullmatch(r"s-[0-9a-z_]+(?:-[0-9a-z_]+)*-working", path.name) is not None
        and (
            rel[-3] == "incremental"
            or (
                len(rel) >= 4
                and rel[-4] == "incremental"
                and re.fullmatch("[0-9a-f]{16}", rel[-3]) is not None
            )
        )
    )


def files(roots):
    unique = {}
    filecount = 0
    alias_count = 0
    slots = {}
    for root in roots:
        require(root.is_dir() and not root.is_symlink(), "foreign or absent native output root")
        stack = [root]
        device = root.stat().st_dev
        while stack:
            path = stack.pop()
            st = path.lstat()
            require(st.st_dev == device, "foreign mount in a measured output root")
            key = (st.st_dev, st.st_ino)
            alloc = st.st_blocks * 512
            if key in unique:
                require(unique[key] == alloc, "allocation changed during suspended snapshot")
                alias_count += 1
            unique[key] = alloc
            filecount += 1
            if stat.S_ISDIR(st.st_mode):
                if working_session(path, root):
                    slots[str(path)] = []
                stack.extend(path.iterdir())
            elif (
                path.name
                in {
                    "query-cache.bin",
                    "dep-graph.bin",
                    "ohm-packed-dep-graph.bin",
                    "ohm-packed-query-cache.bin",
                }
                and str(path.parent) in slots
            ):
                slots[str(path.parent)].append([path.name, alloc])
            elif stat.S_ISBLK(st.st_mode) or stat.S_ISCHR(st.st_mode):
                raise RuntimeError("device opened in output tree")
    return (
        dict(
            allocated=sum(unique.values()),
            inodes=len(unique),
            names=filecount,
            aliases=alias_count,
            working_tables=slots,
        ),
        unique,
    )


def deleted_maps(proc, roots):
    for line in (proc / "maps").read_text().splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) != 6:
            continue
        addr, _, _, dev, ino, path = fields
        if path.endswith(" (deleted)") and any(path.startswith(str(root) + "/") for root in roots):
            major, minor = (int(v, 16) for v in dev.split(":"))
            yield (os.makedev(major, minor), int(ino)), proc / "map_files" / addr, path


def snapshot(roots, processes):
    before = time.monotonic_ns()
    filestate, reachable = files(roots)
    rows = {}
    unlinked = {}
    mappings = []
    for pid, (started, tids) in processes.items():
        if all(s in {"Z", "X"} for s in tids.values()):
            continue
        pp = PROC / str(pid)
        rollup = (pp / "smaps_rollup").read_text()
        pss = re.findall(r"^Pss:\s+(\d+) kB$", rollup, re.M)
        anon = re.findall(r"^Pss_Anon:\s+(\d+) kB$", rollup, re.M)
        rss = re.findall(r"^Rss:\s+(\d+) kB$", rollup, re.M)
        require(len(pss) == len(rss) == len(anon) == 1, "missing authoritative process PSS or RSS")
        rows[str(pid)] = dict(
            start=started,
            name=(pp / "comm").read_text().strip(),
            threads=len(tids),
            pss=int(pss[0]) * 1024,
            pss_anon=int(anon[0]) * 1024,
            rss=int(rss[0]) * 1024,
        )
        mappings.extend(deleted_maps(pp, roots))
        for fd in (pp / "fd").iterdir():
            link = os.readlink(fd)
            if not link.endswith(" (deleted)") or not any(link.startswith(str(r) + "/") for r in roots):
                continue
            st = fd.stat()
            if st.st_nlink == 0:
                require(stat.S_ISREG(st.st_mode), "deleted foreign-kind output")
                if (st.st_dev, st.st_ino) not in reachable:
                    unlinked[(st.st_dev, st.st_ino)] = st.st_blocks * 512
    unknown = {}
    mapped = set()
    for key, link, path in mappings:
        require(key[1] > 0, "missing mapped file identity")
        mapped.add(key)
        if key in reachable or key in unlinked:
            continue
        try:
            st = link.stat()
        except OSError as e:
            if e.errno not in (errno.EPERM, errno.EACCES):
                raise
            unknown[key] = {"path": path, "map": str(link), "errno": e.errno}
            continue
        require(stat.S_ISREG(st.st_mode) and (st.st_dev, st.st_ino) == key, "mapped-file identity mismatch")
        if st.st_nlink == 0:
            unlinked[key] = st.st_blocks * 512
        else:
            unknown[key] = {
                "path": path,
                "map": str(link),
                "reason": "remaining links outside surveyed names",
            }
    unknown = {k: v for k, v in unknown.items() if k not in unlinked}
    require(census() == processes, "process or task set changed while frozen")
    return {
        **filestate,
        "open_deleted": sum(unlinked.values()),
        "deleted_mapping_inodes": [list(k) for k in sorted(mapped)],
        "unresolved_deleted_maps": [[*k, v] for k, v in sorted(unknown.items())],
        "processes": rows,
        "pss_anon": sum(x["pss_anon"] for x in rows.values()),
        "pss": sum(x["pss"] for x in rows.values()),
        "rss": sum(x["rss"] for x in rows.values()),
        "scan_ns": time.monotonic_ns() - before,
    }


def observe(command, roots, outside, result, period=0.075):
    require(
        os.getpid() == 1
        and process_ns() != outside
        and process_ns() == os.readlink(PROC / "1/ns/pid")
        and not pids(),
        "requires a fresh, owned PID namespace and matching procfs",
    )
    require(
        len(set(roots)) == 2
        and roots[0].stat().st_dev == roots[1].stat().st_dev
        and not any(a in b.parents for a in roots for b in roots),
        "distinct same-device target/build required",
    )
    require(not any(r in result.parents for r in roots), "sampler output must be outside target/build")
    base, _ = files(roots)
    child = os.fork()
    if child == 0:
        try:
            os.execvpe(command[0], command, os.environ)
        except OSError as error:
            os.write(2, str(error).encode())
            os._exit(127)
    rows = []
    reaped = {}
    previous_resume = time.monotonic_ns()
    try:
        while True:
            # PID 1 is also the physical adopting reaper for an orphaned worker.
            while True:
                try:
                    pid, value = os.waitpid(-1, os.WNOHANG)
                except ChildProcessError:
                    break
                if not pid:
                    break
                reaped[pid] = os.waitstatus_to_exitcode(value)
            if child in reaped and not pids():
                break
            time.sleep(period)
            request = time.monotonic_ns()
            processes = quiesce()
            captured = time.monotonic_ns()
            row = snapshot(roots, processes)
            for pid, (_, tids) in processes.items():
                if any(s in {"t", "T"} for s in tids.values()):
                    send(pid, signal.SIGCONT)
            resumed = time.monotonic_ns()
            rows.append(
                {
                    **row,
                    "request_ns": request,
                    "quiescent_ns": captured,
                    "resume_ns": resumed,
                    "runnable_window_ns": captured - previous_resume,
                    "suspension_ns": resumed - request,
                }
            )
            previous_resume = resumed
    finally:
        # Namespace-only admission remains true. The command cannot leave its ancestor PID namespace.
        for pid in pids():
            send(pid, signal.SIGKILL)
    end, _ = files(roots)
    lifetimes = {}
    for row in rows:
        for pid, observed in row["processes"].items():
            key = str(pid) + "/" + str(observed["start"])
            high = lifetimes.setdefault(
                key, {"pss": 0, "pss_anon": 0, "rss": 0, "threads": 0, "name": observed["name"]}
            )
            for field in ("pss", "pss_anon", "rss", "threads"):
                high[field] = max(high[field], observed[field])
    output = dict(
        sampled_deleted_accounting_complete=not any(r["unresolved_deleted_maps"] for r in rows),
        resolution="quiescent discrete snapshots; sampled lower bounds, never true maxima",
        lifetime_sampled_max=lifetimes,
        namespace=process_ns(),
        outside_namespace=outside,
        argv=command,
        main_pid=child,
        reaped=reaped,
        exit=reaped[child],
        before=base,
        after=end,
        period_ns=int(period * 1e9),
        samples=rows,
        allocated_peak=max([base["allocated"], end["allocated"]] + [r["allocated"] for r in rows]),
        pss_anon_peak=max((r["pss_anon"] for r in rows), default=0),
        pss_peak=max((r["pss"] for r in rows), default=0),
        rss_peak=max((r["rss"] for r in rows), default=0),
        allocated_including_deleted_peak=max(
            [base["allocated"], end["allocated"]] + [r["allocated"] + r["open_deleted"] for r in rows]
        ),
    )
    result.write_bytes(
        gzip.compress(json.dumps(output, sort_keys=True, separators=(",", ":")).encode(), mtime=0)
    )
    return output["exit"]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, action="append", required=True)
    p.add_argument("--outside", required=True)
    p.add_argument("--result", type=Path, required=True)
    p.add_argument("--period", type=float, default=0.075)
    p.add_argument("command", nargs=argparse.REMAINDER)
    args = p.parse_args()
    require(
        args.command[:1] == ["--"] and len(args.command) > 1 and 0.005 <= args.period <= 0.25,
        "bad observational invocation",
    )
    sys.exit(
        observe(args.command[1:], [r.resolve() for r in args.root], args.outside, args.result, args.period)
    )
