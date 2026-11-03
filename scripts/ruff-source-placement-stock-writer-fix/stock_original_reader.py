"""Read the exact successful native producers in the run whose final job-name lookup failed."""

import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stock_artifacts as artifacts
import stock_gate as gate
import stock_migration as migration
import stock_migration_reader as reader
import stock_scope as scope

need = scope.base.need
ORIGIN = scope.read(scope.HERE / "original-native-history.json")
READER = "Reopen the frozen native migration archive after the producer name lookup failed"
NAME = "placement-stock-original-migration-reopened"
API = "repos/" + scope.base.REPO + "/actions"


def state(run, head, outcome):
    api = scope.receiver.api
    p = f"{API}/runs/{run}"
    m = api(p)
    need((m["id"], m["head_sha"], m["head_branch"], m["event"], m["run_attempt"],
          m["head_repository"]["full_name"], m["status"], m["conclusion"]) ==
         (run, head, scope.BRANCH, "workflow_dispatch", 1, scope.base.REPO, "completed", outcome),
         "wrong native acquisition or reader")
    jobs = [j for j in api(p + "/attempts/1/jobs?per_page=100")["jobs"] if j["conclusion"] != "skipped"]
    rows = api(p + "/artifacts?per_page=100")["artifacts"]
    need(all((j["run_id"], j["head_sha"], j["run_attempt"], j["status"]) ==
             (run, head, 1, "completed") for j in jobs), "unexpected native job origin")
    need(all(not a["expired"] and (a["workflow_run"]["id"], a["workflow_run"]["head_sha"]) ==
             (run, head) for a in rows), "native archive expired or has a different origin")
    return jobs, rows


def original():
    jobs, rows = state(ORIGIN["run"], ORIGIN["qa"], "failure")
    need({j["name"]: {k: j[k] for k in ("id", "conclusion")} for j in jobs} == ORIGIN["jobs"],
         "the original five successful and one failed jobs differ")
    bad, = [j for j in jobs if j["conclusion"] != "success"]
    need(bad["id"] == 125667529470 and
         [s["name"] for s in bad["steps"] if s["conclusion"] == "failure"] == [ORIGIN["failed_step"]],
         "different failure in the original workflow")
    bound = ORIGIN["artifacts"]
    need(len(rows) == len(bound) == 5 and
         all(all(a[k] == v for k, v in bound[a["name"]].items() if k != "job") for a in rows)
         and all(any(j["id"] == a["job"] and j["conclusion"] == "success" for j in jobs)
                 for a in bound.values()), "different native immutable artifacts")
    return bound


def fetch(row, dest, cap):
    n = row["size_in_bytes"]
    need(not dest.exists() and 0 < n <= cap and shutil.disk_usage(dest.parent).free > (15 << 30) + n,
         "storage reserve or compressed original size")
    scope.receiver.api(f"{API}/artifacts/{row['id']}/zip", dest)
    need(dest.stat().st_size == n and "sha256:" + scope.base.sha(dest) == row["digest"],
         "wrong original compressed bytes")
    return row


def migration_readback(dest):
    study = scope.bind()
    frozen = original()
    raw = frozen["placement-stock-migration-raw-1"]
    ref = study["admissions"]["C3b_native"]
    with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as t:
        d = Path(t)
        files = [d / n for n in ("migration.zip", "C3b.zip", "Stock4.zip")]
        fetch(raw, files[0], 3 << 30)
        old = migration.guarded_artifacts.receive(ref["run"], ref["qa"], "admit", 1, "raw",
                                                  files[1], 2 << 30, previous=True)
        need(old == ref["option_raw"], "different original C3b donor")
        new = fetch(frozen["placement-stock-admission-raw-1"], files[2], 2 << 30)
        with zipfile.ZipFile(files[0]) as archive:
            verified = reader.scan(archive, {"C3b": (files[1], old, 3), "Stock4": (files[2], new, 4)},
                                   study, ORIGIN["run"], ORIGIN["qa"])
    verified.update(raw=raw, reader_origin={"run": int(os.environ["GITHUB_RUN_ID"]),
                                            "qa": os.environ["GITHUB_SHA"]})
    scope.base.save(dest, verified)


def replacement(frozen):
    external = frozen["independent_migration_reader"]
    jobs, rows = state(external["run"], external["qa"], "success")
    j, = jobs
    a, = rows
    expected = external["archive"]
    need(j["name"] == READER and j["id"] == expected["job"] and j["conclusion"] == "success"
         and a["name"] == NAME and all(a[k] == v for k, v in expected.items() if k != "job"),
         "different external migration receipt")
    return expected


def certify(dest):
    frozen = scope.read(scope.HERE / "native-enrollment.json")
    need((frozen["run"], frozen["qa"]) == (ORIGIN["run"], ORIGIN["qa"])
         and int(os.environ["ADMISSION_RUN"]) == ORIGIN["run"], "different native acquisition")
    physical = original()
    extra = replacement(frozen)

    def select(run, head, group, slot, kind, out, cap, *, previous):
        need((run, head) == (ORIGIN["run"], ORIGIN["qa"]) and previous and kind == "verified",
             "different requested native prerequisite")
        if group == "migration":
            need(slot == 1, "unregistered migration")
            return fetch(extra, out, cap)
        need(group == "admit" and slot in (1, 2), "unregistered native admission")
        return fetch(physical[f"placement-stock-admission-verified-{slot}"], out, cap)

    with patch.object(artifacts, "receive", select):
        gate.check(frozen["run"], frozen["qa"], dest, previous=True, migration=True)


if __name__ == "__main__":
    mode, dest = sys.argv[1:]
    {"migration": migration_readback, "certify": certify}[mode](Path(dest))
