"""Verify and layer the three frozen evidence archives without overwriting files.

This rehydrates evidence only. It does not build or execute Rust/Cargo/Wild.
Requires Python 3.11+ and approximately 1.3 GiB of free space.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile


ARCHIVES = [
    (
        "correctness",
        "current-cut-correctness.tar.gz",
        "3da176a3a30003bbd2a771f2dd31afa2544a4000097964df32be70a0a58dd986",
        "inventory.json",
        "059a0ad37a126c3e39ed316166ebd61a97e3a79134488b73c3d3f015cdb3d229",
    ),
    (
        "matrix",
        "readiness-matrix.tar.gz",
        "9832541221286816eac2055ae93c47c0b2811d0e83cc6dcd39ee7b561e3261a6",
        "matrix-inventory.json",
        "403abcc2b760ae00a715e74ecf38752dce55f9de0c03fd3b18e310d7aec1e18a",
    ),
    (
        "current",
        "current-cargo-evidence.tar.gz",
        "7a3456f006a8903d59349f28cec8c6c8555542a35b458e755c3e4db10d97355b",
        "current-cargo-inventory.json",
        "4ee6e740c6f96f6275c32d7d3234763dbbadc99987a960dc55ee4860738a089f",
    ),
]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check(condition, message):
    if not condition:
        raise ValueError(message)


def relative_path(name):
    path = PurePosixPath(name)
    check(
        bool(path.parts)
        and not path.is_absolute()
        and ".." not in path.parts
        and str(path) == name,
        f"unsafe or noncanonical path: {name!r}",
    )
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option, *_ in ARCHIVES:
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    check(not args.destination.exists() and not args.destination.is_symlink(),
          "destination must not exist")
    check(not args.receipt.exists() and not args.receipt.is_symlink(),
          "receipt must not exist")
    check(args.destination.parent.is_dir(), "destination parent must exist")
    check(shutil.disk_usage(args.destination.parent).free > 2 * 1024**3,
          "need at least 2 GiB free before extraction")
    for option, name, expected, *_ in ARCHIVES:
        path = getattr(args, option)
        check(path.is_file() and digest(path) == expected, f"archive digest: {name}")
    args.destination.mkdir()
    seen = set()
    receipt = {"passed": False, "overwrite_count": 0, "archives": []}
    for option, name, expected, inventory_name, inventory_digest in ARCHIVES:
        archive = getattr(args, option)
        with tarfile.open(archive, "r:gz") as tar:
            inventory_member = tar.getmember("readiness-proof/" + inventory_name)
            check(inventory_member.isfile(), "inventory must be a regular file")
            inventory_bytes = tar.extractfile(inventory_member).read()
            check(hashlib.sha256(inventory_bytes).hexdigest() == inventory_digest,
                  f"inventory digest: {name}")
            inventory = json.loads(inventory_bytes)
            records = {entry["path"]: entry for entry in inventory["files"]}
            check(len(records) == len(inventory["files"]) == inventory["file_count"],
                  f"unique inventory entries: {name}")
            check(sum(entry["bytes"] for entry in records.values()) == inventory["total_bytes"],
                  f"inventory byte total: {name}")
            for key in records:
                relative_path(key)
            if option == "current":
                ancestors = [
                    {"archive": item[1], "sha256": item[2],
                     "inventory": item[3], "inventory_sha256": item[4]}
                    for item in ARCHIVES[:2]
                ]
                check(inventory["ancestors"] == ancestors, "exact ancestor identities")
            local = set()
            total = 0
            for member in tar:
                path = relative_path(member.name)
                check(member.isfile() and path.parts[0] == "readiness-proof"
                      and len(path.parts) > 1, f"bounded regular member: {member.name}")
                key = str(PurePosixPath(*path.parts[1:]))
                check(key not in seen and key not in local, f"duplicate or overlap: {key}")
                check(key == inventory_name or key in records, f"uninventoried member: {key}")
                expected_size = len(inventory_bytes) if key == inventory_name else records[key]["bytes"]
                expected_hash = inventory_digest if key == inventory_name else records[key]["sha256"]
                check(member.size == expected_size, f"member size: {key}")
                output = args.destination.joinpath(*path.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                content_hash = hashlib.sha256()
                written = 0
                with tar.extractfile(member) as source, output.open("xb") as destination:
                    while block := source.read(1024 * 1024):
                        content_hash.update(block)
                        written += len(block)
                        destination.write(block)
                check(written == expected_size and content_hash.hexdigest() == expected_hash,
                      f"extracted bytes: {key}")
                local.add(key)
                total += written
            check(local == set(records) | {inventory_name}, f"complete inventory: {name}")
            seen.update(local)
            receipt["archives"].append({
                "name": name, "sha256": expected, "compressed_bytes": archive.stat().st_size,
                "archive_regular_files": len(local), "inventory_entries": len(records),
                "inventory_sha256": inventory_digest,
                "payload_bytes": inventory["total_bytes"], "archive_uncompressed_bytes": total,
                "directory_members": 0,
            })
    receipt.update(passed=True, combined_regular_files=len(seen),
                   created_directories=sum(p.is_dir() for p in args.destination.rglob("*")),
                   verifier_sha256=digest(Path(__file__)),
                   scope="Frozen archive digests, three complete member inventories, no overlaps or overwrites; evidence only")
    with args.receipt.open("x") as stream:
        stream.write(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
