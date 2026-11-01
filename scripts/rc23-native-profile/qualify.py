"""Verify the published release manifest against the actual four source checkouts."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

local = Path(__file__).resolve().parent
workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
recipe = json.loads((local / "recipe.json").read_bytes())
coordinator = workspace / "release-candidate"
rust = workspace / "source/rust"
out = workspace / "native-evidence"
out.mkdir()


def git(path, *a):
    return subprocess.check_output(["git", "-C", path, *a], text=True).strip()


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


assert (
    os.environ["GITHUB_REF"] == "refs/heads/charlie/codex-rc23-profile-diagnostic"
    and os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
)
assert (
    git(workspace, "rev-parse", "HEAD")
    == os.environ["GITHUB_SHA"]
    == os.environ["REVIEWED_HEAD"]
    and git(coordinator, "rev-parse", "HEAD") == recipe["coordinator"]
)
manifest = coordinator / "toolchains/1.99.0/23.json"
assert sha(manifest) == recipe["manifest_sha256"]
assert git(rust, "rev-parse", "HEAD") == recipe["base"]
pack = local / "trait.pack"
assert sha(pack) == recipe["sha256"] and pack.stat().st_size == recipe["size"]
with pack.open("rb") as stream:
    subprocess.run(
        ["git", "-C", rust, "index-pack", "--stdin", "--strict"],
        stdin=stream,
        check=True,
    )
subprocess.run(
    ["git", "-C", rust, "checkout", "--detach", recipe["target"]], check=True
)
assert git(rust, "rev-parse", "HEAD^{tree}") == recipe["tree"]
parts = [
    rust,
    rust / "src/tools/cargo",
    rust / "src/tools/clippy",
    rust / "src/tools/rustfmt",
]
source = json.loads(manifest.read_bytes())
assert (
    {
        n: git(d, "rev-parse", "HEAD")
        for n, d in zip(("rust", "cargo", "clippy", "rustfmt"), parts)
    }
    == recipe["pins"]
    == {n: s["revision"] for n, s in source["sources"].items()}
)
assert (
    git(rust, "ls-tree", "HEAD", "src/tools/cargo").split()[2]
    == recipe["pins"]["cargo"]
)
subprocess.run(
    [coordinator / "scripts/verify-release-sources.sh", manifest, *parts], check=True
)
(out / "identity.json").write_text(
    json.dumps(
        {
            "coordinator": recipe["coordinator"],
            "manifest_sha256": sha(manifest),
            "sources": recipe["pins"],
            "official_build": sha(coordinator / "scripts/build-optimized-dist.sh"),
            "official_bootstrap": sha(coordinator / "release/bootstrap.toml"),
            "qa": os.environ["GITHUB_SHA"],
            "run": os.environ["GITHUB_RUN_ID"],
        },
        indent=2,
    )
    + "\n"
)
