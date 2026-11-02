"""Bind the diagnostic to one fresh worker, then use the signed first-A installer."""

import hashlib
import json
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "ruff-default-owner-pmu"
sys.path.insert(0, str(BASE))
import acquire
import common as c

BRANCH = "charlie/qa-ruff-cgu-green-reasons-20261102"
JOB = "Signed GNU Ruff workspace dependency and work-product inputs"
ARTIFACT = "signed-gnu-ruff-workspace-green-inputs"
PARENT = "0eb852b6abb026160a89243aa2a47fca0f4bbc7b"
SIX_DIGEST = "ecce6fb6cfb765bc272f8333fd809eace1d5cd3fa2b3d101723cb57d962ec6e9"
PARENT_MANIFEST = "d040541042531489d77c3f66bc16032db864121657791650e86a92ca1d31fe15"
PARENT_WORKFLOW = "a522c93dc03c4d5dc9b6afcbd5acc753e04bfdbffda303ed1e0eefa2de84d555"
PRIOR = (
    (
        41349575789,
        124976652509,
        1386,
        "nsc-runner-4ob7h4jb469j6",
        "844d5614-1a0d-475c-b902-58b052416435",
        "2026-11-01T21:05:08Z",
    ),
    (
        41352636822,
        124985942040,
        1389,
        "nsc-runner-p49nsmgis2t2a",
        "31ceaf7f-3b2b-491d-b3ba-66d6e129f9da",
        "2026-11-01T21:44:46Z",
    ),
    (
        41357296901,
        125000003584,
        1394,
        "nsc-runner-6usvjkep7dvgc",
        "5ccbe1fd-0a0a-49b5-9ff8-e8c1e14e405d",
        "2026-11-01T22:39:34Z",
    ),
)


def verify_inherited_sources():
    manifest = BASE / "SHA256SUMS"
    c.need(c.sha(manifest) == PARENT_MANIFEST, "first-A source manifest changed")
    entries = dict(line.split("  ", 1)[::-1] for line in manifest.read_text().splitlines())
    c.need(entries.pop(".github/workflows/ci.yml") == PARENT_WORKFLOW, "historical workflow binding")
    for name, digest in entries.items():
        c.need(c.sha(HERE.parents[1] / name) == digest, ("historical source bytes", name))


def check_fresh(state, excluded):
    data = json.dumps(excluded, sort_keys=True, separators=(",", ":")).encode()
    c.need(hashlib.sha256(data).hexdigest() == SIX_DIGEST, "incorrect six original boot descriptors")
    keys = ("run", "job", "runner_id", "runner", "boot")
    for *prior, ended in PRIOR:
        c.need(
            all(state[k] != v for k, v in zip(keys, prior, strict=True))
            and datetime.fromisoformat(state["started"]) >= datetime.fromisoformat(ended),
            "repeated or overlapping earlier diagnostic",
        )
    return state


@contextmanager
def registration():
    # Both the real installer and historical read_subject re-run this same enrollment from raw data.
    original = acquire.enrollment
    branch, job = c.BRANCH, c.JOB

    def enrolled(prior, jobs, artifacts, excluded, current, this_jobs, env, boot):
        return check_fresh(
            original(prior, jobs, artifacts, excluded, current, this_jobs, env, boot), excluded
        )

    c.BRANCH, c.JOB, acquire.enrollment = BRANCH, JOB, enrolled
    try:
        yield
    finally:
        c.BRANCH, c.JOB, acquire.enrollment = branch, job, original


if __name__ == "__main__":
    verify_inherited_sources()
    if sys.argv[1:] != ["--sources"]:
        c.need(not sys.argv[1:], "unexpected acquisition arguments")
        with registration():
            acquire.main()
