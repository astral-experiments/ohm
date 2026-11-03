"""Receive or recheck the bounded independent reader ZIPs, using the frozen QA definitions."""

import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch
import zipfile


def need(condition, message):
    if not condition:
        raise ValueError(message)


def dump(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def keep(path, contents):
    if path.exists():
        need(path.read_bytes() == contents, f"different prior receipt {path.name}")
    else:
        with path.open("xb") as f:
            f.write(contents)


def document(path, member="reopened.json"):
    with zipfile.ZipFile(path) as z:
        need(z.namelist() == [member] and 0 < z.getinfo(member).file_size < 4 << 20,
             f"wrong bounded ZIP {path.name}")
        return json.loads(z.read(member))


def case_rows(stage):
    return [("admit", 1), ("admit", 2), ("migration", 1)] if stage == "native" else [
        ("three", 1), ("three", 2)
    ]


def remote(root, dest, stage, run, head, artifacts, scope, external):
    route = shutil.which("gh-auto") or "/home/dev-user/.local/bin/gh-auto"
    api = f"repos/{scope.base.REPO}/actions"

    def get(path):
        return subprocess.check_output([route, "api", path], cwd=root)

    meta = json.loads(get(f"{api}/runs/{run}"))
    jobs = json.loads(get(f"{api}/runs/{run}/attempts/1/jobs?per_page=100"))["jobs"]
    published = json.loads(get(f"{api}/runs/{run}/artifacts?per_page=100"))["artifacts"]
    receipts = {}

    def binding(row, job):
        return {k: row[k] for k in ("id", "name", "size_in_bytes", "digest")} | {"job": job}

    def fetch(row):
        n = row["size_in_bytes"]
        need(0 < n <= 4 << 20 and shutil.disk_usage(dest).free > (15 << 30) + n,
             f"storage guard {row['name']}")
        target = dest / (row["name"] + ".zip")
        body = target.read_bytes() if target.exists() else get(f"{api}/artifacts/{row['id']}/zip")
        need(len(body) == n and "sha256:" + sha256(body).hexdigest() == row["digest"],
             f"wrong native ZIP {row['name']}")
        keep(target, body)

    companion = {}
    if stage == "native":
        import stock_original_reader as original
        need(external and (run, head) == (original.ORIGIN["run"], original.ORIGIN["qa"]),
             "missing specific original-native readback")
        with patch.object(scope.receiver, "api", lambda p: json.loads(get(p))):
            receipts.update(original.original())
            rr, rh = external.split("/")
            legs, rows = original.state(int(rr), rh, "success")
        j, = legs
        a, = rows
        need(j["name"] == original.READER and a["name"] == original.NAME and j["conclusion"] == "success",
             "different sole external reader")
        companion = {"run": int(rr), "qa": rh, "archive": binding(a, j["id"])}
        receipts[a["name"]] = companion["archive"]
        fetch(a)
        for i in (1, 2):
            fetch(receipts[f"placement-stock-admission-verified-{i}"])
    else:
        for name, slot in case_rows(stage):
            for kind in ("raw", "verified"):
                row, job = artifacts.choose(meta, jobs, published, run, head, name, slot, kind, previous=True)
                receipts[row["name"]] = binding(row, job)
                if kind == "verified":
                    fetch(row)
    if stage == "score":
        row, = [r for r in published if r["name"] == "placement-stock-survey-final"]
        need(not row["expired"] and (row["workflow_run"]["id"], row["workflow_run"]["head_sha"])
             == (run, head), "wrong final origin")
        job, = [j for j in jobs if any(s["name"] == "Independently reopen both source-bound triplets" for s in j["steps"])]
        need(job["status"] == "completed" and job["conclusion"] == "success"
             and (job["head_sha"], job["run_attempt"]) == (head, 1), "wrong final job")
        receipts[row["name"]] = binding(row, job["id"])
        fetch(row)
    keep(dest / "published.json", dump(dict(repo=scope.base.REPO, run=run, qa=head, stage=stage,
                                           external_reader=companion, receipts=receipts)))


def check(root, dest, stage, run, head, download, external=None):
    sys.path.insert(0, str(root))
    import stock_artifacts as artifacts
    import stock_decision as decision
    import stock_gate as gate
    import stock_scope as scope

    study = scope.read(root / "selected-study.json")
    need(root == scope.HERE and study["source"]["Stock4"] == "fba2663650927209e3589fdc807194f66271bd5a",
         "not the repaired source enrollment")
    if download:
        remote(root, dest, stage, run, head, artifacts, scope, external)
    data = json.loads((dest / "published.json").read_bytes())
    need((data["repo"], data["run"], data["qa"], data["stage"]) ==
         (scope.base.REPO, run, head, stage), "wrong frozen projection origin")
    receipts = data["receipts"]
    rows = {}
    for name, slot in case_rows(stage):
        stem = artifacts.ARTIFACTS[name + "-verified"] + "-" + str(slot)
        if name == "migration":
            import stock_original_reader as original
            stem = original.NAME
            need(data["external_reader"]["archive"] == receipts[stem] and
                 data["external_reader"]["run"] != run, "unbound independent migration")
        raw = artifacts.ARTIFACTS[name + "-raw"] + "-" + str(slot)
        row = receipts[stem]
        archive = dest / (stem + ".zip")
        need(archive.stat().st_size == row["size_in_bytes"]
             and "sha256:" + scope.base.sha(archive) == row["digest"], "wrong physical reader bytes")
        obj = document(archive)
        need(obj["raw"] == receipts[raw] and obj["raw"]["job"] != row["job"]
             and (obj["run"], obj["qa"]) == (run, head), "unbound raw producer or source")
        if name == "migration":
            need(obj["reader_origin"] == {k: data["external_reader"][k] for k in ("run", "qa")},
                 "reader did not execute on the expected external job")
        rows[name, slot] = (obj, row, archive)
    if stage == "native":
        def local(run_id, qa, group, slot, kind, out, cap, *, previous):
            _, rec, file = rows[group, slot]
            need((run_id, qa, kind) == (run, head, "verified") and file.stat().st_size <= cap,
                 "different enrolled native reader")
            shutil.copyfile(file, out)
            return rec

        with tempfile.TemporaryDirectory(dir=dest) as t, ExitStack() as st:
            st.enter_context(patch.object(scope, "bind", lambda: study))
            st.enter_context(patch.object(artifacts, "receive", local))
            st.enter_context(patch.dict(os.environ, {"RUNNER_TEMP": t}))
            result = gate.check(run, head, None, previous=False, migration=True)
    else:
        out = []
        for key in case_rows(stage):
            obj, binding, _ = rows[key]
            out.append(obj | {"reader": binding})
        result = decision.summarize(out, study)
        path = dest / "placement-stock-survey-final.zip"
        aggregate = receipts["placement-stock-survey-final"]
        need(path.stat().st_size == aggregate["size_in_bytes"]
             and "sha256:" + scope.base.sha(path) == aggregate["digest"]
             and result == document(path, "decision.json"), "independent aggregate differs")
    keep(dest / "recomputed.json", dump(result))
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("qa_dir", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("stage", choices=["native", "score"])
    p.add_argument("run", type=int)
    p.add_argument("head")
    p.add_argument("--receive", action="store_true")
    p.add_argument("--external-reader", help="successful independent migration reader as RUN/QA")
    a = p.parse_args()
    a.destination.mkdir(exist_ok=True, parents=True)
    check(a.qa_dir.resolve(), a.destination.resolve(), a.stage, a.run, a.head, a.receive, a.external_reader)
    print("Verified", a.stage, a.run, sha256((a.destination / "recomputed.json").read_bytes()).hexdigest())
