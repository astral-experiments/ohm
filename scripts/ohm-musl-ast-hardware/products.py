"""Bind the ordinary compiler's returned AST to its own native code, static reader and allocated storage."""

import collections
import gzip
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
from clocked import CMD, file_sha, require, save, sha
import member_readback
import opened_driver
import signed_exec


def product(messages):
    require(
        messages and messages[-1] == {"reason": "build-finished", "success": True},
        "failed ordinary Cargo command",
    )
    artifacts = [m for m in messages if m.get("reason") == "compiler-artifact"]
    require(
        not any(m.get("reason") == "compiler-message" and m["message"]["level"] == "error" for m in messages),
        "success exposed stale compiler error",
    )
    require(len(artifacts) == 39, ("unexpected typed inventory", len(artifacts)))
    (owner,) = [
        m
        for m in artifacts
        if m["target"]["name"] == "ruff_python_ast"
        and m["target"]["kind"] == ["lib"]
        and not m["profile"]["test"]
    ]
    (compact,) = [m for m in artifacts if m["target"]["name"] == "compact_str"]
    require(compact["features"] == ["std"] and owner["features"] == [], "wrong selected AST/compact features")
    (archive,) = [Path(x) for x in owner["filenames"] if x.endswith(".rlib")]
    rows = sorted(
        json.dumps(
            [m[k] for k in ("package_id", "target", "features", "profile")],
            sort_keys=True,
            separators=(",", ":"),
        )
        for m in artifacts
    )
    return {
        "count": len(artifacts),
        "roster": sha("\n".join(rows).encode()),
        "dirty": sorted(m["target"]["name"] for m in artifacts if not m["fresh"]),
    }, archive


def normalized_archive(raw):
    entries = member_readback.archive(raw)
    parts = {name: data for name, _, data in entries}
    require(len(parts) == len(entries), "duplicate ar member")
    objects = []
    salts = set()
    for name, data in parts.items():
        if not name.endswith(".rcgu.o"):
            continue
        frame = re.fullmatch(r"(ruff_python_ast-[0-9a-f]{16}\.[a-z0-9]{25})\.([a-z0-9]{7})\.rcgu\.o", name)
        require(frame and int(frame[2], 36) < 2**32, name)
        require(
            data[:7] == b"\x7fELF\x02\x01\x01"
            and int.from_bytes(data[16:18], "little") == 1
            and int.from_bytes(data[18:20], "little") == 62,
            name,
        )
        salts.add(frame[2])
        objects.append([frame[1], len(data), sha(data)])
        for table in ["//", "lib.rmeta-link"]:
            require(parts.get(table, b"").count(name.encode()) == 1, ("ar/metadata identity", table, name))
    require(
        objects and len(salts) == 1 and len({o[0] for o in objects}) == len(objects), "unique codegen ownership"
    )
    require(
        set(parts) - {n for n in parts if n.endswith(".rcgu.o")} == {"/", "//", "lib.rmeta", "lib.rmeta-link"},
        "unexpected independently compared archive member",
    )
    salt = ("." + salts.pop() + ".rcgu.o").encode()
    require(
        raw.count(salt) == len(objects) * 2
        and parts["//"].count(salt) == parts["lib.rmeta-link"].count(salt) == len(objects),
        "unexplained invocation suffix",
    )
    canonical = raw.replace(salt, b".0000000.rcgu.o")
    return {
        "bytes": len(raw),
        "raw": sha(raw),
        "complete_canonical_sha256": sha(canonical),
        "salt": salt.decode(),
        "ordered_objects": objects,
        "embedded_metadata": sha(parts["lib.rmeta"]),
        "symbols": sha(parts["/"]),
    }


def store_body(store, data):
    digest = sha(data)
    z = store / (digest + ".gz")
    if not z.exists():
        with z.open("xb") as f:
            f.write(gzip.compress(data, compresslevel=3, mtime=0))
    require(sha(gzip.decompress(z.read_bytes())) == digest, "retained physical output body")
    return digest


