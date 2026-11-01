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
import qualification
import packed_confirmation as six
import source_guard


def check(repo, head):
    repo = repo.resolve(strict=True)
    spec = source_guard.tree(repo, head, "scripts/packed-ref-cli")
    source_guard.tree(repo, head, "scripts/gnu-same-revision-donor")
    six.frozen()
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
        == "9d433e8b403b92daef72417ac0c77989f6ee643abde8699a26020eaca910ec20"
        and git_layout.TABLE_BYTES == 117800
        and git_layout.Y_RANGE == (46, 117),
        "wrong native candidate or packed corpus",
    )
    sdk.need(
        hashlib.sha256((HERE / "inputs/registered-plan.md").read_bytes()).hexdigest()
        == "c10abb820ce6b6da3ab3b2f88d858ee7574ef73d989e55d4a96307aa5c8c26ed",
        "wrong primary/secondary protocol",
    )
    return {
        "head": head,
        "source_files": len(spec),
        "frozen_blobs": len(fixed),
        "source_run": sdk.SOURCE_RUN,
        "prerequisites": qualification.prereqs(),
    }


if __name__ == "__main__":
    print(json.dumps(check(Path(sys.argv[1]), sys.argv[2]), sort_keys=True))
