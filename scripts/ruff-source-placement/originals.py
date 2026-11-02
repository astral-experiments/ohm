"""Reopen an exact successful Actions producer, even if a later reader job is queued or failed."""
import json
import os
import shutil

from common import BRANCH, HERE, REPO, need, sha
import receiver

ORIGIN = 41478151188
ORIGINAL_QA = "b1dc1a4f68436a260a4c15e2562aec5f4c550434"
INPUTS = {
    1: (125389080510, 13159253849, 203340395, "0076aef44e53b5fcd6c647e1630357f5f2fa0e3558c2b7fa8b994cb74b6db374"),
    2: (125389079780, 13160176061, 171259521, "db0b4eb91950f9d4e229e6baac054d0f079896c3ab2c4c827f1daea39994afbc"),
}


def check_producer(meta, jobs, artifacts, run, head, stage, slot, kind, *, frozen):
    need(meta["id"] == run and meta["head_sha"] == head and meta["head_branch"] == BRANCH
         and meta["run_attempt"] == 1 and meta["event"] == "workflow_dispatch"
         and meta["head_repository"]["full_name"] == REPO, "different immutable native workflow")
    if frozen:
        need((run,head,stage,kind)==(ORIGIN,ORIGINAL_QA,"admit","raw")
             and meta["status"] == "completed" and meta["conclusion"] == "failure", "not the closed original reader refusal")
    else:
        need(os.environ["GITHUB_REPOSITORY"] == REPO and os.environ["GITHUB_SHA"] == head and
             int(os.environ["GITHUB_RUN_ID"]) == run and int(os.environ["GITHUB_RUN_ATTEMPT"]) == 1
             and meta["status"] in ("in_progress","queued","completed"), "not the current verified caller")
    job_name = {
        "raw": f"Reversible source placement ordinary Cargo ldv-placement-{stage} block {slot}",
        "verified": f"Independent whole placement artifact and native reader ldv-placement-{stage} {slot}",
    }[kind]
    job, = [j for j in jobs if j["name"] == job_name]
    need(job["run_id"] == run and job["head_sha"] == head and job["run_attempt"] == 1 and
         job["status"] == "completed" and job["conclusion"] == "success", "corpus came from a different or unsuccessful producer")
    name = f"placement-{stage}-{kind}-{slot}"
    row, = [a for a in artifacts if a["name"] == name]
    need(not row["expired"] and row["workflow_run"]["id"] == run and row["workflow_run"]["head_sha"] == head and
         row["workflow_run"]["head_branch"] == BRANCH and row["size_in_bytes"] > 0 and row["digest"].startswith("sha256:"),
         "wrong artifact, owner or source")
    if frozen:
        expected_job, expected_id, size, digest = INPUTS[slot]
        need((job["id"],row["id"],row["size_in_bytes"],row["digest"]) == (expected_job,expected_id,size,"sha256:"+digest),
             "changed original physical job, artifact ID, compressed size or checksum")
    return row


def fetch(run, head, stage, slot, kind, dest, cap, *, frozen=False):
    if frozen:
        source=json.loads((HERE/"attempts/native-reader.json").read_bytes())["unchanged_source_sha256"]
        need(all(sha(HERE/n)==v for n,v in source.items()), "different subject, counter, native custody or SDK enrollment")
    path = f"repos/{REPO}/actions/runs/{run}"
    meta = receiver.api(path)
    jobs = receiver.api(path+"/attempts/1/jobs?per_page=100")["jobs"]
    artifacts = receiver.api(path+"/artifacts?per_page=100")["artifacts"]
    row = check_producer(meta,jobs,artifacts,run,head,stage,slot,kind,frozen=frozen)
    size = row["size_in_bytes"]
    need(size <= cap and shutil.disk_usage(dest.parent).free > (15<<30)+size, "inadequate room for authentic received bytes")
    receiver.api(f"repos/{REPO}/actions/artifacts/{row['id']}/zip", dest)
    need(dest.stat().st_size == size and "sha256:"+sha(dest) == row["digest"], "changed received native ZIP")
    return {k:row[k] for k in ("id","name","size_in_bytes","digest")}
