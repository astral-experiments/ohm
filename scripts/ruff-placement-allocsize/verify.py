"""Relink all six actual projected objects and their independently emitted controls."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile


root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--projector", type=Path, help="Recompute each projection from its three inputs")
args = parser.parse_args()
seen = json.loads((root / "observed.json").read_bytes())
digest = lambda data: hashlib.sha256(data).hexdigest()


def run_object(work, data):
    obj = work / "input.o"
    binary = work / "observed"
    obj.write_bytes(data)
    subprocess.run(["cc", "-O0", root / "main.c", obj, "-o", binary], check=True)
    return int(subprocess.check_output([binary], text=True))


with tempfile.TemporaryDirectory() as directory, tarfile.open(root / "objects.tar.gz") as archive:
    work = Path(directory)
    assert sorted(archive.getnames()) == sorted(seen["files"])
    files = {name: archive.extractfile(name).read() for name in seen["files"]}
    assert {name: digest(value) for name, value in files.items()} == seen["files"]
    failures = controls = 0
    for mode in ["definition-and-call", "definition-only", "no-allocsize"]:
        for old, new in [(16, 32), (32, 16)]:
            step = f"{mode}-{old}-to-{new}"
            row = seen["transitions"][step]
            old_object = files[f"{mode}-{old}.o"]
            clean = files[f"{mode}-{new}.o"]
            projection = files[step + ".o"]
            before = files[f"{mode}-{old}.wire"]
            after = files[f"{mode}-{new}.wire"]
            assert before[:4] == after[:4] == b"OSP\x01"
            assert before[4:36].hex() == after[4:36].hex() == row["key"]
            assert before[36:] != after[36:]
            if args.projector is not None:
                inputs = [work / n for n in ["prior.o", "prior.osp", "current.osp"]]
                for path, data in zip(inputs, [old_object, before, after], strict=True):
                    path.write_bytes(data)
                result = subprocess.run([args.projector.resolve(), "rebase", *inputs],
                                        capture_output=True, check=True)
                assert result.stdout == projection
            assert digest(clean) == row["clean_object"]
            assert digest(projection) == row["projected_object"]
            result = run_object(work, projection)
            expected = run_object(work, clean)
            assert (result, expected) == (row["projected_value"], row["clean_value"])
            if mode == "no-allocsize":
                assert result == expected == 2**64 - 1 and projection == clean
                controls += 1
            else:
                assert result == old and expected == new and projection != clean
                failures += 1
            print(f"{step}   projected {result}, clean {expected}")
    assert (failures, controls) == (4, 2)
