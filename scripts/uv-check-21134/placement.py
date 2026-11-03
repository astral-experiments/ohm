"""Authenticate public service boot receipts before opening an ordinary or counted history."""

from pathlib import Path
from zipfile import ZipFile
import json, os, re, sys, uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
from media import REPO, Transport, authorize

BRANCH = "charlie/codex-21134-handwritten-check"
PRIMARY = ["marginal.initial", "signed.initial", "marginal.repeat", "signed.repeat"]


def valid_uuid(s):
    return str(uuid.UUID(s)) == s


def identity():
    e = os.environ
    w = Path(e["GITHUB_WORKSPACE"]).resolve()
    head = e["REVIEWED_HEAD"]
    require(
        __debug__
        and e["GITHUB_ACTIONS"] == "true"
        and e["GITHUB_REPOSITORY"] == REPO
        and e["GITHUB_REPOSITORY_ID"] == "1319437234"
        and e["GITHUB_REF"] == "refs/heads/" + BRANCH
        and e["GITHUB_EVENT_NAME"] == "workflow_dispatch"
        and e["GITHUB_RUN_ATTEMPT"] == "1"
        and e["GITHUB_SHA"] == head,
        "private worker or review head",
    )
    require(
        subprocess.check_output(["git", "-C", w / "coordinator", "rev-parse", "HEAD"], text=True).strip()
        == head,
        "coordinator checkout",
    )
    lock = HERE / "G-qualified-lock.json"
    require(sha(lock) == e["G_LOCK"], "wrong activation receipt")
    authorize(read(lock))
    return w, Path(e["RUNNER_TEMP"]).resolve(), head


def placement_args(label, priors):
    require(
        label in PRIMARY and len(priors) == len(set((r["run"], r["job"], r["id"]) for r in priors)),
        "duplicate physical assignment",
    )
    refusal = read(HERE / "signed-R-native-refusal.json")
    require(
        refusal["original_protocol"] == sha(HERE / "protocol.json")
        and refusal["F_G_unchanged"] is True
        and label.startswith("marginal."),
        "signed control was refused by native products",
    )
    seen = {x["label"] for x in priors}
    want = {"marginal.initial"} if label == "marginal.repeat" else set()
    require(seen == want and len(seen) == len(priors), "the original marginal host is required on its repeat")
    return seen


def service(runid, head):
    prefix = "repos/" + REPO + "/actions/runs/" + str(runid)
    r = Transport.gh_json("api", prefix)
    jobs = Transport.gh_json("api", prefix + "/jobs?per_page=100")
    require(
        r["id"] == runid
        and r["head_sha"] == head
        and r["head_branch"] == BRANCH
        and r["repository"]["id"] == r["head_repository"]["id"] == 1319437234
        and r["event"] == "workflow_dispatch"
        and r["run_attempt"] == 1
        and len(jobs["jobs"]) == jobs["total_count"] == 1,
        "wrong service run",
    )
    (j,) = jobs["jobs"]
    require(
        j["run_id"] == runid and j["head_sha"] == head and j["run_attempt"] == 1 and j["runner_id"] > 0,
        "wrong job assignment",
    )
    return r, j


def attest(out, tmp):
    w, _, head = identity()
    e = os.environ
    label = e["SERIES"]
    prior = json.loads(e["PRIOR_BOOTS"])
    placement_args(label, prior)
    live = Transport.gh_json(
        "api", f"repos/{REPO}/actions/runs?head_sha={head}&event=workflow_dispatch&per_page=100"
    )
    require(
        live["total_count"] == len(live["workflow_runs"])
        and int(e["GITHUB_RUN_ID"]) in {v["id"] for v in live["workflow_runs"]},
        "incomplete same-head service census",
    )
    actual = set()
    skipped = []
    for v in live["workflow_runs"]:
        if v["head_branch"] != BRANCH or v["head_sha"] != head or v["id"] >= int(e["GITHUB_RUN_ID"]):
            continue
        evidence = Transport.gh_json("api", f"repos/{REPO}/actions/runs/{v['id']}/jobs?per_page=100")
        require(len(evidence["jobs"]) == evidence["total_count"] == 1, "incomplete earlier assignment")
        (previous,) = evidence["jobs"]
        require(previous["head_sha"] == head and previous["run_id"] == v["id"], "bad previous assignment")
        if previous["conclusion"] == "skipped" and not previous.get("runner_id"):
            skipped.append(v["id"])
        else:
            actual.add(v["id"])
    require(actual == {v["run"] for v in prior}, "missing actual earlier allocation, including repeats")
    hist = read(HERE / "known-boots.json")
    boots = set(hist)
    runner_ids = {v["runner_id"] for v in hist.values() if v.get("runner_id")}
    added = []
    for item in sorted(prior, key=lambda x: PRIMARY.index(x["label"])):
        r, j = service(item["run"], head)
        require(j["id"] == item["job"], "wrong prior job")
        id = item["id"]
        art = Transport.gh_json("api", "repos/" + REPO + "/actions/artifacts/" + str(id))
        o = art["workflow_run"]
        require(
            art["id"] == id
            and art["name"] == "uv-21134-" + item["label"] + "-boot"
            and art["digest"] == "sha256:" + item["sha256"]
            and 0 < art["size_in_bytes"] < 65536
            and not art["expired"]
            and o["id"] == r["id"]
            and o["head_sha"] == head
            and o["repository_id"] == o["head_repository_id"] == 1319437234,
            "bad prior early artifact",
        )
        f = tmp / (str(id) + ".zip")
        Transport.gh_bytes(
            "repos/" + REPO + "/actions/artifacts/" + str(id) + "/zip",
            f,
            art["size_in_bytes"],
            item["sha256"],
        )
        with ZipFile(f) as z:
            require(z.namelist() == ["boot-attestation.json"], "public boot-only scope")
            raw = z.read("boot-attestation.json")
            p = json.loads(raw)
        require(
            p["run"] == r["id"]
            and p["job"] == j["id"]
            and p["head"] == head
            and p["series"] == item["label"]
            and p["G_lock"] == e["G_LOCK"]
            and p["protocol"] == sha(HERE / "protocol.json")
            and p["runner_id"] == j["runner_id"]
            and p["boot"] not in boots
            and valid_uuid(p["boot"])
            and set(hist) <= set(p["excluded"])
            and all(len(p[k]) == 64 for k in ("inherited", "threads", "blocking")),
            "unverified earlier calibration",
        )
        boots.add(p["boot"])
        runner_ids.add(p["runner_id"])
        added.append({**item, "boot": p["boot"], "member_sha256": hashlib.sha256(raw).hexdigest()})
    r, j = service(int(e["GITHUB_RUN_ID"]), head)
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    require(
        valid_uuid(boot)
        and boot not in boots
        and j["runner_id"] not in runner_ids
        and j["runner_name"] == e["RUNNER_NAME"],
        "fresh calibrated VM assignment",
    )
    result = {
        "series": label,
        "run": r["id"],
        "job": j["id"],
        "runner_id": j["runner_id"],
        "runner_name": j["runner_name"],
        "head": head,
        "boot": boot,
        "G_lock": e["G_LOCK"],
        "protocol": sha(HERE / "protocol.json"),
        "excluded": sorted(boots),
        "prior_early": added,
        "historical": sha(HERE / "known-boots.json"),
        "same_head_earlier_runs": sorted(actual),
        "service_skipped_no_runner": sorted(skipped),
    }
    save(out / "placement.json", result)
    return result
