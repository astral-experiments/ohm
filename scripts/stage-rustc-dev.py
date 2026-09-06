#!/usr/bin/env python3
"""Stage optional rustc-dev assets only when they match the final compiler archive."""

import argparse
import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path, PurePosixPath

# Installer files and licenses present in Rust's rustc-dev archive. Build
# configuration and source provenance files are deliberately not public.
INSTALLER_FILES = {
    "components",
    "install.sh",
    "rust-installer-version",
    "version",
    "COPYRIGHT",
    "LICENSE-APACHE",
    "LICENSE-MIT",
    "README.md",
}


def archive_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe archive member: {name}")
    return path


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def archive_driver(archive, prefix, suffix, *, development=False):
    drivers = []
    metadata = {"rustc_session": 0, "rustc_driver_impl": 0}
    driver_pattern = re.compile(r"librustc_driver(?:-[0-9a-f]+)?" + re.escape(suffix))
    with tarfile.open(archive, "r|gz") as entries:
        for entry in entries:
            path = archive_path(entry.name)
            if path.parent != prefix:
                continue
            if driver_pattern.fullmatch(path.name):
                if not entry.isfile():
                    raise ValueError(
                        f"compiler driver is not a regular archive member: {entry.name}"
                    )
                with entries.extractfile(entry) as source:
                    drivers.append(
                        (path.name, hashlib.file_digest(source, "sha256").hexdigest())
                    )
            elif development:
                for crate in metadata:
                    if re.fullmatch(r"lib" + crate + r"-[0-9a-f]+\.rmeta", path.name):
                        if not entry.isfile():
                            raise ValueError(
                                f"compiler metadata is not a regular archive member: {entry.name}"
                            )
                        metadata[crate] += 1
    if len(drivers) != 1:
        raise ValueError(
            f"expected one compiler driver in {archive}, found {len(drivers)}"
        )
    if development and any(count != 1 for count in metadata.values()):
        raise ValueError(
            f"missing or ambiguous compiler metadata in {archive}: {metadata}"
        )
    return drivers[0]


def metadata_archive(source, destination, prefix):
    """Keep target compiler libraries and regenerate their file ownership manifest."""
    root = prefix.parents[4]
    component = root / "rustc-dev"
    manifest = component / "manifest.in"
    files = []
    controls = set()
    retained = set()
    with (
        tarfile.open(source, "r|gz") as original,
        destination.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w|") as archive,
    ):
        for entry in original:
            path = archive_path(entry.name)
            if path == manifest:
                continue
            if path == prefix or prefix in path.parents:
                if entry.isfile():
                    files.append(str(path.relative_to(component)))
                elif not entry.isdir():
                    raise ValueError(
                        f"unsupported compiler library member: {entry.name}"
                    )
            elif path in prefix.parents:
                if not entry.isdir():
                    raise ValueError(
                        f"invalid compiler library directory: {entry.name}"
                    )
            elif (
                path.parent == root and path.name in INSTALLER_FILES and entry.isfile()
            ):
                controls.add(path.name)
            else:
                # rustc-dev also contains the private compiler source tree.
                # Only installer control files and target libraries are public.
                continue
            if entry.isfile():
                if path in retained:
                    raise ValueError(f"duplicate retained archive member: {entry.name}")
                retained.add(path)
            if path == root / "components":
                content = original.extractfile(entry).read()
                if content.strip() != b"rustc-dev":
                    raise ValueError("unexpected rustc-dev installer components")
                archive.addfile(entry, io.BytesIO(content))
            else:
                archive.addfile(
                    entry,
                    original.extractfile(entry) if entry.isfile() else None,
                )
        if not {"components", "install.sh"}.issubset(controls):
            raise ValueError("missing rustc-dev installer control files")
        content = "".join(f"file:{path}\n" for path in sorted(files)).encode()
        entry = tarfile.TarInfo(str(manifest))
        entry.mode = 0o644
        entry.size = len(content)
        archive.addfile(entry, io.BytesIO(content))


def stage(toolchain, target, combined, development, provenance_path, output):
    version = re.fullmatch(r"ohm-([0-9]+\.[0-9]+\.[0-9]+)-[1-9][0-9]*", toolchain)
    if version is None:
        raise ValueError(f"invalid Ohm toolchain: {toolchain}")
    suffix = {"x86_64-unknown-linux-gnu": ".so", "aarch64-apple-darwin": ".dylib"}.get(
        target
    )
    if suffix is None:
        raise ValueError(f"unsupported target: {target}")
    for path in (combined, development, provenance_path):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"missing or unsafe input: {path}")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if provenance.get("toolchain") != toolchain or provenance.get("target") != target:
        raise ValueError(
            "compiler provenance does not match the selected toolchain and target"
        )

    upstream = version[1]
    compiler_prefix = PurePosixPath(f"rust-{upstream}-dev-{target}/rustc/lib")
    development_prefix = PurePosixPath(
        f"rustc-dev-{upstream}-dev-{target}/rustc-dev/lib/rustlib/{target}/lib"
    )
    compiler_driver = archive_driver(combined, compiler_prefix, suffix)
    development_driver = archive_driver(
        development, development_prefix, suffix, development=True
    )
    if compiler_driver != development_driver:
        raise ValueError(
            "rustc-dev driver does not match the final optimized compiler archive"
        )

    archive_name = f"{toolchain}-rustc-dev-{target}.tar.gz"
    provenance_name = f"{toolchain}-rustc-dev-{target}-provenance.json"
    provenance["component"] = "rustc-dev"
    provenance["compiler_driver"] = {
        "name": compiler_driver[0],
        "sha256": compiler_driver[1],
    }
    provenance["compiler_archive"] = {
        "name": f"{toolchain}-{target}.tar.gz",
        "sha256": digest(combined),
    }
    output.mkdir(parents=True, exist_ok=True)
    metadata_archive(development, output / archive_name, development_prefix)
    provenance["archive"] = {
        "name": archive_name,
        "sha256": digest(output / archive_name),
    }
    provenance["compiler_sources_included"] = False
    (output / provenance_name).write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    for name in (archive_name, provenance_name):
        (output / (name + ".sha256")).write_text(
            f"{digest(output / name)}  {name}\n", encoding="utf-8"
        )
    return compiler_driver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--combined", type=Path, required=True)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        name, sha256 = stage(
            args.toolchain,
            args.target,
            args.combined,
            args.development,
            args.provenance,
            args.output,
        )
    except (ValueError, OSError, tarfile.TarError) as error:
        parser.error(str(error))
    print(f"Verified rustc-dev driver {name}: {sha256}")


if __name__ == "__main__":
    main()
