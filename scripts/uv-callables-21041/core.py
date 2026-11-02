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
    from direct.cumulative_gate import admit as admit_direct
    admit_direct(HERE, P, PAIR)
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
