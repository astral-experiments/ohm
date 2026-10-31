"""Read the raw or paired zlib incremental tables emitted by the two enrolled rustcs."""

import contextlib
import hashlib
import os
import re
import stat
import subprocess
import zlib
from pathlib import Path

from bindings import need

LIMIT = 512 << 20
MIN_PACKED_RAW = 64 << 10
BLOCK = 256 << 10
TABLES = (("dep-graph.bin", b"G"), ("query-cache.bin", b"Q"))
ALIASES = ("", "ohm-build-", "ohm-check-")
BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def binary_disambiguator(path, crate):
    # print_crate_name/print_disambiguator in rustc_symbol_mangling v0 use a base-62
    # stable crate ID (offset by two). rustc_incremental names its owner using that ID in base 36.
    pattern = re.compile(rf"^_RNvCs([0-9A-Za-z]*)_{len(crate)}{re.escape(crate)}4main [tT] ")
    with subprocess.Popen(
        ["nm", "-P", "--defined-only", path], stdout=subprocess.PIPE, text=True
    ) as proc:
        matches = [m.group(1) for line in proc.stdout if (m := pattern.match(line))]
        need(
            proc.wait() == 0 and len(matches) == 1,
            ("no unique owned Rust main", path, matches),
        )
    value = 0
    for digit in matches[0]:
        value = value * 62 + BASE62.index(digit)
    return value + (2 if matches[0] else 1), "_RNvCs" + matches[0] + f"_{len(crate)}{crate}4main"


def owner(row, base, work):
    crate = row["crate"]
    argv = row["argv"]
    out = Path(argv[argv.index("--out-dir") + 1])
    need(out.resolve() == out and out.is_relative_to(work), ("foreign rustc output", out))
    kind = argv[argv.index("--crate-type") + 1]
    choices = [
        p
        for p in base.glob(crate + "-*")
        if p.is_dir() and p.resolve() == p and re.fullmatch(re.escape(crate) + r"-[0-9a-z]{13}", p.name)
    ]
    if kind == "lib":
        (extra,) = [v.partition("=")[2] for v in argv if v.startswith("extra-filename=")]
        product = out / ("lib" + crate + extra + ".rmeta")
        need(
            product.is_file() and product.resolve() == product,
            ("missing real output metadata", product),
        )
        matches = [
            p
            for p in choices
            if any(
                m.is_file() and m.resolve() == m and product.samefile(m)
                for m in p.glob("s-*/metadata.rmeta")
                if not m.parent.name.endswith("-working")
            )
        ]
        identity = product.stat()
        proof = {
            "method": "returned rmeta inode",
            "device": identity.st_dev,
            "inode": identity.st_ino,
            "extra_filename": extra,
        }
    else:
        need(kind == "bin", ("unexpected owner crate type", kind))
        product = out / crate
        need(
            product.is_file() and product.resolve() == product,
            ("missing actual binary", product),
        )
        crate_id, symbol = binary_disambiguator(product, crate)
        matches = [p for p in choices if int(p.name.rsplit("-", 1)[1], 36) == crate_id]
        proof = {
            "method": "defined v0 Rust main stable crate ID",
            "symbol": symbol,
            "stable_crate_id": crate_id,
        }
    need(
        len(matches) == 1,
        ("wrong producing incremental directory", row["pid"], product, matches),
    )
    return matches[0], {
        "crate_type": kind,
        "output": str(product.relative_to(work)),
        "proof": proof,
    }


@contextlib.contextmanager
def regular(path):
    original = path.lstat()
    need(
        stat.S_ISREG(original.st_mode) and path.resolve() == path,
        ("nonregular input", path),
    )
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME
    with os.fdopen(os.open(path, flags), "rb") as f:

        def identity(s):
            return s.st_dev, s.st_ino, s.st_size, s.st_ctime_ns

        need(
            identity(os.fstat(f.fileno())) == identity(original),
            ("changed before open", path),
        )
        yield f, original
        need(
            identity(os.fstat(f.fileno())) == identity(path.lstat()) == identity(original),
            ("changed during observation", path),
        )


def raw_header(version):
    data = version.encode("ascii")
    need(0 < len(data) < 256, "unexpected compiler version")
    return b"RSIC\x08\x00" + bytes([len(data)]) + data


