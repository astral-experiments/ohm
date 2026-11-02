"""The private real-edit study uses the calibrated worker and independently enrolled source-matched SDKs."""

import os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "handwritten-panel"
sys.path[:0] = [str(HERE), str(BASE)]
import material as m
import deep, scope

P = m.read(HERE / "study.json")
PAIR = m.read(HERE / "pair.json")
ROLES = P["roles"]
CHECK = [str(m.SDK / "bin/cargo"), *P["score_commands"]]


def guard(v, why):
    return m.guard(v, why)


def filehash(p):
    return m.filesha(p)


def host():
    e = os.environ
    guard(
        PAIR["roles"] == ROLES
        and ROLES
        == [
            "callables_ctfe318_incoherent_domain",
            "callables_ctfe318_incoherent_domain_proc_derive",
        ],
        "wrong physical roles",
    )
    guard(
        m.P["branch"] in ("charlie/codex-20988-handwritten-stage1-check", P["branch"]),
        "source scope",
    )
    m.P["branch"] = P["branch"]
    m.P["roles"] = {k: PAIR["arms"][k]["source"] for k in ROLES}
    w, tmp = m.host()
    origin = w / "coordinator"
    raw = (
        m.sha_git(origin, "cat-file", "commit", "HEAD")
        .split(b"\n\n", 1)[0]
        .splitlines()
    )
    guard(
        [v[7:].decode() for v in raw if v.startswith(b"parent ")] == [P["parent"]]
        and m.sha_git(origin, "rev-parse", "HEAD").decode().strip()
        == e["REVIEWED_HEAD"],
        "direct reviewed workflow head",
    )
    guard(
        e["GITHUB_REPOSITORY_ID"] == "1319437234"
        and e["BUILD_RUN_ID"] == str(P["producer_run"])
        and e["BUILD_HEAD"] == P["producer_head"]
        and e["SDK_LOCK_SHA256"]
        == P["sdk_lock_sha256"]
        == filehash(HERE / "pair.json"),
        "unregistered private experiment",
    )
    guard(
        PAIR["arms"][ROLES[0]]["source"]["epoch"] == 43317
        and PAIR["arms"][ROLES[1]]["source"]["epoch"] == 43319,
        "cache/metadata epochs",
    )
    guard(filehash(HERE / "measurement-plan.json") == P["measurement_plan_sha256"] == PAIR["measurement_plan_sha256"], "different preregistered study")
    gate=__import__("runpy").run_path(str(HERE / "stage1-prerequisite.py"))["verify"]
    guard(filehash(HERE / "stage1-qualified.json")==PAIR["qualified_stage1_sha256"] and gate(m.read(HERE / "stage1-qualified.json"))[0]==8, "unqualified prior native study")
    guard(filehash(HERE/"derive/qualified.json")==PAIR["generated_stage1_qualification_sha256"] and filehash(HERE/"derive/source-role.json")==PAIR["production_overlay_source_sha256"], "different generated-derive source or prior real histories")
    guard(PAIR["format_versions"]=={"incremental":[43317,43319],"metadata":[3,43319]} and filehash(HERE/"derive/intent.json")==PAIR["measurement_plan_sha256"], "different native formats or prospective admission")
    for run, item in PAIR["prior_boots"].items():
        if "attestation_sha256" in item:
            certificate=HERE / "domain" / ("prior-boot-"+run+".json")
            witness=m.read(certificate)
            guard(filehash(certificate)==item["attestation_sha256"] and witness["boot"]==item["boot"] and str(witness["run"])==run and witness["coordinator"]==item["head"], "different additional physical run")
    return w, tmp


def main():
    w, tmp = host()
    cmd = sys.argv[1:]
    guard(len(cmd) == 1, "one action")
    if cmd == ["calibrate"]:
        old, _ = m.pmu(w, tmp)
        old.calibrate()
        import domain_control, scoped, wall_clock
        ready=m.read(w/"trait-results/calibration.json")["ready"]
        mask=set(ready["affinity"])
        guard(mask <= os.sched_getaffinity(0),"enrolled calibration CPUs unavailable")
        os.sched_setaffinity(0,mask)
        scoped.calibrate()
        wall_clock.calibrate(w/"trait-results/blocking-clock",tmp/"validated-wall-probe")
        domain_control.boot()
    elif cmd == ["admit"]:
        import admit_pair

        admit_pair.admit()
    elif cmd == ["migration"]:
        import admit_pair

        import domain_control
        domain_control.migration()
    else:
        raise ValueError(cmd)


if __name__ == "__main__":
    main()
