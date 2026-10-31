"""Reopen one role from a verified run's transfer without overwriting a previous SDK."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import sha
from source import BASE, FORWARD, COMBINED, need


def stream_copy(source, path, row):
    h = hashlib.sha256()
    size = 0
    with path.open("xb") as dst:
        while block := source.read(1024 * 1024):
            size += len(block)
            need(size <= row[1], "too many member bytes")
            h.update(block)
            dst.write(block)
    need(size == row[1] and h.hexdigest() == row[0], "member content differs")
    path.chmod(row[2])


def restore(transfer, dst, role, qa, run, attempt):
    manifest = json.loads((transfer / "manifest.json").read_text())
    need(
        [manifest["qa"], str(manifest["run"]), str(manifest["attempt"])] == [qa, str(run), str(attempt)],
        "different QA run/head/attempt",
    )
    need(
        {r: manifest["roles"][r]["source"]["commit"] for r in ("P", "F", "C")}
        == {"P": BASE, "F": FORWARD, "C": COMBINED},
        "foreign sources",
    )
    need(
        set(manifest["products"]) == {"P-sdk.tar.zst", "driver-F.zst", "driver-C.zst"},
        "unknown transfer surface",
    )
    for name, row in manifest["products"].items():
        p = transfer / name
        need(
            p.is_file() and not p.is_symlink() and [sha(p), p.stat().st_size] == row,
            "transfer mismatch: " + name,
        )
    files = manifest["files"]
    driver = manifest["driver"]
    need(
        driver in files
        and len(files) == manifest["common_member_count"] + 1
        and manifest["roles"]["P"]["driver"] == files[driver],
        "incomplete manifest",
    )
    dst.mkdir()
    seen = set()
    with subprocess.Popen(
        ["zstd", "-dq", "-c", transfer / "P-sdk.tar.zst"], stdout=subprocess.PIPE
    ) as z:
        with tarfile.open(fileobj=z.stdout, mode="r|") as archive:
            for item in archive:
                path = Path(item.name)
                need(
                    item.isfile()
                    and item.name in files
                    and item.name not in seen
                    and not path.is_absolute()
                    and ".." not in path.parts
                    and item.size == files[item.name][1]
                    and item.mode == files[item.name][2],
                    "unexpected SDK tar member",
                )
                out = dst / path
                out.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(item) as src:
                    stream_copy(src, out, files[item.name])
                seen.add(item.name)
        while z.stdout.read(1024 * 1024):
            pass
        need(z.wait() == 0 and seen == set(files), "incomplete compressed SDK")
    if role != "P":
        temp = dst / (driver + ".verified")
        with subprocess.Popen(
            ["zstd", "-dq", "-c", transfer / ("driver-" + role + ".zst")], stdout=subprocess.PIPE
        ) as z:
            stream_copy(z.stdout, temp, manifest["roles"][role]["driver"])
            need(z.wait() == 0, "invalid compressed driver")
        temp.replace(dst / driver)
    return manifest["roles"][role]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transfer", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("role", choices=("P", "F", "C"))
    parser.add_argument("--qa", required=True)
    parser.add_argument("--run", type=int, required=True)
    parser.add_argument("--attempt", type=int, required=True)
    a = parser.parse_args()
    print(json.dumps(restore(a.transfer, a.destination, a.role, a.qa, a.run, a.attempt), sort_keys=True))
