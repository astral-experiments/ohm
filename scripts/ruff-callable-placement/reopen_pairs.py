"""Reopen original physical pair archives in RAM and retain only small checked receipts."""
from contextlib import contextmanager
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

import zstandard

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assess
import callable_decision
import native
import replication

REPO = "astral-experiments/ohm"
RUN = 41484772820
QA = "f417930f23db5aa87a0fc6223f7686fe210ebff3"
BRANCH = "charlie/qa-ruff-db-link-cause-20261102"
PLAN = Path(__file__).with_name("replication.json")
sha = lambda data: hashlib.sha256(data).hexdigest()


def api(path, *, binary=False):
    result = subprocess.check_output(["/home/dev-user/.local/bin/gh-auto", "api", f"repos/{REPO}/" + path])
    return result if binary else json.loads(result)


@contextmanager
def selected_members(raw):
    names = {"entry.json", "histories.json", "decision.json", "pair.json", "case.json", "kernel.json",
             "objects.json", "pmu.json", "storage.json", "test-list.txt", "selected-test.txt", "gdb.txt"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as original, zipfile.ZipFile(buffer, "w") as selected:
        assert original.namelist() == ["callable-placement.tar.zst"]
        with original.open("callable-placement.tar.zst") as item, zstandard.ZstdDecompressor().stream_reader(item) as reader:
            with tarfile.open(fileobj=reader, mode="r|") as tf:
                kept = 0
                seen = set()
                for member in tf:
                    p = Path(member.name)
                    assert not p.is_absolute() and ".." not in p.parts
                    if not member.isfile() or (p.name not in names and p.parent != Path("native-witnesses")):
                        continue
                    assert p not in seen and member.size < 48 << 20
                    kept += member.size
                    assert kept < 300 << 20
                    seen.add(p)
                    selected.writestr(p.as_posix(), tf.extractfile(member).read())
    with zipfile.ZipFile(buffer) as files:
        yield zipfile.Path(files)


def qualify(artifact, job, block):
    assert job["run_id"] == RUN and job["run_attempt"] == 1 and job["head_sha"] == QA
    assert job["status"] == "completed" and job["conclusion"] == "success"
    assert artifact["workflow_run"]["id"] == RUN and artifact["workflow_run"]["head_sha"] == QA
    assert not artifact["expired"] and 0 < artifact["size_in_bytes"] < 64 << 20
    raw = api(f"actions/artifacts/{artifact['id']}/zip", binary=True)
    assert len(raw) == artifact["size_in_bytes"] and "sha256:"+sha(raw) == artifact["digest"]
    with selected_members(raw) as out:
        read = lambda name: json.loads((out/name).read_bytes())
        histories = read("histories.json")
        decision = callable_decision.decide(out, histories)
        assert read("decision.json") == decision and decision["qualified_for_replication"]
        pair = read("pair.json")
        assert pair["block"] == block and pair["entry"] == read("entry.json")
        assert pair["entry"]["qa"] == QA and pair["entry"]["run"] == str(RUN) and pair["plan"] == native.sha(PLAN)
        orders = json.loads(PLAN.read_bytes())["orders"]
        assert pair["order"] == list(orders[block-1])
        ref = PLAN.parent/"attempts"/"41480290105"/"decision.json.gz"
        discovery = json.loads(gzip.decompress(ref.read_bytes()))
        expected = sorted(callable_decision.key(k) for k in discovery["roles"]["C"]["admitted"])
        replayed = []
        original_emit = replication.native.emit
        try:
            replication.native.emit = lambda location, value: replayed.append(value)
            os.environ["GITHUB_RUN_ID"] = str(RUN)
            replication.finish(out, histories, decision, block, pair["order"], expected)
        finally:
            replication.native.emit = original_emit
        assert replayed == [pair]
        for role, phases in histories.items():
            for label, record in phases.items():
                if label == "invalid":
                    continue
                history = "edit" if label in ("empty_old", "edit", "unchanged", "repair") else "clean"
                folder = out/f"{role}-{history}"/label
                inventory = (folder/"test-list.txt").read_bytes()
                assert sha(inventory) == record["verdict"]["test_list"]
                assert len([line for line in inventory.splitlines() if line.endswith(b": test")]) == 168
                verdict = (folder/"selected-test.txt").read_bytes()
                if label == "negative":
                    assert b"OHM_28277_RUNTIME_CHANGED" in verdict and b"0 passed; 1 failed" in verdict
                else:
                    assert b"1 passed; 0 failed" in verdict
                if "sites" in record:
                    sites = [json.loads(line[10:]) for line in (folder/"gdb.txt").read_bytes().splitlines() if line.startswith(b"OHM_SITES ")]
                    assert sites == [record["sites"]]
    return {"pair":pair, "original":{k:artifact[k] for k in ("id","name","digest","size_in_bytes")},
            "producer_job":job["id"], "reader":native.sha(Path(__file__))}


def main(dest):
    dest.mkdir(exist_ok=True, parents=True)
    run = api(f"actions/runs/{RUN}")
    assert (run["head_sha"], run["head_branch"], run["head_repository"]["full_name"], run["run_attempt"], run["event"]) == (QA, BRANCH, REPO, 1, "workflow_dispatch")
    jobs = api(f"actions/runs/{RUN}/jobs?per_page=100")["jobs"]
    rows = api(f"actions/runs/{RUN}/artifacts?per_page=100")["artifacts"]
    parts = []
    for block in range(1, 7):
        job, = [j for j in jobs if j["name"].endswith(f"on independent block {block}")]
        if job["status"] != "completed":
            continue
        assert job["conclusion"] == "success", (block, job["conclusion"])
        a, = [r for r in rows if r["name"] == f"callable-placement-pair-{block}"]
        path = dest/f"block-{block}.json"
        if path.exists():
            record = json.loads(path.read_bytes())
            assert record["original"]["digest"] == a["digest"] and record["reader"] == native.sha(Path(__file__))
        else:
            record = qualify(a, job, block)
            native.emit(path, record)
        parts.append(record["pair"])
        print(f"verified block {block}, job {job['id']}, archive {a['id']}", flush=True)
    if len(parts) == 6:
        assert run["conclusion"] == "success" and run["status"] == "completed"
        native.emit(dest/"summary.json", assess.assess(parts))


if __name__ == "__main__":
    assert __debug__
    main(Path(sys.argv[1]).resolve())
