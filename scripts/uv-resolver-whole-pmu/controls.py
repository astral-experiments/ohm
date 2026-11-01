"""Validate the analysis using synthetic observations. Hardware calibration runs separately."""
import itertools
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import read
import run
from intake import P, save


def rejects(fn, *args):
    try:
        fn(*args)
    except (ValueError, FileNotFoundError):
        return
    raise AssertionError("negative control was accepted")


def main():
    if not __debug__:
        raise RuntimeError("assertions are required")
    plan = run.orders()
    assert read.planner(P) == plan and len(plan) == 2
    for hold in plan:
        assert len(hold) == 6
        assert {tuple(r["arms"]) for r in hold} == set(itertools.permutations(P["arms"]))
        assert sum(row["modes"][0] == "pmu" for row in hold) == 3
    data = {"code":0,"instructions":151,"event_errno":0,"start":110,"stop":160,"enabled":10,"running":10,
            "user_us":2,"system_us":1}
    assert read.clock(data) == 151
    for update in ({"code":1}, {"instructions":0}, {"instructions":True}, {"event_errno":13}, {"running":9}, {"enabled":1000, "running":999},
                   {"running":11}, {"enabled":0}, {"stop":110}, {"system_us":0,"user_us":0}):
        rejects(read.clock, data | update)
    rows = [{"a":2.01, "b":1} for _ in range(12)]
    assert read.factors(rows,"a","b")["qualifies_at_2x"]
    rows[0]["a"] = rows[1]["a"] = 1.91
    assert not read.factors(rows,"a","b")["qualifies_at_2x"]
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        folder = root / "h1-01-pmu-base"
        folder.mkdir()
        argv = [str(root / "rc23-trait-work/bin/cargo"), *P["argv"]]
        mask = list(range(8))
        for phase in ("cold", "unchanged-parent", "first-edit", "unchanged-child"):
            names = P["expected_first_dirty"] if phase in ("cold", "first-edit") else P["expected_unchanged_dirty"]
            row = {"argv":argv,"exit":0,"dirty":names,"cpus":mask,"cpu_before":[0]*8,"cpu_after":[0]*8,
                   "start_ns":100,"end_ns":200,"ns":100}
            if phase == "first-edit":
                row["observer_argv"] = [str(root/"logs/observers/plain"),str(folder/"whole-clock.json"),*argv]
            save(folder / (phase+".json"), row)
            (folder / (phase+".stdout")).write_bytes(b"")
            (folder / (phase+".stderr")).write_text("".join(f"    Checking {n} v0.1.0\n" for n in names))
        save(folder/"whole-clock.json", data)
        assert read.verify(folder, P, "pmu", mask) == 151
        rejects(read.verify, folder, P, "native", mask)
        save(folder/"whole-clock.json", data | {"running":9})
        rejects(read.verify, folder, P, "pmu", mask)
        save(folder/"whole-clock.json", data)
        first = folder/"first-edit.json"
        row = json.loads(first.read_bytes())
        save(first, row | {"observer_argv":[*row["observer_argv"][:2], "rustc", *argv[1:]]})
        rejects(read.verify, folder, P, "pmu", mask)
        save(first, row)
        (folder/"first-edit.stderr").write_text("    Checking uv-resolver v0.1.0\n")
        rejects(read.verify, folder, P, "pmu", mask)
    print("Passed balance, timing-source, process scope, roster, counter and paired-interval controls.")


if __name__ == "__main__":
    main()
