"""Bring the identical two runtime trees and bound source fixture to every isolated pair."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "ohm-aarch64-linux")]
import capsule
import runtime as rt
from study import git, load, need, save, sha, text_git

FIXTURE = "tests/run-make/ohm-checked-dep-info/inline.rs"


def export():
    capsule.build()
    dist = rt.ROOT / "private-return"
    source = rt.ROOT / "rust"
    revisions = set()
    for revision in (rt.PARENT, rt.CHILD):
        revisions.add(revision)
        for path in ("", "tests", "tests/run-make", "tests/run-make/ohm-checked-dep-info", FIXTURE):
            revisions.add(text_git(source, "rev-parse", revision + ":" + path))
    data = ("\n".join(sorted(revisions)) + "\n").encode()
    pack = dist / "checked-fixture.pack"
    with pack.open("xb") as out:
        subprocess.run(["git", "-C", source, "pack-objects", "--stdout"], input=data, stdout=out, check=True)
    need(pack.stat().st_size < 2**20, "fixture objects exceeded their bound")
    result = {"archive": sha(dist / "linux-aarch64-sdk-pair.tar.zst"), "fixture": sha(pack),
              "objects": sorted(revisions), "source": [rt.PARENT, rt.CHILD],
              "sdk_receipt": load(rt.LOG / "sdk-custody.json")}
    save(dist / "manifest.json", result)
    save(rt.LOG / "distribution.json", result)


def install(dist, expected):
    need(sha(dist / "manifest.json") == expected, "unexpected transfer manifest")
    manifest = load(dist / "manifest.json")
    path = dist / "linux-aarch64-sdk-pair.tar.zst"
    need(manifest["source"] == [rt.PARENT, rt.CHILD] and 0 < path.stat().st_size <= capsule.MAX_BYTES
         and sha(path) == manifest["archive"], "unexpected source or SDK archive")
    proof = capsule.verify(path)
    for name, value in proof.items():
        need(manifest["sdk_receipt"][name] == value, "capsule inventory differs on this machine")
    pack = dist / "checked-fixture.pack"
    need(sha(pack) == manifest["fixture"] and pack.stat().st_size < 2**20, "fixture transport differs")
    source = rt.ROOT / "rust"
    subprocess.run(["git", "init", "--bare", "-q", "--template=", source], check=True)
    with pack.open("rb") as data:
        subprocess.run(["git", "-C", source, "index-pack", "--stdin"], stdin=data, check=True)
    for revision in (rt.PARENT, rt.CHILD):
        need(text_git(source, "rev-parse", revision + ":" + FIXTURE) == "89ce772800e304c3af6c2cd7071e423ad798a03f",
             "bad restored compiler fixture")
        need(git(source, "show", revision + ":" + FIXTURE), "missing source bytes")

    objects = rt.CAP / "objects"
    objects.mkdir(parents=True)
    roles = None
    written = set()
    with capsule.decompress(path) as stream:
        for member in stream:
            data = stream.extractfile(member)
            if member.name == "roles.json":
                roles = json.load(data)
                allowed = capsule.table(roles)
            elif member.name == "release.json":
                save(rt.LOG / member.name, json.load(data))
            elif member.name not in capsule.METADATA:
                key = member.name.removeprefix("objects/")
                need(member.name == "objects/" + key and key in allowed and member.size == allowed[key],
                     "unexpected transport object")
                file = objects / key
                with file.open("xb") as out:
                    shutil.copyfileobj(data, out, 2**20)
                need(sha(file) == key, "damaged compiler object")
                written.add(key)
    need(written == set(allowed), "incomplete runtime object set")
    for name, key in rt.TOOLS.items():
        dst = rt.SDK / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(objects / key, dst)
        dst.chmod(roles["P"]["files"][name][2])
    for role in "PC":
        for tool in rt.TOOLS:
            del roles[role]["files"][tool]
        save(rt.LOG / (role + "-sdk.json"), roles[role])
    save(rt.LOG / "received.json", {"manifest": expected, "proof": proof, "source": manifest["source"]})


if __name__ == "__main__":
    if sys.argv[1:] == ["export"]:
        export()
    else:
        install(Path(sys.argv[1]), sys.argv[2])
