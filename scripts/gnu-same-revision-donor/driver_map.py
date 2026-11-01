"""Bind an executable VMA to a live mapping made from the verified SDK file descriptor."""

import contextlib
import hashlib
import mmap
import os
import re
from pathlib import Path
import stat

from binding import need


def file_stat(s):
    return [
        s.st_dev,
        s.st_ino,
        stat.S_IMODE(s.st_mode),
        s.st_size,
        s.st_mtime_ns,
        s.st_ctime_ns,
    ]


def mappings(proc, driver):
    lines = []
    for line in (proc / "maps").read_text().splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) != 6 or "x" not in fields[1]:
            continue
        if Path(fields[5].removesuffix(" (deleted)")).name == driver.name:
            lines.append(line)
    return lines


def identity(line, driver):
    region, perms, offset, dev, ino, path = line.split(maxsplit=5)
    start, end = (int(x, 16) for x in region.split("-"))
    major, minor = (int(x, 16) for x in dev.split(":"))
    need(
        perms == "r-xp" and path == str(driver) and start < end and int(ino) > 0,
        ("unexpected executable driver mapping", line),
    )
    return (os.makedev(major, minor), int(ino)), int(offset, 16), end - start


def check_reference(proof, driver, row):
    backing, offset, size = identity(proof["map"], driver)
    need(
        proof["file"] == row
        and proof["path"] == str(driver)
        and proof["page"] == mmap.PAGESIZE
        and offset == 0
        and size == proof["page"]
        and re.fullmatch(r"mnt:\[[0-9]+\]", proof["mount_namespace"]),
        "wrong held SDK file, calibration page or namespace",
    )
    return backing


def check_process(proof, driver, row, namespace, path_stat, lines):
    backing = check_reference(proof, driver, row)
    need(
        namespace == proof["mount_namespace"] and path_stat == row[1:] and lines,
        "compiler namespace or visible driver differs from the verified descriptor",
    )
    for line in lines:
        observed, offset, size = identity(line, driver)
        need(
            observed == backing
            and offset < row[4]
            and offset + size < row[4] + proof["page"],
            ("different mapped SDK object", line, proof["map"]),
        )


@contextlib.contextmanager
def reference(driver, row):
    proc = Path("/proc/self")
    need(
        driver.is_absolute()
        and driver.resolve(strict=True) == driver
        and not mappings(proc, driver),
        "unexpected driver path or pre-existing calibration mapping",
    )
    with os.fdopen(
        os.open(driver, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC), "rb"
    ) as fd:
        meta = os.fstat(fd.fileno())
        need(
            stat.S_ISREG(meta.st_mode)
            and file_stat(meta) == row[1:]
            and os.readlink(proc / "fd" / str(fd.fileno())) == str(driver)
            and hashlib.file_digest(fd, "sha256").hexdigest() == row[0],
            "selected driver is not the authenticated regular SDK member",
        )
        with mmap.mmap(
            fd.fileno(),
            mmap.PAGESIZE,
            mmap.MAP_PRIVATE,
            mmap.PROT_READ | mmap.PROT_EXEC,
        ) as mapped:
            need(mapped[:4] == b"\x7fELF", "held SDK file is not an ELF image")
            (line,) = mappings(proc, driver)
            proof = dict(
                file=row,
                path=str(driver),
                map=line,
                page=mmap.PAGESIZE,
                mount_namespace=os.readlink(proc / "ns/mnt"),
            )
            check_reference(proof, driver, row)
            yield proof
            need(
                mappings(proc, driver) == [line]
                and file_stat(os.fstat(fd.fileno())) == row[1:]
                and file_stat(driver.stat()) == row[1:],
                "held driver changed during Cargo",
            )
        need(not mappings(proc, driver), "calibration mapping survived closing it")
