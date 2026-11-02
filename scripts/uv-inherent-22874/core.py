"""The private real-edit study uses the calibrated worker and independently enrolled source-matched SDKs."""

import os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "handwritten-panel"
sys.path.insert(0, str(BASE))
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
            "fa7a_stack_ctfe318_handwritten",
            "fa7a_stack_ctfe318_handwritten_foreign_inventory",
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
        PAIR["arms"][ROLES[0]]["source"]["epoch"] == 43311
        and PAIR["arms"][ROLES[1]]["source"]["epoch"] == 43420,
        "cache/metadata epochs",
    )
    q = m.read(HERE / "local-native.json")
    guard(
        filehash(HERE / "local-native.json") == PAIR["native_receipt_sha256"]
        and q["matched_source_control"]["commit"] == m.P["roles"][ROLES[0]]["commit"]
        and q["actual_candidate"]["commit"] == m.P["roles"][ROLES[1]]["commit"],
        "unqualified compiler sources",
    )
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
