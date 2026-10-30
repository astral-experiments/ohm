"""Transfer one rebuilt parent kit plus the replacement driver into a fresh holdout worker."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rebuild import MEMBERS, patched_record, rt
from bootstrap import restore as install_patched_driver


def run_identity():
    return {"run": int(os.environ["GITHUB_RUN_ID"]), "qa": os.environ["GITHUB_SHA"]}


def pack(role, transfer):
    selected = rt.load(rt.LOG / "selected.json")
    assert selected["role"] == role
    physical = rt.load(rt.LOG / "physical-sdk.json")
    assert not physical["differences"] and len(physical["files"]) == 119
    transfer.mkdir()
    if role == "parent":
        payload = "sdk.tar.zst"
        expected = MEMBERS["common"] | {MEMBERS["driver_path"]: MEMBERS["roles"]["M"]["driver"]}
        assert physical["files"] == expected
        subprocess.run(["tar", "--zstd", "--hard-dereference", "-cf", transfer / payload, "-C", rt.SDK, *sorted(expected)], check=True)
    else:
        assert role == "patched"
        payload = "driver.so.zst"
        candidate = patched_record()
        assert rt.load(rt.LOG / "candidate.json") == candidate
        assert physical["files"] == MEMBERS["common"] | {candidate["driver_path"]: candidate["driver"]}
        shutil.copyfile(rt.LOG / "candidate.json", transfer / "candidate.json")
        subprocess.run(["zstd", "-q", "-3", rt.SDK / candidate["driver_path"], "-o", transfer / payload], check=True)
    rt.save(transfer / "identity.json", run_identity() | {"role": role, "source": selected["commit"],
            "payload": payload, "bytes": (transfer / payload).stat().st_size, "sha256": rt.sha(transfer / payload)})


def unpack_parent(archive, sdk, expected):
    """Extract only enrolled regular files and verify each complete payload while reading."""
    sdk.mkdir(parents=True)
    seen = set()
    with subprocess.Popen(["zstd", "-qdc", archive], stdout=subprocess.PIPE) as decode:
        with tarfile.open(fileobj=decode.stdout, mode="r|") as files:
            for member in files:
                name = member.name
                assert member.isreg() and name in expected and name not in seen, name
                checksum, size, mode = expected[name]
                assert (member.size, member.mode) == (size, mode), name
                dest = sdk / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with files.extractfile(member) as source, dest.open("xb") as out:
                    shutil.copyfileobj(source, out, 2**20)
                dest.chmod(mode)
                assert rt.sha(dest) == checksum, name
                seen.add(name)
        # A tar stream can end before the compressor flushes its final zero blocks.
        assert not any(decode.stdout.read())
        assert decode.wait() == 0
    assert seen == set(expected)


def restore_kits(parent, patched):
    expected = MEMBERS["common"] | {MEMBERS["driver_path"]: MEMBERS["roles"]["M"]["driver"]}
    for role, folder, payload, commit in (("parent", parent, "sdk.tar.zst", MEMBERS["roles"]["M"]["source"]),
            ("patched", patched, "driver.so.zst", patched_record()["source"])):
        archive = folder / payload
        seal = rt.load(folder / "identity.json")
        assert seal == run_identity() | {"role": role, "source": commit, "payload": payload,
                "bytes": archive.stat().st_size, "sha256": rt.sha(archive)}
    assert rt.load(patched / "candidate.json") == patched_record()
    unpack_parent(parent / "sdk.tar.zst", Path(os.environ["CENSUS_PARENT"]), expected)
    install_patched_driver(patched)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_subparsers(dest="step", required=True)
    emit = stages.add_parser("pack")
    emit.add_argument("role", choices=("parent", "patched"))
    emit.add_argument("destination", type=Path)
    take = stages.add_parser("restore")
    take.add_argument("parent", type=Path)
    take.add_argument("patched", type=Path)
    args = parser.parse_args()
    if args.step == "pack":
        pack(args.role, args.destination)
    else:
        restore_kits(args.parent, args.patched)
