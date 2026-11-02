"""Freeze the workspace compiler's possible donor sessions without changing any compiler input."""

import hashlib
import json
import os
from pathlib import Path
import stat

import physical

assert (
    Path(physical.__file__).resolve()
    == Path(__file__).with_name("physical.py").resolve()
)

OWNER = "ruff_workspace"
MAX_SESSION_BYTES = 4 << 30


def roots(arguments, work):
    def value(flag):
        return [v for i, v in enumerate(arguments[1:], 1) if arguments[i - 1] == flag]

    physical.need(value("--crate-name") == [OWNER], "incorrect compiler owner")
    incremental = [
        v.removeprefix("incremental=")
        for v in value("-C")
        if v.startswith("incremental=")
    ]
    physical.need(len(incremental) == 1, ("ambiguous incremental path", incremental))
    parent = Path(incremental[0])
    physical.need(
        parent.resolve(strict=True) == parent
        and any(parent.is_relative_to(work / k) for k in ("target", "build")),
        ("unowned incremental directory", parent),
    )
    result = []
    for crate in sorted(parent.glob(OWNER + "-*")):
        physical.need(
            crate.is_dir() and crate.resolve(strict=True) == crate,
            ("unexpected crate root", crate),
        )
        for session in sorted(crate.iterdir()):
            if session.is_dir():
                physical.need(
                    session.resolve(strict=True) == session
                    and session.name.startswith("s-")
                    and not session.name.endswith("working"),
                    ("unfinished or redirected session", session),
                )
                result.append(session)
    physical.need(
        0 < len(result) <= 16,
        ("unexpected number of completed sessions", parent, len(result)),
    )
    return parent, result


def read_file(path, store):
    before = path.lstat()
    physical.need(
        stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= 512 << 20,
        ("unexpected session file", path),
    )
    if path.name in {
        "work-products.bin",
        "dep-graph.bin",
        "ohm-build-dep-graph.bin",
        "ohm-check-dep-graph.bin",
    }:
        saved = physical.keep(path, store, b"RSIC")
        digest = saved["sha256"]
        stored = True
    else:
        # Hard links are ordinary for cloned sessions. Bind the bytes and inode of the completed file.
        with path.open("rb") as f:
            physical.need(
                physical.stat_key(os.fstat(f.fileno())) == physical.stat_key(before),
                ("file changed before hash", path),
            )
            digest = hashlib.file_digest(f, "sha256").hexdigest()
            physical.need(
                physical.stat_key(os.fstat(f.fileno())) == physical.stat_key(before),
                ("file changed during hash", path),
            )
        stored = False
    physical.need(
        physical.stat_key(path.lstat()) == physical.stat_key(before),
        ("replaced session input", path),
    )
    return dict(
        name=path.name,
        sha256=digest,
        stored=stored,
        stat=physical.stat_key(before),
        mode=before.st_mode,
    )


def capture(where, original, work, store, moment):
    parent, sessions = roots(physical.nul(original), work)
    evidence = []
    for session in sessions:
        files = sorted(session.iterdir())
        physical.need(
            sum(p.lstat().st_size for p in files) <= MAX_SESSION_BYTES,
            ("oversized session", session),
        )
        recorded = [read_file(p, store) for p in files]
        names = {row["name"] for row in recorded}
        physical.need(
            {"dep-graph.bin", "work-products.bin"} <= names
            and any(n.endswith(".o") for n in names),
            ("incomplete ordinary workspace donor", session, sorted(names)[:6]),
        )
        evidence.append(dict(path=str(session), files=recorded))
    physical.write_json(
        where / ("green-inputs-" + moment + ".json"),
        dict(
            original_argv_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
            incremental=str(parent),
            sessions=evidence,
        ),
    )


def verify(out, lanes=("ordinary-observed", "diagnostic")):
    import gzip
    from collections import Counter

    packets = {}
    objects = {}
    for lane in lanes:
        packets[lane] = {}
        for phase, moment in (("B", "after"), ("A", "before"), ("A", "after")):
            row = json.loads(
                (out / lane / phase / ("green-inputs-" + moment + ".json")).read_bytes()
            )
            call = (
                out
                / lane
                / ("B" if moment == "before" else phase)
                / "stage"
                / OWNER
                / "original.nul"
            )
            physical.need(
                row["original_argv_sha256"]
                == hashlib.sha256(call.read_bytes()).hexdigest(),
                "incorrect argv binding",
            )
            inventories = {}
            for s in row["sessions"]:
                parts = Counter(p["name"] for p in s["files"])
                physical.need(
                    all(n == 1 for n in parts.values())
                    and {"dep-graph.bin", "work-products.bin"} <= parts.keys(),
                    "ambiguous recorded files",
                )
                inventories[s["path"]] = {}
                for f in s["files"]:
                    inventories[s["path"]][f["name"]] = (f["sha256"], f["stat"])
                    if f["stored"] and f["sha256"] not in objects:
                        with gzip.open(
                            out / "green-originals" / (f["sha256"] + ".gz"), "rb"
                        ) as stream:
                            data = stream.read((512 << 20) + 1)
                        physical.need(
                            len(data) == f["stat"][2]
                            and data[:4] == b"RSIC"
                            and hashlib.sha256(data).hexdigest() == f["sha256"],
                            "incorrect saved graph",
                        )
                        objects[f["sha256"]] = len(data)
            packets[lane][phase + "-" + moment] = inventories
        physical.need(
            packets[lane]["B-after"] == packets[lane]["A-before"],
            "candidate donors changed before A",
        )
    return dict(
        graph_objects=objects,
        sessions={l: {m: list(v) for m, v in p.items()} for l, p in packets.items()},
    )
