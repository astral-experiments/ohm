"""Calibrate the exact new selector while retaining the established 28 + 8 independent controls."""

import gzip
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from kernel import (
    SELECTORS,
    build,
    classify,
    digest,
    dump,
    identity,
    load,
    require,
    snapshot,
)

N = (0, 2_000_000, 0, 8_000_000)


def observer_args(binary, trace, mode, catalog, cmd):
    return [
        str(binary),
        str(trace),
        mode,
        *[catalog[n]["path"] for n in SELECTORS],
        *map(str, cmd),
    ]


def prepare(donor, out):
    require(
        digest(donor / "observer.c")
        == "c258cd838bae37b9df99a2ee82b932c98b1acf92fe9c3619e02647851ce9940a",
        "upstream observer",
    )
    sys.path.insert(0, str(donor))
    import pmu

    store = out / "tools"
    store.mkdir()
    bins = pmu.compilers(store)
    build(donor / "observer.c", store)
    dump(
        store / "identities.json",
        {n: digest(store / n) for n in ("observe", "stock-wild-only.c")},
    )
    return pmu, bins


def raw_visit(out, cmd, env, cwd):
    with (out / "stdout.gz").open("xb") as fo, (out / "stderr.gz").open("xb") as fe:
        begin = time.monotonic_ns()
        p = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=1450,
        )
        end = time.monotonic_ns()
        fo.write(gzip.compress(p.stdout, compresslevel=1, mtime=0))
        fe.write(gzip.compress(p.stderr, compresslevel=1, mtime=0))
    dump(
        out / "call.json",
        {
            "argv": list(map(str, cmd)),
            "code": p.returncode,
            "cwd": str(cwd),
            "begin_ns": begin,
            "end_ns": end,
        },
    )
    require(p.returncode == 0, ("command failed", p.returncode, p.stderr[-1800:]))
    return p.stdout


def controls(donor, out, replay=False):
    sys.path.insert(0, str(donor))
    import pmu

    bins = out / "tools/bin"
    pmu.calibration(bins, out, replay=replay)
    roles = bins / "roles"
    store = out / "wild-calibration"
    if not replay:
        store.mkdir()
        dump(store / "selectors.json", {n: identity(roles / n) for n in SELECTORS})
    ids = load(store / "selectors.json")
    measured = {}
    for mode in ("tree", "plain"):
        visits = []
        for i, n in enumerate(N):
            d = store / f"{mode}-{i}"
            cmd = observer_args(
                out / "tools/observe",
                d,
                mode,
                ids,
                [roles / "root", roles, "ignore", n],
            )
            if not replay:
                d.mkdir()
                raw_visit(d, cmd, os.environ, out)
            observed = load(d / "call.json")
            require(
                observed["code"] == 0
                and observed["argv"][2] == mode
                and observed["argv"][-1] == str(n),
                "wrong loop or counter",
            )
            origin = Path(ids["wild"]["path"]).parent
            q = classify(
                snapshot(d, mode, ids),
                {v: str(origin / v) for v in ("alpha", "beta")},
                "cal",
            )
            visits.append(q)
        measured[mode] = visits

    def slopes(values, factor):
        zero = statistics.median(values[::2])
        for i in (1, 3):
            target = 2 * factor * N[i]
            require(
                abs(values[i] - zero - target) < 0.02 * target,
                ("instruction slope", values, factor),
            )

    for rows in measured.values():
        slopes([a["whole"] for a in rows], 88)
    obs = measured["tree"]
    for name, factor in (("alpha", 21), ("beta", 42)):
        slopes([a["outputs"][name] for a in obs], factor)
    slopes([a["whole"] - sum(a["outputs"].values()) for a in obs], 25)
    for i in (1, 3):
        a, b = measured["tree"][i]["whole"], measured["plain"][i]["whole"]
        require(abs(a - b) * 100 < 2 * min(a, b), "calibration tracer disturbance")
    if replay:
        require(load(store / "result.json") == measured, "calibration differs")
    else:
        dump(store / "result.json", measured)
    return measured
