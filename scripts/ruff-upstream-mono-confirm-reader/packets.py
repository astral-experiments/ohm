"""Authenticate the single registered workflow attempt and extract complete immutable ZIPs."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import zipfile

REPO = "astral-experiments/ohm"
HEAD = "dcf095ed65b3529c231560bee0c5e10fdf76b282"
BRANCH = "charlie/qa-upstream-mono-ruff-20261102"
FACTORY = 41431225435
SOURCE_RUN = 41433784058
QUALIFIER = {"run":41432334895,"id":13136080593,"bytes":152647703,
             "digest":"sha256:270d059ccd438c5222dd7b32f92ab2435a9ac6279e34fe4b57ec249e7e5886c1"}
LABEL = "namespace-profile-ubuntu-24-04-16"
NAME = "ruff-upstream-mono-ruff-confirm-"

def need(condition, reason):
    if not condition:
        raise ValueError(reason)

def load(path):
    return json.loads(path.read_bytes())

def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)

def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def gh():
    return "gh" if os.environ.get("GITHUB_ACTIONS") == "true" else "/home/dev-user/.local/bin/gh-auto"

def api(relative):
    return json.loads(subprocess.check_output([gh(), "api", f"repos/{REPO}/actions/{relative}"]))

def enrollment(run, jobs, artifacts):
    need((run["head_sha"], run["head_branch"], run["run_attempt"], run["event"], run["status"], run["path"],
          run["head_repository"]["full_name"], run["repository"]["full_name"]) ==
         (HEAD, BRANCH, 1, "workflow_dispatch", "completed", ".github/workflows/ci.yml", REPO, REPO),
         "wrong source, workflow, attempt, repository or nonterminal run")
    need(run["name"]==run["display_title"]=="Ruff upstream monomorphization experiment "+HEAD,
         "wrong named experiment")
    rid = run["id"]
    need(jobs["total_count"] == len(jobs["jobs"]) == 6, "incorrect job roster")
    job_rows = {}
    for job in jobs["jobs"]:
        match = re.fullmatch(r"ordinary \(([0-5])\)", job["name"])
        need(match and job["run_id"] == rid and job["head_sha"] == HEAD and job["status"] == "completed"
             and LABEL in job["labels"] and job["id"] > 0, "unregistered matrix job")
        key = int(match[1])
        need(key not in job_rows, "duplicate job rank")
        if job["conclusion"] == "success":
            need(job["runner_id"] and job["runner_name"], "missing runner identity")
        job_rows[key] = {field: job[field] for field in ("id", "name", "conclusion", "runner_id", "runner_name")}
    need(len({j["id"] for j in job_rows.values()}) == 6, "duplicate job ID")
    need(artifacts["total_count"] == len(artifacts["artifacts"]), "truncated artifact listing")
    rows = {}
    for item in artifacts["artifacts"]:
        match = re.fullmatch(re.escape(NAME) + r"([0-5])", item["name"])
        need(match and item["workflow_run"]["id"] == rid and item["workflow_run"]["head_sha"] == HEAD
             and not item["expired"] and item["id"] > 0 and 0 < item["size_in_bytes"] < 512 << 20
             and re.fullmatch(r"sha256:[0-9a-f]{64}", item["digest"] or ""), "unregistered artifact")
        key = int(match[1]); need(key not in rows, "duplicate artifact rank")
        rows[key] = {"id": item["id"], "name": item["name"], "bytes": item["size_in_bytes"], "digest": item["digest"]}
    need(len({a["id"] for a in rows.values()}) == len(rows), "duplicate artifact ID")
    return {"run": rid, "head": HEAD, "attempt": 1, "conclusion": run["conclusion"],
            "jobs": {str(k): v for k, v in job_rows.items()}, "artifacts": {str(k): v for k, v in rows.items()}}

def register(run_id):
    need(run_id==SOURCE_RUN, "different confirmation run")
    qualifier=api(f"artifacts/{QUALIFIER['id']}")
    need(qualifier["name"]=="ruff-upstream-mono-ruff-qualify" and qualifier["id"]==QUALIFIER["id"] and
         qualifier["workflow_run"]["id"]==QUALIFIER["run"] and qualifier["workflow_run"]["head_sha"]==HEAD and
         qualifier["size_in_bytes"]==QUALIFIER["bytes"] and qualifier["digest"]==QUALIFIER["digest"],
         "different independent normal-layout reference")
    run = api(f"runs/{run_id}")
    need(run["id"] == run_id, "wrong run ID")
    record=enrollment(run, api(f"runs/{run_id}/attempts/1/jobs?per_page=100"),
                      api(f"runs/{run_id}/artifacts?per_page=100"))
    record["normal_qualification"]=QUALIFIER
    return record

def bytes_command(relative):
    # Recent gh rejects terminal control bytes in raw responses, even through a pipe.
    cmd=[gh(),"api"]
    if "--allow-escape-sequences" in subprocess.check_output([*cmd,"--help"],text=True):
        cmd.append("--allow-escape-sequences")
    return [*cmd,f"repos/{REPO}/actions/{relative}"]

def upload_proof(raw, rid, job, spec):
    sha=spec["digest"].removeprefix("sha256:")
    endings=[f"SHA256 digest of uploaded artifact is {sha}",
             f"Artifact {spec['name']} successfully finalized. Artifact ID {spec['id']}",
             f"Artifact {spec['name']} has been successfully uploaded! Final size is {spec['bytes']} bytes. Artifact ID is {spec['id']}",
             f"Artifact download URL: https://github.com/{REPO}/actions/runs/{rid}/artifacts/{spec['id']}"]
    lines=raw.splitlines()
    for ending in endings:
        need(sum(bool(re.fullmatch(rb"\d{4}-\d\d-\d\dT[\d:.]+Z "+re.escape(ending.encode()),x)) for x in lines)==1,
             "matrix job upload does not prove this artifact: "+ending)
    return {"job":job["id"],"artifact":spec["id"],"log_sha256":hashlib.sha256(raw).hexdigest(),"receipt":endings}

def bind_job(rid,job,spec):
    raw=subprocess.check_output(bytes_command(f"jobs/{job['id']}/logs"),timeout=120)
    return upload_proof(raw,rid,job,spec)

def archive(spec, archives):
    archives.mkdir(parents=True, exist_ok=True)
    path = archives / (spec["name"] + ".zip")
    if not path.exists():
        tmp = path.with_suffix(".download")
        with tmp.open("xb") as f, subprocess.Popen(bytes_command(f"artifacts/{spec['id']}/zip"),
                                                  stdout=subprocess.PIPE) as proc:
            try:
                total = 0
                while block := proc.stdout.read(1 << 20):
                    total += len(block)
                    need(total <= spec["bytes"], "excess archive bytes")
                    f.write(block)
                need(proc.wait() == 0, "artifact download failed")
            finally:
                if proc.poll() is None:
                    proc.kill(); proc.wait()
        need(tmp.stat().st_size == spec["bytes"] and "sha256:" + digest(tmp) == spec["digest"],
             "wrong complete archive digest or size")
        tmp.replace(path)
    need(path.stat().st_size == spec["bytes"] and "sha256:" + digest(path) == spec["digest"],
         "saved complete archive differs")
    return path

def unpack(path, into):
    into.mkdir()
    with zipfile.ZipFile(path) as z:
        seen = set()
        members = z.infolist()
        need(len(members) < 2000 and sum(i.file_size for i in members) < 1200 << 20, "unbounded archive")
        for i in members:
            p = PurePosixPath(i.filename)
            need(i.filename and not p.is_absolute() and ".." not in p.parts and "\\" not in i.filename
                 and p not in seen and not (i.flag_bits & 1), "unsafe or duplicate archive path")
            seen.add(p)
            kind = stat.S_IFMT(i.external_attr >> 16)
            need(kind in (0, stat.S_IFREG, stat.S_IFDIR) and i.file_size < 384 << 20, "unexpected archive entry")
            dest = into / p
            if i.is_dir(): dest.mkdir(exist_ok=True, parents=True); continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, dest.open("xb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            need(dest.stat().st_size == i.file_size, "truncated extracted member")
