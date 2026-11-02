"""Run the typed LLVM reader against the original signed Cargo inputs without an old source tree."""

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--reader", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="a new private output directory")
    parser.add_argument("--price", action="store_true", help="also retain freshly measured Callgrind traces for every edited unit")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    registration = json.loads((HERE / "registration.json").read_bytes())
    native = json.loads(gzip.decompress((HERE / "observations.json.gz").read_bytes()))["native"]
    with args.capture.open("rb") as file:
        assert hashlib.file_digest(file, "sha256").hexdigest() == registration["source_archive"]
    with zipfile.ZipFile(args.capture) as archive:
        owner = args.out / "owner.nul"
        original = archive.read("capture/new/stage/ruff_workspace/original.nul")
        assert original == archive.read("capture/old/stage/ruff_workspace/original.nul")
        assert digest(original) == registration["owner_original_nul"]
        owner.write_bytes(original)
        for role in ("old", "new"):
            stage = json.loads(archive.read(f"capture/{role}/cgus.json"))["ruff_workspace"]["emitted"]
            assert set(stage) == set(native)
            for unit in sorted(stage):
                expected = native[unit][role]
                payload = gzip.decompress(archive.read(f"cgu-originals/{expected['input']}.gz"))
                assert digest(payload) == expected["input"] == stage[unit]["sha256"]
                current = args.out / "current.bc"
                current.write_bytes(payload)
                placements = args.out / "current.placements"
                command = [str(args.reader.resolve()), str(owner), str(current)]
                raw = subprocess.check_output([*command, "roundtrip", str(placements)])
                row = json.loads(raw)
                assert row["complete_key"] == expected["complete_key"]
                assert row["post_dae_roundtrip"] == expected["post_dae_roundtrip"]
                assert row["untouched_ordinary_module"] == row["unmodified_clone"]
                assert digest(placements.read_bytes()) == expected["placements_sha256"]
                if args.price and role == "new":
                    for mode in ("parse", "policy", "total"):
                        dest = args.out / f"{unit}-{mode}.callgrind"
                        subprocess.run(["valgrind", "--tool=callgrind", "--instr-atstart=no",
                                        "--collect-atstart=no", "--cache-sim=no", "--branch-sim=no",
                                        "--dump-line=no", "--compress-strings=yes",
                                        f"--callgrind-out-file={dest}", *command, mode, "-"],
                                       check=True, stdout=subprocess.DEVNULL)
                print(role, unit, row["module_sha256"], flush=True)


if __name__ == "__main__":
    main()
