"""Check the current full Git source against its reviewed tree, including immutable input envelopes."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "ctfe-crossover-pilot")]
import git_layout
import packed_sdk as sdk
import source_guard


def check(repo, head):
    repo = repo.resolve(strict=True)
    spec = source_guard.tree(repo, head, "scripts/packed-ref-cli")
    source_guard.tree(repo, head, "scripts/gnu-same-revision-donor")
    fixed = json.loads((HERE / "inherited-objects.json").read_bytes())
    for path, oid in fixed.items():
        actual = subprocess.check_output(
            ["git", "--no-optional-locks", "-C", repo, "rev-parse", head + ":" + path],
            text=True,
        ).strip()
        blob = (repo / path).read_bytes()
        sdk.need(
            oid
            == actual
            == hashlib.sha1(
                b"blob " + str(len(blob)).encode() + b"\0" + blob
            ).hexdigest(),
            "changed independently frozen source " + path,
        )
    sdk.need(
        sdk.enrolled()["source"]["drivers"][1]
        == "958e60deef3715e21efb968d38c4ef268bc5b58ab0a4e33810b996ff0c4d271c"
        and git_layout.TABLE_BYTES == 117800
        and git_layout.Y_RANGE == (46, 117),
        "wrong native candidate or packed corpus",
    )
    sdk.need(
        hashlib.sha256((HERE / "inputs/registered-plan.md").read_bytes()).hexdigest()
        == "34251812dda5e97898a76e03af900aa38e62856419f8d3c74968d2c2dd9c92eb",
        "wrong primary/secondary protocol",
    )
    return {
        "head": head,
        "source_files": len(spec),
        "frozen_blobs": len(fixed),
        "source_run": sdk.SOURCE_RUN,
    }


if __name__ == "__main__":
    print(json.dumps(check(Path(sys.argv[1]), sys.argv[2]), sort_keys=True))
