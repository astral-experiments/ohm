"""Bound the source SDK archive, invoke its matching reader, then qualify native binaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
REPO = "astral-experiments/ohm"
TRIPLE = "x86_64-unknown-linux-gnu"
RUST = ("625207d26ce4449c9c95d871c88cfb50e904c09f", "8b72462af9b3251a8610e4310d34b9de4f1c8344")
CARGO = {
    "pinned": ("2554a1dfaf22474b360a4298883acf41f82bd78f", "014d4b308410fdaa2acdadaff6aba2a410fc43da"),
    "fourfix": ("4591cf45cc10abb19d2456c40b99606e08167f29", "a2c9a62722e1ef849cb68874e79617c92d165a8b"),
}
WILD = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
LD = f"lib/rustlib/{TRIPLE}/bin/wild-ld/ld.bfd"
DISTRIBUTED_21 = "6f550de85f95440a61b5bd1a9d2ab0528d4fcaf674fdc008f5e986d2138be6c4"
RUST_TREES = {"compiler": "fe04efe2bcbf28820e9c3361d62b299d273e9a24", "library": "4f7a8f755164dc68fff80790db8a844ae030fd03",
              "tests": "76f8c0ecd0eed35042848dfa7036dc546bd1ad6f", "src/bootstrap": "1dcf3e6b142ba5c132f7a2370dffa6ba090b15e1",
              "src/tools/cargo": CARGO["pinned"][0]}
BOOTSTRAP = ["x.py", "--ci", "false", "--set", "build.submodules=false", "--set", "rust.channel=dev",
             "--set", "rust.omit-git-hash=false", "--set", "rust.debug-assertions=false", "--set", "rust.lto=off",
             "--set", "llvm.download-ci-llvm=true", "build", "--stage", "1", "-j8", "--host", TRIPLE, "--target", TRIPLE,
             "compiler/rustc", "library", "src/tools/rustdoc"]
WORKERS = {"native_mounts.py": "afa6fa62a26e8cdcedc9eb4b5009acbbe6128904a0a74b3bb1c6801c3e52029b",
           "ruff_recovery.py": "b950ccd6cde4e1beb6058948bdb1ac3ac55c1ff13fd3c57415b7393e11f83078"}
ZIP_LIMITS = {"receipt.json": 1 << 20, "members.json": 8 << 20, "kit.tar.zst": 2 << 30}
LIMIT = 4 << 30


def need(value, reason):
    if not value:
        raise ValueError(reason)


def checksum(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def strict_json(raw):
    def pairs(items):
        obj = dict(items)
        need(len(obj) == len(items), "duplicate JSON key")
        return obj
    return json.loads(raw, object_pairs_hook=pairs)


def digest(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def save(path, value):
    with path.open("x") as f:
        json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")


def zip_entries(archive):
    entries = archive.infolist()
    need(len(entries) == len(ZIP_LIMITS) and {e.filename for e in entries} == set(ZIP_LIMITS), "unexpected SDK ZIP members")
    for e in entries:
        need(0 < e.file_size <= ZIP_LIMITS[e.filename] and not e.flag_bits & 1 and
             stat.S_IFMT(e.external_attr >> 16) in (0, stat.S_IFREG), "unsafe ZIP member")
    return entries


def unzip(raw, target, official):
    need(raw.stat().st_size == official["size"] and checksum(raw) == official["sha256"], "official SDK ZIP changed")
    target.mkdir(mode=0o700)
    with zipfile.ZipFile(raw) as archive:
        for e in zip_entries(archive):
            with archive.open(e) as src, (target / e.filename).open("xb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
                need(dst.tell() == e.file_size, "wrong decoded ZIP size")


def inventory(index):
    need(type(index) is dict and 0 < len(index) <= 30000, "member census outside envelope")
    total = 0
    for name, m in index.items():
        p = PurePosixPath(name)
        need(name == p.as_posix() and not p.is_absolute() and ".." not in p.parts and len(p.parts) >= 2
             and p.parts[0] in ("sdk", "roles") and "\\" not in name and "\0" not in name, "unsafe member path")
        if p.parts[0] == "roles":
            need(name in ("roles/pinned/cargo", "roles/fourfix/cargo"), "unregistered alternate tool")
        need(set(m) == {"sha256", "bytes", "mode"} and digest(m["sha256"]) and type(m["bytes"]) is int
             and 0 <= m["bytes"] <= 1 << 30 and type(m["mode"]) is int and 0 < m["mode"] <= 0o777, "unsafe member declaration")
        total += m["bytes"]
    need(total <= LIMIT, "decoded SDK exceeds four GiB")
    return total


def validate_tar(pack, index):
    # tarfile may stop at the first zero block (or a bad trailing header).
    # Track where the last nonzero byte really is, including any unread padding.
    limit = inventory(index) + len(index) * 8192 + (1 << 20)
    with subprocess.Popen(["zstd", "-q", "-M512MB", "-dc"], stdin=pack, stdout=subprocess.PIPE) as proc:
        class Stream:
            total = 0
            last_nonzero = 0

            def read(self, size):
                chunk = proc.stdout.read(size)
                used = len(chunk.rstrip(b"\0"))
                if used:
                    self.last_nonzero = self.total + used
                self.total += len(chunk)
                need(self.total <= limit, "unbounded zstd expansion")
                return chunk

        raw = Stream()
        try:
            seen = set()
            with tarfile.open(fileobj=raw, mode="r|") as tar:
                for e in tar:
                    need(e.name in index and e.name not in seen and e.type in (tarfile.REGTYPE, tarfile.AREGTYPE)
                         and e.sparse is None and not e.linkname, "unregistered, sparse, linked or duplicate tar entry")
                    m = index[e.name]
                    need((e.size, e.mode) == (m["bytes"], m["mode"]), "tar declaration differs from authenticated inventory")
                    h = hashlib.sha256()
                    with tar.extractfile(e) as entry:
                        while chunk := entry.read(1 << 20):
                            h.update(chunk)
                    need(h.hexdigest() == m["sha256"], "decoded SDK member changed: " + e.name)
                    seen.add(e.name)
                end = tar.offset
            while raw.read(1 << 20):
                pass
            need(seen == index.keys() and 1024 <= raw.total - end <= 1024 * 1024, "incomplete SDK tar or unreasonable padding")
            need(raw.last_nonzero <= end, "nonzero bytes after registered tar members")
        finally:
            proc.stdout.close()
        need(proc.wait() == 0, "zstd frame did not complete")


def verbose(raw, commit, host=TRIPLE):
    lines = raw.splitlines()
    for field in ("commit-hash: " + commit, "host: " + host, "release: 1.99.0-dev"):
        need(lines.count(field) == 1, "unexpected native version field: " + field)


def registration(receipt, index, anchor):
    inventory(index)
    r = receipt["rust"]
    need(receipt["schema"] == 1 and receipt["source_qualification"] ==
         "source-built native stage1; Cargo release profile with no distribution PGO", "wrong build recipe")
    expected = {"GITHUB_REPOSITORY": REPO, "GITHUB_SHA": anchor["source_head"], "GITHUB_RUN_ID": str(anchor["run"]),
                "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "sdk"}
    need(receipt["qa"] == expected, "wrong source run, attempt or job")
    need((r["commit"], r["tree"]) == RUST and r["host"] == TRIPLE and r["rustc_path"] == "sdk/bin/rustc"
         and re.fullmatch(r"sdk/lib/librustc_driver(?:-[0-9a-f]+)?\.so", r["driver_path"]), "wrong GNU compiler or driver")
    verbose(r["version_verbose"], RUST[0])
    verbose(r["rustdoc_verbose"], RUST[0])
    need(r["bootstrap"][1:] == BOOTSTRAP and r["subtrees"] == RUST_TREES, "different source trees or stage1 build configuration")
    ld, = receipt["native_linkers"]
    need(ld["kind"] == "bundled-wild" and ld["path"] == LD and ld["sha256"] == WILD
         and ld["source_archive"] == DISTRIBUTED_21 and re.fullmatch(r"Wild 0\.11\.0(?: .*)?", ld["version"]),
         "stock signed Wild changed")
    expected_members = {"sdk/bin/rustc": r["rustc_sha256"], "sdk/bin/rustdoc": r["rustdoc_sha256"],
                        r["driver_path"]: r["driver_sha256"], "sdk/" + LD: WILD}
    out = {"rust": RUST[0], "rustc": r["rustc_sha256"], "driver": r["driver_sha256"], "wild": WILD}
    need(set(receipt["cargos"]) == set(CARGO), "missing or additional Cargo role")
    for role, (revision, tree) in CARGO.items():
        c = receipt["cargos"][role]
        need((c["commit"], c["tree"]) == (revision, tree) and c["release_channel"] == "dev" and
             c["path"] == f"roles/{role}/cargo" and {"ohm-defaults", "all-static"} <= set(c["features"])
             and c["command"] == ["cargo", "+ohm", "-Zohm-defaults=no", "build", "--release", "--offline", "--locked",
                                  "-p", "cargo", "--bin", "cargo", "--features", "all-static,ohm-defaults", "-j8", "--message-format=json"],
             "wrong Cargo source, release flags or role")
        verbose(c["version_verbose"], revision)
        expected_members[c["path"]] = c["sha256"]
        out["fixed" if role == "fourfix" else role] = {"source": revision, "tree": tree, "sha256": c["sha256"]}
    expected_members["sdk/bin/cargo"] = out["pinned"]["sha256"]
    need(out["fixed"]["sha256"] != out["pinned"]["sha256"], "two Cargo roles have identical binaries")
    need(all(index[path]["sha256"] == sha for path, sha in expected_members.items()), "physical identity missing from manifest")
    need(sum(n.startswith("sdk/lib/librustc_driver") and n.endswith(".so") for n in index) == 1, "ambiguous driver")
    for name in ("core", "std", "alloc", "proc_macro", "test"):
        pattern = rf"sdk/lib/rustlib/{TRIPLE}/lib/lib{name}-[a-f0-9]+\.rlib"
        need(any(re.fullmatch(pattern, n) for n in index), "missing native standard library " + name)
    need({PurePosixPath(n).parts[3] for n in index if n.startswith("sdk/lib/rustlib/")} <= {TRIPLE, "src"},
         "foreign architecture under sdk/lib/rustlib")
    return out, expected_members


def native_elf(path):
    with path.open("rb") as f:
        h = f.read(64)
        need(len(h) == 64 and h[:7] == b"\x7fELF\x02\x01\x01" and h[7] in (0, 3), "not a GNU ELF64 little-endian binary")
        t, machine, version, _, phoff = struct.unpack_from("<HHIQQ", h, 16)
        nbytes, count = struct.unpack_from("<HH", h, 54)
        need(t in (2, 3) and machine == 62 and version == 1 and nbytes == 56 and
             0 < count <= 1000 and phoff + count * nbytes <= path.stat().st_size, "wrong native x86-64 ELF header")
        f.seek(phoff)
        headers = [struct.unpack("<IIQQQQQQ", f.read(nbytes)) for _ in range(count)]
        need(any(p[0] == 1 for p in headers), "ELF has no loadable segments")
        interpreters = [p for p in headers if p[0] == 3]
        need(len(interpreters) <= 1, "ambiguous ELF interpreter")
        for p in interpreters:
            need(0 < p[5] <= 256 and p[2] + p[5] <= path.stat().st_size, "invalid ELF interpreter range")
            f.seek(p[2])
            need(f.read(p[5]) in (b"/lib64/ld-linux-x86-64.so.2\0", b"/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2\0"),
                 "ELF declares a non-glibc interpreter")


def restore(archive, source, root, anchor):
    need(os.uname().sysname == "Linux" and os.uname().machine == "x86_64", "GNU SDK requires native x86-64 Linux")
    for name, expected in WORKERS.items():
        need(checksum(HERE / name) == expected, "unregistered worker " + name)
    root.mkdir(mode=0o700)
    bundle = root / "bundle"
    unzip(archive, bundle, anchor["artifact"])
    for name in ZIP_LIMITS:
        need(checksum(bundle / name) == anchor["members"][name], "source SDK member hash changed: " + name)
    receipt = strict_json((bundle / "receipt.json").read_bytes())
    index = strict_json((bundle / "members.json").read_bytes())
    need(receipt["kit_bytes"] == (bundle / "kit.tar.zst").stat().st_size and
         receipt["kit_sha256"] == anchor["members"]["kit.tar.zst"] and
         receipt["members_sha256"] == anchor["members"]["members.json"], "internal source custody mismatch")
    reg, native = registration(receipt, index, anchor)
    need(reg == anchor["registration"], "runtime registration changed")
    need(set(anchor["reader"]) == {"sdk.py", "common.py"}, "missing source reader closure")
    for name, sha in anchor["reader"].items():
        need(checksum(source / "scripts/rc22-native" / name) == sha, "source reader changed: " + name)
    need(subprocess.check_output(["git", "-C", source, "rev-parse", "HEAD"], text=True).strip() == anchor["source_head"],
         "different source checkout")
    with (bundle / "kit.tar.zst").open("rb") as pack:
        validate_tar(pack, index)
    installed = root / "installed"
    subprocess.run([sys.executable, "-IB", source / "scripts/rc22-native/sdk.py", "reopen", bundle, installed], check=True)
    for name, expected in native.items():
        path = installed / name
        need(path.resolve(strict=True) == path and checksum(path) == expected, "installed native binary changed: " + name)
        native_elf(path)
    clean = {"PATH": "/usr/bin:/bin", "LANG": "C", "HOME": str(root)}
    versions = {}
    for name, expected, flag in (("sdk/bin/rustc", receipt["rust"]["version_verbose"], "-vV"),
                                 ("sdk/bin/rustdoc", receipt["rust"]["rustdoc_verbose"], "-vV"),
                                 ("sdk/bin/cargo", receipt["cargos"]["pinned"]["version_verbose"], "-Vv"),
                                 ("roles/pinned/cargo", receipt["cargos"]["pinned"]["version_verbose"], "-Vv"),
                                 ("roles/fourfix/cargo", receipt["cargos"]["fourfix"]["version_verbose"], "-Vv"),
                                 ("sdk/" + LD, receipt["native_linkers"][0]["version"], "--version")):
        live = subprocess.check_output([installed / name, flag], env=clean, text=True).strip()
        versions[name] = live
        # Cargo reports the runtime host's distribution in the "os" line.
        if flag == "-Vv":
            def build_fields(value):
                lines = value.splitlines()
                need(len([line for line in lines if line.startswith("os: ")]) == 1, "missing Cargo runtime OS")
                return [line for line in lines if not line.startswith("os: ")]
            need(build_fields(live) == build_fields(expected), "live Cargo build identity changed: " + name)
        else:
            need(live == expected, "live version changed: " + name)
    sysroot = subprocess.check_output([installed / "sdk/bin/rustc", "--print", "sysroot"], env=clean, text=True).strip()
    need(Path(sysroot).resolve() == installed / "sdk", "rustc did not select its restored sysroot")
    save(root / "registration.json", reg)
    save(root / "qualified.json", {"source": anchor, "members": len(index), "decoded_bytes": inventory(index),
                                  "installed_native": native, "live_versions": versions, "sysroot": sysroot, "qualified": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("archive", "source", "root", "anchor"):
        parser.add_argument(argument, type=Path)
    args = parser.parse_args()
    restore(args.archive.resolve(strict=True), args.source.resolve(strict=True), args.root.resolve(),
            strict_json(args.anchor.read_bytes()))
