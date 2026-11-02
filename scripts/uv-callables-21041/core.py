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
            "stock_ctfe318",
            "callables_ctfe318",
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
        PAIR["arms"][ROLES[0]]["source"]["epoch"] == 43310
        and PAIR["arms"][ROLES[1]]["source"]["epoch"] == 43309,
        "cache/metadata epochs",
    )
    plan = m.read(HERE / "measurement-plan.json")
    src = m.read(HERE / "production-source.json")
    replay = m.read(HERE / "source-replay.json")
    guard(filehash(HERE / "measurement-plan.json") == P["measurement_plan_sha256"] == PAIR["plan"]
          and filehash(HERE / "production-source.json") == PAIR["relative_source"] == replay["role_sha256"]
          and plan["control"]["source"] == PAIR["arms"][ROLES[0]]["source"]["commit"]
          and src["parent"] == PAIR["overlay_parent"]["commit"]
          and plan["candidate"]["source"] == src["commit"] == PAIR["arms"][ROLES[1]]["source"]["commit"]
          and replay["candidate"] == src["commit"] and replay["exact_pack_membership"] is True
          and PAIR["prior_boots"] == m.read(HERE / "prior-boots.json"),
          "unqualified production source, offline replay or study")
    guard("fixture" not in PAIR and all(PAIR["arms"][r]["artifact"]["id"] > 0 for r in ROLES),
          "mock SDK inputs cannot execute this physical experiment")
    return w, tmp


def main():
    w, tmp = host()
    cmd = sys.argv[1:]
    guard(len(cmd) == 1, "one action")
    if cmd == ["calibrate"]:
        old, _ = m.pmu(w, tmp)
        old.calibrate()
    elif cmd == ["admit"]:
        import admit_pair

        admit_pair.admit()
    elif cmd == ["migration"]:
        import admit_pair

        admit_pair.migration()
    else:
        raise ValueError(cmd)


if __name__ == "__main__":
    main()
