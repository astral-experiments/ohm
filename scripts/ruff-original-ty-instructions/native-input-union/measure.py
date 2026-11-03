"""Price the surviving positive inputs of the 50 actual native link commands on a single boot."""
from collections import Counter
from pathlib import Path
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import workspace29697 as whole
import workspace_ron_probe as observer

worker = whole.w
proof = whole.PROOF

def scan(tag, paths, mode, expected, environment):
    directory = proof / tag
    directory.mkdir()
    manifest = directory / "paths.nul"
    manifest.write_bytes(b"".join(os.fsencode(path) + b"\0" for path in paths))
    executable = worker.root / "native-input-scan"
    counter = directory / "hardware.json"
    with (directory / "observed.txt").open("xb") as stdout, (directory / "stderr").open("xb") as stderr:
        subprocess.run([worker.root / "whole_count", counter, executable, executable, mode, manifest],
                       cwd=worker.root, env=environment, stdout=stdout, stderr=stderr, check=True, timeout=240)
    hardware = json.loads(counter.read_bytes())
    assert hardware["instructions"] > 0 and hardware["status"] == 0
    assert hardware["running"] == hardware["enabled"] > 0
    size = 0
    lease = Counter()
    failed = []
    with (directory / "observed.txt").open("rb") as raw:
        for index, path in enumerate(paths):
            i, n, err, dev, ino, digest = raw.readline().split()
            assert int(i) == index and int(ino) > 0 and int(dev) >= 0
            assert [int(n), digest.decode()] == expected[path]
            size += int(n)
            lease[int(err)] += 1
            if int(err) > 0:
                failed.append([path, int(err)])
        assert not raw.read(1)
    trailer = re.fullmatch(rb"files=(\d+) leased=(\d+) broken=(\d+) rlimit=(\d+)\n",
                           (directory / "stderr").read_bytes())
    assert trailer and int(trailer[1]) == len(paths) and int(trailer[2]) == lease[0]
    return {"files": len(paths), "bytes": size, "hardware": hardware, "lease_errno": lease,
            "failed_leases": failed, "broken": int(trailer[3]), "fd_limit": int(trailer[4]),
            "scan_sha256": worker.hf(executable), "manifest_sha256": worker.hf(manifest)}

def main():
    assert os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"]
    assert os.environ["GITHUB_RUN_ATTEMPT"] == "1"
    assert worker.git("rev-parse", "HEAD") == whole.NEW
    assert worker.git("rev-parse", "HEAD^") == whole.OLD
    assert worker.hf(worker.src / "sdk.json") == whole.SPEC["sdk_manifest"]
    assert shutil.disk_usage(worker.root).free > 45 * 2**30
    whole.write(proof / "registration.json", {
        "role": "single-boot positive-input budget only", "source": os.environ["GITHUB_SHA"],
        "prior_ordinary": 41617756983, "prior_causal": 41621281440, "study": whole.SPEC,
        "pid": os.getpid(), "run": os.environ["GITHUB_RUN_ID"],
    })
    env = worker.install()
    assert "CARGO_LOG" not in env
    for tool in ("whole_count", "exec_count"):
        subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-O2", HERE.parent / (tool + ".c"),
                        "-o", worker.root / tool], check=True)
    subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                    HERE / "scan.c", "-lcrypto", "-o", worker.root / "native-input-scan"], check=True)
    worker.guard()
    whole.select(whole.OLD)
    whole.write(proof / "locked-registry.json.gz", whole.inputs(env))
    metadata = json.loads(subprocess.check_output(["cargo", "+ohm", "metadata", "--format-version=1",
        "--locked", "--offline", "--no-deps"], cwd=worker.work, env=env))
    graph = json.loads(subprocess.check_output([*whole.CMD[:2], "-Zunstable-options", *whole.CMD[2:-1],
        "--unit-graph"], cwd=worker.work, env=env))
    assert len(metadata["workspace_default_members"]) == 55 and len(graph["units"]) == 693
    whole.write(proof / "unit-graph.json.gz", graph)
    for path in (worker.target, worker.shared):
        if path.exists():
            assert path.parent == worker.root and path.is_dir() and not path.is_symlink()
            shutil.rmtree(path)
    old = whole.inventory("ordinary-old", env, metadata)
    preserved = worker.root / "old-e2e"
    shutil.copy2(worker.root / old["binary"], preserved)
    names = whole.verdict(preserved, "old-verdict", env, 0)
    whole.select(whole.NEW)
    assert whole.verdict(preserved, "old-on-new-verdict", env, 101) == names
    changed = whole.inventory("ordinary-real-edit", env, metadata)
    assert whole.verdict(worker.root / changed["binary"], "edited-verdict", env, 0) == names
    ordinary = whole.inventory("ordinary-unchanged", env, metadata)
    tag = "actual-link-argv"
    census = whole.inventory(tag, env, metadata, "census")
    assert whole.verdict(worker.root / census["binary"], "unchanged-verdict", env, 0) == names
    native = observer.native(tag, census, graph)
    whole.write(proof / "native-owner.json", native)
    assert native["native"] == 50 and len(census["executables"]) == 102
    assert set(ordinary["executables"]) == set(census["executables"])
    packet = json.loads(gzip.decompress((proof / tag / "link-inputs.json.gz").read_bytes()))
    positive = packet["literal_files_after_command"]
    repeated = [name for link in packet["links"] for name in link["absolute_file_operands"] if positive[name]]
    distinct = sorted(set(repeated))
    missing = sorted(name for name, value in positive.items() if value is None)
    leaves = sorted({opt for link in packet["links"] for opt in link["declared_search"] if opt.startswith("-l")})
    assert len(missing) == 50 and all(Path(name).name == "symbols.o" for name in missing)
    assert len(distinct) > 3000 and len(repeated) > 10000
    test_count = sum(line.endswith(b": test") for line in (proof / "unchanged-verdict/test-list").read_bytes().splitlines())
    assert test_count == 200 and len(names) == 64
    state = dict(actual_native_links=native["native"], executables=102, e2e_test_names=test_count,
                 test_list_sha256=names, missing=missing,
                 explicit_search_libraries=leaves, whole=json.loads((proof/"ordinary-unchanged/hardware.json").read_bytes()),
                 retained_paths=len(distinct), replay_count=len(repeated), scans={},
                 limits="Surviving literal operands only. The absent symbols.o files and implicit library/script resolution are outside these passes. No link was skipped.")
    whole.write(proof / "budget.json", state)
    for tag, paths, mode in [("held-union-1", distinct, "lease"), ("per-link-1", repeated, "read"),
                             ("per-link-2", repeated, "read"), ("held-union-2", distinct, "lease")]:
        state["scans"][tag] = scan(tag, paths, mode, positive, env)
        whole.write(proof / "budget.json", state)
    assert not worker.git("status", "--porcelain")

if __name__ == "__main__":
    main()
