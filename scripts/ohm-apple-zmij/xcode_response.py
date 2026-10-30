"""Bind an observed Xcode ld @file to the file LLVM wrote and the actual parent clang."""
import base64
from collections import Counter
from functools import cache
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from study import need

NAME = re.compile(r"response-[A-Za-z0-9]+\.txt")
SAFE = rb"A-Za-z0-9_./,=+:\-"
TOKEN = re.compile(rb'(?:[' + SAFE + rb']+|"[' + SAFE + rb' ]+")')
LIMIT = 2 * 1024 * 1024
LD = {"ld", "ld64", "ld-classic", "ld-prime"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def packed(argv):
    return json.dumps(argv, separators=(",", ":")).encode()


def words(body):
    """Accept unquoted safe words and whole double-quoted words, rejecting shell extensions."""
    need(0 < len(body) <= LIMIT, "empty or oversized Xcode response")
    fields = []
    end = 0
    for item in TOKEN.finditer(body):
        between = body[end:item.start()]
        need((not fields or between) and not between.strip(b" \t\r\n"),
             "unsupported response-file character, escape or adjoining argument")
        token = item.group()
        fields.append(token.strip(b'"').decode("ascii"))
        end = item.end()
    need(fields and not body[end:].strip(b" \t\r\n"), "unparsed Xcode response file")
    return fields


def stamp(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def file_name(raw):
    need(len(raw) == 2 and raw[1].startswith("@/"), "unsupported Xcode response position")
    path = Path(raw[1][1:])
    need(NAME.fullmatch(path.name) and ".." not in path.parts, "foreign Xcode response file")
    return path


@cache
def darwin_user_temp():
    run = subprocess.run(["/usr/bin/getconf", "DARWIN_USER_TEMP_DIR"], check=True, capture_output=True, text=True)
    result = Path(run.stdout.rstrip("\n"))
    need(not run.stderr and result.is_absolute() and result.is_dir() and result.stat().st_uid == os.getuid(),
         "invalid per-user Darwin temporary root")
    return result.resolve(strict=True)


class ResponseRows(list):
    def __init__(self, temporary, system=None):
        super().__init__()
        self.temporary = {Path(temporary).resolve(strict=True)}
        if system is not None:
            self.temporary.add(Path(system).resolve(strict=True))

    def append(self, event):
        raw = event["argv"]
        if Path(event["path"]).name in LD and any(a.startswith("@") for a in raw[1:]):
            path = file_name(raw)
            try:
                parent = path.parent.resolve(strict=True)
                need(parent in self.temporary, f"unmatched linker temp {parent} against {sorted(map(str, self.temporary))}")
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as src:
                    st = os.fstat(fd)
                    identity = stamp(st)
                    need(stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid() and st.st_nlink == 1 and 0 < st.st_size <= LIMIT,
                         "unsafe link response file")
                    data = src.read(LIMIT + 1)
                    need(identity == stamp(os.fstat(fd)) == stamp(os.stat(path, follow_symlinks=False)) and
                         len(data) == st.st_size, "linker response changed during capture")
            except (OSError, RuntimeError) as e:
                super().append({**event, "response_observer_error": str(e), "expected_roots": sorted(map(str, self.temporary))})
                raise RuntimeError(f"could not witness live Xcode response {path}: {e}") from e
            event = {**event, "xcode_response": {"path": str(path), "temporary": str(parent), "identity": identity,
                      "sha256": digest(data), "bytes": base64.b64encode(data).decode(), "raw_argv": digest(packed(raw))}}
        super().append(event)
        if "xcode_response" in event:
            words(data)


def outputs(argv):
    return [v for k, v in zip(argv, argv[1:]) if k == "-o"]


def direct_inputs(argv):
    return Counter(x for x in argv[1:] if x.startswith("/") and x.endswith((".o", ".rlib")))


def resolved(events):
    """Keep every kernel row and expand only a response captured from that very invocation."""
    history = {}
    for event in events:
        path = Path(event["path"])
        raw = event["argv"]
        if path.name in LD and any(a.startswith("@") for a in raw[1:]):
            proof = event.get("xcode_response")
            need(proof and file_name(raw) == Path(proof["path"]) and proof["raw_argv"] == digest(packed(raw)),
                 "missing original ld response or raw kernel argv")
            name = file_name(raw)
            # Darwin's /var path is the conventional alias of /private/var.
            temporary = str(name.parent).removeprefix("/private/")
            recorded = proof["temporary"].removeprefix("/private/")
            need(temporary.lstrip("/") == recorded.lstrip("/"), "different captured response root")
            data = base64.b64decode(proof["bytes"], validate=True)
            _, _, mode, _, links, size, _, _ = proof["identity"]
            need(stat.S_ISREG(mode) and links == 1 and len(data) == size and digest(data) == proof["sha256"],
                 "damaged physical linker response")
            argv = [raw[0], *words(data)]
            parent = history.get(event["ppid"])
            need(parent and parent["seq"] < event["seq"] and parent["pgid"] == event["pgid"] and
                 Path(parent["path"]).name == "clang" and Path(parent["path"]).parent == path.parent and
                 bool(parent.get("cdhash")) and bool(event.get("cdhash")), "missing same-toolchain kernel clang parent")
            want = direct_inputs(parent["argv"])
            got = direct_inputs(argv)
            need(want and not want - got and
                 Counter({p: n for p, n in got.items() if ".rlink-objects/" in p}) ==
                 Counter({p: n for p, n in want.items() if ".rlink-objects/" in p}) and
                 len(outputs(argv)) == 1 and outputs(argv) == outputs(parent["argv"]),
                 "response changed the native output or original compiler objects")
            event = {**event, "argv": argv}
        else:
            need("xcode_response" not in event, "unsolicited response on a direct kernel argv")
        history[event["pid"]] = event
        yield event
