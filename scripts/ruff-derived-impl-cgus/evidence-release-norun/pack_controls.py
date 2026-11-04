"""Preserve every original control and counter, and bind the hosted full native executables by SHA-256."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_hash(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def add_member(archive, name, source, size):
    header = tarfile.TarInfo(name)
    header.size = size
    header.mtime = 0
    header.mode = 0o644
    archive.addfile(header, source)


def collect(output, pilot, confirmation):
    summary = load(confirmation / "combined.json")
    sources = [("pilot", pilot, pilot / "independently-verified-final.json")]
    sources.extend(
        (f"boot-{i}", confirmation / str(i), confirmation / str(i) / "reopened.json")
        for i in range(6)
    )
    compressed = output / "raw-controls.tar.zst"
    inventory = []
    with compressed.open("wb") as stream:
        proc = subprocess.Popen(
            ["zstd", "-q", "-10", "-T1", "-c"], stdin=subprocess.PIPE, stdout=stream
        )
        try:
            with tarfile.open(fileobj=proc.stdin, mode="w|") as packed:
                for label, src, result_file in sources:
                    image = src / "original.zip"
                    meta = load(src / "asset.json")
                    result = load(result_file)
                    digest = meta["digest"].removeprefix("sha256:")
                    require(
                        file_hash(image) == digest == result["original"]["sha256"]
                        and image.stat().st_size
                        == meta["size_in_bytes"]
                        == result["original"]["bytes"],
                        "original receipt changed",
                    )
                    stats = {
                        "label": label,
                        "run": meta["workflow_run"]["id"],
                        "artifact": meta["id"],
                        "original_sha256": digest,
                        "original_bytes": image.stat().st_size,
                        "native_members": [],
                        "raw_controls": 0,
                    }
                    with zipfile.ZipFile(image) as original:
                        for member in sorted(
                            original.infolist(), key=lambda item: item.filename
                        ):
                            if member.is_dir():
                                continue
                            name = member.filename
                            require(
                                not Path(name).is_absolute()
                                and ".." not in Path(name).parts,
                                "unsafe ZIP member",
                            )
                            if re.fullmatch(
                                r"[PC]/native-bodies/[0-9a-f]{64}\.zst", name
                            ):
                                stats["native_members"].append(name)
                                continue
                            require(
                                member.file_size < 48 << 20, "unexpected large control"
                            )
                            with original.open(member) as body:
                                add_member(
                                    packed, label + "/" + name, body, member.file_size
                                )
                            stats["raw_controls"] += 1
                        require(
                            len(stats["native_members"])
                            == result["physical_native_bodies"],
                            "missing independently opened native image",
                        )
                    raw = (json.dumps(result, sort_keys=True) + "\n").encode()
                    add_member(
                        packed,
                        label + "/independent-readback.json",
                        io.BytesIO(raw),
                        len(raw),
                    )
                    inventory.append(stats)
        finally:
            proc.stdin.close()
            require(proc.wait() == 0, "failed to compress original controls")
    write_json(output / "originals.json", inventory)
    write_json(output / "paired.json", summary)
    write_json(
        output / "controls.json",
        {
            "sha256": file_hash(compressed),
            "bytes": compressed.stat().st_size,
            "inputs": len(inventory),
            "original_control_members": sum(row["raw_controls"] for row in inventory),
            "authenticated_native_body_members": sum(
                len(row["native_members"]) for row in inventory
            ),
        },
    )


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--pilot", type=Path, required=True)
    cli.add_argument("--confirmation", type=Path, required=True)
    cli.add_argument("--out", type=Path, required=True)
    args = cli.parse_args()
    args.out.mkdir(exist_ok=True, parents=True)
    collect(args.out, args.pilot, args.confirmation)


if __name__ == "__main__":
    main()