def preserve_archive(raw, directory, rmeta):
    # Archive headers and padding come from the original file. Keep actual code and the *separate*
    # rustc metadata once for this role, outside target and shared, with a cryptographic replay map.
    store = directory.parent / "ar-content"
    store.mkdir(exist_ok=True)
    pos = 8
    entries = []
    for name, header, body in member_readback.archive(raw):
        require(raw[pos : pos + 60] == header and raw[pos + 60 : pos + 60 + len(body)] == body, name)
        pos += 60 + len(body)
        padding = raw[pos : pos + len(body) % 2]
        pos += len(body) % 2
        digest = store_body(store, body)
        entries.append([name, header.hex(), digest, len(body), padding.hex()])
    require(pos == len(raw), "unreconciled archive bytes")
    save(
        directory / "ar-replay.json",
        {"bytes": len(raw), "sha256": sha(raw), "entries": entries, "separate_rmeta": store_body(store, rmeta)},
    )


def reader_link(r, directory):
    rows, resumed = signed_exec.read_execs(gzip.decompress((directory / "client-exec.gz").read_bytes()))
    (ld,) = [
        (pid, Path(path), argv)
        for pid, path, argv in rows
        if Path(path).name in ("ld", "ld.bfd", "ld.lld", "wild")
    ]
    pid, linker, argv = ld
    sdk = r.s.rt.SDK
    musl = sdk / "lib/rustlib" / r.T / "lib/self-contained"
    inputs = [Path(a) for a in argv if not a.startswith("-") and "/self-contained/" in a]
    require(
        {p.name for p in inputs} == {"rcrt1.o", "crti.o", "crtbeginS.o", "crtendS.o", "crtn.o"}
        and all(p.is_file() and p.parent.samefile(musl) for p in inputs),
        "genuine musl startup paths",
    )
    require("-lc" in argv and "-L" + str(musl) in argv, "musl SDK native archive search")
    observed = {
        "path": str(linker),
        "physical": str(linker.resolve(strict=True)),
        "linker_sha256": file_sha(linker),
        "sha256": {p.name: file_sha(p) for p in inputs},
        "available_libc_a": file_sha(musl / "libc.a"),
        "actual_argv": argv,
        "pid": pid,
        "resumed_execs": resumed,
    }
    save(directory / "reader-link.json", observed)
    return {k: observed[k] for k in ("path", "physical", "linker_sha256", "sha256", "available_libc_a")}


def checked_reader(r, trained, messages, directory, env, state):
    graph, archive = product(messages)
    observed = r.client(trained, archive, directory, env, r.WANT[state])
    selected_link = reader_link(r, directory)
    raw = archive.read_bytes()
    require(
        sha(raw) == observed["rlib_sha256"]
        and file_sha(trained[0].with_suffix(".rmeta")) == observed["rmeta_sha256"],
        "native reader input",
    )
    summary = normalized_archive(raw)
    preserve_archive(raw, directory, trained[0].with_suffix(".rmeta").read_bytes())
    save(directory / "full-archive.json", summary)
    save(directory / "reader.json", observed)
    return {
        "roster": graph["roster"],
        "elf": observed["client"]["sha256"],
        "reader_link": selected_link,
        "elf_bytes": observed["client"]["bytes"],
        "result": observed["stdout"],
        "rlib": summary["raw"],
        "canonical_rlib": summary["complete_canonical_sha256"],
        "objects": sha(json.dumps(summary["ordered_objects"], separators=(",", ":")).encode()),
        "object_count": len(summary["ordered_objects"]),
        "rmeta": observed["rmeta_sha256"],
        "embedded_metadata": summary["embedded_metadata"],
        "symbols": summary["symbols"],
    }