def raw_file(path, expected_header):
    with regular(path) as (f, s):
        need(
            s.st_size > len(expected_header) and f.read(len(expected_header)) == expected_header,
            ("wrong raw incremental producer", path),
        )
        f.seek(0)
        return {
            "bytes": s.st_size,
            "sha256": hashlib.file_digest(f, "sha256").hexdigest(),
        }


def packed_file(path, tag, prefix, expected_header):
    # This is the checked stream read by Table::restore in rustc_incremental/src/persist/fs/packed.rs.
    # The trailer is the zlib checksum, not a second member. Never materialize the full table.
    head_len = 11 + len(prefix) + 1
    header = bytearray()
    encoded = hashlib.sha256()
    decoded = hashlib.sha256()
    total = 0
    plain_size = aliases = None
    decoder = zlib.decompressobj()
    with regular(path) as (f, s):
        need(0 < s.st_size <= LIMIT, ("packed file size", path))
        while block := f.read(BLOCK):
            encoded.update(block)
            while block:
                raw = decoder.decompress(block, BLOCK)
                block = decoder.unconsumed_tail
                need(not decoder.unused_data, ("trailing zlib data", path))
                take = max(0, head_len - len(header))
                if take:
                    header.extend(raw[:take])
                    raw = raw[take:]
                if len(header) == head_len and plain_size is None:
                    aliases = header[2]
                    plain_size = int.from_bytes(header[3:11], "little")
                    need(
                        header[:2] == b"\x01" + tag
                        and aliases in (1, 3, 5, 7)
                        and MIN_PACKED_RAW <= plain_size <= LIMIT
                        and header[11:] == prefix + b"\0",
                        ("wrong table, aliases or session", path),
                    )
                if raw:
                    need(
                        plain_size is not None and total + len(raw) <= plain_size,
                        ("overlong table", path),
                    )
                    remaining = max(0, len(expected_header) - total)
                    need(
                        raw[:remaining] == expected_header[total : total + min(remaining, len(raw))],
                        ("wrong packed incremental producer", path),
                    )
                    decoded.update(raw)
                    total += len(raw)
        need(
            decoder.eof
            and not decoder.unused_data
            and not decoder.unconsumed_tail
            and total == plain_size,
            ("incomplete packed table", path),
        )
        return {
            "bytes": total,
            "sha256": decoded.hexdigest(),
            "stored_bytes": s.st_size,
            "stored_sha256": encoded.hexdigest(),
            "aliases": aliases,
            "session_prefix": prefix.decode("ascii"),
            "tag": tag.decode("ascii"),
        }


def finalized(session, version):
    need(
        session.resolve() == session
        and session.is_dir()
        and re.fullmatch(r"s-[0-9a-z]+-[0-9a-z_]+-[0-9a-z]+", session.name)
        and not session.name.endswith("-working"),
        ("foreign session path", session),
    )
    prefix = session.name.rsplit("-", 1)[0].encode("ascii")
    header = raw_header(version)
    names = {p.name for p in session.iterdir()}
    files = {}
    packed = any("ohm-packed-" + n in names for n, _ in TABLES)
    for name, tag in TABLES:
        variants = {a + name for a in ALIASES}
        if packed:
            need(
                "ohm-packed-" + name in names and names.isdisjoint(variants),
                ("missing packed partner or mixed raw/packed table", session, name),
            )
            files[name] = packed_file(session / ("ohm-packed-" + name), tag, prefix, header)
        else:
            need(name in names, ("missing raw table", session, name))
            raw = session / name
            files[name] = raw_file(raw, header)
            for alias in variants.intersection(names) - {name}:
                other = session / alias
                need(
                    not other.is_symlink() and other.samefile(raw),
                    ("distinct stage alias in build-only history", other),
                )
    products = raw_file(session / "work-products.bin", header)
    objects = {n for n in names if n.endswith(".o")}
    packed_objects = {
        n for n in names if re.fullmatch(r"ohm-packed-object-[0-9a-z]+\.o-blake3=[0-9a-f]{64}", n)
    }
    need(objects or packed_objects, ("no codegen objects for linked crate", session))
    for name in objects | packed_objects:
        entry = (session / name).lstat()
        need(
            stat.S_ISREG(entry.st_mode) and entry.st_size > 0,
            ("invalid native work product", name),
        )
    return {
        "representation": "packed" if packed else "raw",
        "tables": files,
        "compiler": version,
        "graph_bytes": files["dep-graph.bin"]["bytes"],
        "objects": len(objects),
        "packed_objects": len(packed_objects),
        "work_products": [products["bytes"], products["sha256"]],
    }
