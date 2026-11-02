"""Reproduce the optional coalescer's full-bootstrap and actual build-script controls."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import tomllib

KIT = Path(__file__).resolve().parent
REVISION = "1b9c0d5ff9bbe7634aead059efe6b11a7eeba145"
ORIGINAL = {
    "RegisterCoalescer.cpp": "426715cf2ea5bf705ec793a88d7e5c415e25025152437b3d7fa9b0381bfa17c1",
    "RegisterCoalescer.h": "4e3f176f2e4f6ec785dfeb937219e98cf404298e95a676c89571243d15a5b82b",
}
BUILD_SCRIPT = "compiler/rustc_llvm/build.rs"
DOWNLOAD = "src/bootstrap/src/core/download.rs"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(rust, *args):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", rust, *args])


def sparse_row(name):
    if len(name) <= 2:
        return Path(str(len(name)), name)
    if len(name) == 3:
        return Path("3", name[0], name)
    return Path(name[:2], name[2:4], name)


def seed_private_registry(rust, registry, cargo):
    """Copy only public sparse rows and hash-checked archives from the reviewer's local Cargo home."""
    packages = {}
    for file, extras_only in [
        (rust / "src/bootstrap/Cargo.lock", False),
        (rust / "Cargo.lock", True),
    ]:
        for row in tomllib.loads(file.read_text())["package"]:
            name, version = row["name"], row["version"]
            if not row.get("checksum") or (
                extras_only
                and (name, version) not in {("cc", "1.2.16"), ("shlex", "1.3.0")}
            ):
                continue
            packages[name, version] = row["checksum"]
    for index in (registry / "index").glob("*"):
        if not (index / "config.json").is_file():
            continue
        i = cargo / "registry/index" / index.name
        i.mkdir(parents=True)
        shutil.copy2(index / "config.json", i / "config.json")
        dest = cargo / "registry/cache" / index.name
        dest.mkdir(parents=True)
        for (name, version), expected in packages.items():
            row = Path(".cache") / sparse_row(name)
            if (index / row).is_file():
                (i / row).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(index / row, i / row)
            archive = registry / "cache" / index.name / f"{name}-{version}.crate"
            if archive.is_file():
                assert digest(archive) == expected, archive
                shutil.copy2(archive, dest / archive.name)


def prepare_bootstrap(rust, work, sdk):
    """Copy the real crate, expose unchanged private functions, and give all outputs private paths."""
    src = work / "snapshot/src"
    src.mkdir(parents=True)
    for name in ("bootstrap", "build_helper", "shim_utils"):
        shutil.copytree(
            rust / "src" / name,
            src / name,
            ignore=shutil.ignore_patterns("target", "__pycache__"),
        )
    for rel in ("stage0", "ci/channel", "version"):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rust / "src" / rel, src / rel)
    (src / "etc").mkdir()
    for file in (rust / "src/etc").glob("rust_analyzer*"):
        shutil.copy2(file, src / "etc" / file.name)
    download = src / "bootstrap/src/core/download.rs"
    assert digest(download) == digest(rust / DOWNLOAD)
    with download.open("a") as f:
        f.write("\n" + (KIT / "bootstrap_adapter.rs").read_text())
    with (src / "bootstrap/src/lib.rs").open("a") as f:
        f.write(
            "\npub fn optional_source_probe() { crate::core::download::local_optional_source_probe(); }\n"
        )
    (src / "bootstrap/src/bin/main.rs").write_text(
        "fn main() { bootstrap::optional_source_probe(); }\n"
    )
    manifest = src / "bootstrap/Cargo.toml"
    original = manifest.read_text()
    assert original.count("bootstrap.debug = 1") == 1
    manifest.write_text(original.replace("bootstrap.debug = 1", "bootstrap.debug = 0"))
    (work / "bootstrap.toml").write_text(
        'profile = "compiler"\nchange-id = "ignore"\n[build]\nsubmodules = false\n'
        f"rustc = {json.dumps(str(sdk / 'bin/rustc'))}\ncargo = {json.dumps(str(sdk / 'bin/cargo'))}\n"
        "[llvm]\ndownload-ci-llvm = false\n[rust]\ndownload-rustc = false\n"
    )


def prepare_patch(rust, work):
    crate = work / "patch-probe"
    (crate / "src").mkdir(parents=True)
    # Reconstruct the original complete build.rs even when the original pre-review commit is
    # not advertised by Git. The digest pins every byte, beyond the one function under test.
    baseline = subprocess.run(
        [
            "patch",
            "--batch",
            "--fuzz=0",
            "--reject-file=-",
            "--quiet",
            "--output=-",
            rust / BUILD_SCRIPT,
        ],
        cwd=work,
        input=(KIT / "baseline-build-script.patch").read_bytes(),
        capture_output=True,
        check=True,
    ).stdout
    assert (
        hashlib.sha256(baseline).hexdigest()
        == "f8d58249d1d98a5a9ede32608c1845978f0ed86fd927728fd9d7feb7394404ab"
    )
    for arm, source in [
        ("old", baseline.decode()),
        ("new", (rust / BUILD_SCRIPT).read_text()),
    ]:
        start = source.index(
            '    if let Some(sources) = tracked_env_var_os("LLVM_RUSTC_OHM_COALESCER_SOURCE")'
        )
        end = source.index('    cfg.file("llvm-wrapper/PassWrapper.cpp")', start)
        call = source[start:end]
        assert "prepare_ohm_coalescer" in call
        adapter = (
            (KIT / "build_script_adapter.rs")
            .read_text()
            .replace("    // REPLACE_WITH_PRODUCTION_CALL\n", call)
        )
        (crate / "src" / f"{arm}.rs").write_text(source + "\n" + adapter)
    (crate / "src/main.rs").write_text(
        "#![allow(dead_code)]\nmod old; mod new;\nfn main() { match std::env::args().nth(1).as_deref() { "
        'Some("old") => old::qa(), Some("new") => new::qa(), _ => panic!() } }\n'
    )
    (crate / "Cargo.toml").write_text(
        '[package]\nname="ohm-private-optional-patch"\nversion="0.0.0"\nedition="2024"\n'
        '[dependencies]\ncc="=1.2.16"\nshlex="=1.3.0"\n[profile.dev]\ndebug=0\n'
    )
    shutil.copy2(KIT / "original-manager.c", work / "original-manager.c")


