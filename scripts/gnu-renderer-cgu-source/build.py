"""Rebuild three native SDKs at one path, qualify the original placement signals and seal one common SDK."""

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source import (
    HERE,
    BASE,
    SIGNED,
    FORWARD_TEST,
    CALLABLE_TEST,
    FTEST,
    KTEST,
    git,
    need,
    obj,
    reconstruct,
)
from cargo import HASH as CARGO_HASH

HOST = "x86_64-unknown-linux-gnu"
ROOT = Path("/tmp/ohm-gnu-renderer-source-native")
WILD = Path("lib/rustlib") / HOST / "bin/wild-ld/ld.bfd"
WILD_HASH = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
SIGNED_CARGO = "4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e"
LLVM = "fba1b05a7bd8bdc73080edd02f672cef44648267"
BOR = "b940084d7eb6a299eb4bfeb8e34901bc051e7ac4"
STAGE0 = {
    "source": "759b73eca37a7b589b1ecc0fea77d94a1f8ca36cddb94f1401c72343e0dc1d4e",
    "rustc": "3690cc576ede140504698405d5d8fa3826aaadbe71699c6c4ed0a565d6f493e2",
    "cargo": "ff3022fcbd13b08434ea7afde9a0ef9d5b3f5c17b5fc7a40031be3ee000a6a24",
}
OPTIONS = [
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
HOST_FLAGS = ["--stage", "1", "-j8", "--host", HOST, "--target", HOST]
SDK_COMPONENTS = ["compiler/rustc", "library", "src/tools/rustdoc"]
BASE_CONTROLS = ("caller-local-codegen", "ohm-split-large-cgus")


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def log_run(argv, cwd, log, env=None):
    start = time.monotonic()
    with log.open("xb") as fd:
        rc = subprocess.run(
            ["/usr/bin/time", "-v", "-o", str(log) + ".resource", *map(str, argv)],
            cwd=cwd,
            env=env,
            stdout=fd,
            stderr=subprocess.STDOUT,
        ).returncode
    write(
        log.with_suffix(".command.json"),
        dict(
            argv=list(map(str, argv)),
            cwd=str(cwd),
            returncode=rc,
            elapsed_seconds=time.monotonic() - start,
            free_bytes=shutil.disk_usage(cwd).free,
            output_sha256=sha(log),
        ),
    )
    return rc


def succeeded(args, repo, log, env=None):
    rc = log_run(args, repo, log, env)
    if rc:
        print(log.read_text(errors="replace")[-9500:], flush=True)
    need(rc == 0, "failed command: " + str(log))


def verdict(log, name, success, rc):
    log = re.sub(r"\x1b\[[0-9;]*m", "", log)
    need(log.splitlines().count("running 1 tests") == 1, "expected one registered run-make test")
    pre = "test [run-make] tests/run-make/" + name + " ... "
    names = [line for line in log.splitlines() if line.startswith("test [run-make] ")]
    if success:
        need(
            rc == 0
            and names == [pre + "ok"]
            and re.search(r"test result: ok\. 1 passed; 0 failed; 0 ignored;", log)
            and "internal compiler error" not in log,
            "missing named native pass for " + name,
        )
    else:
        need(
            rc == 1
            and names == [pre + "FAILED"]
            and re.search(r"test result: FAILED\. 0 passed; 1 failed; 0 ignored;", log),
            "missing named failing test for " + name,
        )
        need(
            "error[E" not in log and "internal compiler error" not in log,
            "compiler/fixture build failed before placement",
        )
        if name == FORWARD_TEST:
            need(
                name + "/rmake.rs:37:" in log
                and re.search(
                    r"<&Derived as std::fmt::Debug>::fmt: forwarders\.[0-9a-f]{16}\.volatile\[External\]",
                    log,
                )
                and "left: false" in log
                and "right: true" in log,
                "wrong initial derived placement",
            )
        else:
            need(
                name + "/rmake.rs:41:" in log and re.search(r"(?m)^fixture\.[0-9a-f]{16}\s*$", log),
                "wrong initial callable owner",
            )


def collect(stage, root):
    native = stage / "lib/rustlib" / HOST
    paths = [stage / "bin/rustc", stage / "bin/rustdoc", *sorted((stage / "lib").glob("*.so*"))]
    for directory in (stage / "bin", native / "lib", native / "bin"):
        paths.extend(p for p in directory.rglob("*") if p.is_file())
    selected = {p.relative_to(stage): p for p in paths}
    need(
        all(
            p.is_file() and p.resolve().is_relative_to((stage.parents[1]).resolve())
            for p in selected.values()
        ),
        "missing or foreign stage product",
    )
    selected[Path("bin/cargo")] = root / "cargo/cargo-301"
    selected[WILD] = root / "packages/sdk-21" / WILD
    for prefix in ("core", "alloc", "std", "test", "proc_macro", "panic_unwind"):
        need(
            any(p.name.startswith("lib" + prefix + "-") and p.suffix == ".rlib" for p in selected),
            "incomplete host standard library " + prefix,
        )
    need(any(p.name.startswith("libLLVM") for p in selected), "no LLVM")
    need(any(p.name == "rust-lld" for p in selected), "missing host linker")
    return selected


def manifest(selected):
    return {
        str(k): [sha(p), p.stat().st_size, p.stat().st_mode & 0o777] for k, p in sorted(selected.items())
    }


def archive(selected, out):
    with subprocess.Popen(["zstd", "-q", "-T3", "-3", "-o", out], stdin=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdin, mode="w|", dereference=True) as tar:
            for key, p in sorted(selected.items()):
                tar.add(p, arcname=str(key), recursive=False)
        proc.stdin.close()
        need(proc.wait() == 0, "SDK compression failed")


ENTRYPOINTS = {
    "x": "768ed1674641e020c4fb9985d53c197ca5bf3e16",
    "x.py": "928a7496cb70ef2a6caf8e890fb09f12883a26e3",
}


def launcher(repo):
    for name, oid in ENTRYPOINTS.items():
        row = git(repo, "ls-tree", "HEAD", "--", name).decode().strip()
        need(
            row == f"100755 blob {oid}\t{name}"
            and os.access(repo / name, os.X_OK)
            and git(repo, "hash-object", name).decode().strip() == oid,
            "wrong checked-in native bootstrap entrypoint: " + name,
        )
    # The checked-in Linux launcher searches PATH for python3 before every other interpreter.
    interpreter = shutil.which("python3")
    need(
        interpreter
        and os.path.samefile(interpreter, sys.executable)
        and sys.version_info[:2] == (3, 13)
        and not os.environ.get("OSTYPE", "").startswith(("cygwin", "msys")),
        "./x would not select the pinned Python 3.13",
    )
    return {
        "blobs": ENTRYPOINTS,
        "python": interpreter,
        "python_version": sys.version,
        "python_sha256": sha(Path(interpreter)),
    }


def check_source(repo, head):
    need(
        obj(repo, "HEAD") == head and not git(repo, "status", "--porcelain=v1", "--untracked-files=no"),
        "dirty or wrong native source",
    )
    usr = (
        git(repo, "rev-list", "--author-date-order", "--author=bors@rust-lang\\.org", "-n1", "HEAD")
        .decode()
        .strip()
    )
    llvm = (
        git(
            repo,
            "rev-list",
            "--first-parent",
            "-n1",
            usr,
            "--author=bors@rust-lang\\.org",
            "--",
            "src/llvm-project",
            "src/bootstrap/download-ci-llvm-stamp",
            "src/version",
        )
        .decode()
        .strip()
    )
    need(
        usr == BOR
        and llvm == LLVM
        and not git(
            repo,
            "diff",
            "--stat",
            llvm,
            "HEAD",
            "--",
            "src/llvm-project",
            "src/bootstrap/download-ci-llvm-stamp",
            "src/version",
        ),
        "LLVM inputs changed",
    )
    need(
        obj(repo / "library/backtrace", "HEAD") == "d902726a1dcdc1e1c66f73d1162181b5423c645b",
        "backtrace source differs",
    )


def product_tests(repo, combined, role, log):
    inserted = []
    try:
        for f in sorted(FTEST | KTEST):
            path = repo / f
            data = git(repo, "show", combined + ":" + f)
            if path.exists():
                need(path.read_bytes() == data, "unchecked fixture")
            else:
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(data)
                inserted.append((path, data))
        for test in (*BASE_CONTROLS, FORWARD_TEST, CALLABLE_TEST):
            expect = test in BASE_CONTROLS or role == "C" or (role == "F" and test == FORWARD_TEST)
            path = log / (test + ".log")
            args = [
                "./x",
                *OPTIONS,
                "--set",
                "rust.verbose-tests=true",
                "test",
                *HOST_FLAGS,
                "tests/run-make/" + test,
            ]
            rc = log_run(args, repo, path)
            out = path.read_text(errors="replace")
            try:
                verdict(out, test, expect, rc)
            except ValueError:
                print(out[-12000:], flush=True)
                raise
    finally:
        for path, data in inserted:
            need(path.read_bytes() == data, "test changed borrowed source")
            path.unlink()
        for d in {p.parent for p, _ in inserted}:
            if not any(d.iterdir()):
                d.rmdir()


def operational(root, stage, selected, role, log):
    sdk = root / "operational"
    need(not sdk.exists(), "previous SDK still active")
    sdk.mkdir()
    for key, p in selected.items():
        dest = sdk / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.link(p.resolve(), dest)
    home = root / "rustup"
    tools = home / "toolchains"
    tools.mkdir(parents=True, exist_ok=True)
    alias = tools / "ohm"
    if not alias.exists():
        alias.symlink_to(sdk, target_is_directory=True)
    need(alias.resolve() == sdk, "wrong operational Rustup binding")
    # Ordinary Cargo, Rustc and Rustdoc exercise the same complete installation used for later Ruff.
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in (
            "RUSTFLAGS",
            "RUSTDOCFLAGS",
            "RUSTC",
            "RUSTDOC",
            "RUSTC_WRAPPER",
            "RUSTUP_TOOLCHAIN",
            "RUSTC_WORKSPACE_WRAPPER",
        )
        and not k.startswith("CARGO_")
    }
    env.update(
        RUSTUP_HOME=str(home),
        CARGO_HOME=str(root / "cargo-home"),
        CARGO_TARGET_DIR=str(root / "smoke-target"),
        CARGO_BUILD_BUILD_DIR=str(root / "smoke-shared"),
    )
    work = root / "std-consumer"
    work.mkdir(exist_ok=True)
    (work / "Cargo.toml").write_text('[package]\nname="qa_cgu_std"\nversion="0.0.0"\nedition="2024"\n')
    (work / "src").mkdir(exist_ok=True)
    (work / "src/main.rs").write_text(
        '#[derive(Clone, Debug)] struct Witness(String);\nfn main(){let v=Witness(String::from("native")); println!("{}",v.clone().0);}\n#[test] fn native_case(){assert_eq!(Witness(String::from("test")).clone().0,"test");}\n'
    )
    for name, args in [
        ("rustc", ["rustc", "+ohm", "-vV"]),
        ("rustdoc", ["rustdoc", "+ohm", "-vV"]),
        ("cargo", ["cargo", "+ohm", "-Vv"]),
        ("sysroot", ["rustc", "+ohm", "--print", "sysroot"]),
        ("libs", ["rustc", "+ohm", "--print", "target-libdir"]),
        ("build", ["cargo", "+ohm", "build", "--offline", "--message-format=json"]),
        ("test", ["cargo", "+ohm", "test", "--no-run", "--offline", "--message-format=json"]),
    ]:
        if name in ("build", "test"):
            trace_dir = log / (name + "-execs")
            trace_dir.mkdir()
            args = [
                "strace",
                "-ff",
                "-qq",
                "-s",
                "8192",
                "-e",
                "trace=execve,execveat",
                "-o",
                trace_dir / "trace",
                *args,
            ]
        succeeded(args, work, log / (name + ".log"), env)
        if name in ("build", "test"):
            seen = []
            for path in trace_dir.glob("trace.*"):
                for line in path.read_text(errors="replace").splitlines():
                    match = re.match(r'^execve\("([^"]+)",.*= 0$', line)
                    if not match:
                        continue
                    exe = Path(match[1])
                    if exe.is_absolute() and exe.is_file() and exe.resolve() == (sdk / WILD).resolve():
                        seen.append(
                            {"pid": path.name.split(".")[-1], "path": str(exe), "sha256": sha(exe)}
                        )
            need(
                seen and all(item["sha256"] == WILD_HASH for item in seen),
                "native Cargo did not execute the physical stock Wild",
            )
            write(log / (name + "-linkers.json"), seen)
    need(Path((log / "sysroot.log").read_text().strip()).resolve() == sdk, "Rustup selected other SDK")
    need(
        Path((log / "libs.log").read_text().strip()).resolve()
        == (sdk / "lib/rustlib" / HOST / "lib").resolve(),
        "wrong target std",
    )
    for name in ("build", "test"):
        rows = [
            json.loads(line)
            for line in (log / (name + ".log")).read_text().splitlines()
            if line.startswith("{")
        ]
        need(rows[-1] == {"reason": "build-finished", "success": True}, "Cargo terminal verdict")
        exes = {r["executable"] for r in rows if r.get("executable")}
        need(len(exes) == 1, "wrong physical Cargo output")
        exe = Path(exes.pop())
        args = [exe] if name == "build" else [exe, "--list"]
        succeeded(args, work, log / (name + "-exec.log"), env)
        need(
            (log / (name + "-exec.log"))
            .read_text()
            .startswith("native\n" if name == "build" else "native_case: test\n"),
            "std binary or test inventory differs",
        )
    src = work / "donor.rs"
    src.write_text('pub fn value()->String { String::from("cross-stage1") }\n')
    donor = root / "libqa_donor.rlib"
    if role == "P":
        succeeded(
            ["rustc", "+ohm", src, "--crate-name", "qa_donor", "--crate-type", "rlib", "-o", donor],
            work,
            log / "donor.log",
            env,
        )
    (work / "receiver.rs").write_text(
        'extern crate qa_donor; fn main(){println!("{}",qa_donor::value())}\n'
    )
    succeeded(
        [
            "rustc",
            "+ohm",
            work / "receiver.rs",
            "--extern",
            "qa_donor=" + str(donor),
            "-o",
            work / "receiver",
        ],
        work,
        log / "receiver.log",
        env,
    )
    succeeded([work / "receiver"], work, log / "receiver-exec.log", env)
    need((log / "receiver-exec.log").read_text() == "cross-stage1\n", "parent metadata consumer changed")
    if role == "P":
        # Retail and stage1 can share source while differing in the version stamp in crate metadata.
        signed = root / "packages/sdk-21"
        shipped = [signed / "bin/rustc", "--sysroot", signed]
        old = root / "libqa_signed_donor.rlib"
        succeeded([*shipped, "-vV"], work, log / "signed-rustc.log", env)
        succeeded(
            [*shipped, src, "--crate-name", "qa_donor", "--crate-type", "rlib", "-o", old],
            work,
            log / "signed-donor.log",
            env,
        )
        out = {}
        for label, cmd, held in [
            ("signed-to-stage", ["rustc", "+ohm"], old),
            ("stage-to-signed", shipped, donor),
        ]:
            receipt = log / (label + ".log")
            rc = log_run(
                [
                    *cmd,
                    work / "receiver.rs",
                    "--extern",
                    "qa_donor=" + str(held),
                    "-o",
                    work / (label + "-receiver"),
                ],
                work,
                receipt,
                env,
            )
            if rc == 0:
                succeeded([work / (label + "-receiver")], work, log / (label + "-exec.log"), env)
                need(
                    (log / (label + "-exec.log")).read_text() == "cross-stage1\n",
                    "wrong cross-SDK native output",
                )
            else:
                reason = receipt.read_text(errors="replace")
                need(
                    rc == 1 and "error[E0514]" in reason and "internal compiler error" not in reason,
                    "unexpected signed/stage interoperability failure",
                )
            out[label] = {"rustc": rc, "diagnostic_sha256": sha(receipt), "rlib_sha256": sha(held)}
        write(log / "signed-vs-stage-metadata.json", out)
    for name in ("operational", "smoke-target", "smoke-shared"):
        path = root / name
        if path.exists():
            need(path.parent == ROOT and not path.is_symlink(), "unexpected scratch path")
            shutil.rmtree(path)


