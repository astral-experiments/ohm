import gzip
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

TRIPLE = "aarch64-apple-darwin"
PARENT = "82911b516fb35608fd70ada4deb6f8429277f410"
CHILD = "919199fc9c2b05ee49ccf7da4d53ec68ef117e5f"
COMPILER_TREE = "0640088775e03b6948942395dcdeb7220def02a0"
ASM_BLOB = "8cbe3af554b92ce387c7430a9d88b68dbe4ca51b"
RUFF = "97e3bd58752cccffab11bc5af937ee7b9cda0c6b"
EDIT = "ef23c9c39eb3029bab0139c3ea7ae6d95c4131e0"
EDIT_TREE = "98a52bb4dd68ff5ce9ccae612fd0dd3c27bdbae5"
SOURCE = "crates/ruff_python_ast/src/python_version.rs"
OLD_BLOB = "e4a45a36f25910aef3a852261b724dfa489fbdf6"
NEW_BLOB = "40899ad3e5e32c5f1fa2720d0d8c5f45a3a18f80"
LOCK = "9e59dd9a48f343e2edbecfad4d47ce8dd38017cb8b773d385b8f8b1556df01bc"
ZMIJ = "30e0d8dffbae3d840f64bda38e28391faef673a7b5a6017840f2a106c8145868"
ZMIJ_LIB = "98cf9b5dfdd97b5fa57d9efa2041119fb8c844a6a31764f7cd3e8ac270f969d2"
ARCHIVE = "ohm-1.99.0-20-aarch64-apple-darwin.tar.gz"
ARCHIVE_SHA = "7cd292583785c25a315f67bf85c8f028a15ccb0be5461ac39ce6e46720807bb8"
ARCHIVE_SIZE = 294960329
SIDECAR = "406960a6082942c3440db8d61d1882379af52e46c1b3f2378f9b083dd5ace622"
CARGO_SOURCE = "2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c"
STOCK_RUST = "7e71d3150938ff8ed82aca03416439d7e5b87ef3"
READER = b'use ruff_python_ast::PythonVersion as V; fn main(){println!("{} {} {}", V::latest(), V::latest_ty(), V::default());}\n'
EXPECTED = {"old": "3.14 3.14 3.10", "new": "3.15 3.15 3.11"}
MISSING = b"ohm-untracked-relink-inputs"
RECHECK = b"/dev/null/ohm-recheck-dependent-links"
GIB = 2**30
ARGS = [
    "cargo",
    "+ohm",
    "build",
    "-p",
    "ruff_python_ast",
    "--locked",
    "--offline",
    "-j4",
    "--message-format=json",
]
ORDERS = {
    "screen": ["PC", "CP"],
    # Balanced allocation 695 of 924, fixed from the release digest and Ruff edit.
    "confirm": ["CP", "PC", "CP", "CP", "CP", "PC", "PC", "PC", "PC", "CP", "CP", "PC"],
}


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(body)
    return digest(body)


def load(path):
    return json.loads(Path(path).read_bytes())


