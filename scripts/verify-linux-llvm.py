"""Check that the packaged LLVM library can load on Rust's supported glibc baseline."""

import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


def check_library(readelf, library):
    info = subprocess.check_output(
        [readelf, "--wide", "--dynamic", "--version-info", library], text=True
    )
    needed = re.findall(r"\(NEEDED\).*?\[([^]]+)\]", info)
    if any(name.startswith(("libstdc++.", "libzstd.")) for name in needed):
        raise SystemExit(f"LLVM has an unexpected dynamic dependency: {needed}")

    versions = re.findall(r"\bName: GLIBC_([\w.]+)", info)
    if not versions or any(not re.fullmatch(r"\d+(?:\.\d+)+", version) for version in versions):
        raise SystemExit(f"unexpected LLVM glibc requirements: {versions}")
    maximum = max(tuple(map(int, version.split("."))) for version in versions)
    if maximum > (2, 17):
        raise SystemExit(f"LLVM requires glibc {maximum}, above the glibc 2.17 baseline")
    print("Packaged LLVM requires glibc", ".".join(map(str, maximum)), "and", ", ".join(needed))


def main(archive, readelf):
    with tarfile.open(archive, "r|gz") as tar:
        for member in tar:
            path = pathlib.PurePosixPath(member.name)
            if not member.isfile() or path.parts[1:-1] != ("rustc", "lib"):
                continue
            if path.name.startswith("libLLVM.so"):
                with tempfile.NamedTemporaryFile() as library:
                    shutil.copyfileobj(tar.extractfile(member), library)
                    library.flush()
                    check_library(readelf, library.name)
                return
    raise SystemExit("packaged rustc does not contain its LLVM shared library")


if __name__ == "__main__":
    main(*sys.argv[1:])