def main(root):
    need(
        root == ROOT
        and root.is_dir()
        and not root.is_symlink()
        and platform.system() == "Linux"
        and platform.machine() == "x86_64",
        "wrong host or scratch root",
    )
    need(shutil.disk_usage(root).free > 32 * 2**30, "need 32 GiB free")
    mem = next(
        int(l.split()[1])
        for l in Path("/proc/meminfo").read_text().splitlines()
        if l.startswith("MemAvailable:")
    )
    need(mem > 6 * 2**20, "need 6 GiB RAM")
    repo = root / "rust"
    rec = root / "receipts"
    transfer = root / "transfer"
    transfer.mkdir()
    roles = reconstruct(repo, HERE / "packet", True)
    signed = root / "packages/sdk-21"
    need(
        sha(signed / "bin/cargo") == SIGNED_CARGO
        and sha(signed / WILD) == WILD_HASH
        and sha(root / "cargo/cargo-301") == CARGO_HASH,
        "wrong signed tool or #301",
    )
    write(
        rec / "signed-tools.json",
        {
            str(k): [sha(signed / k), (signed / k).stat().st_size]
            for k in (
                Path("bin/cargo"),
                Path("bin/rustc"),
                Path("bin/rustdoc"),
                WILD,
                *[p.relative_to(signed) for p in (signed / "lib").glob("librustc_driver*.so")],
            )
        },
    )
    sources = roles
    expected = None
    driver_key = None
    drivers = {}
    vvs = []
    received = {}
    for role in ("P", "F", "C"):
        head = sources[role]["commit"]
        log = rec / role
        log.mkdir()
        need(not (repo / "build").exists(), "stale bootstrap products")
        git(repo, "checkout", "--detach", head)
        check_source(repo, head)
        write(
            log / "source.json",
            dict(
                sources[role],
                qa=os.environ["GITHUB_SHA"],
                run=os.environ["GITHUB_RUN_ID"],
                attempt=os.environ["GITHUB_RUN_ATTEMPT"],
                llvm=LLVM,
                stage0=STAGE0,
                launcher=launcher(repo),
                base_path=str(repo),
                role=role,
                signed_provenance=SIGNED,
                review_base=BASE,
            ),
        )
        # Each bootstrap process creates a new stage sysroot with only the components it requests.
        sdk_build = ["./x", *OPTIONS, "build", *HOST_FLAGS, *SDK_COMPONENTS]
        succeeded(sdk_build, repo, log / "bootstrap.log")
        stage = repo / "build" / HOST / "stage1"
        bootstrap = stage.parent / "stage0/bin"
        found = {
            "source": sha(repo / "src/stage0"),
            **{k: sha(bootstrap / k) for k in ("rustc", "cargo")},
        }
        need(found == STAGE0, "stage0 replacement")
        selected = collect(stage, root)
        before = manifest(selected)
        write(log / "physical-files-before-tests.json", before)
        product_tests(repo, sources["C"]["commit"], role, log)
        remaining = manifest({key: path for key, path in selected.items() if path.is_file()})
        write(log / "physical-files-after-tests.json", remaining)
        need(
            all(before[name] == row for name, row in remaining.items()),
            "native tests changed a retained SDK file",
        )
        succeeded(sdk_build, repo, log / "reassemble.log")
        selected = collect(stage, root)
        actual = manifest(selected)
        write(log / "physical-files.json", actual)
        need(before == actual, "building checked-in regression changed installed native runtime")
        (driver,) = [n for n in actual if n.startswith("lib/librustc_driver") and n.endswith(".so")]
        if expected is None:
            expected = actual
            driver_key = driver
            archive(selected, transfer / "P-sdk.tar.zst")
        else:
            differences = {
                n: [expected.get(n), actual.get(n)]
                for n in sorted(set(expected) | set(actual))
                if n != driver_key and expected.get(n) != actual.get(n)
            }
            write(log / "non-driver-comparison.json", differences)
            if differences:
                # Preserve original complete P SDK and bounded full differing arm bytes even on red.
                keep = {}
                total = 0
                for name in differences:
                    p = selected.get(Path(name))
                    if p and p.stat().st_size + total <= 128 * 2**20:
                        keep[Path(name)] = p
                        total += p.stat().st_size
                if keep:
                    archive(keep, log / "differing-non-driver.tar.zst")
            need(driver == driver_key and not differences, "a non-driver source SDK member differs")
            output = transfer / ("driver-" + role + ".zst")
            succeeded(
                ["zstd", "-q", "-T2", "-3", selected[Path(driver)], "-o", output],
                repo,
                log / "compress-driver.log",
            )
        drivers[role] = actual[driver][0]
        need(
            len(set(drivers.values())) == len(drivers),
            "different source role returned the same physical driver",
        )
        operational(root, stage, selected, role, log)
        vvs.append((log / "rustc.log").read_bytes())
        need(all(v == vvs[0] for v in vvs), "stage1 complete verbose version changed")
        need(manifest(collect(stage, root)) == actual, "ordinary SDK use changed installed native files")
        check_source(repo, head)
        # Wipe only the hosted, private build after its fresh members and native controls are sealed.
        dir = repo / "build"
        need(
            dir.resolve() == ROOT / "rust/build"
            and not dir.is_symlink()
            and repo.resolve() == ROOT / "rust",
            "unsafe bootstrap scratch cleanup",
        )
        shutil.rmtree(dir)
        received[role] = {
            "source": sources[role],
            "driver": actual[driver],
            "manifest_sha256": sha(log / "physical-files.json"),
        }
    products = {str(f.name): [sha(f), f.stat().st_size] for f in transfer.iterdir() if f.is_file()}
    result = {
        "qa": os.environ["GITHUB_SHA"],
        "run": os.environ["GITHUB_RUN_ID"],
        "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "roles": received,
        "common_member_count": len(expected) - 1,
        "driver": driver_key,
        "files": expected,
        "products": products,
        "signed_cargo": SIGNED_CARGO,
        "operative_cargo": CARGO_HASH,
        "native_linker": WILD_HASH,
        "compiler_verbose": vvs[0].decode(),
        "review_base": BASE,
        "signed_provenance": SIGNED,
    }
    write(transfer / "manifest.json", result)
    # Reopen every complete official transfer using the actual downstream reader before admission.
    from restore import restore

    for role in ("P", "F", "C"):
        view = root / "reopened"
        restore(transfer, view, role, result["qa"], result["run"], result["attempt"])
        check = rec / role / "restored-rustc.log"
        succeeded([view / "bin/rustc", "-vV"], repo, check)
        need(check.read_bytes() == vvs[0], "restored native compiler differs")
        need(view.parent == ROOT and not view.is_symlink(), "unexpected transfer view")
        shutil.rmtree(view)
    write(rec / "complete.json", result)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
