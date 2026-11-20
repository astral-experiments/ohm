"""Sample two units at the first held-out uv check after the twenty-edit replay."""

import argparse
import collections
import gzip
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import CHECK, TIP, HOLDOUT, command, git, sha


def find_perf():
    for path in [shutil.which("perf"), *Path("/usr/lib/linux-tools").glob("*/perf")]:
        if path and subprocess.run([path, "--version"], capture_output=True).returncode == 0:
            return path
    raise RuntimeError("install linux-tools-generic")


def main():
    parser = argparse.ArgumentParser()
    for arg in ("uv", "control", "candidate", "cargo", "candidate-cargo", "scratch", "output"):
        parser.add_argument("--" + arg, type=lambda p: Path(p).resolve())
    parser.add_argument("--first")
    parser.add_argument("--jobs", type=int)
    args = parser.parse_args()
    perf = find_perf()
    commits = git(args.uv, "rev-list", "--first-parent", "--max-count=23", HOLDOUT).decode().splitlines()[::-1]
    assert len(commits) == 23 and commits[20] == TIP
    src = args.scratch / "uv"
    src.mkdir(parents=True)
    args.output.mkdir(parents=True, exist_ok=True)
    annotate = bool(os.getenv("ANNOTATE_UV"))
    role = "candidate" if annotate else args.first
    sdk = getattr(args, role)
    (args.output / "profile-role").write_text(role + "\n")
    cargo = sdk / "bin/cargo"
    shutil.copy2(args.candidate_cargo or args.cargo, cargo)
    tc = args.scratch / "rustup/toolchains/ohm"
    tc.parent.mkdir(parents=True)
    tc.symlink_to(sdk)
    env = dict(HOME=os.environ["HOME"], LANG="C.UTF-8",
               PATH=str(sdk / "bin") + ":" + os.environ["PATH"],
               CARGO_HOME=os.environ["CARGO_HOME"],
               CARGO_BUILD_JOBS=str(args.jobs), CARGO_TARGET_DIR=str(args.scratch / "target"),
               RUSTUP_HOME=str(args.scratch / "rustup"), RUSTUP_TOOLCHAIN="ohm")
    old_lock = None
    wrapper = Path(__file__).resolve().parent / "repeat-rustc.py"
    wrapper.chmod(0o755)
    for i, commit in enumerate(commits):
        if i == 0:
            subprocess.run(["tar", "-x"], input=git(args.uv, "archive", commit), cwd=src, check=True)
        else:
            diff = git(args.uv, "diff", "--no-renames", "--binary", commits[i-1], commit)
            subprocess.run(["git", "apply", "--whitespace=nowarn"], cwd=src, input=diff, check=True)
        lock = sha(src / "Cargo.lock")
        if lock != old_lock:
            command([cargo, "fetch", "--locked", "--target", "x86_64-unknown-linux-gnu"],
                    src, env, args.output / f"{i}-fetch.log")
        old_lock = lock
        argv = [cargo, *CHECK]
        subjects = ["uv_lock", "uv_project_commands"] if i == 21 else []
        step = env
        if subjects:
            step = dict(env, RUSTC_WRAPPER=str(wrapper), REPEAT_UNITS=",".join(subjects),
                        REPEAT_COUNT="16", REPEAT_DIR=str(args.output),
                        PERF_DIR=str(args.scratch), PROFILER=str(perf))
        command(argv, src, step, args.output / f"{i}-build.log")
        for unit in subjects:
            assert (args.output / (unit+"-repeats")).is_file()
            binary = args.scratch / (unit+".data")
            data = subprocess.check_output([perf, "report", "--stdio", "-i", binary,
                "--sort=comm,dso,symbol", "--fields=period,sample,comm,dso,symbol",
                "--percent-limit=0", "--field-separator=|", "--call-graph=none", "--no-children"], env=env)
            with gzip.open(args.output / f"{unit}-symbols.txt.gz", "wb") as f:
                f.write(data)
            data = subprocess.check_output([perf, "report", "--stdio", "-i", binary,
                "--sort=dso,symbol", "--comms=rustc", "--field-separator=|",
                "--call-graph=none", "--percent-limit=0", "--children"], env=env)
            with gzip.open(args.output / f"{unit}-children.txt.gz", "wb") as f:
                f.write(data)
            binary.unlink()
        if subjects:
            break
        print(i, commit, flush=True)


if __name__ == "__main__":
    main()
