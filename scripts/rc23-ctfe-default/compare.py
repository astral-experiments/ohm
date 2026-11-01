"""Compare Rust #318 with its parent under the ordinary single-session policy."""

import hashlib
import importlib.util
import json
import os
import resource
import subprocess
import sys
import threading
import time
from pathlib import Path

workspace = Path(os.environ["GITHUB_WORKSPACE"])
history = workspace / "historical" / "scripts" / "ctfe-crossover-pilot"
sys.path.insert(0, str(history))
import pilot

spec = importlib.util.spec_from_file_location("original_routes", history / "routes.py")
routes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routes)
keys = {
    "A": "b5dba861cc38e3f7fb4524c9ceba3e01a474ea13",
    "B": "7b13f01ba1569887a25670820764b24c206da8e5",
}
names = {"A": "study-x", "B": "study-y"}
root = workspace / "ruff"
data = Path(os.environ["RUNNER_TEMP"]) / "ctfe-default"
data.mkdir()
cpus = sorted(os.sched_getaffinity(0))[:4]
assert len(cpus) == 4
os.sched_setaffinity(0, cpus)


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", root, *args], text=True).strip()


def res():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return [usage.ru_utime, usage.ru_stime]


def cpu(fp):
    prefix = {f"cpu{n}" for n in cpus}
    fp.write(
        json.dumps(
            [
                time.monotonic_ns(),
                [
                    r.split()
                    for r in Path("/proc/stat").read_text().splitlines()
                    if r.split()[0] in prefix
                ],
            ]
        )
        + "\n"
    )


def build(phase, arm, env, out):
    slot = out / phase
    slot.mkdir()
    cmd = [
        "cargo",
        "+ohm",
        "build",
        "-p",
        "ruff",
        "--bin",
        "ruff",
        "--locked",
        "--offline",
        "-j4",
        "--message-format=json",
        "-v",
    ]
    stopped = threading.Event()
    with (slot / "cpu.jsonl").open("x") as intervals:

        def monitor():
            while not stopped.wait(1):
                cpu(intervals)

        cpu(intervals)
        thread = threading.Thread(target=monitor)
        thread.start()
        try:
            before = res()
            start = time.monotonic_ns()
            with (
                (slot / "stdout.jsonl").open("xb") as stdout,
                (slot / "stderr.log").open("xb") as stderr,
            ):
                p = subprocess.run(
                    cmd, cwd=root, env=env, stdout=stdout, stderr=stderr, check=False
                )
            end = time.monotonic_ns()
            after = res()
        finally:
            stopped.set()
            thread.join()
            cpu(intervals)
    records = [
        json.loads(line)
        for line in (slot / "stdout.jsonl").read_bytes().splitlines()
        if line.startswith(b"{")
    ]
    dirty = sorted(
        (r["package_id"], r["target"]["name"], r["target"]["kind"])
        for r in records
        if r.get("reason") == "compiler-artifact" and not r["fresh"]
    )
    diagnostics = sorted(
        {
            r["message"]["code"]["code"]
            for r in records
            if r.get("reason") == "compiler-message" and r["message"].get("code")
        }
    )
    stderr = (slot / "stderr.log").read_text(errors="backslashreplace")
    assert "ohm-branch-cache=yes" not in stderr
    runs = [
        line
        for line in stderr.splitlines()
        if "Running `" in line and " --crate-name " in line
    ]
    output = None
    checks = []
    if phase != "invalid" and p.returncode == 0:
        exe = Path(env["CARGO_TARGET_DIR"]) / "debug/ruff"
        output = sha(exe)
        for code, rc in [(b"l = 1\n", 1), (b"answer = 1\n", 0)]:
            probe = subprocess.run(
                [
                    exe,
                    "check",
                    "--isolated",
                    "--no-cache",
                    "--select",
                    "E741",
                    "--stdin-filename",
                    "case.py",
                    "-",
                ],
                input=code,
                check=False,
                capture_output=True,
                env=env,
            )
            checks.append(
                {
                    "rc": probe.returncode,
                    "out": probe.stdout.decode(),
                    "err": probe.stderr.decode(),
                }
            )
            assert probe.returncode == rc and ((b"E741" in probe.stdout) == bool(rc)), (
                checks
            )
    row = {
        "arm": arm,
        "phase": phase,
        "sha": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "modified": git("diff", "--name-only").splitlines(),
        "ast": sha(root / routes.NODES),
        "parser": sha(root / routes.PARSER),
        "command": cmd,
        "returncode": p.returncode,
        "wall_ns": end - start,
        "cpu_seconds": [a - b for a, b in zip(after, before)],
        "dirty": dirty,
        "rustc_commands": len(runs),
        "codegen_commands": sum(
            "link" in line.partition("--emit=")[2].split(" ", 1)[0] for line in runs
        ),
        "diagnostics": diagnostics,
        "output": output,
        "behavior": checks,
        "log_sha256": {
            name: sha(slot / name)
            for name in ("cpu.jsonl", "stdout.jsonl", "stderr.log")
        },
    }
    save(slot / "receipt.json", row)
    assert p.returncode == (101 if phase == "invalid" else 0) and (
        phase != "invalid" or "E0308" in diagnostics
    ), (phase, p.returncode, diagnostics)
    return row


