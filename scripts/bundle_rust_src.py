#!/usr/bin/env python3
"""Add the matching rust-src installer component to an extended distribution."""

import argparse
import gzip
import io
import tarfile
import tempfile
from pathlib import Path


def bundle(extended: Path, sources: Path, destination: Path) -> None:
    extended_root = extended.name.removesuffix(".tar.gz")
    source_root = sources.name.removesuffix(".tar.gz")
    metadata: list[dict[str, bytes]] = [{}, {}]
    controls = {"components", "rust-installer-version", "git-commit-hash"}

    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        output = Path(temporary) / "bundle.tar.gz"
        with (
            output.open("wb") as raw,
            gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed,
            tarfile.open(fileobj=compressed, mode="w|") as combined,
        ):
            for index, (archive, root) in enumerate(
                [(extended, extended_root), (sources, source_root)]
            ):
                with tarfile.open(archive, "r|gz") as incoming:
                    for member in incoming:
                        relative = Path(member.name).relative_to(root).as_posix()
                        content = (
                            incoming.extractfile(member) if member.isfile() else None
                        )
                        if relative in controls:
                            if content is None:
                                raise ValueError(f"invalid {relative} in {archive}")
                            data = content.read()
                            metadata[index][relative] = data
                            if index == 0 and relative == "components":
                                if b"rust-src" in data.splitlines():
                                    raise ValueError(
                                        "extended archive already contains rust-src"
                                    )
                                data = data.rstrip(b"\n") + b"\nrust-src\n"
                            member.size = len(data)
                            content = io.BytesIO(data)
                        if index == 1:
                            if relative != "rust-src" and not relative.startswith(
                                "rust-src/"
                            ):
                                continue
                            member.name = f"{extended_root}/{relative}"
                            member.pax_headers.pop("path", None)
                        combined.addfile(member, content)

        if metadata[1].get("components") != b"rust-src\n":
            raise ValueError("source archive must contain the rust-src component")
        if "components" not in metadata[0]:
            raise ValueError("extended archive has no component manifest")
        for name in ("rust-installer-version", "git-commit-hash"):
            if not metadata[0].get(name) or metadata[0][name] != metadata[1].get(name):
                raise ValueError(f"archives have missing or mismatched {name}")
        output.replace(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extended", type=Path)
    parser.add_argument("sources", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    bundle(args.extended, args.sources, args.destination)
