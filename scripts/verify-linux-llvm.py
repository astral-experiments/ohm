"""Check that the packaged LLVM library can load on Rust's supported glibc baseline."""

import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


def dependencies(info):
    return re.findall(r"\(NEEDED\).*?\[([^]]+)\]", info)


def required_library(needed, prefix):
    names = [name for name in needed if name.startswith(prefix) and "/" not in name]
    if len(names) != 1:
        raise SystemExit(f"expected one {prefix} dependency, found {names}")
    return names[0]


def check_library(info):
    needed = dependencies(info)
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
    with tarfile.open(archive, "r:gz") as tar:
        # Extraction installs the last entry for each path.
        members = {pathlib.PurePosixPath(member.name): member for member in tar}
        launchers = [path for path in members if path.parts[1:] == ("rustc", "bin", "rustc")]
        if len(launchers) != 1:
            raise SystemExit("expected one packaged rustc executable")
        rustc = launchers[0]
        lib = rustc.parent.parent / "lib"

        def headers(path, *sections):
            try:
                data = tar.extractfile(members[path])
            except KeyError:
                raise SystemExit(f"missing packaged file: {path}") from None
            if data is None:
                raise SystemExit(f"expected a packaged file: {path}")
            with data, tempfile.NamedTemporaryFile() as file:
                shutil.copyfileobj(data, file)
                file.flush()
                return subprocess.check_output([readelf, "--wide", *sections, file.name], text=True)

        needed = dependencies(headers(rustc, "--dynamic"))
        if not any(name.startswith("libLLVM") for name in needed):
            driver = required_library(needed, "librustc_driver")
            needed = dependencies(headers(lib / driver, "--dynamic"))
        llvm = required_library(needed, "libLLVM")
        check_library(headers(lib / llvm, "--dynamic", "--version-info"))


if __name__ == "__main__":
    main(*sys.argv[1:])
