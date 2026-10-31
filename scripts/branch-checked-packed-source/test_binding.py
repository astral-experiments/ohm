"""Reject a different commit, source-only success, wrong carrier or a counterfeit native readback."""

import argparse
import copy
import gzip
import json
from pathlib import Path
import sys
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import corrected as s
import locate_checked as loc
import locate_e
import read_collision as reader
from objects import need

F = "c6fe8ecda65452c105f85367a009af80cbb5efbc"


def no(fn):
    try:
        fn()
    except (RuntimeError, AssertionError, ValueError, KeyError, IndexError, OSError):
        return True
    raise AssertionError("a rejected input was incorrectly admitted")


def static():
    x = s.load()
    need(
        x["role"]["commit"] == s.SHA
        and x["rebase_parent"]["commit"] == s.PARENT
        and x["anchor"]["commit"] == s.ANCHOR,
        "source ancestry",
    )
    for p in ("compiler", "library", "tests", "src/bootstrap"):
        need(
            x["rebase_parent"][p] == x["previous"][p]
            and x["anchor"][p] == s.reg.SOURCE()["roles"]["F"].get(p, x["anchor"][p]),
            "different executable source",
        )
    a = json.loads((HERE / "inputs/old-natural-F.json").read_bytes())
    need(
        a["E"] == s.PREVIOUS
        and a["F"] == F
        and a["regenerated_raw_B83"] != a["packed_payload_B29"]
        and a["same_foreign_packed_inode"] is True
        and a["older_and_newer_session_prefix_differ"] is True,
        "natural original",
    )
    c = json.loads((HERE / "inputs/old-cargo-cases.json").read_bytes())
    need(
        c["cases"]["conflicting-raw"]["program"]
        == c["cases"]["raw-only-old"]["program"]
        != c["cases"]["honest"]["program"]
        and c["cases"]["malformed-raw"]["status"] == 101,
        "old collision not observed",
    )
    a = json.loads((HERE / "inputs/old-run-make.json").read_bytes())
    need(
        a["conflicting-object"]["recovered"]
        == a["conflicting-object"]["A"]
        != a["conflicting-object"]["B"]
        and a["damaged-object"]["recovered"] == a["damaged-object"]["B"],
        "old compiler negative missing",
    )
    original = s.ORIGINAL_ARTIFACT

    def run_catalog():
        head = "a" * 40
        run = 7
        event = dict(
            id=run,
            head_sha=head,
            head_branch=s.REF[11:],
            run_attempt=1,
            event="workflow_dispatch",
            path=".github/workflows/ci.yml",
            conclusion="success",
        )
        jobs = [
            dict(
                id=8,
                name=loc.NAME,
                head_sha=head,
                run_attempt=1,
                status="completed",
                conclusion="success",
                steps=[dict(name=n, conclusion="success") for n in loc.STEPS],
            )
        ]
        artifacts = [
            dict(**row, name=name, expired=False, workflow_run=dict(id=run, head_sha=head))
            for name, row in original["artifacts"].items()
        ]
        return run, head, event, jobs, artifacts

    def official(*args):
        return locate_e.check(*args, ref=s.REF, job_name=loc.NAME, steps=loc.STEPS)

    args = run_catalog()
    need(official(*args)["job"] == 8, "normal official contract")
    cases = []
    for key, val in (
        ("run_attempt", 2),
        ("head_sha", "b" * 40),
        ("head_branch", s.old.REF[11:]),
        ("conclusion", "failure"),
    ):
        a = copy.deepcopy(args)
        a[2][key] = val
        cases.append(no(lambda: official(*a)))
    a = copy.deepcopy(args)
    a[3][0]["steps"] = [v for v in a[3][0]["steps"] if v["name"] != loc.OLD_STEP]
    cases.append(no(lambda: official(*a)))
    a = copy.deepcopy(args)
    a[4][0]["expired"] = True
    cases.append(no(lambda: official(*a)))
    a = copy.deepcopy(args)
    a[3][0]["steps"][-3]["conclusion"] = "failure"
    cases.append(no(lambda: official(*a)))
    for path in ("old-natural-F.json", "old-run-make.json", "source.pack", "subject.json"):
        real = s.reg.sha
        with mock.patch.object(
            s.reg, "sha", side_effect=lambda p: "0" * 64 if p.name == path else real(p)
        ):
            cases.append(no(s.load))
    need(len(cases) == 11, "missing custody negatives")
    return {"source": x["role"], "historical_witnesses": 3, "admission_refusals": len(cases)}


def native(root):
    complete = root / "natural-old/complete.json"
    roles = json.loads(complete.read_bytes())["source_drivers"]
    need(roles["old"]["source"] == s.PREVIOUS and roles["F"]["source"] == F, "wrong old sources")
    with reader.from_directory(root) as get:
        results = {
            f.__name__: f(get, "old", roles) for f in (reader.cargo, reader.direct, reader.natural)
        }
        tests = []

        def change(fn, name, apply):
            called = []

            def read(path):
                raw = get(path)
                if path != name:
                    return raw
                called.append(path)
                return apply(raw)

            rejected = no(lambda: fn(read, "old", roles))
            need(called and rejected, "negative did not touch its raw input")
            tests.append(name)

        j = lambda fn: (lambda raw: json.dumps(fn(json.loads(raw))).encode())
        change(
            reader.natural, "natural-old/F-B83-physical.json", j(lambda d: d | {"source": s.PREVIOUS})
        )
        change(
            reader.natural, "natural-old/F-B83-physical.json", j(lambda d: d | {"positive_traces": []})
        )
        change(reader.natural, "natural-old/F-B83-physical.json", j(lambda d: d | {"status": 101}))
        change(
            reader.natural,
            "natural-old/F-B83.json",
            j(lambda d: d | {"files": {k: [v[0], v[1] + 1, *v[2:]] for k, v in d["files"].items()}}),
        )
        change(reader.natural, "natural-old/read-B83.runtime", lambda raw: b"29\n")
        change(reader.natural, "natural-old/inputs/raw-83.gz", lambda raw: gzip.compress(b"wrong"))
        change(
            reader.natural,
            "natural-old/inputs/packed-29.gz",
            lambda raw: gzip.compress(gzip.decompress(raw)[:-1]),
        )
        change(
            reader.direct, "writer-old-reader-old/conflict-read-B.json", j(lambda d: d | {"output": 29})
        )
        change(
            reader.direct,
            "writer-old-reader-old/complete.json",
            j(lambda d: d | {"cases": {k: v for k, v in d["cases"].items() if k != "conflict"}}),
        )
        change(reader.cargo, "cargo-old/B-conflicting-raw.json", j(lambda d: d | {"marker": False}))
        change(reader.cargo, "cargo-old/B-malformed-raw.json", j(lambda d: d | {"status": 0}))
        change(
            reader.cargo,
            "cargo-old/conflicting-raw-source-unchanged.json",
            j(lambda d: d | {"after": {}}),
        )
        change(
            reader.cargo,
            "cargo-old/B-honest.stdout.gz",
            lambda raw: gzip.compress(b'{"reason":"build-finished","success":true}\n'),
        )
        change(reader.cargo, "cargo-old/B-honest.runtime", lambda raw: b"17\n")
        change(reader.cargo, "cargo-old/inputs/raw-A.gz", lambda raw: gzip.compress(b"bad"))
        return {"positive": results, "rejected": tests, "roles": roles}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--native", type=Path)
    a = p.parse_args()
    out = static()
    if a.native:
        out["previous_native"] = native(a.native)
    print(json.dumps(out, sort_keys=True, indent=2))
