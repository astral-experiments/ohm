"""Bind the fresh repaired tables to open read-only descriptors through the post-sync allocation census."""

from contextlib import ExitStack, contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat
import time

import protocol

RAW = ("dep-graph.bin", "query-cache.bin")
PACKED = ("ohm-packed-dep-graph.bin", "ohm-packed-query-cache.bin")
FINAL = re.compile(r"s-[a-z0-9]+-_[a-f0-9]{16}_[a-z0-9]+-[a-z0-9]+")
need = protocol.require


def names(mode, owner, selected):
    need(mode in ("E", "O", "P", "B"), "unknown repair role")
    return PACKED if mode in ("O", "P") and owner in selected else RAW


def immutable(st):
    return [st.st_dev, st.st_ino, st.st_mode, st.st_nlink, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def digest(f):
    f.seek(0)
    return hashlib.file_digest(f, "sha256").hexdigest()


@contextmanager
def hold(before, selected, mode, work, wait):
    """Keep all fresh table inodes live and confirm their path, data and allocation at both census boundaries."""
    proof = {"wait_ns": wait, "begin_ns": time.monotonic_ns(), "files": {}}
    handles = {}
    with ExitStack() as stack:
        for owner, directory in before["owners"].items():
            root = Path(directory)
            need(
                root.name == owner and root.is_relative_to(work) and root.resolve(strict=True) == root,
                "unexpected physical incremental owner",
            )
            current = {p.name for p in root.iterdir() if FINAL.fullmatch(p.name)}
            (new,) = current - before["sessions"][owner].keys()
            session = root / new
            wanted = names(mode, owner, selected)
            need(
                session.resolve(strict=True) == session
                and session.is_dir()
                and {p.name for p in session.iterdir() if p.name in (*RAW, *PACKED)} == set(wanted),
                "wrong fresh raw/packed tables",
            )
            for name in wanted:
                path = session / name
                need(stat.S_ISREG(path.lstat().st_mode), "refuse nonregular table before opening")
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
                f = stack.enter_context(os.fdopen(fd, "rb"))
                handles[path] = f
                a = os.fstat(fd)
                need(
                    stat.S_ISREG(a.st_mode) and immutable(a) == immutable(path.lstat()),
                    "table FD/path mismatch",
                )
                prehash = digest(f)
                pre = os.fstat(fd)
                need(immutable(a) == immutable(pre), "table changed during first read")
                os.fsync(fd)
                posthash = digest(f)
                post = os.fstat(fd)
                need(
                    immutable(pre) == immutable(post) == immutable(path.lstat()) and prehash == posthash,
                    "table replaced or bytes changed across fsync",
                )
                proof["files"][str(path.relative_to(work))] = {
                    "identity": immutable(post),
                    "before_bytes": pre.st_blocks * 512,
                    "after_bytes": post.st_blocks * 512,
                    "before_sha256": prehash,
                    "after_sha256": posthash,
                }
        need(len(handles) == 2 * len(before["owners"]), "incomplete fresh table enrollment")
        need(
            len({tuple(d["identity"][:2]) for d in proof["files"].values()}) == len(handles),
            "different table streams alias one identity",
        )
        proof["ready_ns"] = time.monotonic_ns()
        yield proof
        for path, f in handles.items():
            row = proof["files"][str(path.relative_to(work))]
            final = os.fstat(f.fileno())
            need(
                immutable(final) == row["identity"] == immutable(path.lstat())
                and final.st_blocks * 512 == path.lstat().st_blocks * 512 == row["after_bytes"],
                "different table identity or post-sync allocation at final census",
            )
        proof["end_ns"] = time.monotonic_ns()


def verify(proof, before, after, placements, ledger, selected, mode, work, clock):
    need(
        set(proof) == {"wait_ns", "begin_ns", "ready_ns", "end_ns", "files"}
        and 0 < proof["wait_ns"] <= proof["begin_ns"] <= proof["ready_ns"] <= proof["end_ns"]
        and (clock is None or clock["stop"] <= proof["wait_ns"]),
        "table accounting overlapped Cargo",
    )
    wanted = {}
    for owner, row in placements.items():
        root = Path(before["owners"][owner])
        for name in names(mode, owner, selected):
            rel = str(root.relative_to(work) / row["final"] / name)
            wanted[rel] = after["sessions"][owner][row["final"]][name]
    need(
        len(wanted) == 2 * len(before["owners"]) and set(wanted) == set(proof["files"]),
        "missing/foreign post-sync table",
    )
    for path, identity in wanted.items():
        row = proof["files"][path]
        need(
            set(row) == {"identity", "before_bytes", "after_bytes", "before_sha256", "after_sha256"}
            and all(type(i) is int for i in row["identity"])
            and len(row["identity"]) == 7,
            "invalid table FD ledger",
        )
        dev, ino, mode_bits, links, size, mtime, ctime = row["identity"]
        need(
            stat.S_ISREG(mode_bits)
            and min(dev, ino, links, size, mtime, ctime) > 0
            and (dev, ino, links, size) == tuple(identity[k] for k in ("dev", "ino", "links", "bytes"))
            and row["after_sha256"] == row["before_sha256"] == identity["sha256"]
            and re.fullmatch("[0-9a-f]{64}", row["after_sha256"])
            and all(
                type(v) is int and v >= 0 and v % 512 == 0
                for v in (row["before_bytes"], row["after_bytes"])
            )
            and row["after_bytes"] == identity["blocks"]
            and list(ledger[path]) == [dev, ino, links, mode_bits, row["after_bytes"] // 512, size],
            "wrong held table, SHA, or post-sync whole-tree allocation",
        )
    need(
        len({tuple(v["identity"][:2]) for v in proof["files"].values()}) == len(wanted),
        "different table streams alias one identity",
    )
