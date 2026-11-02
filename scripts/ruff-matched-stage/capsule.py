"""Reopen the two checked compilers from their shared, immutable object transport."""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

HERE = Path(__file__).resolve().parent
REG = json.loads((HERE / "registration.json").read_bytes())
HOST = REG["target"]


def need(ok, why):
    if not ok:
        raise ValueError(why)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, obj):
    with path.open("x") as f:
        print(json.dumps(obj, sort_keys=True, indent=2), file=f)


def native_files(capsule, role):
    files = json.loads((capsule / (role + ".json")).read_bytes())["files"].copy()
    need(
        "bin/rustc" in files and all(n not in files for n in REG["signed_cargo"]["members"]),
        "wrong compiler kit",
    )
    for n, (_member, mode, size, digest) in REG["signed_cargo"]["members"].items():
        files[n] = [digest, size, mode]
    inventory(files)
    return files


def object_modes(manifests):
    modes = {}
    for files in manifests:
        for key, _, native_mode in files.values():
            mode = native_mode & ~0o222
            need(
                modes.setdefault(key, mode) == mode,
                "identical bytes require conflicting installed permissions",
            )
    return modes


def seal(capsule):
    for key, mode in object_modes(native_files(capsule, role) for role in REG["roles"]).items():
        (capsule / "objects" / key).chmod(mode)


def inventory(rows):
    need(1 <= len(rows) < 400, "unbounded compiler inventory")
    host = "lib/rustlib/" + HOST + "/"
    for name, row in rows.items():
        path = Path(name)
        need(
            name == str(path)
            and not path.is_absolute()
            and ".." not in path.parts
            and (
                name in ("bin/cargo", "bin/rustc")
                or name.startswith("lib/")
                and (len(path.parts) == 2 or name.startswith(host))
            ),
            ("unexpected compiler member", name),
        )
        need(
            type(row) is list
            and len(row) == 3
            and re.fullmatch("[a-f0-9]{64}", row[0])
            and type(row[1]) is int
            and 0 < row[1] <= 700 * 2**20
            and type(row[2]) is int
            and 0 < row[2] <= 0o777,
            ("invalid compiler object", name),
        )
    need(sum(r[1] for r in rows.values()) < 2800 * 2**20, "oversize compiler manifest")
    need(
        any(n.startswith("lib/libLLVM") for n in rows)
        and all(
            any(n.startswith(host + "lib/lib" + library + "-") and n.endswith(".rlib") for n in rows)
            for library in ("core", "std", "test", "proc_macro")
        ),
        "missing LLVM or standard libraries",
    )


def admit(capsule):
    need(
        capsule.is_dir()
        and not capsule.is_symlink()
        and {p.name for p in capsule.iterdir()} == {"objects", "P.json", "C.json", "qualified.json"},
        "unexpected capsule contents",
    )
    qualified = capsule / "qualified.json"
    need(qualified.is_file() and not qualified.is_symlink(), "non-regular capsule receipt")
    receipt = json.loads(qualified.read_bytes())
    need(
        receipt["schema"] == "ohm-remat-rustc-capsule-v1"
        and receipt["registration"] == sha(HERE / "registration.json"),
        "wrong builder registration",
    )
    reports = {}
    names = {}
    for role in REG["roles"]:
        p = capsule / (role + ".json")
        need(
            p.is_file() and not p.is_symlink() and sha(p) == receipt["manifests"][role],
            "changed compiler manifest",
        )
        record = json.loads(p.read_bytes())
        spec = REG["roles"][role]
        need(
            (record["role"], record["commit"], record["compiler_tree"])
            == (role, spec["revision"], spec["compiler"]),
            ("wrong compiler source", role),
        )
        reports[role] = record
        names[role] = native_files(capsule, role)
    normal, defer = names["P"], names["C"]
    for item in ("stage0_rustc", "stage0_cargo", "stage0_source"):
        need(
            re.fullmatch("[a-f0-9]{64}", reports["P"][item]) and reports["P"][item] == reports["C"][item],
            ("different bootstrap", item),
        )
    common = lambda rows: {
        n: v for n, v in rows.items() if n != "bin/rustc" and not n.startswith("lib/librustc_driver-")
    }
    need(
        common(normal) == common(defer),
        "different standard library, LLVM, linker, Cargo or other common runtime",
    )
    driver = lambda rows: sorted(v[0] for n, v in rows.items() if n.startswith("lib/librustc_driver-"))
    need(
        len(driver(normal)) == len(driver(defer)) == 1 and driver(normal) != driver(defer),
        "unchanged compiler driver",
    )
    sizes = {}
    for files in names.values():
        for key, size, _ in files.values():
            need(sizes.setdefault(key, size) == size, "inconsistent object size")
    objects = capsule / "objects"
    need(
        objects.is_dir() and not objects.is_symlink() and {p.name for p in objects.iterdir()} == sizes.keys(),
        "missing or unregistered capsule object",
    )
    modes = object_modes(names.values())
    for key, size in sizes.items():
        path = objects / key
        need(
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size == size
            and stat.S_IMODE(path.stat().st_mode) == modes[key]
            and sha(path) == key,
            ("invalid physical compiler object", key),
        )
    return names


def reopen(capsule, out):
    capsule = capsule.resolve(strict=True)
    out = out.resolve()
    need(
        not out.is_relative_to(capsule) and not capsule.is_relative_to(out),
        "overlapping compiler transport and destination",
    )
    names = admit(capsule)
    need(
        capsule.stat().st_dev == out.parent.stat().st_dev,
        "extract the capsule and reopen on one private filesystem",
    )
    out.mkdir()
    objects = capsule / "objects"
    links = {p: p.stat().st_nlink for p in objects.iterdir()}
    arms = {}
    for role, label in (("P", "normal"), ("C", "defer")):
        target = out / label
        for name, (key, _, _) in names[role].items():
            private = objects / key
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            os.link(private, path)
            links[private] += 1
        arms[label] = {"root": str(target), "files": {n: r[0] for n, r in names[role].items()}}
    need(all(p.stat().st_nlink == refs for p, refs in links.items()), "incomplete private deduplication")
    manifest = {"schema": "ohm-matched-rustcs-v1", "arms": arms}
    save(out / "rustcs.json", manifest)
    save(
        out / "storage.json",
        {
            "distinct_objects": len(links),
            "distinct_bytes": sum(p.stat().st_size for p in links),
            "logical_named_bytes": sum(r[1] for files in names.values() for r in files.values()),
        },
    )
    return manifest


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("capsule.py CAPSULE FRESH_DESTINATION")
    reopen(Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[2]).resolve())
