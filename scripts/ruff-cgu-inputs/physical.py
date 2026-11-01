"""Keep exact pre-optimization files and the Cargo-selected native archives."""

import gzip
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

CRATES = ("ruff_linter", "ruff_workspace")
ALLOWED = re.compile(
    r"([a-z][a-z0-9_]*)-([0-9a-f]{16})\.([a-z0-9]{25})(?:\.([a-z0-9]{7}))?\.rcgu\.(no-opt\.bc|o)"
)
LIMIT = 2 << 30


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def module(name, owner, suffix):
    match = ALLOWED.fullmatch(name)
    need(match and match[1] == owner and match[5] == suffix, ("unexpected CGU name", owner, name))
    return ".".join(match.groups()[:3])


def write_json(path, value):
    with path.open("x") as output:
        json.dump(value, output, sort_keys=True, separators=(",", ":"))
        output.write("\n")


def stat_key(st):
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def keep(source, store, magic):
    """Bind a real file to the content-addressed store before the next Cargo operation."""
    need(source.is_file() and not source.is_symlink(), ("nonregular physical original", source))
    with source.open("rb") as stream:
        before = stat_key(os.fstat(stream.fileno()))
        need(0 < before[2] <= 512 << 20 and stream.read(len(magic)) == magic, ("unexpected original", source))
        stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        dest = store / (digest + ".gz")
        if not dest.exists():
            stream.seek(0)
            with tempfile.NamedTemporaryFile(dir=store, prefix=".staging-", delete=False) as raw:
                temp = Path(raw.name)
                try:
                    with gzip.GzipFile(
                        filename="", mode="wb", fileobj=raw, compresslevel=1, mtime=0
                    ) as compressed:
                        shutil.copyfileobj(stream, compressed, 1 << 20)
                    raw.flush()
                    with gzip.open(temp, "rb") as verify:
                        need(
                            hashlib.file_digest(verify, "sha256").hexdigest() == digest,
                            "damaged new original",
                        )
                    os.link(temp, dest)
                finally:
                    temp.unlink(missing_ok=True)
        need(
            stat_key(os.fstat(stream.fileno())) == before == stat_key(source.stat()),
            "file changed during capture",
        )
    return {"name": source.name, "sha256": digest, "stat": before}


def stage(owner, outdir, dest):
    """Move only new optional snapshots once rustc has returned, before Cargo can replace them."""
    dest.mkdir()
    captured = []
    for path in sorted(outdir.glob(owner + "-*.rcgu.no-opt.bc")):
        key = module(path.name, owner, "no-opt.bc")
        before = stat_key(path.lstat())
        need(path.is_file() and not path.is_symlink(), ("unsafe saved output", path))
        moved = dest / path.name
        need(not moved.exists(), ("repeated saved output", moved))
        path.rename(moved)
        # rename can legitimately change ctime.
        after = stat_key(moved.stat())
        need(not path.exists() and before[:4] == after[:4], "saved output lost its physical identity")
        captured.append({"unit": key, "name": moved.name, "before": before, "after": after})
    return captured


def assert_empty(work):
    """A future receipt can only count a file created during its own Cargo request."""
    leftover = [
        p
        for item in ("target", "build")
        for p in (work / item).rglob("*.rcgu.no-opt.bc")
        if p.name.startswith(tuple(n + "-" for n in CRATES))
    ]
    need(not leftover, ("optional snapshots preceded the selected invocation", leftover[:3]))


def nul(path):
    raw = path.read_bytes()
    need(raw and raw.endswith(b"\0"), "incomplete physical argv")
    return [os.fsdecode(word) for word in raw[:-1].split(b"\0")]


def snapshot(where, rows, stage_dir, store, work, instrumented):
    receipt = {}
    for owner in CRATES:
        artifacts = [
            x
            for x in rows
            if x.get("reason") == "compiler-artifact"
            and x["target"]["name"] == owner
            and x["target"]["kind"] == ["lib"]
        ]
        root = stage_dir / owner
        if not artifacts:
            need(not root.exists(), ("instrumented crate missing from Cargo events", owner))
            if rows[-1].get("success"):
                raise ValueError(("missing library", owner))
            continue
        (artifact,) = artifacts
        (archive,) = (Path(p) for p in artifact["filenames"] if p.endswith(".rlib"))
        need(archive.resolve(strict=True) == archive and archive.is_relative_to(work), "unrelated archive")
        native = keep(archive, store, b"!<arch>\n")
        captures = {}
        call = None
        if root.exists():
            original = nul(root / "original.nul")
            actual = nul(root / "observed.nul")
            process = json.loads((root / "process.json").read_bytes())
            need(
                actual == original + (["-Csave-temps=yes"] if instrumented else [])
                and process["capture"] == instrumented
                and process["argc"] == [len(original), len(actual)]
                and process["envc"][0] - process["envc"][1] == int(instrumented)
                and process["aux_pairs"] > 1,
                ("wrong actual compiler invocation", owner),
            )
            need(
                original.count("--out-dir") == original.count("--crate-name") == 1
                and original[original.index("--crate-name") + 1] == owner,
                "ambiguous actual compiler owner",
            )
            out = Path(original[original.index("--out-dir") + 1])
            need(archive.parent == out, ("different native output directory", archive, out))
            call = {"owner": owner, "argv": actual, "outdir": str(out), "process": process}
            files = stage(owner, out, root / "emitted")
            write_json(root / "emitted.json", files)
            need(instrumented or not files, "ordinary selected compiler emitted a saved snapshot")
            for f in files:
                original = root / "emitted" / f["name"]
                obj = keep(original, store, b"BC\xc0\xde")
                key = module(obj["name"], owner, "no-opt.bc")
                need(
                    key == f["unit"] and key not in captures and obj["stat"] == f["after"],
                    "ambiguous bitcode owner",
                )
                captures[key] = obj
                original.unlink()
        receipt[owner] = {
            "archive": native,
            "archive_path": str(archive),
            "fresh": artifact["fresh"],
            "call": call,
            "emitted": captures,
        }
    assert_empty(work)
    need(sum(p.stat().st_size for p in store.glob("*.gz")) < LIMIT, "original capture exceeded 2 GiB")
    write_json(where / "cgus.json", receipt)
    return receipt
