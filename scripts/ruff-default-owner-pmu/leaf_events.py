"""Read fixed-period, no-stack x86 perf files. Never infer a leaf from an unwound frame."""

from collections import Counter, defaultdict
from dataclasses import dataclass
import struct


def require(cond, msg):
    if not cond:
        raise ValueError(msg)


@dataclass(frozen=True)
class Mapping:
    pid: int
    when: int
    low: int
    high: int
    offset: int
    dev: tuple
    ino: int
    perm: int
    path: str


def read(b, event, period, explicit_period=False, historical_dwarf=False):
    magic, head, unit, ao, az, do, dz = struct.unpack_from("<8s6Q", b)
    require(
        magic == b"PERFILE2"
        and 56 <= head <= ao
        and az == unit
        and 100 <= unit <= 512
        and ao + az <= do
        and do + dz <= len(b),
        "perf header/attr bounds",
    )
    typ, size, cfg, per, mask, readfmt, flags = struct.unpack_from("<II5Q", b, ao)
    expected = {"retired": (0, 1), "cpu-clock": (1, 0)}
    require(
        (typ, cfg) == expected[event] and per == period and period > 0,
        "event is not registered source and fixed period",
    )
    require(
        96 <= size <= unit - 16
        and (mask == 0xB12F if historical_dwarf else mask in (7, 263))
        and flags & 2
        and flags & 32
        and flags & 64
        and flags & (1 << 18)
        and not flags & (16 | 1024),
        "unregistered sample/time/thread scope",
    )
    require(not explicit_period or mask & 256, "individual sample periods were not recorded")
    if explicit_period and not historical_dwarf:
        require(
            flags & (1 << 25) and struct.unpack_from("<i", b, ao + 92)[0] == 1,
            "samples do not use the registered monotonic clock",
        )
    require(readfmt & 16, "no loss reporting requested")
    rows, maps, execs, forks, exits = [], [], [], [], []
    kinds = Counter()
    pos = do
    tail = 16
    while pos < do + dz:
        kind, misc, length = struct.unpack_from("<IHH", b, pos)
        require(8 <= length <= do + dz - pos, "record length")
        d = memoryview(b)[pos + 8 : pos + length]
        pos += length
        kinds[kind] += 1
        require(kind not in (2, 5, 6, 13), "lost or throttled sample stream")
        if kind == 9:
            ip, pid, tid, clock = struct.unpack_from("<QIIQ", d)
            weight_at = 32 if historical_dwarf else 24
            weight = struct.unpack_from("<Q", d, weight_at)[0] if mask & 256 else per
            if historical_dwarf:
                # Prior f5667dc0 hardware originals alone contain these optional stack fields.
                slots = struct.unpack_from("<Q", d, 40)[0]
                sample_pos = 48 + 8 * slots
                abi = struct.unpack_from("<Q", d, sample_pos)[0]
                require(abi in (0, 2), "invalid historical sample ABI")
                sample_pos += 8 + (8 * struct.unpack_from("<Q", b, ao + 80)[0].bit_count() if abi else 0)
                stack = struct.unpack_from("<Q", d, sample_pos)[0]
                require(
                    stack <= 4096 and sample_pos + 8 + stack + (8 if stack else 0) + 8 == len(d),
                    "malformed historical stack",
                )
                if stack:
                    require(
                        struct.unpack_from("<Q", d, sample_pos + 8 + stack)[0] <= stack,
                        "bad historical stack size",
                    )
            else:
                require(len(d) == (32 if mask & 256 else 24), "unexpected sample fields")
            mode = misc & 7
            require(
                (mode == 2 or (mode == 1 and ip >> 63 == 1))
                and pid > 0
                and tid > 0
                and clock > 0
                and weight == per,
                "sample ownership/mode/observed period",
            )
            rows.append((clock, pid, tid, ip, weight, mode))
        elif kind == 10:
            require(not misc & (1 << 14), "MMAP2 lacks file device/inode")
            pid, tid, lo, length, offset, maj, minor, ino, gen, prot, ff = struct.unpack_from(
                "<II3QII2QII", d
            )
            src = bytes(d[64:-tail])
            require(b"\0" in src and length > 0, "MMAP2 region")
            image = src.split(b"\0")[0].decode()
            _, _, clock = struct.unpack_from("<IIQ", d, len(d) - tail)
            maps.append(Mapping(pid, clock, lo, lo + length, offset, (maj, minor), ino, prot, image))
        elif kind == 3 and misc & (1 << 13):
            pid, tid = struct.unpack_from("<II", d)
            spid, stid, clock = struct.unpack_from("<IIQ", d, len(d) - tail)
            require((pid, tid) == (spid, stid), "COMM_EXEC ownership")
            execs.append((clock, pid, tid, bytes(d[8:-tail]).split(b"\0")[0].decode()))
        elif kind in (4, 7):
            pid, ppid, tid, ptid, clock = struct.unpack_from("<IIIIQ", d)
            (forks if kind == 7 else exits).append((clock, pid, ppid, tid, ptid))
    return rows, maps, execs, forks, exits, kinds


def epochs(rows, maps, execs, forks, exits, pid, rustc_path):
    selected = [e for e in execs if e[1] == pid and e[2] == pid and e[3] == "rustc"]
    require(len(selected) == 1, "nonunique rustc exec generation")
    start = selected[0][0]
    next_exec = [t for t, p, ti, _ in execs if p == pid and t > start]
    ends = [t for t, p, pp, ti, pti in exits if p == pid and ti == pid and t > start]
    require(ends and not next_exec, "missing/ambiguous final rustc lifetime")
    end = min(ends)
    pmap = [m for m in maps if m.pid == pid and start <= m.when <= end]
    require(any(m.path == rustc_path for m in pmap), "missing matching actual signed rustc binary")
    ranges = defaultdict(list)
    for t, p, pp, ti, pti in forks:
        if p == pid and ti != pid and start <= t <= end:
            stop = [e for e, q, qp, qt, qpt in exits if q == pid and qt == ti and e >= t]
            require(len(stop) == 1, "unclosed or reused worker TID")
            ranges[ti].append((t, stop[0]))
    used = []
    for row in rows:
        clock, p, tid, ip, weight, mode = row
        if p != pid or not start <= clock <= end:
            continue
        require(
            tid == pid or len([a for a, b in ranges[tid] if a <= clock <= b]) == 1,
            "sample outside native worker lifetime",
        )
        used.append(row)
    return used, pmap


def named_mapping(row, pmap, enrolled):
    clock, pid, tid, ip, weight, mode = row
    if mode != 2:
        return "kernel skid", None
    candidates = [m for m in pmap if m.when <= clock and m.low <= ip < m.high]
    # ld.so reserves a PROT_NONE address range and maps an R/O ELF image before installing
    # the executable segment. Only a strictly older non-executable reservation can be
    # superseded here. Multiple executable mappings or a later replacement stay unresolved.
    executable = [m for m in candidates if m.perm & 4]
    if not executable and len(candidates) == 1 and candidates[0].path in enrolled:
        raise ValueError("signed mapping identity/permissions differ")
    if len(executable) != 1:
        return "overlap or absent mapping", None
    m = executable[0]
    if any(other is not m and other.when >= m.when for other in candidates):
        return "overlap or absent mapping", None
    if m.path not in enrolled:
        return "outside enrolled driver/LLVM", None
    dev, ino, basename = enrolled[m.path]
    require(m.perm & 4 and (m.dev, m.ino) == (dev, ino), "signed mapping identity/permissions differ")
    return basename, m.offset + (ip - m.low)
