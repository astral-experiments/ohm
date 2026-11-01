"""Keep the natural Cargo jobserver's actual kernel endpoints across the original-artifact upload."""

from array import array
import ctypes
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import termios
import time


def need(ok, why):
    if not ok:
        raise ValueError(why)


def numbers(env):
    pairs = re.findall(r"(?:^|\s)--jobserver-(?:auth|fds)=(\d+),(\d+)(?=\s|$)", env["CARGO_MAKEFLAGS"])
    need(pairs and len(set(pairs)) == 1, "missing or ambiguous Cargo jobserver")
    read, write = map(int, pairs[0])
    need(2 < read < 1024 and 2 < write < 1024 and read != write, "unsafe Cargo descriptors")
    return (read, write)


def describe(fds):
    ends = []
    for fd, mode in zip(fds, (os.O_RDONLY, os.O_WRONLY), strict=True):
        st = os.fstat(fd)
        access = fcntl.fcntl(fd, fcntl.F_GETFL)
        need(stat.S_ISFIFO(st.st_mode) and access & os.O_ACCMODE == mode, "wrong jobserver endpoint or open mode")
        ends.append({"fd": fd, "dev": st.st_dev, "ino": st.st_ino, "mode": st.st_mode, "flags": access})
    n = array("i", [0])
    fcntl.ioctl(fds[0], termios.FIONREAD, n, True)
    return {"platform": sys.platform, "ends": ends, "available_bytes": n[0]}


def identity(description):
    """Compare the pipe endpoints and their open status while preserving raw F_GETFL in each receipt."""
    platform = description["platform"]
    need(platform in ("darwin", "linux") and len(description["ends"]) == 2, "unknown pipe description")
    # XNU exposes FMARK and FDEFER from Unix-socket garbage collection in F_GETFL.
    # Neither controls pipe I/O. Every other bit still has to match across SCM_RIGHTS.
    gc_bits = (0x1000 | 0x2000) if platform == "darwin" else 0
    ends = []
    for end, mode in zip(description["ends"], (os.O_RDONLY, os.O_WRONLY), strict=True):
        need(stat.S_ISFIFO(end["mode"]) and end["flags"] & os.O_ACCMODE == mode, "invalid recorded pipe")
        ends.append((end["dev"], end["ino"], end["mode"], end["flags"] & ~gc_bits))
    return platform, ends


def process_list(pid):
    """Darwin PROC_PIDLISTFDS. Preserve the live process's FD type without consuming a token."""
    lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    size = 8192
    buf = (ctypes.c_int32 * (size // 4))()
    got = lib.proc_pidinfo(ctypes.c_int(pid), 1, ctypes.c_ulonglong(0), buf, size)
    if got <= 0:
        return {"errno": ctypes.get_errno(), "fds": {}}
    need(got % 8 == 0 and got < size, "partial/oversize native FD roster")
    return {"errno": 0, "fds": {str(buf[i]): buf[i + 1] for i in range(0, got // 4, 2)}}


def transmit(sock, message, fds=()):
    extra = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array("i", fds))] if fds else []
    raw = json.dumps(message).encode() + b"\n"
    need(len(raw) < 2048 and sock.sendmsg([raw], extra) == len(raw), "short jobserver handoff")


def receive(sock):
    data, extra, flags, _ = sock.recvmsg(2048, socket.CMSG_SPACE(2 * array("i").itemsize))
    need(not flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC), "truncated jobserver handoff")
    while not data.endswith(b"\n"):
        more = sock.recv(2048 - len(data))
        need(more and len(data) < 2048, "incomplete jobserver message")
        data += more
    fds = array("i")
    for level, typ, raw in extra:
        need((level, typ) == (socket.SOL_SOCKET, socket.SCM_RIGHTS), "foreign handoff data")
        fds.frombytes(raw)
    return json.loads(data), list(fds)


def address(root):
    path = root / "archive-handoff" / "sock"
    need(len(os.fsencode(path)) < 103 and path.parent.stat().st_mode & 0o777 == 0o700, "unsafe local broker socket")
    return str(path)


def exchange(root, message, fds=()):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(10)
        sock.connect(address(root))
        transmit(sock, message, fds)
        return receive(sock)


def broker(root):
    path = address(root)
    saved = []
    deadline = time.monotonic() + 40 * 60
    try:
        with socket.socket(socket.AF_UNIX) as srv:
            srv.bind(path)
            os.chmod(path, 0o600)
            srv.listen(2)
            for expected in ("offer", "claim"):
                srv.settimeout(deadline - time.monotonic())
                conn, _ = srv.accept()
                with conn:
                    conn.settimeout(10)
                    msg, fds = receive(conn)
                    if msg == "stop" and not fds:
                        transmit(conn, "stopped")
                        return
                    need(msg == expected, "unexpected broker operation")
                    if expected == "offer":
                        need(len(fds) == 2, "required actual open file descriptions")
                        saved = fds
                        transmit(conn, describe(saved))
                    else:
                        need(not fds and len(saved) == 2, "invalid claim")
                        transmit(conn, describe(saved), saved)
    finally:
        for fd in saved:
            os.close(fd)
        if os.path.exists(path):
            os.unlink(path)


def exec_child(record_path, receipt, role, high):
    rec = json.loads(Path(record_path).read_bytes())
    env = rec["environment"]
    nums = numbers(env)
    if role == "closed-fds":
        need(not high, "closed FD control received the pipe")
        for fd in nums:
            try:
                os.fstat(fd)
            except OSError as error:
                need(error.errno == errno.EBADF, "unexpected FD refusal")
            else:
                raise ValueError("closed FD control retained an actor")
        desc = None
    else:
        need(len(high) == 2 and min(high) > max(nums), "descriptor collision")
        for src, dst in zip(high, nums, strict=True):
            os.dup2(src, dst, inheritable=True)
            os.close(src)
        desc = describe(nums)
    argv = rec["argv"] + (["-Zassert-incr-state=loaded"] if role == "loaded" else [])
    with Path(receipt).open("x") as out:
        json.dump(
            {"pid": os.getpid(), "cwd": os.getcwd(), "argv": argv, "env": env, "fds": desc}, out, sort_keys=True
        )
    os.execve(argv[0], argv, env)


if __name__ == "__main__":
    if sys.argv[1] == "serve":
        broker(Path(sys.argv[2]))
    elif sys.argv[1] == "exec":
        exec_child(sys.argv[2], sys.argv[3], sys.argv[4], list(map(int, sys.argv[5:])))
    else:
        raise SystemExit(2)
