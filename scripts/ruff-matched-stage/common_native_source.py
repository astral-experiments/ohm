"""Reopen both composite Rust source histories from separately supplied signed sparse trees."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build


def main(seed, repo):
    reg = build.REG
    if repo.exists():
        raise ValueError("the receiving Git database must be new")
    subprocess.run(["git", "init", "--bare", "-q", repo], check=True)

    def git(*args):
        return build.git(repo, *args)

    prerequisite = reg["bundle"]["prerequisite"]
    upstream = reg["common_sete"]["upstream"]
    for pack in (seed, HERE / "native-prerequisite-inputs.pack"):
        with pack.open("rb") as contents:
            subprocess.run(
                ["git", "--no-lazy-fetch", "-C", repo, "index-pack", "--stdin"],
                stdin=contents,
                check=True,
            )
    (repo / "shallow").write_text(prerequisite + "\n")
    git("update-ref", "refs/heads/signed", prerequisite)
    heads = [upstream, *(p["revision"] for p in reg["roles"].values())]
    for c in heads:
        missing = subprocess.run(
            ["git", "--no-lazy-fetch", "-C", repo, "cat-file", "-e", c + "^{commit}"],
            stderr=subprocess.DEVNULL,
        )
        if missing.returncode == 0:
            raise ValueError("new source commit was already present")
    build.bundle(repo)
    roles = {
        k: {
            "commit": p["revision"],
            "tree": git("rev-parse", p["revision"] + "^{tree}"),
            "compiler": git("rev-parse", p["revision"] + ":compiler"),
        }
        for k, p in reg["roles"].items()
    }
    assert not (repo / "objects/info/alternates").exists()
    for path, row in reg["common_sete"]["blobs"].items():
        for c, k in (
            (prerequisite, "old"),
            (upstream, "new"),
            (roles["P"]["commit"], "new"),
            (roles["C"]["commit"], "new"),
        ):
            data = subprocess.check_output(
                [
                    "git",
                    "--no-lazy-fetch",
                    "-C",
                    repo,
                    "cat-file",
                    "blob",
                    c + ":" + path,
                ]
            )
            assert (
                hashlib.sha1(
                    b"blob " + str(len(data)).encode() + b"\0" + data
                ).hexdigest()
                == row[k]
            )
    return dict(
        roles=roles,
        upstream=upstream,
        common_native_inputs=reg["common_sete"]["blobs"],
        six_treatment_blobs=reg["changed_sources"],
        prerequisite=prerequisite,
        original_signed_roster={seed.name: build.sha(seed)},
        packets={
            k: build.sha(HERE / k)
            for k in (
                "candidate.bundle",
                "upstream-sete.bundle",
                "native-prerequisite-inputs.pack",
            )
        },
        originally_absent=heads,
        physical_old_and_new_native_bodies_reopened=True,
    )


if __name__ == "__main__":
    print(
        json.dumps(
            main(Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[2]).resolve()),
            sort_keys=True,
            indent=2,
        )
    )
