"""Sample a dependency update and a source edit in the uv history on the candidate."""

import argparse
import gzip
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import CHECK, TIP, command, git, sha


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
    commits = git(args.uv, "rev-list", "--first-parent", "--max-count=21", TIP).decode().splitlines()[::-1]
    assert len(commits) == 21
    src = args.scratch / "uv"
    src.mkdir(parents=True)
    args.output.mkdir(parents=True, exist_ok=True)
    sdk = args.candidate
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
    for i, commit in enumerate(commits[:11]):
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
        binary = args.scratch / "perf.data"
        if i in (4, 10):
            argv = [perf, "record", "-e", "instructions:u", "-c", "3000017",
                    "--call-graph", "dwarf,4096", "-o", binary, "--", *argv]
        command(argv, src, env, args.output / f"{i}-build.log")
        if binary.is_file():
            for key in ("children", "no-children"):
                data = subprocess.check_output([perf, "report", "--stdio", "-i", binary,
                    "--sort=dso,symbol", "--percent-limit=0.002", "--field-separator=|",
                    "--call-graph=none", "--" + key], env=env)
                with gzip.open(args.output / f"{i}-{key}.txt.gz", "wb") as f:
                    f.write(data)
            binary.unlink()
        print(i, commit, flush=True)


if __name__ == "__main__":
    main()
