"""Load the exact deployed exec/PERF reader, calibration, and source-matched callback seam."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

import common as c


def compile_sources(collector, contract, output):
    c.need(
        c.git(collector, "rev-parse", "HEAD").decode().strip() == c.COLLECTOR
        and c.git(contract, "rev-parse", "HEAD").decode().strip() == c.CONTRACT,
        "wrong observer checkout",
    )
    rules = contract / "scripts/notebook-fanout-ceiling"
    c.need(
        c.sha(rules / "sources.json") == "87cf9b6473ff57b225e4dfa795cea764b269d4c7a30bc04fff8f8edd0245110e"
        and c.sha(rules / "ledger.patch") == "f78c8ae99a3fd954d5d5c0b39f5297c4ada8f6f66ee69a1752779090d3c2906f",
        "historical reader registration or callback changed",
    )
    manifest = json.loads((rules / "sources.json").read_bytes())
    output.mkdir()
    for name, digest in manifest["counter"].items():
        original = collector / name
        c.need(c.sha(original) == digest, "changed observer source: " + name)
        shutil.copyfile(original, output / Path(name).name)
    subprocess.run(["git", "apply", "--no-index", "--check", rules / "ledger.patch"], cwd=output, check=True)
    subprocess.run(["git", "apply", "--no-index", rules / "ledger.patch"], cwd=output, check=True)
    c.need(c.sha(output / "topology.py") == manifest["joined_topology"], "different historical reader seam")
    sys.path.insert(0, str(output))
    import topology, pmu, kit

    c.need(
        all(Path(m.__file__).resolve().parent == output.resolve() for m in (topology, pmu, kit)),
        "unexpected module binding",
    )
    return topology, pmu


def strict_clock(path):
    return clock_value(c.read(path))


def clock_value(row):
    c.need(
        row["code"] == row["event_errno"] == 0 and row["instructions"] > 0 and row["enabled"] == row["running"] > 0,
        "incomplete ordinary userspace hardware counter",
    )
    return row["instructions"]
