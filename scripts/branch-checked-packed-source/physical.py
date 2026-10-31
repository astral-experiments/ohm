"""Retain the actual decoded file-descriptor opens and executable mappings of the selected compiler."""

import gzip
import os
from pathlib import Path
import re
import subprocess
import tempfile

from objects import digest, dump, file_sha, need


def native_lines(raw, path):
    actual = os.fsencode("<" + str(path) + ">")
    opened = [
        line
        for line in raw.splitlines()
        if actual in line and re.search(rb"^openat\(.*\)\s+=\s+[0-9]+<", line)
    ]
    mapped = [
        line
        for line in raw.splitlines()
        if actual in line
        and line.startswith(b"mmap(")
        and b"PROT_EXEC" in line
        and re.search(rb"\)\s+=\s+0x[0-9a-f]+$", line)
    ]
    return len(opened), len(mapped)


def observe(argv, cwd, env, logs, label, driver, source):
    before = file_sha(driver)
    proofs = []
    with tempfile.TemporaryDirectory(dir=cwd, prefix=".driver-") as tmp:
        prefix = Path(tmp) / "fd"
        cmd = [
            "strace",
            "-ff",
            "-qq",
            "-yy",
            "-s",
            "4096",
            "-e",
            "trace=execve,openat,mmap",
            "-o",
            str(prefix),
            *argv,
        ]
        result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, timeout=120)
        for p in sorted(prefix.parent.glob("fd.*")):
            raw = p.read_bytes()
            op, mm = native_lines(raw, driver)
            if not (op or mm):
                continue
            name = f"{label}-pid-{p.suffix[1:]}.kernel.gz"
            (logs / name).write_bytes(gzip.compress(raw, compresslevel=1, mtime=0))
            proofs.append({"name": name, "opened": op, "mapped_exec": mm, "raw_sha256": digest(raw)})
    if result.returncode and not proofs:
        (logs / (label + "-trace-refusal.stderr.gz")).write_bytes(gzip.compress(result.stderr, mtime=0))
    dump(
        logs / (label + "-physical.json"),
        {
            "driver": str(driver),
            "sha256": before,
            "source": source,
            "argv": argv,
            "cwd": str(cwd),
            "status": result.returncode,
            "positive_traces": proofs,
        },
    )
    need(
        before == file_sha(driver) and any(p["opened"] and p["mapped_exec"] for p in proofs),
        "no positive kernel FD and executable mmap for the selected driver in " + label,
    )
    return result
