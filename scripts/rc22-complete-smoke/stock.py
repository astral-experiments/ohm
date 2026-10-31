"""Use the upstream release analyzer, independently verifying its executable."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media import CFG, locations, need, save, sha


def compare_binary(archive, installed, target):
    reg = CFG["targets"][target]["analyzer"]
    need(sha(archive) == reg["xz_hash"], "different rust-analyzer release archive")
    member = f"rust-analyzer-1.99.0-{target}/rust-analyzer-preview/bin/rust-analyzer"
    with tarfile.open(archive, "r|xz") as t:
        seen = []
        for m in t:
            if m.name == member:
                need(m.isreg(), "not stock rust-analyzer's regular file")
                seen.append((m.size, hashlib.file_digest(t.extractfile(m), "sha256").hexdigest()))
    need(
        seen == [(installed.stat().st_size, sha(installed))],
        "installed stock analyzer differs from official component",
    )
    return {
        "archive_sha256": reg["xz_hash"],
        "member": member,
        "binary_sha256": seen[0][1],
        "binary_bytes": seen[0][0],
    }


def main():
    root, target = locations()
    home = root / "stock"
    home.mkdir(mode=0o700)
    base = "https://static.rust-lang.org/dist/"
    url = base + "channel-rust-1.99.0.toml"

    def fetch(url, dest):
        subprocess.run(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--retry",
                "2",
                "--proto",
                "=https",
                "--tlsv1.2",
                "--max-time",
                "120",
                url,
                "-o",
                dest,
            ],
            check=True,
        )

    channel = home / "official.toml"
    fetch(url, channel)
    need(sha(channel) == CFG["upstream"]["channel_sha256"], "upstream release channel changed")
    source = tomllib.loads(channel.read_text())
    row = source["pkg"]["rust-analyzer-preview"]["target"][target]
    spec = CFG["targets"][target]["analyzer"]
    need(
        all(spec[k] == row[k] for k in ("xz_url", "xz_hash"))
        and source["date"] == CFG["upstream"]["channel_date"],
        "wrong upstream release",
    )
    archive = home / "analyzer.tar.xz"
    fetch(spec["xz_url"], archive)
    env = {
        k: os.environ[k]
        for k in ("HOME", "PATH", "TMPDIR", "DEVELOPER_DIR", "SDKROOT", "LANG")
        if k in os.environ
    }
    env.update(
        RUSTUP_HOME=str(home / "rustup"),
        CARGO_HOME=str(home / "cargo"),
        RUSTUP_DIST_SERVER="https://static.rust-lang.org",
        RUSTUP_AUTO_INSTALL="0",
    )
    subprocess.run(
        [
            "rustup",
            "toolchain",
            "install",
            "1.99.0",
            "--profile",
            "minimal",
            "--component",
            "rust-analyzer",
            "--no-self-update",
        ],
        env=env,
        check=True,
    )

    def which(n):
        return Path(
            subprocess.check_output(
                ["rustup", "which", "--toolchain", "1.99.0", n], env=env, text=True
            ).strip()
        ).resolve(strict=True)

    ra = which("rust-analyzer")
    need(ra.is_relative_to(home), "stock analyzer outside private install")
    rust = subprocess.check_output([which("rustc"), "-vV"], env=env, text=True)
    need(
        "commit-hash: " + source["pkg"]["rustc"]["git_commit_hash"] + "\n" in rust
        and "host: " + target + "\n" in rust,
        "wrong upstream rustc",
    )
    proof = compare_binary(archive, ra, target)
    with (root / "stock-analyzer.path").open("x") as f:
        f.write(str(ra) + "\n")
    save(
        root / "receipts/upstream.json",
        proof
        | {
            "source": url,
            "channel_sha256": sha(channel),
            "rustc": rust,
            "version": subprocess.check_output([ra, "--version"], env=env, text=True).strip(),
        },
    )


if __name__ == "__main__":
    main()
