"""Retain and restore only the allowlisted binary SDKs from the two completed builds."""
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime as rt
from study import need, save, sha

MAX_BYTES = 768 * 2**20
METADATA = ("roles.json", "release.json", "release.sha256", "release-provenance.json")


def sdk_path(name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != name:
        return False
    if name in rt.TOOLS or name == "bin/rustc":
        return True
    if path.parent in (Path("lib"), Path("lib/rustlib") / rt.HOST / "lib") and re.fullmatch(r"lib[0-9A-Za-z_.+-]+\.so(?:\.[0-9A-Za-z.+-]+)?", path.name):
        return True
    for triple in (rt.HOST, rt.TARGET):
        base = Path("lib/rustlib") / triple
        if path.is_relative_to(base / "lib") and path.suffix in (".rlib", ".rmeta", ".o", ".a", ".so"):
            return True
        if triple == rt.HOST and (path == base / "bin/rust-lld" or path.is_relative_to(base / "bin/gcc-ld")):
            return path.name in ("rust-lld", "ld.lld", "ld64.lld", "lld-link", "wasm-ld")
    return False


def table(roles):
    unique = {}
    for role, rev in (("P", rt.PARENT), ("C", rt.CHILD)):
        product = roles[role]
        need(product["source"] == rev and re.fullmatch(r"[a-f0-9]{40}", product["tree"]), "unexpected source")
        for name, (key, size, mode) in product["files"].items():
            need(sdk_path(name) and re.fullmatch(r"[0-9a-f]{64}", key) and 0 < size < 2**31 and mode & ~0o777 == 0,
                 f"non-runtime member {name}")
            need(unique.setdefault(key, size) == size, "inconsistent size for shared bytes")
        need(all(product["files"][n][0] == key for n, key in rt.TOOLS.items()), "signed executable mismatch")
    need(roles["P"]["files"].keys() == roles["C"]["files"].keys() and roles["P"]["bootstrap"] == roles["C"]["bootstrap"], "unmatched builds")
    diff = [n for n in roles["P"]["files"] if roles["P"]["files"][n] != roles["C"]["files"][n]]
    need(any(n.startswith("lib/librustc_driver") for n in diff) and all(n == "bin/rustc" or n.startswith(("lib/librustc_driver", "lib/librustc_codegen_llvm")) for n in diff), "unmatched compiler pair")
    return unique


def add(tar, name, size, stream):
    header = tarfile.TarInfo(name)
    header.mode, header.size = 0o444, size
    tar.addfile(header, stream)


def binary_payload(path, names):
    with path.open("rb") as stream:
        magic = stream.read(192)
    if magic.startswith((b"\x7fELF", b"!<arch>\n", b"rust\0")):
        return True
    return (all(Path(n).name.startswith("libLLVM") for n in names) and path.stat().st_size < 192
            and re.fullmatch(rb"INPUT\(libLLVM\.so\.[0-9A-Za-z.+-]+\)\s*", magic) is not None)


@contextmanager
def decompress(path):
    with subprocess.Popen(["zstd", "-qdc", str(path)], stdout=subprocess.PIPE) as proc:
        try:
            with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
                yield tar
            need(not proc.stdout.read().strip(b"\0"), "unexpected data after archive")
            need(proc.wait() == 0, "invalid compressed stream")
        finally:
            proc.stdout.close()


def verify(path, wanted=None, target=None):
    roles, objects, seen = {}, {}, set()
    if wanted is not None:
        need(wanted in ("P", "C") and not target.exists(), "restore needs a fresh destination")
        target.mkdir()
    with decompress(path) as tar:
        for i, member in enumerate(tar):
            n = member.name
            need(n not in seen and member.isreg(), "duplicate or nonregular capsule member")
            seen.add(n)
            stream = tar.extractfile(member)
            if i < len(METADATA):
                need(n == METADATA[i] and member.size < 2**20, "invalid capsule metadata")
                raw = stream.read()
                if i == 0:
                    roles = json.loads(raw)
                    objects = table(roles)
                elif i == 1:
                    need(json.loads(raw) == {"release": rt.A, "checksum": rt.SIDE, "provenance": rt.PROV, "tools": rt.TOOLS}, "unbound release")
                else:
                    need(hashlib.sha256(raw).hexdigest() == (rt.SIDE if i == 2 else rt.PROV), "wrong original signed release data")
                continue
            key = n.removeprefix("objects/")
            need(n == "objects/" + key and objects.get(key) == member.size, "unknown binary")
            paths = [(target / name, mode) for name, (h, _, mode) in roles[wanted]["files"].items() if h == key] if wanted else []
            if paths:
                first, mode = paths[0]
                first.parent.mkdir(parents=True, exist_ok=True)
                with first.open("xb") as out:
                    shutil.copyfileobj(stream, out, 2**20)
                need(sha(first) == key, "bad restored bytes")
                first.chmod(mode)
                for rest, new_mode in paths[1:]:
                    rest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(first, rest)
                    rest.chmod(new_mode)
            else:
                need(hashlib.file_digest(stream, "sha256").hexdigest() == key, "bad stored bytes")
    need(seen == set(METADATA) | {"objects/" + k for k in objects}, "missing stored bytes")
    if wanted:
        for name, (key, size, mode) in roles[wanted]["files"].items():
            p = target / name
            need(p.stat().st_size == size and p.stat().st_mode & 0o777 == mode and sha(p) == key, "failed physical mode or SHA readback")
    return {"objects": len(objects), "raw_unique_bytes": sum(objects.values()), "members_per_role": {r: len(p["files"]) for r, p in roles.items()}}


def build():
    rt.room()
    roles = {r: rt.load(rt.LOG / (r + "-sdk.json")) for r in "PC"}
    files = {}
    for role in roles.values():
        for key, _, _ in role["files"].values():
            files[key] = rt.CAP / "objects" / key
        for n, key in rt.TOOLS.items():
            p = rt.SDK / n
            need(sha(p) == key, "signed executable changed")
            role["files"][n] = [key, p.stat().st_size, p.stat().st_mode & 0o777]
            files[key] = p
    rows = table(roles)
    for key, file in files.items():
        names = {n for role in roles.values() for n, (h, _, _) in role["files"].items() if h == key}
        need(binary_payload(file, names), f"unrecognized binary input {names}")
    folder = rt.ROOT / "private-return"
    folder.mkdir()
    path = folder / "linux-aarch64-sdk-pair.tar.zst"
    metadata = (json.dumps(roles, sort_keys=True).encode(), (rt.LOG / "release.json").read_bytes(),
                (rt.ROOT / "inbox" / (rt.ARCHIVE + ".sha256")).read_bytes(), (rt.ROOT / "inbox" / (rt.BASE + "-provenance.json")).read_bytes())
    with path.open("xb") as out:
        def cap():
            resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))
        with subprocess.Popen(["zstd", "-qT2", "-3", "-c"], stdin=subprocess.PIPE, stdout=out, preexec_fn=cap) as proc:
            with tarfile.open(fileobj=proc.stdin, mode="w|", format=tarfile.USTAR_FORMAT) as tar:
                for n, data in zip(METADATA, metadata):
                    add(tar, n, len(data), io.BytesIO(data))
                for key, size in sorted(rows.items()):
                    with files[key].open("rb") as body:
                        add(tar, "objects/" + key, size, body)
            proc.stdin.close()
            need(proc.wait() == 0, "compressed SDK exceeded its cap or failed")
    need(0 < path.stat().st_size <= MAX_BYTES, "invalid compressed SDK size")
    receipt = dict(verify(path), compressed_bytes=path.stat().st_size, sha256=sha(path), mode_ledger="roles.json", days=3)
    save(rt.LOG / "sdk-custody.json", receipt)


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        build()
    elif sys.argv[1:] == ["--help"]:
        print("capsule.py build | ARCHIVE SHA256 P|C NEW_SDK")
    else:
        archive, expected, role, dst = sys.argv[1:]
        archive = Path(archive)
        need(0 < archive.stat().st_size <= MAX_BYTES and sha(archive) == expected, "incorrect input archive")
        print(json.dumps(verify(archive, role, Path(dst))))