def run(args, *, cwd=None, env=None, timeout=240, data=None):
    proc = subprocess.run(args, cwd=cwd, env=env, input=data, capture_output=True, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(
            f"{args[:4]} exited {proc.returncode}\n" + proc.stderr.decode(errors="replace")[-3500:]
        )
    return proc.stdout


def git(repo, *args):
    return run(["git", "--no-optional-locks", "-C", str(repo), *args])


def text_git(repo, *args):
    return git(repo, *args).decode().strip()


def physical(path):
    p = Path(path).resolve(strict=True)
    st = p.stat()
    return {"name": p.name, "dev": st.st_dev, "ino": st.st_ino, "size": st.st_size, "sha256": sha(p)}


def check_host(root, free=8):
    need(platform.system() == "Darwin" and platform.machine() == "arm64", "requires native Apple silicon")
    need(run(["sysctl", "-n", "hw.optional.arm64"]).strip() == b"1", "hardware is not arm64")
    need(shutil.disk_usage(root).free > free * GIB, f"need more than {free} GiB free")
    total = int(run(["sysctl", "-n", "hw.memsize"]))
    vm = run(["vm_stat"]).decode()
    pages = int(re.search(r"page size of (\d+) bytes", vm)[1])
    reclaimable = (
        sum(
            int(re.search(rf"^Pages {kind}:\s*(\d+)\.", vm, re.MULTILINE)[1])
            for kind in ("free", "inactive", "speculative")
        )
        * pages
    )
    need(total >= 6 * GIB and reclaimable > (1.5 if free >= 32 else 0.75) * GIB, "Darwin memory floor")
    return {
        "machine": platform.machine(),
        "Darwin": platform.release(),
        "available": shutil.disk_usage(root).free,
        "memory": total,
        "free_inactive_speculative": reclaimable,
        "xcode": run(["xcodebuild", "-version"]).decode().strip(),
    }


def env_for(root, sdk):
    root = Path(root)
    rustup = root / "rustup"
    toolchains = rustup / "toolchains"
    toolchains.mkdir(parents=True, exist_ok=True)
    alias = toolchains / "ohm"
    if not alias.exists():
        alias.symlink_to(sdk.resolve(), target_is_directory=True)
    need(alias.samefile(sdk), "SDK alias moved")
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith(
            ("CARGO_", "RUSTC_", "RUSTDOC_", "RUSTUP_", "RUSTFLAGS", "DYLD_", "OHM_")
        ) or key in ("RUSTC", "RUSTDOC", "GH_TOKEN", "GITHUB_TOKEN", "RUSTC_BOOTSTRAP"):
            del environment[key]
    environment.update(
        RUSTUP_HOME=str(rustup),
        CARGO_HOME=str(root / "cargo-home"),
        CARGO_TARGET_DIR=str(root / "target"),
        CARGO_BUILD_BUILD_DIR=str(root / "shared"),
        CARGO_NET_OFFLINE="true",
        CARGO_TERM_COLOR="never",
        CARGO_CACHE_AUTO_CLEAN_FREQUENCY="never",
        LC_ALL="C",
        TZ="UTC",
    )
    return environment


def sdk_id(sdk, env):
    expected_cargo = CARGO_SOURCE
    if sdk.name == "native" and (sdk.parent / "receipts/fixed-cargo-293.json").is_file():
        pinned = load(sdk.parent / "receipts/fixed-cargo-293.json")
        expected_cargo = "735e1528ed741015c57676dccf05dbdc0ff7bed1"
        need(pinned["commit"] == expected_cargo and physical(sdk/"bin/cargo") == pinned["binary"]
             and (sdk/"bin/cargo").samefile(sdk.parent/"cargo-293"), "measured Cargo identity changed")
    compiler = run(["rustc", "+ohm", "-vV"], env=env).decode()
    cargo = run(["cargo", "+ohm", "-Vv"], env=env).decode()
    need(
        str(sdk.resolve())
        == str(Path(run(["rustc", "+ohm", "--print", "sysroot"], env=env).decode().strip()).resolve()),
        "incorrect sysroot",
    )
    need(
        f"host: {TRIPLE}" in compiler and f"commit-hash: {expected_cargo}" in cargo,
        "foreign compiler host or Cargo source",
    )
    libs = sorted((sdk / "lib").glob("librustc_driver*.dylib"))
    need(len(libs) == 1, f"ambiguous driver: {libs}")
    stddir = sdk / "lib" / "rustlib" / TRIPLE / "lib"
    std = {p.name: sha(p) for p in stddir.iterdir() if p.is_file()}
    need(
        any(k.startswith("libcore-") for k in std) and any(k.startswith("libstd-") for k in std),
        "incomplete sysroot",
    )
    return {
        "rustc_version": compiler,
        "cargo_version": cargo,
        "rustc": physical(sdk / "bin/rustc"),
        "driver": physical(libs[0]),
        "cargo": physical(sdk / "bin/cargo"),
        "std": std,
    }


def source_values(repo):
    need(text_git(repo, "rev-parse", "HEAD") == RUFF, "wrong Ruff HEAD")
    need(text_git(repo, "symbolic-ref", "--short", "HEAD") == "qa-apple-zmij", "use one named branch")
    need(sha(repo / "Cargo.lock") == LOCK, "wrong Ruff lockfile")
    need(text_git(repo, "rev-parse", f"{EDIT}^:{SOURCE}") == OLD_BLOB, "old source mismatch")
    need(text_git(repo, "rev-parse", f"{EDIT}:{SOURCE}") == NEW_BLOB, "edited source mismatch")
    need(
        text_git(repo, "rev-parse", f"{EDIT}^") == RUFF
        and text_git(repo, "rev-parse", f"{EDIT}^{{tree}}") == EDIT_TREE,
        "historical commit mismatch",
    )
    return {"old": git(repo, "cat-file", "blob", OLD_BLOB), "new": git(repo, "cat-file", "blob", NEW_BLOB)}


def change_source(repo, values, state):
    p = repo / SOURCE
    revision = RUFF if state == "old" else EDIT
    git(repo, "restore", "--source", revision, "--staged", "--worktree", "--", ".")
    need(
        text_git(repo, "write-tree") == text_git(repo, "rev-parse", f"{revision}^{{tree}}"),
        "not the exact historical tree",
    )
    need(not git(repo, "diff", "--name-only").strip(), "unexpected unstaged edit")
    need(p.read_bytes() == values["old" if state == "old" else "new"], "incorrect version source")
    if state == "invalid":
        p.write_bytes(values["new"] + b"\npub const QA_INVALID: u32 = apple_zmij_missing_name;\n")
    need(
        sha(repo / "Cargo.lock") == LOCK and text_git(repo, "rev-parse", "HEAD") == RUFF,
        "workspace identity changed",
    )
    return sha(p)


def copy_tree(source, destination):
    need(not destination.exists(), f"refuse existing {destination}")
    run(["/bin/cp", "-cR", str(source), str(destination)], timeout=600)


def compress_bytes(path, body):
    with Path(path).open("xb") as s:
        s.write(gzip.compress(body, compresslevel=3, mtime=0))
    return digest(body)
