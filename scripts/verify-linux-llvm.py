"""Check the packaged LLVM baseline or report the Linux toolchain’s glibc requirement."""

import argparse
import pathlib
import re
import shutil
import subprocess
import tarfile
import tempfile


def dependencies(info):
    """Require library names so the loader can search for them after installation."""
    names = []
    for line in info.splitlines():
        if "(NEEDED)" not in line:
            continue
        match = re.search(r"\[(.+)\]\s*$", line)
        if not match or "/" in match[1]:
            raise SystemExit(f"expected a library name in DT_NEEDED: {line.strip()}")
        names.append(match[1])
    return names


def required_library(needed, prefix):
    names = [name for name in needed if name.startswith(prefix)]
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


def minimum_glibc(members, headers, lib):
    """Find the newest glibc required by an installed tool or a library it loads."""
    tools = {"rustc", "rustdoc", "cargo", "cargo-clippy", "clippy-driver", "rustfmt", "cargo-fmt"}
    pending = {
        path
        for path in members
        if len(path.parts) == 4 and path.parts[2] == "bin" and path.name in tools
    }
    inspected = set()
    versions = []
    while pending:
        # Minimize seeks in the compressed archive. Ignore unused copies of libraries.
        path = min(pending, key=lambda name: members[name].offset)
        pending.remove(path)
        inspected.add(path)
        info = headers(path, "--dynamic", "--version-info")
        for name in dependencies(info):
            library = lib / name
            if library in members and library not in inspected:
                pending.add(library)
        # A missing WEAK version (e.g. pidfd_spawnp@GLIBC_2.39) does not prevent loading.
        for major, minor in re.findall(
            r"\bName: GLIBC_(\d+)\.(\d+)(?:\.\d+)*\s+Flags: none\b", info
        ):
            versions.append((int(major), int(minor)))
    if not versions:
        raise SystemExit("found no required glibc versions in the Linux toolchain")
    return ".".join(map(str, max(versions)))


def main(archive, readelf, *, report_minimum=False):
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

        if report_minimum:
            print(minimum_glibc(members, headers, lib))
            return

        needed = dependencies(headers(rustc, "--dynamic"))
        if not any(name.startswith("libLLVM") for name in needed):
            driver = required_library(needed, "librustc_driver")
            needed = dependencies(headers(lib / driver, "--dynamic"))
        llvm = required_library(needed, "libLLVM")
        check_library(headers(lib / llvm, "--dynamic", "--version-info"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum-glibc", action="store_true")
    parser.add_argument("archive")
    parser.add_argument("readelf")
    args = parser.parse_args()
    main(args.archive, args.readelf, report_minimum=args.minimum_glibc)
