"""Recover intact ordinary rmeta/prefixes and native CGU work products outside PMU windows."""

import gzip
import hashlib
import json
from pathlib import Path
import stat

from contract import EIGHT, require


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(path, obj):
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    with path.open("xb") as f:
        f.write(gzip.compress(raw, compresslevel=2, mtime=0) if path.suffix == ".gz" else raw + b"\n")


def load(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def collect(root, typed_paths, out, cas):
    inc = root / "slot/target/debug/incremental"

    def file_row(path, keep=False):
        a = path.lstat()
        require(stat.S_ISREG(a.st_mode) and not path.is_symlink() and a.st_size > 0, str(path))
        if keep:
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            obj = cas / (digest + ".gz")
            if not obj.exists():
                with obj.open("xb") as f:
                    f.write(gzip.compress(data, compresslevel=2, mtime=0))
            else:
                require(gzip.decompress(obj.read_bytes()) == data, "metadata CAS corruption")
        else:
            digest = sha(path)
        b = path.lstat()
        require(
            (a.st_dev, a.st_ino, a.st_size, a.st_mtime_ns, a.st_ctime_ns)
            == (b.st_dev, b.st_ino, b.st_size, b.st_mtime_ns, b.st_ctime_ns),
            "observed a mutating product",
        )
        return {
            "path": str(path.relative_to(root / "slot")),
            "dev": a.st_dev,
            "ino": a.st_ino,
            "size": a.st_size,
            "mtime_ns": a.st_mtime_ns,
            "ctime_ns": a.st_ctime_ns,
            "nlink": a.st_nlink,
            "blocks": a.st_blocks,
            "sha256": digest,
        }

    observed = {}
    for name, expected in EIGHT.items():
        meta = Path(typed_paths[name])
        sessions = [p for p in inc.glob(f"*/{name}-*/s-*") if p.is_dir()]
        require(
            len(sessions) == 1 and not sessions[0].name.endswith("-working"),
            (name, "ambiguous incremental state", sessions),
        )
        session = sessions[0]
        files = sorted(session.glob("*.o"))
        require(
            len(files) == expected and len({p.name for p in files}) == expected,
            (name, "unexpected CGU count", len(files)),
        )
        payload = {"cargo": file_row(meta, True)}
        for label in (
            "metadata.rmeta",
            "ohm-build-metadata.rmeta",
            "metadata-prefix-v3.ohm-prefix-v3",
            "ohm-build-metadata-prefix-v3.ohm-prefix-v3",
        ):
            payload[label] = file_row(session / label, True)
        require(
            meta.samefile(session / "metadata.rmeta")
            and meta.samefile(session / "ohm-build-metadata.rmeta")
            and (session / "metadata-prefix-v3.ohm-prefix-v3").samefile(
                session / "ohm-build-metadata-prefix-v3.ohm-prefix-v3"
            ),
            (name, "ordinary cached metadata changed storage form"),
        )
        observed[name] = {
            "session": str(session.relative_to(root / "slot")),
            "meta": payload,
            "objects": {p.name: file_row(p) for p in files},
        }
    require(
        len({(o["dev"], o["ino"]) for g in observed.values() for o in g["objects"].values()})
        == sum(EIGHT.values()),
        "aliased native object names",
    )
    save(out, observed)
    return observed


def compare(a, b, changed):
    require(set(a) == set(b) == set(EIGHT), "wrong work-product owners")
    details = {}
    for name, n in EIGHT.items():
        x, y = a[name], b[name]
        require(set(x["objects"]) == set(y["objects"]) and len(x["objects"]) == n, ("CGU names", name))
        for key in x["objects"]:
            require(
                all(
                    x["objects"][key][k] == y["objects"][key][k]
                    for k in ("dev", "ino", "size", "mtime_ns", "sha256")
                ),
                (name, key, "native work product changed"),
            )
        pair = lambda key: [t["meta"][key]["sha256"] for t in (x, y)]
        metadata = pair("cargo")
        require(
            (metadata[0] != metadata[1]) == changed, (name, "unexpected public metadata byte identity")
        )
        details[name] = {
            "objects": n,
            "rmeta": metadata,
            "prefix": pair("metadata-prefix-v3.ohm-prefix-v3"),
        }
    return details


def header_witnesses(raw, root, receipt, cas):
    """Retain original header, exact issuer and a bounded CrateRoot sample from each workspace rmeta."""
    found = {}

    def keep(data):
        key = hashlib.sha256(data).hexdigest()
        p = cas / (key + ".gz")
        if not p.exists():
            with p.open("xb") as f:
                f.write(gzip.compress(data, compresslevel=2, mtime=0))
        require(gzip.decompress(p.read_bytes()) == data, "header CAS mismatch")
        return key

    for event in map(json.loads, raw.splitlines()):
        if event["reason"] != "compiler-artifact":
            continue
        target = event["target"]
        source = Path(target["src_path"])
        if not source.is_relative_to(root / "ruff/crates"):
            continue
        for file in (Path(n) for n in event["filenames"] if n.endswith(".rmeta")):
            require(file.is_relative_to(root / "slot") and file.is_file(), ("foreign rmeta", file))
            key = str(file.relative_to(root / "slot"))
            if key in found:
                continue
            st = file.stat()
            row = {
                "source": str(source.relative_to(root / "ruff")),
                "target": target["name"],
                "size": st.st_size,
                "sha256": sha(file),
                "dev": st.st_dev,
                "ino": st.st_ino,
            }
            if st.st_size:
                with file.open("rb") as f:
                    first = f.read(16)
                    require(first[:8] == b"rust\0\0\0\n" and len(first) == 16, (file, "rmeta magic"))
                    size = 0
                    tag = b""
                    for i in range(6):
                        b = f.read(1)
                        require(b, "missing compiler stamp")
                        tag += b
                        size |= (b[0] & 127) << (7 * i)
                        if b[0] < 128:
                            break
                    else:
                        raise ValueError("unclosed compiler stamp")
                    stamp = f.read(size)
                    off = int.from_bytes(first[8:16], "little")
                    require(
                        0 < size < 900
                        and len(stamp) == size
                        and "c79998a5c" in stamp.decode()
                        and f.tell() <= off < st.st_size,
                        ("header", file, off),
                    )
                    initial = first + tag + stamp
                    f.seek(off)
                    sample = f.read(384)
                    require(len(sample) == min(384, st.st_size - off), "short root read")
                    row.update(
                        header_sha256=keep(initial),
                        header_bytes=len(initial),
                        issuer=stamp.decode(),
                        root_offset=off,
                        root_bytes=len(sample),
                        root_sha256=keep(sample),
                    )
            now = file.stat()
            require(
                (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
                == (now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns, now.st_ctime_ns),
                "racing header",
            )
            found[key] = row
    require(
        set(EIGHT) | {"ruff_notebook", "ty_python_core", "ty_python_semantic", "ty_server"}
        <= {v["target"] for v in found.values() if v.get("root_bytes")},
        "missing workspace CrateRoot witness",
    )
    save(receipt, found)
    return found
