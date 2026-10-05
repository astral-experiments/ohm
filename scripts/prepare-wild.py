#!/usr/bin/env python3
"""Prepare checksum-pinned or source-pinned Wild for a Linux release."""

import argparse
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

TARGET = "x86_64-unknown-linux-gnu"
FILES = ("wild", "LICENSE-APACHE", "LICENSE-MIT")
SOURCE_REPOSITORY = "https://github.com/astral-sh/ohm-wild"
COMPACT_CAPABILITY = "compact-artifacts-v1"
COMPACT_FORMAT = b"RCOBJ001\n"


def verify_source(wild, checkout):
    """Require the exact clean source tree shared by rustc and the bundled linker."""
    source = wild["source"]
    if source["repository"] != SOURCE_REPOSITORY:
        raise ValueError("invalid Wild source repository")
    if not re.fullmatch(r"[0-9a-f]{40}", source["revision"]) or source["revision"] == "0" * 40:
        raise ValueError("invalid Wild source revision")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", source["rust_toolchain"]):
        raise ValueError("invalid Wild build toolchain")
    if checkout is None:
        raise ValueError("source-pinned Wild requires a source checkout")
    checkout = pathlib.Path(checkout).resolve()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(checkout), *args], text=True).strip()

    if git("rev-parse", "HEAD") != source["revision"]:
        raise ValueError("Wild source revision mismatch")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Wild source checkout is not clean")
    repository = git("remote", "get-url", "origin").removesuffix(".git")
    repository = repository.replace("git@github.com:", "https://github.com/")
    if repository != SOURCE_REPOSITORY:
        raise ValueError("Wild source checkout repository mismatch")
    if not (checkout / "compact-artifact/Cargo.toml").is_file():
        raise ValueError("Wild source checkout has no shared compact-artifact crate")
    return checkout


def build_source(wild, checkout, destination):
    checkout = verify_source(wild, checkout)
    source = wild["source"]
    build_directory = destination.parent / f".{destination.name}-build"
    cargo = ["rustup", "run", source["rust_toolchain"], "cargo"]
    environment = os.environ.copy()
    for name in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER"):
        environment.pop(name, None)
    environment["CARGO_INCREMENTAL"] = "0"
    subprocess.run(
        [*cargo, "build", "--locked", "--release", "--target", TARGET,
         "--package", "wild-linker", "--bin", "wild", "--target-dir", str(build_directory)],
        cwd=checkout, env=environment, check=True, stdout=sys.stderr,
    )
    # Cargo must neither update the lockfile nor alter the crate rustc will compile.
    verify_source(wild, checkout)
    executable = build_directory / TARGET / "release/wild"
    if not executable.is_file() or executable.is_symlink():
        raise ValueError("missing or unsafe built Wild executable")
    version = subprocess.check_output([str(executable), "--version"], text=True).strip()
    expected = f"Wild {wild['version']}"
    if version != expected and not version.startswith(expected + " "):
        raise ValueError("built Wild version mismatch")
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staged = pathlib.Path(temporary) / "wild"
        staged.mkdir()
        for name in FILES:
            origin = executable if name == "wild" else checkout / name
            if not origin.is_file() or origin.is_symlink():
                raise ValueError(f"missing or unsafe Wild source payload: {name}")
            shutil.copyfile(origin, staged / name)
            (staged / name).chmod(0o755 if name == "wild" else 0o644)
        (staged / COMPACT_CAPABILITY).write_bytes(COMPACT_FORMAT)
        provenance = {
            "binary_sha256": hashlib.sha256((staged / "wild").read_bytes()).hexdigest(),
            "rustc_version": subprocess.check_output(
                ["rustup", "run", source["rust_toolchain"], "rustc", "-vV"], text=True,
            ).strip(),
            "cargo_version": subprocess.check_output([*cargo, "-V"], text=True).strip(),
        }
        (staged / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        staged.rename(destination)
    return destination


def prepare(manifest, target, destination, source_checkout=None):
    wild = manifest.get("bundled_tools", {}).get("wild")
    if target != TARGET or wild is None:
        return None
    version = wild["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("invalid Wild version")
    destination = pathlib.Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Wild destination already exists: {destination}")
    if "source" in wild:
        if "sha256" in wild:
            raise ValueError("Wild cannot pin both source and archive")
        return build_source(wild, source_checkout, destination)
    checksum = wild["sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("invalid Wild SHA-256")
    name = f"wild-linker-{version}-{TARGET}"
    url = f"https://github.com/wild-linker/wild/releases/download/{version}/{name}.tar.gz"
    with urllib.request.urlopen(url, timeout=120) as response:
        payload = response.read()
    if hashlib.sha256(payload).hexdigest() != checksum:
        raise ValueError("Wild archive checksum mismatch")

    # Extract only the expected regular files; do not follow archive links or
    # interpret paths supplied by the archive as filesystem destinations.
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staged = pathlib.Path(temporary) / "wild"
        staged.mkdir()
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            members = archive.getmembers()
            for filename in FILES:
                matches = [m for m in members if m.name == f"{name}/{filename}"]
                if len(matches) != 1 or not matches[0].isfile():
                    raise ValueError(f"missing or unsafe Wild archive member: {filename}")
                with archive.extractfile(matches[0]) as source:
                    with (staged / filename).open("wb") as output:
                        shutil.copyfileobj(source, output)
                (staged / filename).chmod(0o755 if filename == "wild" else 0o644)
        # Fail on an existing destination instead of reusing unverified bytes.
        staged.rename(destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=pathlib.Path)
    parser.add_argument("target", nargs="?")
    parser.add_argument("destination", nargs="?")
    parser.add_argument("--source-checkout", type=pathlib.Path)
    parser.add_argument("--verify-source", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if args.verify_source:
        verify_source(manifest["bundled_tools"]["wild"], args.source_checkout)
    elif args.target is None or args.destination is None:
        parser.error("TARGET and DESTINATION are required unless --verify-source is used")
    else:
        result = prepare(manifest, args.target, args.destination, args.source_checkout)
        if result is not None:
            print(result)
