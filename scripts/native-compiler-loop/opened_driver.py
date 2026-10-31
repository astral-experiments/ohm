"""Bind real successful rustc execs to successful dynamic compiler-driver opens on that PID."""

from collections import defaultdict
from pathlib import Path
import os
import re


def inspect(lines, rustc, driver):
    crates = defaultdict(list)
    opens = defaultdict(list)
    for raw in lines:
        ident, proc = raw.rstrip().split(b" ", 1)
        pid = int(ident)
        if (
            proc.startswith(b"execve(")
            and proc.endswith(b"= 0")
            and b'"--crate-name"' in proc
            and b'"--out-dir"' in proc
            and not re.search(rb'"--print(?:=|")', proc)
        ):
            exe = re.match(rb'execve\("([^"]+)",', proc)
            name = re.search(rb'"--crate-name", "([^"]+)"', proc)
            assert exe and name
            path = Path(os.fsdecode(exe[1]))
            if rustc(path):
                crates[pid].append(name[1].decode())
        if b"librustc_driver" not in proc or not proc.startswith((b"openat(", b"openat2(")):
            continue
        call = re.search(rb'^openat2?\([^"]*"([^"]+)"[^\n]*\)\s+=\s*[0-9]+$', proc)
        if not call:
            continue
        actual = Path(os.fsdecode(call[1]))
        assert actual.is_absolute() and driver(actual), actual
        opens[pid].append(str(actual))
    found = []
    for pid, values in crates.items():
        assert len(values) == 1 and opens[pid], (pid, values, opens[pid])
        found.append([pid, values[0], opens[pid]])
    return sorted(found)
