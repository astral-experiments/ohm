"""Acquire two adjacent ordinary user commands using the previously validated descendant PMU boundary."""

import contextlib
import hashlib
import json
import subprocess
from pathlib import Path

PLAN_SHA = "f5d5776020bee6e1d08980e891aa38410a8c4b6fe1fb39746784e9a438eba57a"
POSITIONS_SHA = "2afef068002e7a4da305d2f937003d6b3bccd0aaf308000916631b3688e73da1"
COUNTER_SOURCES = {
    "watch.c": "ee82d0f9f0410861f3680c7ebf7f26547cd3a73833290d7272e83b4e29e0d903",
    "calibrate.c": "dacd1dd7fef85cacb44a236e0c4191d95db036a623b2a01ae3a5d76d2f3d0b0e",
    "paired.py": "079adce5ae5304ec7d33a4b3ca9223a4cceb1081f267d65669cfa6aeaa20284f",
}
CMD = [
    "cargo",
    "+ohm",
    "build",
    "--locked",
    "--offline",
    "-p",
    "ruff_python_ast",
    "--lib",
    "--target",
    "x86_64-unknown-linux-musl",
    "-j4",
    "--message-format=json",
]
PHASES = ("edit", "repeat")


def require(test, message):
    if not test:
        raise RuntimeError(str(message))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        json.dump(data, f, sort_keys=True, indent=2)
        f.write("\n")


def assignment(here, cohort):
    require(
        file_sha(here / "PLAN.md") == PLAN_SHA and file_sha(here / "positions.json") == POSITIONS_SHA,
        "changed enrollment",
    )
    positions = json.loads((here / "positions.json").read_bytes())
    require(positions["plan_sha256"] == PLAN_SHA and cohort in ("screen", "primary", "independent"), cohort)
    return positions["screen"] if cohort == "screen" else positions["cohorts"][cohort]


def calibrate(src, previous, out, env):
    actual = {name: file_sha(src / name) for name in COUNTER_SOURCES}
    require(
        actual == COUNTER_SOURCES and Path(previous.__file__).resolve() == (src / "paired.py").resolve(),
        "historical counter sources",
    )
    bindir = out / "tools"
    bindir.mkdir()
    watch = bindir / "watch"
    loop = bindir / "calibrate"
    for c, exe in [("watch.c", watch), ("calibrate.c", loop)]:
        subprocess.run(
            ["cc", "-std=c11", "-O2", "-pthread", "-Wall", "-Wextra", "-Werror", src / c, "-o", exe],
            env=env,
            check=True,
        )
    hw, tree_cpu = previous.calibrate(out / "calibration", watch, loop)
    require(
        hw,
        "28 actual parent, child, grandchild, duplicate descendant, exec and thread PMU calibrations must pass",
    )
    clocks = [json.loads((out / "calibration" / f"{i}.json").read_bytes()) for i in range(28)]
    for row in clocks:
        check_clock(row)
    save(
        out / "tools/identity.json",
        {
            "sources": actual,
            "binaries": {f.name: file_sha(f) for f in (watch, loop)},
            "supplemental_tree_cpu": tree_cpu,
        },
    )
    return watch


def check_clock(row):
    require(
        row["event_errno"] == row["code"] == 0
        and row["instructions"] > 0
        and row["stop"] > row["start"]
        and row["user_us"] + row["system_us"] > 0
        and 0 < row["running"] <= row["enabled"]
        and 1000 * row["running"] >= 995 * row["enabled"],
        ("unqualified counter", row),
    )


def consecutive(watch, out, env, source, runner=subprocess.run):
    # Pre-open all four independent streams before either clock starts. Neither the Rust products,
    # Cargo messages, clock receipts nor cache files are inspected until both commands have exited.
    slots = []
    codes = []
    with contextlib.ExitStack() as stack:
        for phase in PHASES:
            dest = out / phase
            dest.mkdir()
            stdout = stack.enter_context((dest / "stdout.raw").open("xb"))
            stderr = stack.enter_context((dest / "stderr.raw").open("xb"))
            slots.append((phase, dest, stdout, stderr))
        for phase, dest, stdout, stderr in slots:
            code = runner(
                [watch, dest / "clock.json", *CMD],
                cwd=source,
                env=env,
                stdout=stdout,
                stderr=stderr,
                timeout=2400,
            ).returncode
            codes.append(code)
            if code:
                break
    save(
        out / "clocked-commands.json",
        {"cwd": str(source), "argv": CMD, "watch": str(watch), "statuses": codes, "phases": PHASES},
    )
    require(codes == [0, 0], ("incomplete measured prefix", codes))
    values = {}
    for phase in PHASES:
        d = out / phase
        clock = json.loads((d / "clock.json").read_bytes())
        check_clock(clock)
        out_bytes = (d / "stdout.raw").read_bytes()
        err_bytes = (d / "stderr.raw").read_bytes()
        # Strict UTF-8 provides a lossless direct round trip through the portable JSON/zstd pack.
        require(
            out_bytes.decode().encode() == out_bytes and err_bytes.decode().encode() == err_bytes,
            "non-UTF8 native stream",
        )
        save(
            d / "streams.json",
            {
                name: {"sha256": sha(raw), "bytes": len(raw)}
                for name, raw in [("stdout", out_bytes), ("stderr", err_bytes)]
            },
        )
        values[phase] = {"clock": clock, "stdout": out_bytes}
    require(
        values["repeat"]["clock"]["start"] >= values["edit"]["clock"]["stop"], "overlapping native Cargo clocks"
    )
    return values


def pack(out, position):
    # Native structural binaries/traces are supplied by the separate content-addressed witness artifact.
    # All 28 raw calibration counters plus both actual clock/stdout/stderr triplets are in this small pack.
    wanted = ["pair.json", "host.json", "admission.json", "tools/identity.json", "calibration/summary.json"]
    wanted.extend(f"calibration/{i}.json" for i in range(28))
    for role in "PC":
        wanted.extend([f"{role}/role.json", f"{role}/terminal.json", f"{role}/clocked-commands.json"])
        for phase in PHASES:
            wanted.extend(
                f"{role}/{phase}/{n}" for n in ("clock.json", "stdout.raw", "stderr.raw", "streams.json")
            )
    files = {}
    for key in wanted:
        raw = (out / key).read_bytes()
        label = "musl-measurements/" + key
        require(label not in files, key)
        files[label] = raw.decode("utf-8")
    envelope = json.dumps(files, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    dest = out.parent / f"{position:02}.json.zst"
    with dest.open("xb") as stream:
        subprocess.run(["zstd", "-q", "-9", "-c"], input=envelope, stdout=stream, check=True)
    require(subprocess.check_output(["zstd", "-qdc", dest]) == envelope, "packed native bytes")
    return dest
