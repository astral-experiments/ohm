"""Use the published -24 Linux SDK with the exact source release enrollment."""

import json, os, shutil, subprocess as sp, tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
M = json.loads((HERE / "release-compiler-24.json").read_bytes())
PUB = json.loads((HERE / "release-published-24.json").read_bytes())


def install(w, P):
    name = "ohm-1.99.0-24-x86_64-unknown-linux-gnu.tar.gz"
    spec = PUB["assets"][name]
    assert (
        spec["id"] == 707031606
        and spec["sha256"] == "sha256:" + M["tar_sha256"]
        and len(M["members"]) == 79
    )
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "GH_TOKEN": os.environ.pop("OHM_SDK_READ_TOKEN"),
    }
    api = "repos/astral-experiments/ohm/releases/assets/" + str(spec["id"])
    row = json.loads(sp.check_output(["gh", "api", api], env=env))
    assert (
        row["digest"] == spec["sha256"]
        and row["size"] == spec["bytes"]
        and row["name"] == name
    )
    archive = w.root / name
    with archive.open("xb") as out:
        sp.run(
            ["gh", "api", api, "-H", "Accept: application/octet-stream"],
            env=env,
            stdout=out,
            check=True,
        )
    del env
    assert w.hf(archive) == M["tar_sha256"] and archive.stat().st_size == spec["bytes"]
    w.sdk.mkdir()
    lookup = {r["source"]: (k, r) for k, r in M["members"].items()}
    found = {}
    with tarfile.open(archive, "r|gz") as tar:
        for member in tar:
            if member.name not in lookup:
                continue
            k, r = lookup[member.name]
            dst = w.sdk / k
            assert (
                k not in found
                and not Path(k).is_absolute()
                and ".." not in Path(k).parts
                and member.isfile()
            )
            dst.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, dst.open("xb") as out:
                shutil.copyfileobj(src, out)
            dst.chmod(member.mode & 0o777)
            assert (
                dst.stat().st_size == r["bytes"]
                and w.hf(dst) == r["sha256"]
                and dst.stat().st_nlink == 1
            )
            found[k] = [
                r["sha256"],
                member.mode & 0o777,
                dst.stat().st_dev,
                dst.stat().st_ino,
            ]
    assert set(found) == set(M["members"])
    e = {k: os.environ[k] for k in ("HOME", "USER", "PATH", "LANG") if k in os.environ}
    e.update(
        RUSTUP_HOME=str(w.ru),
        CARGO_HOME=str(w.home),
        CARGO_TARGET_DIR=str(w.target),
        CARGO_BUILD_BUILD_DIR=str(w.shared),
        CARGO_NET_GIT_FETCH_WITH_CLI="true",
    )
    sp.run(["rustup", "toolchain", "link", "ohm", w.sdk], env=e, check=True)
    versions = {}
    for program, revision in [
        ("rustc", "f5a51d8cc3e76236c2d0f17d495d59ebb03306e4"),
        ("cargo", "abc70d60a6fd89c10d5f65cf85820d9b78d5affe"),
    ]:
        vv = sp.check_output([program, "+ohm", "-vV"], text=True, env=e)
        assert revision in vv
        versions[program] = vv
    w.put(P / "sdk-24.json", {"archive": spec, "files": found, "versions": versions})
    return e
