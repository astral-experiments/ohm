"""Check the originally calibrated counter when its parent is the actual notifier."""

import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import protocol

SIZES = (0, 4_000_000, 0, 12_000_000)


def parse(commands, mode):
    protocol.require(mode in ("P", "B") and len(commands) == len(SIZES), "missing notifier calibration")
    ns = []
    for index, (record, n) in enumerate(zip(commands, SIZES, strict=True)):
        protocol.require(
            record["loop"] == n
            and record["arg_mode"] == "1"
            and record["copies"] == 2
            and record["status"] == 0
            and record["source"] == mode
            and record["listener"][:2] == [0, 0]
            and record["listener"][2] > 0
            and record["listener"][3:] == [0, 0]
            and record["stdout_bytes"] == record["stderr_bytes"] == 0,
            "different native calibrated tree or intervention",
        )
        ns.append(protocol.measured(record["clock"]))
    # The genuine depth-one fixture creates two child processes, each execs a DEC/JNE loop.
    # Compare against its own immediate zero; one percent plus 30,000 covers fixed tiny process costs.
    deltas = []
    for lo, hi in [(0, 1), (2, 3)]:
        delta = ns[hi] - ns[lo]
        wanted = 4 * SIZES[hi]
        protocol.require(
            abs(delta - wanted) <= wanted // 100 + 30_000,
            "nested positive instruction count did not follow known child loop",
        )
        deltas.append([delta, wanted])
    return deltas


def exercise(p, ev, env):
    base = p.OUT / "nested-notifier-meter"
    base.mkdir()
    report = {}
    for mode in ("P", "B"):
        report[mode] = []
        for i, n in enumerate(SIZES):
            where = base / f"{mode}-{i}"
            where.mkdir()
            calls = where / "calls"
            calls.mkdir()
            selector = where / "empty-owner"
            selector.mkdir()
            (calls / "config").write_text(ev.config(mode, [str(selector)]))
            (calls / "owners").write_text(str(selector) + "\n")
            cmd = [
                str(p.OUT / "tools/table-notify"),
                str(calls),
                str(p.b.SDK),
                str(calls / "notify.status"),
                "--",
                str(p.OUT / "observers/plain"),
                str(where / "clock.json"),
                str(p.OUT / "observers/loop"),
                "1",
                str(n),
                "2",
            ]
            c = subprocess.run(cmd, cwd=where, env=env, input=b"", capture_output=True, timeout=60)
            p.save(where / "intent.json", dict(argv=cmd, env=env, cwd=str(where)))
            for k, raw in (("stdout", c.stdout), ("stderr", c.stderr)):
                (where / k).write_bytes(raw)
            record = dict(
                loop=n,
                arg_mode="1",
                copies=2,
                status=c.returncode,
                source=mode,
                stdout_bytes=len(c.stdout),
                stderr_bytes=len(c.stderr),
                listener=list(map(int, (calls / "notify.status").read_text().split())),
                clock=json.loads((where / "clock.json").read_bytes()),
            )
            p.save(where / "receipt.json", record)
            report[mode].append(record)
        parse(report[mode], mode)
    return {k: parse(v, k) for k, v in report.items()}
