"""Require the previous, successful signed pilot on this exact packaging CI commit."""

import argparse
import json
import os
from pathlib import Path

from study import ARCHIVE_SHA, EXPECTED, need, run, save, sha


def main():
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    a = p.parse_args()
    root = a.root
    revision = os.environ["GITHUB_SHA"]
    repo = os.environ["GITHUB_REPOSITORY"]
    number = os.environ["APPLE_PILOT"]
    need(
        repo == "astral-experiments/ohm" and number.isascii() and number.isdecimal(),
        "use this packaging repository and an integer run ID",
    )
    info = json.loads(run(["gh", "api", f"repos/{repo}/actions/runs/{number}"]))
    need(
        info["conclusion"] == "success"
        and info["event"] == "workflow_dispatch"
        and info["head_sha"] == revision
        and info["path"] == ".github/workflows/ci.yml",
        "pilot did not pass this exact CI revision",
    )
    destination = root / "pilot-receipts"
    run(
        [
            "gh",
            "run",
            "download",
            number,
            "--repo",
            repo,
            "-n",
            "apple-zmij-mechanism",
            "-D",
            str(destination),
        ],
        timeout=420,
    )
    record = json.loads((destination / "mechanism.json").read_bytes())
    need(
        record["status"] == "passed"
        and record["scores"] == 0
        and record["causal_counts"]
        == {"untouched": [1, 1, 1], "omit-vector-comment": [1, 0, 0], "restored": [1, 1, 1]},
        "signed causal baseline missing",
    )
    reldoc = destination / "release.json"
    need(
        sha(reldoc) == record["signed_release"] and json.loads(reldoc.read_bytes())["archive"] == ARCHIVE_SHA,
        "unsigned or incorrect compiler",
    )
    need(
        record["signed_verdicts"]["cold"] == EXPECTED["old"]
        and record["signed_verdicts"]["repeat-1"] == EXPECTED["new"]
        and "E0425" in record["signed_verdicts"]["invalid"],
        "incomplete ordinary Ruff witness",
    )
    save(
        root / "receipts/accepted-pilot.json",
        {
            "run": int(number),
            "revision": revision,
            "mechanism": sha(destination / "mechanism.json"),
            "observer_scope": record["observer_scope"],
            "signed_archive": ARCHIVE_SHA,
        },
    )


if __name__ == "__main__":
    main()
