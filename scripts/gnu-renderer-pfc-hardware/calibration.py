"""Use the immutable ordinary-command observer and its independently replayable hardware controls."""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingress import OBSERVERS, need, put, sha


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def earlier(repo):
    head = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    need(head == OBSERVERS, "wrong instrument source checkout")
    family = repo / "scripts/gnu-renderer-library-workers"
    common = repo / "scripts/gnu-example-ceiling"
    for path in (family, common):
        subprocess.run(["sha256sum", "--strict", "--check", "--status", "SHA256SUMS"], cwd=path, check=True)
    base = module(family / "study.py", "registered_worker")
    c = module(common / "study.py", "registered_whole")
    return family, common, base, c


def host(repo, out):
    _, _, _, c = earlier(repo)
    info = c.host()
    boot = info["raw_system"]["/proc/sys/kernel/random/boot_id"]
    need(isinstance(boot, str) and re.fullmatch("[a-f0-9-]{36}", boot), "missing kernel boot identity")
    need(
        len(info["affinity"]) == 8 and sorted(os.sched_getaffinity(0)) == info["affinity"],
        "unexpected actual CPU isolation",
    )
    put(out / "host.json", info)
    return boot


def setup(repo, root, out):
    family, common, base, _ = earlier(repo)
    bins = base.pmu.compilers(root)
    for name, file, flags in [
        ("workers", "workers.c", ["-I", str(common)]),
        ("calibrator", "calibrator.c", ["-pthread"]),
    ]:
        argv = [
            "cc",
            "-std=gnu11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            *flags,
            family / file,
            "-o",
            bins / name,
        ]
        need(
            base.run(out / ("build-observer-" + name), argv, root).returncode == 0,
            "observer failed to compile",
        )
    saved = out / "observers"
    saved.mkdir()
    for name in ("plain", "loop", "tree", "nested", "workers", "calibrator"):
        shutil.copy2(bins / name, saved / name)
    put(
        out / "observer.json",
        {
            "compiler": subprocess.check_output(["cc", "--version"], text=True),
            "ref": OBSERVERS,
            "sources": {
                str(p.relative_to(repo)): sha(p)
                for p in [
                    common / "watch.c",
                    common / "calibrate.c",
                    common / "observer.c",
                    common / "nested.c",
                    family / "workers.c",
                    family / "calibrator.c",
                ]
            },
            "bins": {p.name: sha(p) for p in saved.iterdir()},
            "abi": {
                "type": "PERF_TYPE_HARDWARE",
                "config": "PERF_COUNT_HW_INSTRUCTIONS",
                "pid": "fork child blocked on its one-byte pipe before execvp cargo +ohm",
                "inherit": 1,
                "disabled": 1,
                "enable_on_exec": 1,
                "exclude_kernel": 1,
                "exclude_hv": 1,
                "cpu": -1,
                "group_fd": -1,
                "read_format": ["PERF_FORMAT_TOTAL_TIME_ENABLED", "PERF_FORMAT_TOTAL_TIME_RUNNING"],
                "read_bytes": 24,
            },
        },
    )
    base.calibration(root, out, bins)
    replay(repo, out)
    return saved / "plain"


def replay(repo, out):
    _, _, base, _ = earlier(repo)
    # The library workers and the whole-counter scope are disjoint checks, never summed.
    base.pmu.calibration(out / "observers", out, replay=True)
    workers = base.readback.worker_calibration(out / "worker-calibration")
    expected = json.loads((out / "worker-calibration.json").read_bytes())
    need(
        workers == expected and len(list((out / "calibration-commands").iterdir())) == 36,
        "observer replay or nested calibration differs",
    )
    return workers
