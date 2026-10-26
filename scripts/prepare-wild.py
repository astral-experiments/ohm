#!/usr/bin/env python3
"""Fetch the checksum-pinned Wild payload used by a Linux release."""

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
PATCH_DIRECTORY = pathlib.Path(__file__).resolve().parents[1] / "release" / "wild-patches"


def fetch_archive(url, checksum):
    with urllib.request.urlopen(url, timeout=120) as response:
        payload = response.read()
    if hashlib.sha256(payload).hexdigest() != checksum:
        raise ValueError("Wild archive checksum mismatch")
    return payload


def build_source(source, version, checksum, destination):
    revision = source["revision"]
    builder = source["builder_sha256"]
    binary = source["binary_sha256"]
    patch = source.get("patch_sha256")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("invalid Wild source revision")
    if not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in (builder, binary)):
        raise ValueError("invalid Wild build digest")
    if patch is not None and not re.fullmatch(r"[0-9a-f]{64}", patch):
        raise ValueError("invalid Wild patch digest")

    payload = fetch_archive(f"https://codeload.github.com/wild-linker/wild/tar.gz/{revision}", checksum)
    destination = pathlib.Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        work = pathlib.Path(temporary)
        (work / "source.tar.gz").write_bytes(payload)
        if patch is not None:
            contents = (PATCH_DIRECTORY / f"{patch}.patch").read_bytes()
            if hashlib.sha256(contents).hexdigest() != patch:
                raise ValueError("Wild patch checksum mismatch")
            (work / "source.patch").write_bytes(contents)
        shutil.copyfile(pathlib.Path(__file__).with_name("build-wild.sh"), work / "build-wild.sh")
        subprocess.run([
            "docker", "run", "--rm", "--platform=linux/amd64", "--user", f"{os.getuid()}:{os.getgid()}",
            "--mount", f"type=bind,src={work},dst=/work", "--workdir=/work", "--env", "CARGO_HOME=/work/cargo",
            f"docker.io/library/rust@sha256:{builder}", "sh", "build-wild.sh",
        ], check=True, stdout=sys.stderr)
        staged = work / "wild"
        executable = staged / "wild"
        if hashlib.sha256(executable.read_bytes()).hexdigest() != binary:
            raise ValueError("Wild binary checksum mismatch")
        actual = subprocess.check_output([executable, "--version"], text=True)
        if not actual.startswith(f"Wild {version} "):
            raise ValueError(f"unexpected Wild version: {actual.strip()}")
        staged.rename(destination)
    return destination


def prepare(manifest, target, destination):
    wild = manifest.get("bundled_tools", {}).get("wild")
    if target != TARGET or wild is None:
        return None
    version = wild["version"]
    checksum = wild["sha256"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("invalid Wild version")
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("invalid Wild SHA-256")
    if "source" in wild:
        return build_source(wild["source"], version, checksum, destination)
    name = f"wild-linker-{version}-{TARGET}"
    url = f"https://github.com/wild-linker/wild/releases/download/{version}/{name}.tar.gz"
    payload = fetch_archive(url, checksum)

    destination = pathlib.Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
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
    if len(sys.argv) != 4:
        sys.exit("usage: prepare-wild.py MANIFEST TARGET DESTINATION")
    result = prepare(json.loads(pathlib.Path(sys.argv[1]).read_text()), *sys.argv[2:])
    if result is not None:
        print(result)
