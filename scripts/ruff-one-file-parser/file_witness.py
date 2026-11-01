"""Read selected build artifacts outside counters and compare regular inodes with complete content."""

import hashlib
import os
from pathlib import Path
import re
import stat
import traceback

import protocol as p

f = p.f


def local_libraries(records, repo):
    return [
        row
        for row in records
        if row["target"]["kind"] == ["lib"] and Path(row["target"]["src_path"]).is_relative_to(repo / "crates")
    ]


def relative(path, work):
    path = Path(path)
    f.require(
        path.is_absolute() and ".." not in path.parts and path.is_relative_to(work / "target"),
        "foreign workspace artifact",
    )
    return str(path.relative_to(work))


def identify(path, work):
    relative(path, work)
    f.require(path.resolve(strict=True) == path, "redirected artifact")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as fp:

        def identity(s):
            return [s.st_dev, s.st_ino, s.st_size, s.st_mode, s.st_mtime_ns, s.st_ctime_ns]

        before = identity(os.fstat(fp.fileno()))
        f.require(stat.S_ISREG(before[3]) and before[2] > 0, "empty or nonregular artifact")
        digest = hashlib.file_digest(fp, "sha256").hexdigest()
        f.require(
            before == identity(os.fstat(fp.fileno())) == identity(path.lstat()), "artifact changed while read"
        )
    return [*before, digest]


def capture(role, records, repo, work):
    paths = {Path(n) for row in local_libraries(records, repo) for n in row["filenames"]}
    _, _, name, kind = p.ROLES[role]
    (unit,) = [r for r in records if r["target"]["name"] == name and r["target"]["kind"] == [kind]]
    product = Path(unit["executable"])
    # Cargo's public executable can be a different filename for the physical --out-dir inode.
    # Match an actual sibling in the existing target by that inode, before the new compiler starts.
    inputs = []
    for recipe in (work / "target").rglob(product.name + ".rlink"):
        output = recipe.with_suffix("")
        if output.is_file() and output.samefile(product):
            inputs.append(recipe)
    f.require(len(inputs) <= 1, "ambiguous live saved link input")
    return {
        "libraries": {relative(q, work): identify(q, work) for q in sorted(paths)},
        "recipes": {relative(q, work): identify(q, work) for q in inputs},
    }


def validate(before, after, role, records, report, inodes, repo, work):
    libraries = local_libraries(records, repo)
    keys = {relative(n, work) for r in libraries for n in r["filenames"]}
    for frame in (before, after):
        f.require(
            set(frame) == {"libraries", "recipes"}
            and set(frame["libraries"]) == keys
            and len(frame["recipes"]) <= 1,
            "incomplete physical library or input census",
        )
        for k, v in (frame["libraries"] | frame["recipes"]).items():
            f.require(
                relative(work / k, work) == k
                and len(v) == 7
                and min(v[:3]) > 0
                and stat.S_ISREG(v[3])
                and min(v[4:6]) > 0
                and re.fullmatch("[0-9a-f]{64}", v[6]),
                "invalid physical file witness",
            )
    for n in keys:
        f.require(
            after["libraries"][n][:6] == inodes[n], "post-command census differs from actual Cargo output"
        )
    for entry in report["without_rustc"]:
        for n in entry["outputs"]:
            key = relative(n, work)
            a, b = before["libraries"][key], after["libraries"][key]
            # Signed Cargo may advance input-dependent rmeta/rlib timestamps after early cutoff.
            f.require(a[:4] == b[:4] and a[6] == b[6], "uncompiled local artifact changed inode or bytes")
    for e in report["owners"]:
        if e["mode"] == "link-only":
            (out,) = e["outputs"]
            key = relative(Path(out).with_suffix(".rlink"), work)
            f.require(
                list(before["recipes"]) == list(after["recipes"]) == [key]
                and before["recipes"][key] == after["recipes"][key],
                "saved linker input missing, replaced or changed",
            )


def record(where, stage, take):
    """Preserve a structural refusal while the independent native histories finish."""
    try:
        return take()
    except Exception:
        (where / f"{stage}-inventory-refusal.txt").write_text(traceback.format_exc())
        return None


def complete(logs):
    failures = sorted(
        str(path.relative_to(logs)) for path in logs.glob("*/inventory/edited/*-inventory-refusal.txt")
    )
    f.require(not failures, ("structural evidence refused", failures))


def final_image(before, after, binary, desc, inodes, work):
    expected = [*inodes[relative(binary, work)], desc["whole"]]
    f.require(
        before == after == expected and expected[2] == desc["size"],
        "native client image differs from the final writer's Cargo output",
    )
