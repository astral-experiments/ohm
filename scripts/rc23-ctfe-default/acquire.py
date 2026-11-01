"""Bind this comparison to its own review and reuse the original authenticated SDK reader."""

import os
import subprocess
import sys
from pathlib import Path

work = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
current = work / "current"
earlier = work / "historical"
source = work / "source"
root = Path(os.environ["RUNNER_TEMP"]).resolve() / "ohm-branch-object-qa"


def rev(path):
    return subprocess.check_output(
        ["git", "-C", path, "rev-parse", "HEAD"], text=True
    ).strip()


assert os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
assert os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
assert os.environ["GITHUB_REF"] == "refs/heads/charlie/codex-rc23-ctfe-default"
assert rev(current) == os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"]
assert Path(__file__).resolve().parent == current / "scripts/rc23-ctfe-default"
assert rev(earlier) == "0b50022990577aadd904731e51c4d6c2a0f9b665"
assert rev(source) == "762fc25095e317ac5632ec835df3c7f9cfc64a64"
assert root == root.resolve(strict=True) and (
    root / "work/.owned-by-packed-study"
).read_text() == str(root)
sys.path.insert(0, str(earlier / "scripts/ctfe-crossover-pilot"))
import pilot

assert pilot.ROOT == root and not pilot.b.PARK.exists()
pilot.subjects.acquire(source)