def run(work, name, argv, env):
    cmd = [sys.executable, "-IB", KIT / "guarded.py", name, *argv]
    print(f"{name}: child output goes to {work}/{name}.std{{out,err}}", flush=True)
    subprocess.run(cmd, cwd=work, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rust",
        type=Path,
        required=True,
        help="Ohm Rust checkout with the reviewed fallback applied",
    )
    parser.add_argument(
        "--llvm",
        type=Path,
        required=True,
        help="matching rust-ci LLVM prefix including headers and original dynamic library",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        help="stock pinned LLVM llvm/lib/CodeGen directory, defaults to the Rust LLVM submodule",
    )
    parser.add_argument(
        "--sdk",
        type=Path,
        required=True,
        help="matching signed Ohm toolchain root with bin/{rustc,cargo} and libLLVM",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")) / "registry",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="allow Cargo to fetch missing public locked build dependencies",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="empty output directory; defaults to a fresh temporary directory",
    )
    a = parser.parse_args()
    rust, llvm, sdk = a.rust.resolve(), a.llvm.resolve(), a.sdk.resolve()
    source = (a.sources or rust / "src/llvm-project/llvm/lib/CodeGen").resolve()
    for name, expected in ORIGINAL.items():
        assert digest(source / name) == expected, source / name
    assert REVISION in (llvm / "include/llvm/Support/VCSRevision.h").read_text()
    libs = [
        p for p in (sdk / "lib").glob("libLLVM.so.*") if p.stat().st_size > 20 << 20
    ]
    assert len(libs) == 1, libs
    lib = libs[0]
    release_hash = digest(lib)
    assert digest(llvm / "lib" / lib.name) == release_hash
    work = (a.out or Path(tempfile.mkdtemp(prefix="ohm-optional-coalescer-"))).resolve()
    work.mkdir(parents=True, exist_ok=True)
    assert not any(work.iterdir()), work
    config = {
        "rust": str(rust),
        "sources": str(source),
        "llvm": str(llvm),
        "sdk": str(sdk),
        "library": str(lib),
        "library_sha256": release_hash,
        "candidate": git(rust, "rev-parse", "HEAD").decode().strip(),
        "base": "d1c2e85990d0d9fdb34052af19a1b3cf8ebba36b",
        "candidate_inputs": {
            n: digest(rust / n)
            for n in [
                BUILD_SCRIPT,
                DOWNLOAD,
                "compiler/rustc_llvm/llvm-wrapper/OhmRegisterCoalescer.cpp",
                "compiler/rustc_llvm/llvm-wrapper/ohm-register-coalescer/RegisterCoalescer.patch",
            ]
        },
    }
    for name, expected in config["candidate_inputs"].items():
        assert (
            hashlib.sha256(
                git(rust, "show", config["candidate"] + ":" + name)
            ).hexdigest()
            == expected
        ), ("uncommitted product input", name)
    (work / "inputs.json").write_text(json.dumps(config, indent=2) + "\n")
    (work / "cargo").mkdir()
    seed_private_registry(rust, a.registry.resolve(), work / "cargo")
    prepare_bootstrap(rust, work, sdk)
    prepare_patch(rust, work)
    env = os.environ.copy()
    for key in (
        "RUSTFLAGS",
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
        "CARGO_ENCODED_RUSTFLAGS",
        "CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST",
        "CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST",
    ):
        env.pop(key, None)
    env.update(
        CARGO_HOME=str(work / "cargo"),
        CARGO_INCREMENTAL="0",
        GIT_OPTIONAL_LOCKS="0",
        PYTHONDONTWRITEBYTECODE="1",
    )
    cargo = ["cargo", "+ohm", "build", "-j1"] + ([] if a.online else ["--offline"])
    for kind, more, command in [
        (
            "bootstrap-build",
            [
                "--locked",
                "--manifest-path",
                "snapshot/src/bootstrap/Cargo.toml",
                "--bin",
                "bootstrap",
            ],
            "target",
        ),
        (
            "product-build",
            ["--manifest-path", "patch-probe/Cargo.toml"],
            "product-target",
        ),
    ]:
        material = env | {
            "CARGO_TARGET_DIR": str(work / command),
            "CARGO_BUILD_BUILD_DIR": str(work / (command + "-build")),
        }
        run(work, kind, [*cargo, *more], material)
    for name, script in [
        ("bootstrap-cases", "bootstrap_cases.py"),
        ("patch-cases", "patch_cases.py"),
    ]:
        run(work, name, [sys.executable, "-IB", KIT / script], env)
    print("Passed nine full-bootstrap and seven build-script cases. Receipts:", work)


if __name__ == "__main__":
    main()
