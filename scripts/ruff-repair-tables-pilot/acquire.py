"""Once per official worker, restore the original, already accepted E through its own verifier."""

import json
from pathlib import Path
import sys
import subprocess

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "branch-storage-e-confirmation")]
import source_binding as bound
import policy


def main(src):
    bound.official_job()
    b = policy.b
    bound.need(
        b.git(src, "rev-parse", "HEAD") == bound.QA and not (b.ROOT / "physical-sdks").exists(),
        "source observer or fresh work changed",
    )
    trusted = policy.checked_source.enrollment()
    api = lambda path: json.loads(
        subprocess.check_output(["gh", "api", "repos/" + b.REPO + "/actions/" + path])
    )
    policy.checked_source.official(api, trusted)
    prior = json.loads((HERE / "inputs/previous.json").read_bytes())
    rid = prior["official"]
    head = prior["head"]
    top = api(f"runs/{rid}")
    old_jobs = api(f"runs/{rid}/attempts/1/jobs?per_page=100")["jobs"]
    by_job = {j["id"]: j for j in old_jobs}
    by_media = {a["id"]: a for a in api(f"runs/{rid}/artifacts?per_page=100")["artifacts"]}
    bound.need(
        (top["head_sha"], top["run_attempt"], top["conclusion"], top["path"])
        == (head, 1, "success", ".github/workflows/ci.yml")
        and len(prior["sessions"]) == 12,
        "unverified earlier measurement run",
    )
    for pos, r in prior["sessions"].items():
        j = by_job[r["job"]]
        a = by_media[r["id"]]
        bound.need(
            (j["head_sha"], j["conclusion"]) == (head, "success")
            and j["name"].endswith(" " + pos)
            and (a["digest"], a["size_in_bytes"], a["workflow_run"]["id"], a["workflow_run"]["head_sha"])
            == ("sha256:" + r["sha256"], r["size"], rid, head)
            and a["name"] == "checked-e-storage-confirmation-" + pos,
            "incorrect previous job/ZIP",
        )
    b.save(b.OUT / "previous-source-hardware.json", prior)
    rows = policy.acquire(src)
    bound.need(
        rows["E"]["bin/cargo"][0] == b.CARGO_ELF
        and rows["E"][b.WILD][0] == b.WILD_ELF
        and len(rows["E"]) == 81,
        "different original SDK",
    )
    terminal = {
        "source": bound.P,
        "sdk_manifest": trusted["qualified"]["manifest"],
        "run": trusted["run"],
        "job": trusted["job"],
        "archives": trusted["artifacts"],
        "physical_driver": trusted["qualified"]["driver"],
    }
    b.save(b.OUT / "sdk/authoritative-E.json", terminal)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
