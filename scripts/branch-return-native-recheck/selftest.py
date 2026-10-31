"""Exercise the binary record and file-owner readers on valid and deliberately misleading input."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from file_trace import TRACE, read, receiver, witnesses
from records import MARK, need, save, b3, translated

C = """
#include <unistd.h>
#include <pthread.h>
#include <fcntl.h>
#include <sys/wait.h>
#include <string.h>
static void *consume(void *path) {
    int fd = open(path, O_RDONLY); char c;
    if (fd < 0 || read(fd, &c, 1) != 1 || c != 'E') _exit(4);
    close(fd); return 0;
}
int main(int argc, char **argv) {
    pid_t pid = fork(); if (pid < 0) return 5;
    if (!pid) {
        if (!strcmp(argv[1], "negative")) { execl("/usr/bin/cat", "cat", argv[2], (char*)0); _exit(6); }
        pthread_t t; if (pthread_create(&t, 0, consume, argv[2])) _exit(7);
        pthread_join(t, 0); _exit(0);
    }
    int status; if (waitpid(pid, &status, 0) != pid || !WIFEXITED(status)) return 8;
    return WEXITSTATUS(status);
}
"""


def test_wire():
    u = lambda n: n.to_bytes(4, "little")

    def name(s):
        return u(len(s)) + s.encode()

    records = b"".join(
        bytes([1]) + name(s) + bytes([0]) for s in (MARK, "/dev/null/ohm-foreign-span-bytes")
    )
    for version in (2, 4):
        base = b"\x01\0\0\0\xff" + bytes([version]) + u(2) + records + u(0)
        need(translated(base)["link_index"] is None, "absent marker trailer")
        linked = base + b"LNK1" + u(0)
        linked += b3(linked)
        observed = linked + b"OBS1" + u(1) + b"\1"
        observed += b3(observed)
        need(translated(observed)["link_index"] == 0, "valid LNK1+OBS1")
        for wrong in (
            observed[:-1],
            observed + b"?",
            linked[:-1] + bytes([linked[-1] ^ 1]),
            base + b"LNK1" + u(1) + bytes(32),
        ):
            try:
                translated(wrong)
            except ValueError:
                continue
            raise ValueError("accepted invalid indexed/digested record")
    return "strict #761ea115 wire versions 2 and 4, independent trailer and digest errors"


def role_witness(raw, calls, side, cargo, wild):
    return witnesses(read(raw, calls, {}, side), cargo, wild, {}, side)


def test_kernel(calls, temp):
    src = temp / "probe.c"
    src.write_text(C)
    exe = temp / "probe"
    subprocess.run(["cc", "-O1", "-pthread", src, "-o", exe], check=True)
    provider = temp / "payload.a"
    provider.write_bytes(b"ELF identity witness\n")
    output = {}
    for mode in ("positive", "negative"):
        dest = temp / mode
        dest.mkdir()
        result = subprocess.run(
            [
                "strace",
                "-ff",
                "-q",
                "-yy",
                "--seccomp-bpf",
                "-s",
                "16384",
                "-e",
                "trace=" + TRACE,
                "-o",
                str(dest / "pid"),
                "/usr/bin/env",
                str(exe),
                mode,
                str(provider),
            ],
            capture_output=True,
        )
        need(
            result.returncode == 0
            and result.stdout == (b"" if mode == "positive" else provider.read_bytes()),
            ("physical branch", mode, result.stderr[-500:]),
        )
        raw = {int(p.suffix[1:]): p.read_text().splitlines() for p in dest.glob("pid.*")}
        roots = [
            pid
            for pid, lines in raw.items()
            if any(s.startswith('execve("/usr/bin/env",') for s in lines)
        ]
        need(len(roots) == 1, "actual process root")
        wild = {(roots[0], str(exe))}
        got = role_witness(raw.items(), calls, provider, (roots[0], "/usr/bin/env"), wild)
        if mode == "positive":
            rows = got["wild_opens"]
            need(
                len(rows) == 1
                and [x["kind"] for x in rows[0]["lineage"][:-1]] == ["thread", "process"],
                "real fork+thread read",
            )
        else:
            rows = got["foreign"]
            need(
                not got["wild_opens"]
                and len(rows) == 1
                and rows[0]["lineage"][-1]["image"] == "/usr/bin/cat",
                "attributed a foreign cat reader to parent",
            )
        output[mode] = rows
    # Kernel PC order matters, including if the parent's foreign exec happened *after* the fork.
    raw = [
        (
            100,
            [
                'execve("/a", ["/a"], []) = 0',
                "clone(child_stack=NULL, flags=SIGCHLD <unfinished ...>",
                "<... clone resumed>) = 101",
                'execve("/b", ["/b"], []) = 0',
            ],
        ),
        (101, ['openat(AT_FDCWD, "/s", O_RDONLY) = 3</s>']),
    ]
    result = role_witness(raw, calls, Path("/s"), (99, "/cargo"), {(100, "/a")})
    need(
        len(result["wild_opens"]) == 1 and result["wild_opens"][0]["lineage"][-1]["image"] == "/a",
        "resumed fork event before later parent exec",
    )
    return output


def from_original(zip_path, calls):
    with zip_path.open("rb") as f:
        sha = hashlib.file_digest(f, "sha256").hexdigest()
    need(
        sha == "10231fdc356a0ed95fde6c0db7dd49ed6d8b8a633d9dcf12720830ae5dfdbedd",
        "wrong official source observations",
    )
    result = {}
    with zipfile.ZipFile(zip_path) as z:
        for arm in ("F", "K"):
            prefix = f"receipts/{arm}/native-shadow/higher-warm/"
            terminal = json.loads(z.read(prefix + "terminal.json"))["native"]
            archive = Path(terminal["resolved"])
            split = re.split(
                r"^== ([0-9]+) ==\n",
                gzip.decompress(z.read(prefix + "trace.gz")).decode(),
                flags=re.M,
            )
            need(not split[0] and len(split) > 1, "original raw TID corpus")
            raw = zip(map(int, split[1::2]), (x.splitlines() for x in split[2::2]))
            selected = terminal["linux_fd_evidence"]
            wild = {(s["lineage"][-1]["pid"], s["lineage"][-1]["exec"]) for s in selected}
            got = role_witness(raw, calls, archive, None, wild)
            need(
                {(x["pid"], x["event"]) for x in got["wild_opens"]}
                == {(x["pid"], x["event"]) for x in selected},
                "different original native openings",
            )
            need(
                all(
                    [k["kind"] for k in x["lineage"][:-1]] == ["thread", "process"]
                    for x in got["wild_opens"]
                ),
                "lost original forked linker worker",
            )
            result[arm] = got["wild_opens"]
    return dict(official_sha256=sha, arms=result)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("source_receiver", type=Path)
    p.add_argument("--origin", type=Path)
    p.add_argument("--receipt", type=Path)
    args = p.parse_args()
    calls = receiver(args.source_receiver)
    with tempfile.TemporaryDirectory(prefix="owned-native-reader-") as temp:
        result = {"wire": test_wire(), "kernel": test_kernel(calls, Path(temp))}
    if args.origin:
        result["independent_original"] = from_original(args.origin, calls)
    if args.receipt:
        save(args.receipt, result)
    print(json.dumps(result))
