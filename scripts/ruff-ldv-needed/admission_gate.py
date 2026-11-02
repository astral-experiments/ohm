"""Verify the completed native admissions before an independent scored acquisition."""

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


def checked(condition, message):
    if not condition:
        raise ValueError(message)


def acquire(run_id, commit, destination):
    checked(run_id.isdecimal() and len(commit) == 40, "an exact prior native run and head are required")
    repo = "astral-experiments/ohm"
    base = f"repos/{repo}/actions/runs/{run_id}"

    def get(path):
        return subprocess.check_output(["gh", "api", path])

    run = json.loads(get(base))
    checked(run["repository"]["full_name"] == repo and run["head_sha"] == commit and run["run_attempt"] == 1
            and run["head_branch"] == "charlie/qa-ruff-workspace-link-census-20261102" and
            run["event"] == "workflow_dispatch" and run["conclusion"] == "success", "invalid admission provenance")
    artifacts = json.loads(get(base + "/artifacts?per_page=100"))["artifacts"]
    receipts = {}
    for suite in ("option", "e2e"):
        row, = [a for a in artifacts if a["name"] == f"ldv-needed-admit-terminal-{suite}-1"]
        checked(0 < row["size_in_bytes"] <= 8 * 1024 * 1024 and not row["expired"], "missing compact admission")
        data = get(f"repos/{repo}/actions/artifacts/{row['id']}/zip")
        checked(len(data) == row["size_in_bytes"] and "sha256:" + hashlib.sha256(data).hexdigest() == row["digest"],
                "corrupt prior artifact")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            checked(archive.testzip() is None, "invalid prior CRC")
            terminal = json.loads(archive.read("verified.json"))
            checked(terminal["source"] and terminal["qa"] == commit and terminal["stage"] == "admit" and
                    terminal["run"] == int(run_id) and terminal["suite"] == suite and
                    terminal["guarded_owner_skips"] > 0 and set(terminal["qualified_native"]) ==
                    {"plain-A", "plain-B", "original", "guard"}, "different prior experiment")
            checked(terminal["acquired"] == hashlib.sha256(archive.read("acquired.json")).hexdigest() and
                    terminal["physical"] == hashlib.sha256(archive.read("physical-contact.json")).hexdigest() and
                    "whole_tree_user_instructions" not in terminal, "broken or already-scored native records")
        raw, = [a for a in artifacts if a["name"] == f"ldv-needed-admit-originals-{suite}-1"]
        second, = [a for a in artifacts if a["name"] == f"ldv-needed-admit-independent-{suite}-1"]
        checked(not raw["expired"] and not second["expired"] and 0 < second["size_in_bytes"] <= 65536,
                "absent independent physical readback")
        again = get(f"repos/{repo}/actions/artifacts/{second['id']}/zip")
        checked(len(again) == second["size_in_bytes"] and "sha256:" + hashlib.sha256(again).hexdigest() == second["digest"],
                "corrupt independent receipt")
        with zipfile.ZipFile(io.BytesIO(again)) as archive:
            reopened = json.loads(archive.read("reopened.json"))
        checked(reopened["qa"] == commit and reopened["run"] == int(run_id) and reopened["stage"] == "admit" and
                reopened["suite"] == suite and reopened["pair"] == 1 and reopened["acquired"] == terminal["acquired"] and
                reopened["new_guard_skips"] == terminal["guarded_owner_skips"] and reopened["artifact_id"] == raw["id"]
                and reopened["archive_digest"] == raw["digest"], "independent readback belongs to different inputs")
        receipts[suite] = {"artifact_id": row["id"], "digest": row["digest"], "acquired": terminal["acquired"],
                           "physical": terminal["physical"], "raw": raw["digest"], "reopened": second["digest"]}
    with Path(destination).open("x") as out:
        json.dump({"run": int(run_id), "qa": commit, "native": receipts}, out, sort_keys=True)
        out.write("\n")


if __name__ == "__main__":
    acquire(sys.argv[1], os.environ["GITHUB_SHA"], sys.argv[2])
