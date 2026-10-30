"""Prepare private, source-enrolled inputs on an ephemeral arm64 Actions worker."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

from measure import capture
from study import (
    ARCHIVE,
    ARCHIVE_SHA,
    ARCHIVE_SIZE,
    ASM_BLOB,
    CARGO_SOURCE,
    CHILD,
    COMPILER_TREE,
    EDIT,
    PARENT,
    RUFF,
    SIDECAR,
    STOCK_RUST,
    TRIPLE,
    ZMIJ,
    ZMIJ_LIB,
    check_host,
    digest,
    env_for,
    git,
    need,
    physical,
    run,
    save,
    sdk_id,
    sha,
    source_values,
    text_git,
)

RELEASE = "astral-experiments/ohm"
TAG = "ohm-1.99.0-20"
PROV = "1c69f4ffadeed83885a4f1b4c5878b912516223b9b061de3f884bd45dc87b060"
ASM = "compiler/rustc_codegen_llvm/src/asm.rs"


def probe_proc_macro(root, sdk, role):
    """Build a native proc macro, expand it in a second compiler, and execute the result."""
    work = root / "proc-macro-probe" / role
    work.mkdir(parents=True)
    env = env_for(work, sdk)
    sysroot = Path(run(["rustc", "+ohm", "--print", "sysroot"], env=env).decode().strip())
    need(sysroot.samefile(sdk), "wrong proc-macro probe SDK")
    sources = {
        "count.rs": (
            "extern crate proc_macro;\nuse proc_macro::TokenStream;\n#[proc_macro]\n"
            "pub fn count(input: TokenStream) -> TokenStream {\n"
            "    input.into_iter().count().to_string().parse().unwrap()\n}\n"
        ),
        "reader.rs": 'fn main() { println!("{}", qa_count::count!(one two three)); }\n',
    }
    for name, contents in sources.items():
        (work / name).write_text(contents)
    out = root / "receipts/proc-macro" / role
    rustc = ["rustc", "+ohm", "--edition=2024"]
    for label, args in (
        ("producer", [*rustc, "--crate-name=qa_count", "--crate-type=proc-macro", "count.rs", "-o", "libqa_count.dylib"]),
        ("consumer", [*rustc, "reader.rs", "--extern", "qa_count=libqa_count.dylib", "-o", "reader"]),
        ("run", ["./reader"]),
    ):
        status, stdout, stderr, _, stats = capture(args, work, env, out / label)
        save(out / label / "command.json", {"argv": args, "exit": status, **stats})
        need(status == 0, f"{role} proc-macro {label}: {stderr.decode(errors='replace')[-1000:]}")
    need(stdout == b"3\n", "wrong expanded token count")
    files = {}
    for name, kind in (("libqa_count.dylib", 6), ("reader", 2)):
        path = work / name
        with path.open("rb") as f:
            header = f.read(16)
        need(
            header[:8] == bytes.fromhex("cffaedfe0c000001") and int.from_bytes(header[12:16], "little") == kind,
            "wrong native proc-macro probe output",
        )
        files[name] = {"sha256": sha(path), "bytes": path.stat().st_size, "header": header.hex()}
    members = {p.name: sha(p) for p in (sdk / "lib/rustlib" / TRIPLE / "lib").glob("libproc_macro-*")}
    need(any(n.endswith(".rlib") for n in members), "missing sysroot proc_macro rlib")
    save(
        out / "verified.json",
        {"rustc": physical(sdk / "bin/rustc"), "members": members, "sources": sources, "outputs": files, "value": 3},
    )


def checked_archive(inbox):
    archive = inbox / ARCHIVE
    sidecar = inbox / (ARCHIVE + ".sha256")
    provenance = inbox / ARCHIVE.replace(".tar.gz", "-provenance.json")
    need(
        archive.stat().st_size == ARCHIVE_SIZE and sha(archive) == ARCHIVE_SHA, "wrong signed Darwin archive"
    )
    need(
        sha(sidecar) == SIDECAR and sidecar.read_text().split() == [ARCHIVE_SHA, ARCHIVE],
        "wrong checksum sidecar",
    )
    need(sha(provenance) == PROV, "wrong release provenance bytes")
    return archive


def prepare_release(root, inbox):
    check_host(root, 8)
    archive = checked_archive(inbox)
    unpack = root / "unpack"
    unpack.mkdir()
    selected = {"rustc", "cargo", "rust-std-" + TRIPLE}
    with tarfile.open(archive, "r|gz") as f:
        for member in f:
            names = Path(member.name).parts
            if len(names) <= 2 or names[1] in selected:
                f.extract(member, unpack, filter="data")
    (distribution,) = unpack.iterdir()
    sdk = root / "signed"
    run(
        [
            str(distribution / "install.sh"),
            "--prefix=" + str(sdk),
            "--disable-ldconfig",
            "--components=rustc,rust-std-" + TRIPLE + ",cargo",
        ],
        cwd=distribution,
        timeout=420,
    )
    packed_cargo = distribution / "cargo/bin/cargo"
    need(sha(packed_cargo) == sha(sdk / "bin/cargo"), "installer changed Cargo")
    runtime = root / "release-work"
    runtime.mkdir()
    env = env_for(runtime, sdk)
    manifest = sdk_id(sdk, env)
    need(
        STOCK_RUST in manifest["rustc_version"] and CARGO_SOURCE in manifest["cargo_version"],
        "wrong release sources",
    )
    manifest.update(
        archive=ARCHIVE_SHA, checksum=SIDECAR, provenance=PROV, packed_cargo=physical(packed_cargo)
    )
    save(root / "receipts/release.json", manifest)
    probe_proc_macro(root, sdk, "S")
    shutil.rmtree(unpack)


def prepare_ruff(root, old=RUFF, new=EDIT, verify_source=source_values):
    repo = root / "ruff"
    run(["git", "init", "-q", str(repo)])
    git(repo, "remote", "add", "origin", "https://github.com/astral-sh/ruff.git")
    git(repo, "fetch", "-q", "--depth=2", "origin", new)
    git(repo, "switch", "-q", "-c", "qa-apple-zmij", old)
    verify_source(repo)
    donor = root / "release-work"
    env = env_for(donor, root / "signed")
    env.pop("CARGO_NET_OFFLINE")
    run(["cargo", "+ohm", "fetch", "--locked", "--target", TRIPLE], cwd=repo, env=env, timeout=900)
    registry = donor / "cargo-home/registry"
    crates = sorted(registry.glob("cache/*/*.crate"))
    locked = {
        r["name"] + "-" + r["version"] + ".crate": r["checksum"]
        for r in tomllib.loads((repo / "Cargo.lock").read_text())["package"]
        if "checksum" in r
    }
    verified = {str(p.relative_to(registry)): sha(p) for p in crates}
    need(
        all(locked.get(Path(k).name) == v for k, v in verified.items()),
        "registry archive disagrees with Cargo.lock",
    )
    zmij = [p for p in crates if p.name == "zmij-1.0.10.crate"]
    need(len(zmij) == 1 and sha(zmij[0]) == ZMIJ, "wrong registry package")
    lib = list(registry.glob("src/*/zmij-1.0.10/src/lib.rs"))
    # Cargo fetch downloads .crate archives and is allowed to defer the unpack to the first build.
    need(not lib or len(lib) == 1 and sha(lib[0]) == ZMIJ_LIB, "wrong extracted package")
    save(
        root / "receipts/ruff.json",
        {
            "old": old,
            "new": new,
            "old_tree": text_git(repo, "rev-parse", "HEAD^{tree}"),
            "new_tree": text_git(repo, "rev-parse", new + "^{tree}"),
            "lock": sha(repo / "Cargo.lock"),
            "archives": verified,
        },
    )
    # Never clone warmed Rust target/build data. Each install starts with independently writable registry + empty stores.
    target = root / "seed"
    target.mkdir()
    shutil.copytree(registry, target / "registry", symlinks=False)
    if (donor / "cargo-home/git").is_dir():
        shutil.copytree(donor / "cargo-home/git", target / "git", symlinks=False)


def role_files(prefix):
    return {str(p.relative_to(prefix)): sha(p) for p in sorted(prefix.rglob("*")) if p.is_file()}


def identity_digest(prefix, members):
    rows = []
    for name in sorted(members):
        st = (prefix / name).stat()
        rows.append((name, st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns))
    return digest(json.dumps(rows).encode())


def freeze_stage(stage, frozen, source, library):
    """Snapshot runtime files without following bootstrap's two source-checkout symlinks."""
    stage = stage.resolve(strict=True)
    backrefs = {Path("lib/rustlib") / component / "rust" for component in ("src", "rustc-src")}
    for ref in backrefs:
        link = stage / ref
        need(link.is_symlink() and link.samefile(source), f"unexpected bootstrap source alias {link}")
    aliases = {}

    def exclude(directory, names):
        skip = []
        for name in names:
            path = Path(directory) / name
            rel = path.relative_to(stage)
            if rel in backrefs:
                skip.append(name)
            elif path.is_symlink() and path.is_dir():
                target = path.resolve(strict=True)
                need(
                    target.is_relative_to(stage) and target not in path.parents,
                    f"external or cyclic SDK alias {path}",
                )
                aliases[rel] = target.relative_to(stage)
                skip.append(name)
        return skip

    # Copy file aliases as ordinary files, including LLVM, driver and host std
    # objects linked out of the mutable build. Keep internal directory aliases local.
    shutil.copytree(stage, frozen, symlinks=False, ignore=exclude)
    for relative, target in aliases.items():
        link = frozen / relative
        need((frozen / target).is_dir(), f"missing SDK directory {target}")
        link.symlink_to(os.path.relpath(frozen / target, link.parent), target_is_directory=True)
    # This consumer uses the ordinary rust-src library, not rustc-dev sources.
    # Its clean checkout has the same library tree and backtrace gitlink in both arms.
    std = frozen / "lib/rustlib/src/rust/library"
    shutil.copytree(library, std, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    need(not any(p.is_symlink() for p in std.rglob("*")), "unexpected symlink in enrolled standard-library source")
    need((std / "std/src/lib.rs").is_file(), "missing frozen standard-library source")
    return {str(k): str(v) for k, v in sorted(aliases.items())}


def build_pair(root, checkout):
    check_host(root, 32)
    src = root / "compiler-source"
    run(["git", "clone", "--shared", "--no-checkout", str(checkout), str(src)], timeout=600)
    need(
        text_git(src, "rev-parse", CHILD + "^") == "7924254acf6ee5a17473ac47dfb33b5842d72005"
        and text_git(src, "rev-parse", PARENT + "^") == "82911b516fb35608fd70ada4deb6f8429277f410"
        and text_git(src, "rev-parse", PARENT + ":compiler") == "49c6df377f483d1f3db47dbb71988869dfdcdc61"
        and text_git(src, "rev-parse", PARENT + ":compiler/rustc_interface/src/passes.rs")
        == text_git(src, "rev-parse", CHILD + ":compiler/rustc_interface/src/passes.rs")
        == "ca1e085f38ac756aa37baa2edd2395d163bfedae"
        and text_git(src, "rev-parse", CHILD + ":compiler") == COMPILER_TREE
        and text_git(src, "rev-parse", CHILD + ":" + ASM) == ASM_BLOB,
        "unenrolled Rust source",
    )
    paths = git(src, "diff", "--name-only", PARENT, CHILD).decode().splitlines()
    need(
        set(paths)
        == {
            ASM,
            "tests/run-make/ohm-checked-dep-info/inline.rs",
            "tests/run-make/ohm-checked-dep-info/rmake.rs",
        },
        "unexpected product change",
    )
    library = checkout / "library"
    lib_tree = text_git(checkout, "rev-parse", CHILD + ":library")
    need(text_git(checkout, "rev-parse", PARENT + ":library") == lib_tree, "standard-library source changed")
    need(
        not text_git(checkout, "status", "--porcelain", "--ignore-submodules=none", "--", "library"),
        "dirty library source",
    )
    # Pin the ordinary full-history LLVM merge base; never use a hosted ephemeral SHA as a compiler version.
    # The reconstructed bundle deliberately has no private remote. Bootstrap only
    # needs the original public LLVM ancestry and standard-library backtrace gitlink.
    git(src, "remote", "set-url", "origin", "https://github.com/rust-lang/rust.git")
    products = {}
    for name, rev in (("P", PARENT), ("C", CHILD)):
        git(src, "checkout", "--detach", rev)
        git(src, "submodule", "update", "--init", "--depth", "1", "library/backtrace")
        need(
            text_git(src, "rev-parse", "HEAD") == rev and not text_git(src, "diff", "--name-only", "HEAD"),
            "dirty source",
        )
        log = root / "receipts" / ("bootstrap-" + name + ".log")
        base = [
            sys.executable,
            "x.py",
            "--ci",
            "false",
            "--set",
            "build.submodules=false",
            "--set",
            "rust.omit-git-hash=true",
            "--set",
            "rust.debug-assertions=false",
            "--set",
            "rust.lto=off",
            "--set",
            "llvm.download-ci-llvm=true",
        ]
        build = [*base, "build", "--stage", "1", "-j4", "compiler/rustc", "library"]
        with log.open("xb") as stream:
            subprocess.run(
                build,
                cwd=src,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=7800,
                check=True,
            )
        stage = src / "build" / TRIPLE
        stage1 = stage / "stage1"
        frozen = root / ("stage-" + name)
        aliases = freeze_stage(stage1, frozen, src, library)
        cargo = frozen / "bin/cargo"
        if cargo.exists():
            cargo.unlink()
        os.link(root / "signed/bin/cargo", cargo)
        runtime_files = role_files(frozen)
        products[name] = {
            "source": rev,
            "tree": text_git(src, "rev-parse", "HEAD^{tree}"),
            "runtime": runtime_files,
            "physical_inventory": identity_digest(frozen, runtime_files),
            "library_tree": lib_tree,
            "directory_aliases": aliases,
            "stage0_cargo": physical(stage / "stage0/bin/cargo"),
            "stage0_rustc": physical(stage / "stage0/bin/rustc"),
            "source_stamp_input": sha(src / "src/stage0"),
            "build_log": sha(log),
            "rustc": run([str(frozen / "bin/rustc"), "-vV"]).decode(),
            "build_flags": base[1:],
            "build_argv": build,
        }
        save(root / "receipts" / f"bootstrap-{name}-product.json", products[name])
        probe_proc_macro(root, frozen, name)
    p, c = (products[k] for k in "PC")
    need(
        identity_digest(root / "stage-P", p["runtime"]) == p["physical_inventory"]
        and role_files(root / "stage-P") == p["runtime"],
        "parent SDK changed during child bootstrap",
    )
    need(p["directory_aliases"] == c["directory_aliases"], "SDK directory aliases changed")
    need(
        p["stage0_rustc"] == c["stage0_rustc"]
        and p["stage0_cargo"] == c["stage0_cargo"]
        and p["rustc"] == c["rustc"],
        "unmatched bootstrap",
    )
    need(p["runtime"].keys() == c["runtime"].keys(), "SDK paths differ")
    differ = [n for n, h in p["runtime"].items() if c["runtime"][n] != h]
    need(
        differ
        and all(
            Path(n).suffix == ".dylib"
            and Path(n).name.startswith(("librustc_driver", "librustc_codegen_llvm"))
            for n in differ
        ),
        f"SDK differs outside compiler implementation: {differ}",
    )
    save(
        root / "receipts/pair.json",
        {
            "products": products,
            "differ": differ,
            "link_loads": {
                k: {n: run(["otool", "-L", str(root / ("stage-" + k) / n)]).decode() for n in differ}
                for k in "PC"
            },
        },
    )
    runtime = root / "native"
    shutil.copytree(root / "stage-P", runtime, symlinks=True, copy_function=os.link)
    # Run the exact checked-in NEON-positive, :q and .incbin-negative test using this child and backend.
    rm = root / "receipts/run-make.log"
    with rm.open("xb") as stream:
        subprocess.run(
            [*base, "test", "--stage", "1", "-j4", "tests/run-make/ohm-checked-dep-info"],
            cwd=src,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=3600,
            check=True,
        )
    save(root / "receipts/run-make.json", {"source": CHILD, "log": sha(rm)})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("release", "ruff", "pair"))
    p.add_argument("root", type=Path)
    p.add_argument("input", type=Path, nargs="?")
    a = p.parse_args()
    root = a.root.resolve()
    root.mkdir(exist_ok=True)
    (root / "receipts").mkdir(exist_ok=True)
    if a.action == "release":
        prepare_release(root, a.input.resolve())
    elif a.action == "ruff":
        prepare_ruff(root)
    else:
        build_pair(root, a.input.resolve())


if __name__ == "__main__":
    main()
