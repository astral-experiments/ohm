"""Exercise the source certificate guard without obtaining a native compiler or reading counters."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def run(tmp):
    os.environ.setdefault("RUNNER_TEMP", str(tmp))
    import subjects

    capsule = tmp / "replay.json"
    descriptor = tmp / "binding.json"
    source_commit = "c9a6a212d38d778ed0e9d2c7057a9dedb179fff2"
    sha = "1" * 64
    qual = {"source": source_commit, "manifest": sha, "members": 81}
    e = {
        "run": 41227867294,
        "head": "2c305c16f72e9797a724f42adee34e9adb717792",
        "job": 124615704444,
        "attempt": 1,
        "artifacts": {
            n: {}
            for n in (
                "first-session-linux-source-driver",
                "first-session-linux-source-observations",
            )
        },
        "qualified": qual,
    }
    states = {
        n: {"return_elf": "a", "first_B": "b"}
        for n in ("E-cold-A-to-K", "E-first-A-to-K", "K-first-A-to-E", "K-packed-A-to-E")
    }
    proof = {
        "official": e,
        "trusted_member_count": 81,
        "restored": {"members": 81, "commit": source_commit, "manifest": sha},
        "whole_cargo_counts": None,
        "cross_readers": states,
        "actual_native_test_logs_sha256": dict.fromkeys(range(11), "test"),
        "native_replayed_here": {
            "a": {"value": 17, "observed": {"17": 0, "18": 19}},
            "b": {"value": 29, "observed": {"29": 0, "30": 19}},
        },
    }

    def check(s, p, foreign_sha=False):
        capsule.write_text(json.dumps(p))
        rec = {
            "source": source_commit,
            "manifest": sha,
            "raw_sha256": hashlib.sha256(capsule.read_bytes()).hexdigest(),
        }
        if foreign_sha:
            rec["raw_sha256"] = "0" * 64
        descriptor.write_text(json.dumps({"schema": 1, "source": s, "reviewer": rec}))
        return subjects.enrollment(descriptor, capsule)

    assert check(e, proof) == e
    fail = 0

    def rejected(f):
        nonlocal fail
        try:
            f()
        except (ValueError, KeyError):
            fail += 1
            return
        raise AssertionError("accepted wrong native enrollment")

    rejected(lambda: check(None, proof))
    rejected(lambda: check(e, proof, True))
    for k, bad in (
        ("run", 41227026886),
        ("head", "5715d83f60cdf6a4014ca2a5292a3a6fe78ee24d"),
        ("attempt", 2),
        ("job", 124613212397),
        ("artifacts", {"a": {}, "b": {}}),
    ):
        rejected(lambda: check(e | {k: bad}, proof))
    for k, bad in (
        ("official", {}),
        ("trusted_member_count", 80),
        ("cross_readers", dict(list(states.items())[:-1])),
        ("actual_native_test_logs_sha256", {}),
        ("whole_cargo_counts", 35),
    ):
        rejected(lambda: check(e, proof | {k: bad}))
    changed = deepcopy(proof)
    changed["native_replayed_here"]["b"]["observed"]["30"] = 0
    rejected(lambda: check(e, changed))
    print(json.dumps({"synthetic_only": True, "positive": 1, "refused": fail}, sort_keys=True))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        run(Path(tmp))
