"""Materialize verified Ruff sources and a small locked registry for offline Cargo."""
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import tomllib

HERE = Path(__file__).resolve().parent
BIND = json.loads((HERE / "registration.json").read_bytes())


def need(ok, message):
    if not ok:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def members(name, seal, size):
    file = HERE / name
    data = file.read_bytes()
    need([len(data), digest(data)] == seal, "changed fixture archive")
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as f:
        expanded = f.read(size + 1)
    need(len(expanded) <= size, "excessive fixture data")
    rows = {}
    with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as tar:
        for m in tar:
            p = PurePosixPath(m.name)
            need(m.isfile() and not p.is_absolute() and ".." not in p.parts
                 and str(p) == m.name and m.name not in rows, "unsafe fixture member")
            rows[m.name] = tar.extractfile(m).read()
    return rows


def write_source(src):
    source = members("ruff-inputs.tar.gz", BIND["archive"], 1 << 20)
    need({n: digest(b) for n, b in source.items()} == BIND["source_files"], "different source corpus")
    for n, blob in BIND["ruff"]["blobs"].items():
        data = source[n]
        need(hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == blob,
             "different original Ruff Git blob")
    for n, b in source.items():
        file = src / n
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("xb") as f:
            f.write(b)
    return source


def sparse_path(name):
    if len(name) <= 2:
        return Path(str(len(name)), name)
    if len(name) == 3:
        return Path("3", name[0], name)
    return Path(name[:2], name[2:4], name)


def registry(home, lock, cache_id):
    need(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]+-[0-9a-f]{16}", cache_id), "invalid registry cache name")
    rows = members("locked-sparse-inputs.tar.gz", BIND["registry"], 2 << 20)
    packages = [p for p in tomllib.loads(lock.decode())["package"] if "checksum" in p]
    need(len(packages) == 42 and digest(lock) == BIND["lock_sha256"], "wrong Cargo lock")
    by_name = {}
    for p in packages:
        n, v = p["name"], p["version"]
        line = rows.pop(f"rows/{n}/{v}.json")
        meta = json.loads(line)
        need(meta["name"] == n and meta["vers"] == v and meta["cksum"] == p["checksum"]
             and p["source"] == "registry+https://github.com/rust-lang/crates.io-index", "wrong local registry record")
        by_name.setdefault(n, []).append((v.encode(), line))
    catalog = home / "registry" / "index" / cache_id
    catalog.mkdir(parents=True)
    (catalog / "config.json").write_text('{"dl":"https://static.crates.io/crates","api":"https://crates.io"}\n')
    for n, versions in by_name.items():
        path = catalog / ".cache" / sparse_path(n)
        path.parent.mkdir(parents=True, exist_ok=True)
        # The ordinary crates.io sparse-cache v3 encoding. Cargo runs offline.
        data = b'\x03\x02\0\0\0etag: "locked-native-fixture"\0' + b"".join(v + b"\0" + s + b"\0" for v, s in versions)
        path.write_bytes(data)
    dest = home / "registry" / "cache" / cache_id
    dest.mkdir(parents=True)
    name = "memchr-2.8.3.crate"
    need(set(rows) == {name} and digest(rows[name]) == BIND["memchr"]["checksum"], "wrong native dependency")
    (dest / name).write_bytes(rows[name])