def equal_state(left, right):
    # The complete archive may contain a fresh per-invocation rustc salt in its authenticated
    # GNU name table and .rmeta-link only. No change to payload, ordering or any remaining byte is allowed.
    keys = (
        "roster",
        "elf",
        "elf_bytes",
        "reader_link",
        "result",
        "canonical_rlib",
        "objects",
        "object_count",
        "rmeta",
        "embedded_metadata",
        "symbols",
    )
    require(
        all(left[k] == right[k] for k in keys), {k: [left[k], right[k]] for k in keys if left[k] != right[k]}
    )


def ledger(work, dest):
    objects = {}
    rows = []
    placements = collections.Counter()
    duplicates = collections.defaultdict(set)
    counts = collections.Counter()
    placements_by_owner = collections.Counter()
    for placement in ("target", "shared"):
        root = work / placement
        require(root.is_dir() and not root.is_symlink(), root)
        for at, dirs, files in os.walk(root, followlinks=False):
            dirs.sort()
            files.sort()
            parent = Path(at)
            paths = ([parent] if parent == root else []) + [parent / x for x in sorted(dirs + files)]
            for p in paths:
                st = p.lstat()
                ident = (st.st_dev, st.st_ino)
                if ident not in objects and (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
                    try:
                        os.fsync(fd)
                        st = os.fstat(fd)
                        require(ident == (st.st_dev, st.st_ino), "storage identity changed")
                    finally:
                        os.close(fd)
                meta = (st.st_mode, st.st_size, st.st_blocks)
                first = ident not in objects
                if not first:
                    require(tuple(objects[ident][:3]) == meta, ("changing hardlink", p))
                if first:
                    placements[placement] += st.st_blocks * 512
                    kind = None
                    digest = None
                    if stat.S_ISREG(st.st_mode):
                        suffix = p.suffix
                        if suffix in (".o", ".rlib", ".rmeta", ".rlink", ".so"):
                            kind = suffix
                        elif st.st_mode & 0o111:
                            with p.open("rb") as f:
                                header = f.read(20)
                            if header.startswith(b"\x7fELF"):
                                kind = "ELF-executable"
                        if kind:
                            digest = file_sha(p)
                            counts[kind] += 1
                            # An extra similar product may have different session salts and complete hashes.
                            key = re.sub(r"-[a-f0-9]{16}(?=\.|$)", "-<metadata>", p.name)
                            key = re.sub(r"\.[0-9a-z]{7}(?=\.rcgu\.o$)", ".<invocation>", key)
                            placements_by_owner[kind + ":" + key] += 1
                            duplicates[kind, digest].add(ident)
                    objects[ident] = [*meta, kind, digest]
                rows.append([p.relative_to(work).as_posix(), *ident, *objects[ident]])
    raw = json.dumps(rows, separators=(",", ":")).encode()
    archive = dest / "allocated-inodes.json.gz"
    with archive.open("xb") as f:
        f.write(gzip.compress(raw, compresslevel=3, mtime=0))
    result = {
        "allocated_unique": sum(placements.values()),
        "first_placement": dict(placements),
        "unique_inodes": len(objects),
        "pathnames": len(rows),
        "hardlink_aliases": len(rows) - len(objects),
        "physical_payloads": dict(counts),
        "physical_payloads_by_filename": dict(placements_by_owner),
        "exact_duplicate_payloads": {
            kind + ":" + h: len(ids) for (kind, h), ids in sorted(duplicates.items()) if len(ids) > 1
        },
        "raw_sha256": sha(raw),
        "raw_gzip_sha256": file_sha(archive),
    }
    du = subprocess.check_output(["du", "-sc", "-B1", "--", work / "target", work / "shared"], text=True)
    require(
        du.splitlines()[-1].split() == [str(result["allocated_unique"]), "total"],
        ("physical GNU du disagrees", du, result["allocated_unique"]),
    )
    result["gnu_du"] = du
    save(dest / "storage.json", result)
    return result


def storage_calibration(out, work):
    import tempfile

    destination = out / "storage-calibration"
    destination.mkdir()
    with tempfile.TemporaryDirectory(dir=work) as tmp:
        d = Path(tmp)
        for name in ("target", "shared"):
            (d / name).mkdir()
        f = d / "target/object.o"
        f.write_bytes(b"const actual file")
        os.link(f, d / "shared/alias.o")
        (d / "shared/other.o").write_bytes(f.read_bytes())
        (d / "shared/symlink").symlink_to("alias.o")
        with (d / "shared/sparse").open("xb") as stream:
            stream.seek(4 * 1024 * 1024)
            stream.write(b"x")
        result = ledger(d, destination)
    require(
        result["hardlink_aliases"] == 1
        and result["physical_payloads"] == {".o": 2}
        and sorted(result["exact_duplicate_payloads"].values()) == [2]
        and result["allocated_unique"] < 4 * 1024 * 1024,
        "host physical ledger failed on a hardlink, duplicate, symlink or sparse inode",
    )


def complete_execs(path):
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        require(members and all(x.isfile() and re.fullmatch(r"proc\.[0-9]+", x.name) for x in members), path)
        for entry in members:
            for line in archive.extractfile(entry):
                if line.startswith((b"execve(", b"execveat(", b"<... execve")):
                    require(
                        b"<unfinished ...>" not in line and b"resumed>" not in line,
                        ("incomplete physical exec", entry.name, line[:120]),
                    )


def observed_edit(r, env, active, dest):
    # This is the ordinary, separately repeated real edit used for physical validation. All open/exec instrumentation
    # stays outside the consecutive hardware pair. -ff keeps each kernel process stream intact under parallel Cargo.

    dest.mkdir()
    trace = dest / "proc"
    trace.mkdir()
    args = [
        "strace",
        "-ff",
        "-q",
        "-s",
        "262144",
        "-e",
        "trace=execve,execveat,openat,openat2",
        "-o",
        str(trace / "proc"),
        *CMD,
    ]
    p = subprocess.run(args, cwd=r.R, env=env, capture_output=True, timeout=2400)
    r.census.blob(dest / "stdout.gz", p.stdout)
    r.census.blob(dest / "stderr.gz", p.stderr)
    original = dest / "all-kernel-events.tar.gz"
    with tarfile.open(original, "w:gz", compresslevel=3) as ar:
        for f in sorted(trace.iterdir()):
            ar.add(f, arcname=f.name, recursive=False)
    complete_execs(original)
    require(p.returncode == 0, p.stderr[-1400:])
    native = r.census.qualify.native(trace, r.R)
    lines = []
    for f in sorted(trace.iterdir()):
        pid = f.name.rsplit(".", 1)[1].encode()
        require(pid.isdigit(), f)
        for raw in f.read_bytes().splitlines():
            if raw.startswith((b"execve(", b"execveat(")) or b"librustc_driver" in raw:
                lines.append(pid + b" " + raw)
    rustc = r.s.rt.SDK / "bin/rustc"
    seen = opened_driver.inspect(
        lines,
        lambda path: path.is_absolute() and path.is_file() and path.samefile(rustc),
        lambda path: path.samefile(active),
    )
    need_pids = sorted(pid["pid"] for pid in native["rustcs"] if not pid["link_only"])
    require(
        need_pids and sorted(x[0] for x in seen) == need_pids and any(x[1] == "ruff_python_ast" for x in seen),
        "actual Cargo full rustcs and authenticated opened driver",
    )
    save(
        dest / "provenance.json",
        {
            "command": args,
            "physical_rustc": str(rustc),
            "driver": str(active),
            "driver_sha256": file_sha(active),
            "observed": seen,
            "native": native,
            "raw_archive_sha256": file_sha(original),
        },
    )
    import shutil

    shutil.rmtree(trace)
    return [json.loads(line) for line in p.stdout.splitlines()], native
