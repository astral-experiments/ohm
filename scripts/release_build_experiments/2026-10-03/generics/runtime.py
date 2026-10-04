#!/usr/bin/env python3
"""Paired runtime and output equivalence checks for saved release binaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import threading
import time

from ablate import host_limits, monitor_delta, process_ticks, system_snapshot


parser = argparse.ArgumentParser()
parser.add_argument("--name", choices=["uv", "ruff"], required=True)
parser.add_argument("--baseline", type=Path, required=True)
parser.add_argument("--candidate", type=Path, required=True)
parser.add_argument("--sources", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--cache", type=Path)
parser.add_argument("--runs", type=int, default=30)
args = parser.parse_args()
before_idle = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
time.sleep(3)
after_idle = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
idle_deltas = [b-a for a,b in zip(before_idle, after_idle)]
if idle_deltas[3] / sum(idle_deltas) < 0.95:
    raise SystemExit("Refusing runtime cohort with less than 95% CPU idle")
args.output.mkdir(parents=True, exist_ok=False)
bins = {"baseline": str(args.baseline.resolve()), "candidate": str(args.candidate.resolve())}
workloads = ["check", "format"] if args.name == "ruff" else ["trio", "jupyter"]
result = {"name": args.name, "binaries": {}, "workloads": {}, "samples": [], "system_before": system_snapshot(), "host_limits": host_limits(), "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
source_name = "cpython" if args.name == "ruff" else "uv"
result["source_sha"] = subprocess.check_output(["git", "-C", str(args.sources / source_name), "rev-parse", "HEAD"], text=True).strip()
for label, binary in bins.items():
    with open(binary, "rb") as stream:
        result["binaries"][label] = {"path": binary, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}


def run(label, workload, kind, pair=None):
    if args.name == "ruff":
        command = [bins[label], workload, "--isolated", "--no-cache"]
        command += ["--exit-zero", "--output-format", "concise"] if workload == "check" else ["--check"]
        command += [str(args.sources.resolve() / "cpython/Lib")]
    else:
        command = [bins[label], "pip", "compile", str(args.sources.resolve() / f"uv/test/requirements/{workload}.in"), "--no-header", "--exclude-newer", "2026-10-01T00:00:00Z", "--python-version", "3.12", "--cache-dir", str(args.cache.resolve()), "--default-index", "https://pypi.org/simple", "--output-file", str(args.output.resolve() / "requirements.txt")]
        if kind != "network-setup":
            command += ["--offline"]
        (args.output / "requirements.txt").unlink(missing_ok=True)
    index = len(result["samples"])
    stdout = args.output / f"{index:04d}-{label}-{workload}-{kind}.stdout"
    stderr = stdout.with_suffix(".stderr")
    prior = process_ticks()
    monitor = []
    stopped = threading.Event()
    def observe():
        nonlocal prior
        while not stopped.wait(2):
            current = process_ticks()
            monitor.append(monitor_delta(prior, current))
            prior = current
    observer = threading.Thread(target=observe)
    observer.start()
    start = time.monotonic()
    with stdout.open("wb") as out, stderr.open("wb") as err:
        proc = subprocess.run(command, stdout=out, stderr=err, env=os.environ, cwd=args.sources.resolve() / "cpython" if args.name == "ruff" else None)
    elapsed = time.monotonic() - start
    stopped.set()
    observer.join()
    monitor.append(monitor_delta(prior, process_ticks()))
    accepted = [2] if args.name == "ruff" and workload == "format" else [0]  # CPython Lib includes intentionally invalid syntax fixtures.
    record = {"label": label, "workload": workload, "kind": kind, "pair": pair, "elapsed": elapsed, "returncode": proc.returncode, "command": command, "cwd": str(args.sources.resolve() / "cpython") if args.name == "ruff" else os.getcwd(), "monitor": monitor}
    output_path = stdout if args.name == "ruff" else args.output / "requirements.txt"
    record["output_sha256"] = hashlib.sha256(output_path.read_bytes()).hexdigest() if output_path.exists() else None
    result["samples"].append(record)
    (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    if proc.returncode not in accepted:
        raise SystemExit(f"Failed workload {workload}: {stderr.read_text()[-3000:]}")
    if kind != "network-setup":
        expected = result["workloads"].setdefault(workload, record["output_sha256"])
        if expected != record["output_sha256"]:
            raise SystemExit(f"Output mismatch for {workload}: {label}")


for workload in workloads:
    if args.name == "uv":
        if args.cache is None:
            raise SystemExit("--cache required for uv")
        run("baseline", workload, "network-setup")
    for _ in range(3):
        run("baseline", workload, "warmup")
        run("candidate", workload, "warmup")
    rng = random.Random(12809)
    for pair_index in range(args.runs):
        pair = ["baseline", "candidate"]
        rng.shuffle(pair)
        for label in pair:
            run(label, workload, "measure", pair_index)
print(args.output / "results.json", flush=True)
