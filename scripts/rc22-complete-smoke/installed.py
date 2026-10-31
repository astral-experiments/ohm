"""Verify installed component bytes, and keep the optional Cargo replacement explicit."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media import CFG, locations, need, save, sha

TOOLS = {"cargo", "rustc", "rustdoc", "clippy-driver", "cargo-clippy", "rustfmt", "cargo-fmt"}


def catalog(root, target):
    tar = root / "release" / (CFG["release"] + "-" + target + ".tar.gz")
    need(sha(tar) == CFG["checksums"][tar.name], "wrong native tar")
    rows = {}
    with tarfile.open(tar, "r|gz", bufsize=1 << 20) as z:
        for m in z:
            parts = PurePosixPath(m.name).parts
            if len(parts) < 4 or not m.isreg():
                continue
            n = "/".join(parts[2:])
            if (
                n in {"bin/" + t for t in TOOLS}
                or n.startswith("lib/librustc_driver-")
                or n.startswith("lib/rustlib/" + target + "/lib/")
                or n.startswith("lib/rustlib/wasm32-unknown-unknown/lib/")
                or n
                in (
                    "lib/rustlib/src/rust/library/core/src/lib.rs",
                    "lib/rustlib/" + target + "/bin/rust-lld",
                    "lib/rustlib/" + target + "/bin/wild-ld/ld.bfd",
                )
            ):
                need(n not in rows, "duplicate installed component mapping")
                rows[n] = [m.size, hashlib.file_digest(z.extractfile(m), "sha256").hexdigest()]
    need(
        {"bin/" + t for t in TOOLS} <= rows.keys()
        and any(n.startswith("lib/librustc_driver-") for n in rows)
        and any(n.startswith("lib/rustlib/wasm32-unknown-unknown/lib/libstd-") for n in rows)
        and {"lib/rustlib/src/rust/library/core/src/lib.rs", "lib/rustlib/" + target + "/bin/rust-lld"}
        <= rows.keys(),
        "missing compiler, wasm std, rust-src, tools or host lld",
    )
    if target.startswith("x86_64"):
        need("lib/rustlib/" + target + "/bin/wild-ld/ld.bfd" in rows, "missing original Wild")
    save(root / "receipts/archive-binaries.json", rows)
    return rows


def replacement_digest(root, target, role):
    if role == "fourfix":
        return CFG["targets"][target]["fourfix_sha256"]
    need(role == "static-fourfix" and target == "x86_64-unknown-linux-gnu", "wrong static role")
    from static_cargo import verify_product

    return verify_product(root)["sha256"]


def inspect(root, target, prefix, role):
    rows = json.loads((root / "receipts/archive-binaries.json").read_bytes())
    observed = {}
    for name, (n, digest) in rows.items():
        f = prefix / name
        need(
            f.is_file() and not f.is_symlink() and f.resolve().is_relative_to(prefix.resolve()),
            "non-regular or external installed member",
        )
        got = sha(f)
        if role != "packaged" and name == "bin/cargo":
            need(got == replacement_digest(root, target, role), "different substitute Cargo")
        else:
            need(f.stat().st_size == n and got == digest, ("wrong installed archive bytes", name))
        observed[name] = got
    versions = {
        name: subprocess.check_output([prefix / "bin" / name, "-vV"], text=True)
        for name in ("rustc", "cargo")
    }
    for k, rev in [("rustc", CFG["rust"]), ("cargo", CFG["cargo"] if role == "packaged" else CFG["fourfix"])]:
        need(
            "commit-hash: " + rev + "\n" in versions[k] and "host: " + target + "\n" in versions[k],
            "unexpected installed version",
        )
    return {"actual": observed, "versions": versions, "role": role}


def main():
    root, target = locations()
    operation = sys.argv[1]
    if operation == "catalog":
        catalog(root, target)
        return
    prefix = Path(sys.argv[2])
    receipts = Path(os.environ["OHM_QA_RECEIPTS"])
    need(
        prefix.name == "toolchain"
        and prefix.is_dir()
        and not prefix.is_symlink()
        and prefix.resolve().is_relative_to((root / "sessions").resolve()),
        "wrong private disposable installation",
    )
    if operation == "swap":
        before = inspect(root, target, prefix, "packaged")
        save(receipts / "before-swap.json", before)
        role = os.environ["OHM_QA_ROLE"]
        src = root / ("static-cargo" if role == "static-fourfix" else "fourfix-cargo")
        need(sha(src) == replacement_digest(root, target, role), "unauthenticated Cargo")
        dest = prefix / "bin/cargo"
        tmp = dest.with_name("cargo.qa-replacement")
        with src.open("rb") as f, tmp.open("xb") as out:
            shutil.copyfileobj(f, out, 1 << 20)
        tmp.chmod(0o755)
        os.replace(tmp, dest)
        after = inspect(root, target, prefix, role)
        need(
            {k for k in before["actual"] if before["actual"][k] != after["actual"][k]} == {"bin/cargo"},
            "unexpected SDK change",
        )
        save(receipts / "after-swap.json", after)
    elif operation == "final":
        role = os.environ["OHM_QA_ROLE"]
        report = inspect(root, target, prefix, role)
        active = Path(
            subprocess.check_output(["rustc", "+" + CFG["release"], "--print", "sysroot"], text=True).strip()
        )
        need(active.samefile(prefix), "unexpected installed rustup selection")
        need(
            Path(
                subprocess.check_output(
                    ["rustup", "which", "--toolchain", CFG["release"], "cargo"], text=True
                ).strip()
            ).samefile(prefix / "bin/cargo"),
            "wrong active Cargo file",
        )
        save(receipts / "installed.json", report)
    else:
        raise SystemExit("wrong operation")


if __name__ == "__main__":
    main()