assert git("rev-parse", "HEAD") == keys["B"] and git("rev-parse", "HEAD^") == keys["A"]
trees = {k: git("rev-parse", v + "^{tree}") for k, v in keys.items()}
git("switch", "-c", names["B"])
git("branch", names["A"], keys["A"])
roles = {
    k: json.loads((pilot.OUT / "sdk" / (k + ".json")).read_bytes())["files"]
    for k in ("E", "C")
}
nonce = os.environ["COHORT"]
order = ("Eon", "Con") if nonce in ("01", "03") else ("Con", "Eon")
save(
    data / "host.json",
    {
        "job": os.environ["GITHUB_JOB"],
        "run": os.environ["GITHUB_RUN_ID"],
        "cohort": nonce,
        "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "source": os.environ["GITHUB_SHA"],
        "order": order,
        "cpus": cpus,
        "compiler": {"Eon": pilot.subjects.E, "Con": pilot.subjects.C},
        "cargo": pilot.b.CARGO,
        "source_refs": keys,
    },
)
for arm in order:
    top = data / arm
    top.mkdir()
    env = pilot.subjects.activate(arm, roles, top)
    assert env.pop("CARGO_ENCODED_RUSTFLAGS") == "-Zohm-branch-cache=yes"
    assert not set(env).intersection(
        {
            "RUSTFLAGS",
            "CARGO_ENCODED_RUSTFLAGS",
            "RUSTC_WRAPPER",
            "CARGO_UNSTABLE_OHM_BRANCH_CACHE",
        }
    )
    binary = pilot.b.SDK / "bin/rustc"
    assert sha(pilot.b.SDK / "bin/cargo") == pilot.b.CARGO_ELF
    version = subprocess.check_output([binary, "-vV"], env=env, text=True)
    opts = subprocess.check_output([binary, "-Z", "help"], env=env, text=True)
    save(
        top / "effective.json",
        {
            "environment": env,
            "version": version,
            "branch_flags": [
                x.strip() for x in opts.splitlines() if "ohm-branch-cache" in x
            ],
            "cargo_sha": pilot.b.CARGO_ELF,
            "driver_sha": sha(pilot.b.SDK / pilot.subjects.DRIVER),
        },
    )
    routes.begin(root, keys, names)
    # Populate both locked revision inputs before the timed commands. Each measured call is offline.
    for k in ("A", "B"):
        git("switch", "--quiet", names[k])
        with (top / ("fetch-" + k + ".log")).open("xb") as log:
            subprocess.run(
                [
                    "cargo",
                    "+ohm",
                    "fetch",
                    "--locked",
                    "--target",
                    "x86_64-unknown-linux-gnu",
                ],
                cwd=root,
                env={**env, "CARGO_NET_OFFLINE": "false"},
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
    pilot.b.fresh_outputs()
    rows = {}
    for phase in (
        "Y-B",
        "X-A",
        "X-B",
        "comment",
        "unchanged",
        "invalid",
        "repair",
        "clean-edited",
    ):
        if phase == "clean-edited":
            pilot.b.fresh_outputs()
        elif phase == "repair":
            old = pilot.original.failed_session.observed(pilot.WORK)
            pilot.original.failed_session.before_repair(
                pilot.WORK, old, top / "repair-grace.json"
            )
            routes.advance(root, names, phase, "return")
        else:
            routes.advance(root, names, phase, "return")
        want = keys["A" if phase == "X-A" else "B"]
        assert (
            git("rev-parse", "HEAD") == want
            and git("rev-parse", "HEAD^{tree}") == trees["A" if phase == "X-A" else "B"]
        )
        expected = (
            {routes.NODES}
            if phase in ("comment", "unchanged", "invalid", "repair", "clean-edited")
            else set()
        )
        if phase == "invalid":
            expected.add(routes.PARSER)
        assert set(git("diff", "--name-only").splitlines()) == expected
        if routes.NODES in expected:
            assert sha(root / routes.NODES) == routes.AFTER
        rows[phase] = build(phase, arm, env, top)
    clean = rows["clean-edited"]["output"]
    assert all(rows[k]["output"] == clean for k in ("comment", "unchanged", "repair"))
    save(top / "summary.json", rows)

# The archived parent and candidate both predate the fix for a missing native-link marker.
# Record both arms before applying gates so a control failure cannot erase the paired evidence.
legacy = {}
for arm in order:
    top = data / arm / "unchanged"
    row = json.loads((top / "receipt.json").read_bytes())
    dirty = row["dirty"]
    reasons = [
        line.strip()
        for line in (top / "stderr.log").read_text().splitlines()
        if "Dirty " in line
    ]
    skipped = not dirty and not row["rustc_commands"]
    same_marker = (
        row["rustc_commands"] == row["codegen_commands"] == 1
        and len(dirty) == len(reasons) == 1
        and dirty[0][1:] == ["ruff", ["bin"]]
        and dirty[0][0].endswith("/crates/ruff#0.16.7")
        and "Dirty ruff v0.16.7" in reasons[0]
        and reasons[0].endswith(
            "the file `/dev/null/ohm-recheck-dependent-links` is missing"
        )
    )
    legacy[arm] = {
        "skipped": skipped,
        "historical_marker": same_marker,
        "dirty": dirty,
        "reasons": reasons,
    }
save(data / "unchanged-gates.json", legacy)
assert all(x["skipped"] for x in legacy.values()) or all(
    x["historical_marker"] for x in legacy.values()
)
save(
    data / "complete.json",
    {
        "cohort": nonce,
        "phases": 8,
        "arms": 2,
        "relative_only": any(x["historical_marker"] for x in legacy.values()),
    },
)
