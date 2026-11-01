"""Restore only the exact previously qualified public Actions artifact; the official native proof runs separately."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import protocol


def main(work):
    record = json.loads((HERE / "contact-admission.json").read_bytes())
    protocol.admit(record, record)
    protocol.require(
        work.is_absolute()
        and work.parent.resolve() == work.parent
        and not work.exists()
        and os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
        and os.environ["GITHUB_ACTIONS"] == "true",
        "unowned authenticated intake",
    )
    repo = "repos/astral-experiments/ohm"
    work.mkdir()
    for label, endpoint in (
        ("run", f"actions/runs/{protocol.CONTACT_RUN}"),
        ("jobs", f"actions/runs/{protocol.CONTACT_RUN}/attempts/1/jobs?per_page=100"),
        ("artifacts", f"actions/runs/{protocol.CONTACT_RUN}/artifacts?per_page=100"),
    ):
        payload = subprocess.check_output(["gh", "api", repo + "/" + endpoint])
        protocol.require(0 < len(payload) < 1 << 20, "oversize issuer metadata")
        (work / (label + ".json")).write_bytes(payload)
    runs = [json.loads((work / (k + ".json")).read_bytes()) for k in ("run", "jobs", "artifacts")]
    r, j, a = runs
    (job,) = j["jobs"]
    (art,) = a["artifacts"]
    protocol.require(
        r["conclusion"] == job["conclusion"] == "success"
        and r["head_sha"] == job["head_sha"] == protocol.CONTACT_HEAD
        and r["id"] == job["run_id"] == protocol.CONTACT_RUN
        and job["id"] == protocol.CONTACT_JOB
        and job["runner_name"] == protocol.CONTACT_RUNNER
        and (art["id"], art["digest"], art["size_in_bytes"], art["name"], art["expired"])
        == (
            record["artifact"],
            "sha256:" + record["sha256"],
            record["bytes"],
            "ctfe-repair-contact",
            False,
        )
        and art["archive_download_url"]
        == "https://api.github.com/" + repo + f"/actions/artifacts/{art['id']}/zip"
        and art["workflow_run"]["id"] == protocol.CONTACT_RUN
        and art["workflow_run"]["head_sha"] == protocol.CONTACT_HEAD
        and 0 < record["bytes"] < 384 << 20,
        "foreign contact job/ZIP",
    )
    dest = work / "contact.zip"
    with subprocess.Popen(
        ["gh", "api", repo + f"/actions/artifacts/{art['id']}/zip"], stdout=subprocess.PIPE
    ) as p, dest.open("xb") as f:
        h = hashlib.sha256()
        n = 0
        while chunk := p.stdout.read(1 << 20):
            n += len(chunk)
            protocol.require(n <= record["bytes"], "oversize official ZIP")
            h.update(chunk)
            f.write(chunk)
        protocol.require(
            p.wait() == 0 and n == record["bytes"] and h.hexdigest() == record["sha256"],
            "incomplete official transfer",
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
