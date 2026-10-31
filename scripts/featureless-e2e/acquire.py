"""Reopen signed distribution and the two previously built, independently verified Cargo subjects."""

import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess

PINS = {
    "signed": "f40b16cdb9c041c941a5e339f816111a80a84bdf",
    "physical": "9d1dd09be4d2346142957cc298093d8a75c755c3",
    "tree": "77e33ee7781b8d823dc7f046d3bd9bea43818bc8",
    "classic": "b3a1bbd38e07293168f06cb21648821b8cacd206",
}
REPO = "repos/astral-experiments/ohm/"


def main(workspace, downloaded, role):
    for directory, oid in PINS.items():
        assert subprocess.check_output(["git", "-C", workspace / directory, "rev-parse", "HEAD"]).decode().strip() == oid
    cli = os.environ.get("GITHUB_CLI", "gh")
    signed = downloaded / "signed"
    runpy.run_path(str(workspace / "signed/scripts/packaged-release-workspace/packages.py"))["prepare"](signed, "21")
    if role == "strict":
        run = json.loads(subprocess.check_output([cli, "api", REPO + "actions/runs/41151297839"]))
        job = json.loads(subprocess.check_output([cli, "api", REPO + "actions/jobs/124388202956"]))
        # The artifact-producing builder passed; another, separately diagnosed Ruff job failed.
        assert (run["head_sha"], run["run_attempt"], run["status"], run["conclusion"]) == (
            "f23a67771c625785cd70f58e9b46e8d26af3d317", 1, "completed", "failure")
        assert (job["name"], job["run_id"], job["head_sha"], job["conclusion"]) == (
            "builder", run["id"], run["head_sha"], "success")
        runpy.run_path(str(workspace / "tree/scripts/strict-unicode-cost/acquire-cargo.py"))["fetch"](downloaded / "selected")
    else:
        runpy.run_path(str(workspace / "classic/scripts/ohm-aarch64-fallback/acquire.py"))["acquire"](
            cli, downloaded / "cargo-custody.json", downloaded / "selected")
        (downloaded / "cargo-custody.json").rename(downloaded / "selected/custody.json")


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("workspace", type=Path)
    a.add_argument("destination", type=Path)
    a.add_argument("role", choices=("strict", "293"))
    opts = a.parse_args()
    main(opts.workspace, opts.destination, opts.role)
