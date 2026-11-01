"""Passively report selected Linux file inodes and originating process IDs without tracing Cargo's syscalls."""

import array
import ctypes
import errno
import hashlib
import json
import os
import socket
import stat
import struct
import subprocess
import sys
from pathlib import Path

OPEN = 0x20
ACCESS = 1
CLOSE = 0x10
MASK = OPEN | ACCESS | CLOSE
EVENT = struct.Struct("=IBBHQii")
LIMIT = 48
LIB = ctypes.CDLL(None, use_errno=True)
LIB.fanotify_init.argtypes = [ctypes.c_uint, ctypes.c_uint]
LIB.fanotify_mark.argtypes = [
    ctypes.c_int,
    ctypes.c_uint,
    ctypes.c_uint64,
    ctypes.c_int,
    ctypes.c_char_p,
]


def need(value, message):
    if not value:
        raise ValueError(message)


def syscall(value):
    if value < 0:
        n = ctypes.get_errno()
        raise OSError(n, os.strerror(n))
    return value


def recv_fds(sock):
    payload, control, flags, _ = sock.recvmsg(
        128, socket.CMSG_SPACE(LIMIT * 4), socket.MSG_CMSG_CLOEXEC
    )
    need(
        not flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) and len(control) == 1,
        "truncated file handoff",
    )
    level, typ, raw = control[0]
    need((level, typ) == (socket.SOL_SOCKET, socket.SCM_RIGHTS), "foreign ancillary data")
    fds = array.array("i")
    fds.frombytes(raw)
    need(0 < len(fds) <= LIMIT and payload == str(len(fds)).encode(), "wrong descriptor count")
    return list(fds)


def send_fds(sock, values):
    rights = array.array("i", values)
    payload = str(len(rights)).encode()
    need(
        sock.sendmsg([payload], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights)]) == len(payload),
        "short handoff",
    )


def grant():
    """The helper can watch only extant regular objects opened by its unprivileged caller."""
    uid = int(os.environ["SUDO_UID"])
    need(os.geteuid() == 0 and uid > 0, "expected disposable sudo helper, not a privileged Cargo")
    os.umask(0o077)
    channel = socket.socket(fileno=os.dup(1))
    need(
        channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_SEQPACKET, "wrong pipe"
    )
    fds = recv_fds(channel)
    group = syscall(LIB.fanotify_init(0x01 | 0x02, os.O_RDONLY | os.O_CLOEXEC | os.O_LARGEFILE))
    try:
        seen = set()
        for fd in fds:
            s = os.fstat(fd)
            identity = (s.st_dev, s.st_ino)
            need(
                stat.S_ISREG(s.st_mode)
                and s.st_uid == uid
                and 0 < s.st_size <= 256 * 1024**2
                and identity not in seen,
                "foreign or repeated marked object",
            )
            seen.add(identity)
            anchor = b"/proc/self/fd/" + str(fd).encode()
            pinned = os.stat(anchor)
            need((pinned.st_dev, pinned.st_ino) == identity, "kernel descriptor alias changed")
            syscall(LIB.fanotify_mark(group, 1, MASK, -100, anchor))
        send_fds(channel, [group])
    finally:
        for fd in fds + [group]:
            os.close(fd)


def fingerprint(path):
    s = path.lstat()
    need(
        path.resolve(strict=True) == path and stat.S_ISREG(s.st_mode),
        "indirect or nonregular donor",
    )
    with path.open("rb") as f:
        t = os.fstat(f.fileno())
        h = hashlib.file_digest(f, "sha256").hexdigest()
    need(
        (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        == (t.st_dev, t.st_ino, t.st_size, t.st_mtime_ns),
        "donor changed while registering",
    )
    return {"path": str(path), "dev": s.st_dev, "ino": s.st_ino, "length": s.st_size, "sha256": h}


class Watch:
    def __init__(self, paths):
        self.registrations = [fingerprint(p) for p in sorted(set(paths))]
        by_identity = {}
        for r in self.registrations:
            by_identity.setdefault((r["dev"], r["ino"]), []).append(r)
        self.identities = by_identity
        ports = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        marked = []
        try:
            for entries in by_identity.values():
                fd = os.open(entries[0]["path"], os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
                marked.append(fd)
                s = os.fstat(fd)
                need(
                    (s.st_dev, s.st_ino) == (entries[0]["dev"], entries[0]["ino"]), "changed donor"
                )
            send_fds(ports[0], marked)
            comp = subprocess.run(
                [
                    "sudo",
                    "-n",
                    "--",
                    "/usr/bin/python3",
                    "-IB",
                    str(Path(__file__).resolve()),
                    "--grant",
                ],
                stdout=ports[1],
                stderr=subprocess.PIPE,
                timeout=20,
            )
            need(
                comp.returncode == 0,
                ("fanotify not admitted", comp.returncode, comp.stderr.decode()[-900:]),
            )
            ports[0].settimeout(3)
            (self.group,) = recv_fds(ports[0])
        finally:
            for port in ports:
                port.close()
            for fd in marked:
                os.close(fd)

    def close(self):
        events = []
        try:
            while True:
                try:
                    buf = os.read(self.group, 65536)
                except BlockingIOError:
                    break
                need(buf, "unexpected fanotify EOF")
                pos = 0
                while pos < len(buf):
                    length, version, _, meta, mask, fd, pid = EVENT.unpack_from(buf, pos)
                    need(
                        version == 3
                        and length == meta == EVENT.size
                        and mask
                        and not mask & ~MASK
                        and fd >= 0
                        and pid > 0,
                        "unattributed file event or queue overflow",
                    )
                    try:
                        s = os.fstat(fd)
                        key = (s.st_dev, s.st_ino)
                        need(
                            stat.S_ISREG(s.st_mode)
                            and key in self.identities
                            and s.st_size == self.identities[key][0]["length"],
                            "wrong event file descriptor",
                        )
                        events.append(
                            {
                                "pid": pid,
                                "mask": mask,
                                "dev": s.st_dev,
                                "ino": s.st_ino,
                                "length": s.st_size,
                            }
                        )
                    finally:
                        os.close(fd)
                    pos += length
                need(pos == len(buf), "truncated kernel fanotify record")
        finally:
            os.close(self.group)
        return {"registered": self.registrations, "events": events}


def canary(where):
    where.mkdir()
    a = where / "a"
    b = where / "b"
    alias = where / "a-hardlink"
    a.write_bytes(b"original-A")
    b.write_bytes(b"unread-B")
    os.link(a, alias)
    w = Watch([a, b, alias])
    child = subprocess.Popen(
        [
            sys.executable,
            "-IB",
            "-c",
            "import sys;print(open(sys.argv[1],'rb').read().hex())",
            str(alias),
        ],
        stdout=subprocess.PIPE,
    )
    body, _ = child.communicate(timeout=10)
    proof = w.close()
    events = proof["events"]
    need(
        child.returncode == 0
        and body == b"6f726967696e616c2d41\n"
        and {e["pid"] for e in events} == {child.pid}
        and {e["ino"] for e in events} == {a.stat().st_ino}
        and all(any(e["mask"] & k for e in events) for k in (OPEN, ACCESS, CLOSE)),
        "did not correctly attribute open/read/close of the actual hardlinked object",
    )
    return {
        **proof,
        "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "kernel": os.uname().release,
        "child": child.pid,
        "exit": child.returncode,
        "stdout": body.decode(),
    }


if __name__ == "__main__":
    if sys.argv[1:] == ["--grant"]:
        grant()
    else:
        print(json.dumps(canary(Path(sys.argv[1]).resolve()), sort_keys=True))
