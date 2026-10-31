"""Bind the unscored, source-qualified cold native replay and reject reused hosts."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.environ.setdefault("RUNNER_TEMP", "/home/runner/work/_temp")

import bindings as b
from bindings import need

HEAD = "2969895dc49c9d8970ef121e1ff024ef001dc7ce"
RUN, JOB = 41209337030, 124560845134
BRANCH = "charlie/qa-branch-return-execstop-20261031"
ARTIFACT = "cold-Ruff-Koff-exec-qualification"
SOURCE_HASH = "6c46d80e12a69c496cbcc9b8db60d0ab33a143905a33044916c4c766b668c409"
SOURCES = ("observe.c", "read_events.py", "fixture.c", "long_argv.py", "control-script", "run_cases.py", "qualify.py")
PREVIOUS = {
    "41200174886/01": "cf938e9c-a8d2-4a0d-8260-fb5f89d89d65",
    "41200174886/02": "3b0e4081-536a-4f6a-a945-674825be2329",
    "41204995845/01": "3060b886-0ac1-46a3-a1c1-a3c34b9073b6",
    "41204995845/02": "701225ea-feee-4195-82a3-9a1f70d39c46",
}
FILE = b.HERE / "kernel-qualification.json"
AUDIT = b.HERE / "kernel-contact-independent.json"
ROOT_AUDIT = b.HERE / "kernel-contact-root.json"
WORK = b.ROOT / "kernel-qualification"
OUT = b.OUT / "kernel-qualification"
OBSERVER = WORK / "tools/observe"
COUNTS = {"typed": 375, "full": 379, "wild": 69, "system": 62, "execs": 4188}


def hexsha(x):
    return isinstance(x, str) and bool(re.fullmatch(r"[a-f0-9]{64}", x))


def boot_id(x):
    return isinstance(x, str) and bool(re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", x))


def spec(seal=None, audit_raw=None, root_raw=None):
    seal = json.loads(FILE.read_bytes()) if seal is None else seal
    raw = AUDIT.read_bytes() if audit_raw is None else audit_raw
    root_raw = ROOT_AUDIT.read_bytes() if root_raw is None else root_raw
    need((seal.get("schema"), seal.get("head"), seal.get("run"), seal.get("job"), seal.get("attempt")) ==
         (1, HEAD, RUN, JOB, 1), "wrong source-qualified exec contact")
    need(hexsha(seal.get("independent_sha256")) and hashlib.sha256(raw).hexdigest() == seal["independent_sha256"],
         "missing or changed independent successful cold contact; stop before acquisition")
    a = json.loads(raw)
    need(hexsha(seal.get("root_independent_sha256")) and hashlib.sha256(root_raw).hexdigest() == seal["root_independent_sha256"],
         "missing or changed independent whole-ELF cold readback")
    root = json.loads(root_raw)
    art = seal.get("artifact")
    need(isinstance(art, dict) and type(art.get("id")) is int and art["id"] > 0 and
         type(art.get("size")) is int and 0 < art["size"] < 2**30 and
         all(hexsha(x) for x in (art.get("sha256"), seal.get("complete_sha256"), seal.get("offline_sha256"))),
         "incomplete official native contact ZIP")
    need(isinstance(a, dict) and (a.get("schema"), a.get("kind"), a.get("qualified")) ==
         (1, "gnu-positive-exec-Koff-cold", True)
         and (a.get("run"), a.get("attempt"), a.get("head"), a.get("archive_sha256")) == (RUN, 1, HEAD, art["sha256"])
         and a.get("observer_sources_sha256") == SOURCE_HASH and a.get("source_manifest") == b.spec()["manifest"]
         and a.get("counts") == COUNTS and boot_id(a.get("boot")) and a["boot"] == seal.get("boot")
         and a["boot"] not in PREVIOUS.values()
         and all(hexsha(a.get(k)) for k in ("positive_ledger_sha256", "observer_sha256", "system_ld_sha256",
                                           "typed_sha256", "cli_sha256", "reader_sha256", "marker_sha256")),
         "incomplete or mismatched independent physical contact")
    need((root["head"], root["job"], root["run"], root["boot"], root["complete"]) ==
         (HEAD, JOB, RUN, a["boot"], seal["complete_sha256"]) and
         root["official_artifact"] == {"id": art["id"], "sha256": art["sha256"], "size_in_bytes": art["size"]} and
         (root["raw_kernel"], root["native_fingerprint"], root["source_manifest"]) ==
         (a["positive_ledger_sha256"], a["marker_sha256"], a["source_manifest"]) and
         (root["typed"], root["rustcs"], root["wild_links"], root["gnu_links"], root["performance_observations"]) ==
         (375, 379, 69, 62, 0) and root["family"] == {"displaced": 0, "images": 86, "lifetimes": 13915,
         "positive_execs": 4188, "reaped": 13915} and root["compiler_owners"]["actual_rustcs"] == 4 and
         all(root["whole_elf"][k]["whole"] == a[k + "_sha256"] for k in ("cli", "reader")),
         "independent native family, tools, or full ELF readbacks disagree")
    return seal, a, root


def fresh_boot(boot, contact):
    need(boot_id(boot) and boot not in {*PREVIOUS.values(), contact["boot"]}, "reused pilot or qualification boot")


def enrollment(seal):
    return {"run": RUN, "head": HEAD, "artifact": seal["artifact"]["id"], "archive_sha256": seal["artifact"]["sha256"],
            "independent_sha256": seal["independent_sha256"], "root_independent_sha256": seal["root_independent_sha256"]}


def pair(left, right, contact):
    """A result may be admitted only after reopening both official enrollment records."""
    need({left["position"], right["position"]} == {"01", "02"} and left["run"] == right["run"]
         and left["head"] == right["head"] and left["attempt"] == right["attempt"] == 1, "unmatched two-worker enrollment")
    for item in (left, right):
        fresh_boot(item["boot"], contact)
        need(item["kernel_contact"] == enrollment(spec()[0]), "different genuine native contact in the two-worker pilot")
    need(left["boot"] != right["boot"], "workers share a kernel boot")


def official(run, jobs, artifacts, seal):
    need((run["id"], run["head_sha"], run["run_attempt"], run["head_branch"], run["event"], run["status"],
          run["conclusion"], run["repository"]["full_name"]) ==
         (RUN, HEAD, 1, BRANCH, "workflow_dispatch", "completed", "success", b.REPO), "unqualified official run")
    need(jobs["total_count"] == len(jobs["jobs"]) == artifacts["total_count"] == len(artifacts["artifacts"]) == 1,
         "unexpected job or artifact count")
    job, = jobs["jobs"]
    need((job["id"], job["head_sha"], job["name"], job["status"], job["conclusion"]) ==
         (JOB, HEAD, "native", "completed", "success"), "unqualified native job")
    steps = {s["name"]: s["conclusion"] for s in job["steps"]}
    need(all(steps.get(k) == "success" for k in ("Establish fresh task-owned filesystem and native fixture controls",
             "Compare true-empty ordinary and kernel-observed Ruff binaries")), "missing physical native or empty qualification")
    art, = artifacts["artifacts"]
    expected = seal["artifact"]
    need((art["name"], art["id"], art["size_in_bytes"], art["digest"], art["expired"], art["workflow_run"]["id"],
          art["workflow_run"]["head_sha"]) == (ARTIFACT, expected["id"], expected["size"], "sha256:" + expected["sha256"],
                                               False, RUN, HEAD), "different official cold qualification archive")


def original(path, seal, audit):
    need(path.stat().st_size == seal["artifact"]["size"] and b.sha(path) == seal["artifact"]["sha256"], "wrong original ZIP")
    with zipfile.ZipFile(path) as z:
        need(len(z.infolist()) == len(set(z.namelist())) and "refusal.txt" not in z.namelist(), "refused or duplicate contact")
        def get(name, expected_sha=None):
            data = z.read(name)
            if expected_sha:
                need(hashlib.sha256(data).hexdigest() == expected_sha, ("changed official contact member", name))
            return json.loads(data)
        done = get("complete.json", seal["complete_sha256"])
        replay = get("offline-reopened.json", seal["offline_sha256"])
        enroll = get("enrollment.json")
        catalog = get("observed/catalog.json")
        native = get("fixtures/qualified.json")
        need(done["host_complete"] is True and replay["performance_observations"] == 0 and
             (enroll["run"], enroll["head"], enroll["attempt"], enroll["boot"], enroll["source"], enroll["arm"], enroll["counter"]) ==
             (RUN, HEAD, 1, audit["boot"], b.spec(), "Koff", None), "wrong contact checkout or SDK")
        need((replay["run"], replay["head"], replay["boot"], replay["typed"], replay["full_rustcs"], replay["wild_outputs"],
              replay["gnu_configure_links"], replay["physical_execs"]) == (RUN, HEAD, audit["boot"], 375, 379, 69, 62, 4188)
             and replay["positive_ledger"] == done["ledger_sha256"] == audit["positive_ledger_sha256"]
             and done["typed_sha256"] == audit["typed_sha256"]
             and replay["bodies"] == done["native"] == {"cli": audit["cli_sha256"], "reader": audit["reader_sha256"]},
             "wrong independent programs, typed roster, or native events")
        need(catalog["sysld"]["identity"][0] == audit["system_ld_sha256"] and
             hashlib.sha256(z.read("observed/cold-A/dep-lib-zmij")).hexdigest() == audit["marker_sha256"] and
             hashlib.sha256(z.read("fixtures/observe.elf")).hexdigest() == done["observer_sha256"] == native["observer_sha256"] ==
             audit["observer_sha256"] and native["qualified"] is True, "different native source, tool or marker")
        with z.open("observed/cold-A/kernel.tsv.gz") as file, gzip.GzipFile(fileobj=file) as stream:
            need(hashlib.file_digest(stream, "sha256").hexdigest() == done["ledger_sha256"], "changed original positive ledger")
    return replay


def prepare(checkout, current_boot):
    seal, audit, root_audit = spec()
    fresh_boot(current_boot, audit)
    b.prepare_checkout(checkout, HEAD, "scripts/branch-return-execstop")
    package = checkout / "scripts/branch-return-execstop"
    subprocess.run(["sha256sum", "--strict", "--check", "--status", "SHA256SUMS"], cwd=package, check=True)
    source = "".join(f"{b.sha(package/'kernel'/name)}  {name}\n" for name in SOURCES).encode()
    need(hashlib.sha256(source).hexdigest() == SOURCE_HASH, "different positive observer/fixture sources")
    WORK.mkdir()
    OUT.mkdir()
    api = "repos/" + b.REPO + "/actions/"
    def get(name):
        return json.loads(subprocess.check_output(["gh", "api", api + name]))
    base = "runs/" + str(RUN)
    official(get(base), get(base + "/attempts/1/jobs"), get(base + "/artifacts"), seal)
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        path = Path(tmp) / "qualification.zip"
        with path.open("xb") as sink:
            subprocess.run(["gh", "api", api + "artifacts/" + str(seal["artifact"]["id"]) + "/zip"], stdout=sink, check=True)
        checked = original(path, seal, audit)
    subprocess.run([sys.executable, "-IB", package / "fixtures.py", WORK / "tools", OUT / "fixtures"], check=True)
    fixtures = json.loads((OUT / "fixtures/qualified.json").read_bytes())
    need(fixtures["qualified"] is True and b.sha(OBSERVER) == fixtures["observer_sha256"] == audit["observer_sha256"],
         "this boot's observer ELF differs from the source-qualified one")
    b.save(OUT / "binding.json", {"official": seal, "independent": audit, "root_independent": root_audit, "source": str(package),
           "observer": str(OBSERVER), "boot": current_boot, "excluded_boots": dict(PREVIOUS, qualification=audit["boot"]),
           "official_reopened": checked})
    return enrollment(seal)


if __name__ == "__main__":
    left, right = (json.loads(Path(path).read_bytes()) for path in sys.argv[1:])
    pair(left, right, spec()[1])
    print("Both enrolled positions came from distinct, eligible kernel boots.")
