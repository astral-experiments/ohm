"""Observe exactly one anonymous child compiler's first mapping of an ordinary private file."""

import ctypes
import hashlib
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import time


def sha(data):
    return hashlib.sha256(data).hexdigest()


def masks(fd):
    events = []
    while select.select([fd], [], [], 0)[0]:
        raw = os.read(fd, 4096)
        for _, mask, _, count in struct.iter_unpack("iIII", raw):
            assert count == 0
            events.append(mask)
    return events


def mutate(path, stamp, first):
    with path.open("r+b", buffering=0) as f:
        assert os.pwrite(f.fileno(), first, 0) == len(first)
        os.fsync(f.fileno())
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))


def run_child(args, cwd, env, source, exe, out, record, mode):
    original = source.read_bytes()
    assert original[:4] == b"rust" and source.stat().st_nlink == 1
    bad = b"R" + original[1:]
    stamp = source.stat()
    actor = ctypes.CDLL(None, use_errno=True)
    fd = actor.inotify_init1(os.O_CLOEXEC | os.O_NONBLOCK)
    assert fd >= 0 and actor.inotify_add_watch(fd, os.fsencode(source), 16 | 32) >= 0
    with (record / "stdout").open("xb") as so, (record / "stderr").open("xb") as se:
        child = subprocess.Popen(args, cwd=cwd, env=env, stdout=so, stderr=se)
        try:
            assert select.select([fd], [], [], 8)[0]
            events = masks(fd)
            maps = Path(f"/proc/{child.pid}/maps")

            def look():
                return [l for l in maps.read_text().splitlines() if str(source) in l]

            end = time.monotonic() + 3
            while not look() and child.poll() is None and time.monotonic() < end:
                time.sleep(0.0002)
            child.send_signal(signal.SIGSTOP)
            assert os.WIFSTOPPED(os.waitpid(child.pid, os.WUNTRACED)[1])
            try:
                real = Path(os.readlink(f"/proc/{child.pid}/exe"))
                assert real.samefile(exe)
                entries = look()
                events.extend(masks(fd))
                assert (
                    events == [32] and len(entries) == 1 and not list(out.glob("*.d"))
                ), (events, entries)
                cols = entries[0].split(maxsplit=5)
                assert (
                    cols[1] == "r--p"
                    and int(cols[2], 16) == 0
                    and int(cols[4]) == stamp.st_ino
                )
                assert [int(x, 16) for x in cols[3].split(":")] == [
                    os.major(stamp.st_dev),
                    os.minor(stamp.st_dev),
                ]
                addr = int(cols[0].split("-")[0], 16)
                with Path(f"/proc/{child.pid}/mem").open("rb", buffering=0) as mem:
                    before = os.pread(mem.fileno(), 16, addr)
                    assert before == original[:16]
                    if mode == "rename":
                        replacement = record / "fresh-inode"
                        replacement.write_bytes(bad)
                        replacement.chmod(stamp.st_mode)
                        os.utime(replacement, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                        os.replace(replacement, source)
                    elif mode in {"inplace", "inplace_restore"}:
                        mutate(source, stamp, bad[:1])
                    else:
                        assert mode == "sham"
                    after = source.stat()
                    visible = os.pread(mem.fileno(), 16, addr)
                    path_prefix = source.open("rb").read(16)
                    assert (stamp.st_size, stamp.st_mtime_ns) == (
                        after.st_size,
                        after.st_mtime_ns,
                    )
                    assert (stamp.st_ino != after.st_ino) == (mode == "rename")
                    expected = bad if mode.startswith("inplace") else original
                    assert (
                        visible == expected[:16]
                        and path_prefix == (original if mode == "sham" else bad)[:16]
                    )
                    changed_maps = look()
                    assert all(l.endswith(" (deleted)") for l in changed_maps) == (
                        mode == "rename"
                    )
                    if mode == "inplace_restore":
                        mutate(source, stamp, original[:1])
                    resumed = os.pread(mem.fileno(), 16, addr)
                    assert (
                        resumed
                        == (original if mode == "inplace_restore" else expected)[:16]
                    )
                    result = dict(
                        pid=child.pid,
                        actual_executable=str(real),
                        action=mode,
                        open_masks_before_intervention=events,
                        original_map=entries[0],
                        map_after=changed_maps[0],
                        size=after.st_size,
                        inode_before=stamp.st_ino,
                        inode_after=after.st_ino,
                        same_mtime=stamp.st_mtime_ns == after.st_mtime_ns,
                        original_sha256=sha(original),
                        malformed_sha256=sha(bad),
                        mapped_before=before.hex(),
                        mapped_after=visible.hex(),
                        path_after=path_prefix.hex(),
                        mapped_on_resume=resumed.hex(),
                    )
            finally:
                child.send_signal(signal.SIGCONT)
            result["rc"] = child.wait(timeout=120)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            os.close(fd)
    return result
