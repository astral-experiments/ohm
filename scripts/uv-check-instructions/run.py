"""Count rustc user instructions across the 20 first-parent uv edits ending at c99faeee."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
TIP = "c99faeeeeb8318d874007b4c48635d009838c1a0"
CHECK = ["check", "--locked", "--offline"]


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def command(argv, cwd, env, log):
    with log.open("w") as f:
        p = subprocess.run(argv, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT)
    if p.returncode:
        print(log.read_text()[-4000:], flush=True)
        raise RuntimeError(f"{argv} failed ({p.returncode})")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args])


def read_counts(output):
    units = []
    for line in output.read_text().splitlines():
        pid, name, kind, n, enabled, running = line.split("\t")
        assert int(n) > 0 and 0 < int(enabled) * .995 <= int(running) <= int(enabled)
        units.append(dict(pid=int(pid), name=name, kind=kind, instructions=int(n),
                          enabled=int(enabled), running=int(running)))
    return sorted(units, key=lambda v: (v["name"], v["kind"]))


def calibrate(tmp, out):
    for name in ("meter", "exercise"):
        subprocess.run(["cc", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-pthread", HERE / f"{name}.c", "-o", tmp / name], check=True)
    worker = tmp / "exercise"
    other = tmp / "excluded"
    shutil.copy2(worker, other)
    observations = []
    for rounds in (1, 10_000_001):
        receipt = out / f"calibration-{rounds}.tsv"
        subprocess.run([tmp / "meter", worker, receipt, worker, str(rounds), other], check=True)
        counts = sorted(u["instructions"] for u in read_counts(receipt))
        assert len(counts) == 2, counts
        observations.append(counts)
    # The child runs one two-instruction loop. The parent runs two across
    # its main and worker threads. A third image runs a loop and is excluded.
    for short, long, expected in zip(*observations, [20_000_000, 40_000_000], strict=True):
        assert abs(long - short - expected) <= expected * .005, observations


def link_or_copy(src, dest):
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def run(args, commits, role):
    fixed = args.scratch / "trial"
    fixed.mkdir()
    kit = fixed / "sdk"
    shutil.copytree(getattr(args, role), kit, symlinks=True, copy_function=link_or_copy)
    cargo = kit / "bin/cargo"
    cargo.unlink(missing_ok=True)
    cargo_src = args.candidate_cargo if role == "candidate" and args.candidate_cargo else args.cargo
    shutil.copy2(cargo_src, cargo)
    rustc = kit / "bin/rustc"
    tool = fixed / "rustup/toolchains/ohm"
    tool.parent.mkdir(parents=True)
    tool.symlink_to(kit)
    env = dict(HOME=os.environ["HOME"], LANG="C.UTF-8",
               PATH=str(kit / "bin") + ":" + os.environ["PATH"],
               CARGO_HOME=os.getenv("CARGO_HOME", str(Path.home() / ".cargo")),
               CARGO_BUILD_JOBS=str(args.jobs), CARGO_TARGET_DIR=str(fixed / "target"),
               RUSTUP_HOME=str(fixed / "rustup"), RUSTUP_TOOLCHAIN="ohm")
    src = fixed / "uv"
    src.mkdir()
    out = args.output / role
    out.mkdir()
    driver, = (kit / "lib").glob("librustc_driver-*.so")
    save(out / "sdk.json", dict(rustc=sha(rustc), driver=sha(driver), cargo=sha(cargo)))
    rows = []
    previous_lock = None
    for i, commit in enumerate(commits):
        folder = out / str(i)
        folder.mkdir()
        if i == 0:
            data = git(args.uv, "archive", commit)
            subprocess.run(["tar", "-x"], input=data, cwd=src, check=True)
        else:
            data = git(args.uv, "diff", "--no-renames", "--binary", commits[i-1], commit)
            subprocess.run(["git", "apply", "--whitespace=nowarn"], input=data, cwd=src,
                           env=dict(env, GIT_CEILING_DIRECTORIES=str(fixed)), check=True)
        lock = sha(src / "Cargo.lock")
        if lock != previous_lock and not args.offline:
            command([cargo, "fetch", "--locked", "--target", "x86_64-unknown-linux-gnu"],
                    src, env, folder / "fetch.log")
        previous_lock = lock
        units = []
        if i == 0:
            command([cargo, *CHECK], src, env, folder / "prime.log")
        else:
            receipt = folder / "units.tsv"
            command([args.scratch / "meter", rustc, receipt, cargo, *CHECK],
                    src, env, folder / "check.log")
            units = read_counts(receipt)
        noop = folder / "noop.tsv"
        command([args.scratch / "meter", rustc, noop, cargo, *CHECK],
                src, env, folder / "noop.log")
        assert not read_counts(noop), (i, "unexpected recompilation")
        total = sum(x["instructions"] for x in units)
        title = git(args.uv, "log", "-1", "--format=%s", commit).decode().strip()
        rows.append(dict(commit=commit, title=title, diff=hashlib.sha256(data).hexdigest(),
                         total=total, units=units))
        print(role, i, commit[:8], len(units), total, flush=True)
        save(out / "results.json", rows)
    shutil.rmtree(fixed)
    return dict(total=sum(row["total"] for row in rows),
                invocations=sum(len(row["units"]) for row in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("uv", "control", "candidate", "cargo", "candidate-cargo", "scratch", "output"):
        parser.add_argument("--" + arg, type=lambda p: Path(p).resolve(), required=arg != "candidate-cargo")
    parser.add_argument("--first", choices=["control", "candidate"], required=True)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    args.scratch.mkdir(exist_ok=True, parents=True)
    assert not any(args.scratch.iterdir()), "expected an empty scratch directory"
    calibrate(args.scratch, args.output)
    commits = git(args.uv, "rev-list", "--first-parent", "--max-count=21", TIP).decode().splitlines()[::-1]
    assert len(commits) == 21 and commits[0].startswith("fdc9403a") and commits[-1] == TIP
    cpu = re.search(r"^model name\s*:\s*(.+)$", Path("/proc/cpuinfo").read_text(), re.M)[1]
    summary = dict(cpu=cpu, kernel=platform.release(), jobs=args.jobs, commits=commits,
                   command=["cargo", *CHECK], first=args.first,
                   boot=sha(Path("/proc/sys/kernel/random/boot_id")))
    for role in [args.first, "candidate" if args.first == "control" else "control"]:
        summary[role] = run(args, commits, role)
        assert summary[role]["total"] > 0
    summary["reduction_pct"] = 100 * (1 - summary["candidate"]["total"] / summary["control"]["total"])
    print(summary["reduction_pct"], flush=True)
    save(args.output / "summary.json", summary)


if __name__ == "__main__":
    main()
