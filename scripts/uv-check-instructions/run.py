"""Count rustc user instructions across the 20 first-parent uv edits and the two following holdouts."""

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
HOLDOUT = "7bf2d9a3ae44f53a19eed9dcc2348492c8f9f2be"
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


def messages(cargo, src, env, log):
    with log.open("w") as err:
        text = subprocess.check_output([cargo, *CHECK, "--message-format=json"],
                                       cwd=src, env=env, stderr=err, text=True)
    rows = []
    for line in text.splitlines():
        event = json.loads(line)
        if event["reason"] == "compiler-message":
            rows.append(json.dumps(event, sort_keys=True))
    return sorted(rows)


def local_outputs(target, local):
    records = {}
    for pkgdir in (target / "debug/build").iterdir():
        if pkgdir.name not in local:
            continue
        for pattern in ("*/out/*.rmeta", "*/fingerprint/*.public-api-hash"):
            for path in pkgdir.glob(pattern):
                with path.open("rb") as f:
                    header = f.read(56)
                public = header[40:56].hex() if header.startswith(b"rust") else None
                records[path.relative_to(target).as_posix()] = dict(public=public, sha=sha(path))
    return records


def compare_fresh(cargo, src, env, out):
    target = Path(env["CARGO_TARGET_DIR"])
    saved = target.with_name("preserved-target")
    local = {p.name for p in (src / "crates").iterdir()}
    warm = local_outputs(target, local)
    warm_diagnostics = messages(cargo, src, env, out / "warm-diagnostics.log")
    target.rename(saved)
    try:
        # Registry artifacts carry no uv workspace state. Use the same paths
        # for both checks so file hashes include identical source locations.
        build = target / "debug/build"
        build.mkdir(parents=True)
        for package in (saved / "debug/build").iterdir():
            if package.name not in local and package.is_dir():
                shutil.copytree(package, build / package.name, symlinks=True)
        command([cargo, *CHECK], src, env, out / "fresh.log")
        fresh = local_outputs(target, local)
        diagnostics = messages(cargo, src, env, out / "fresh-diagnostics.log")
        assert sum(x["public"] is not None for x in fresh.values()) > 50
        assert fresh.keys() <= warm.keys(), fresh.keys() - warm.keys()
        # Look up the active units using the fresh output paths. The history
        # retains other files from builds using earlier dependency versions.
        records = {p: dict(warm=warm[p], fresh=v) for p, v in fresh.items()}
        if out.name == '4':
            for p in records:
                path = Path(p)
                if path.name.startswith('libuv_auth-') and path.suffix == '.rmeta':
                    shutil.copyfile(target / path, out / 'fresh-uv-auth.rmeta')
                    shutil.copyfile(saved / path, out / 'warm-uv-auth.rmeta')
        save(out / "audit.json", dict(outputs=records, warm_diagnostics=warm_diagnostics,
                                      fresh_diagnostics=diagnostics))
    finally:
        shutil.rmtree(target)
        saved.rename(target)


import struct

END = b"rust-end-file"
TAG = 0xC0FFEE_C0FFEE_C0FFEE_C0FFEE_C0FFEE

def leb(stream):
    n = shift = 0
    while True:
        c = stream.read(1)[0]
        n |= (c & 127) << shift
        if c < 128:
            return n
        shift += 7

def generations(path):
    lengths = []
    with path.open('rb') as stream:
        end = path.stat().st_size
        while True:
            lengths.append(end)
            stream.seek(end - len(END) - 8)
            footer, = struct.unpack('<Q', stream.read(8))
            assert stream.read(len(END)) == END
            stream.seek(footer)
            assert leb(stream) == TAG, (path, footer)
            present = stream.read(1)[0]
            if not present:
                break
            assert present == 1
            end = leb(stream)
            assert end <= footer
    return lengths

def shape(path):
    with path.open('rb') as stream:
        stream.seek(-len(END) - 24, 2)
        slots,live,edges = struct.unpack('<QQQ',stream.read(24))
        assert stream.read(len(END)) == END
        return dict(slots=slots,live=live,edges=edges)


def cache_state(target):
    rows = {}
    for graph in target.rglob('dep-graph.bin'):
        try:
            row = dict(shape(graph), modified=graph.stat().st_mtime_ns,
                       generations=generations(graph.with_name('query-cache.bin')))
        except (OSError, IndexError, AssertionError, ValueError, struct.error) as e:
            row = dict(error=repr(e))
        rows[str(graph.relative_to(target))] = row
    return rows


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
        receipt = folder / ("units.tsv" if i else "prime.tsv")
        log = folder / ("check.log" if i else "prime.log")
        command([args.scratch / "meter", rustc, receipt, cargo, *CHECK], src, env, log)
        units = read_counts(receipt)
        if i == 0:
            assert units
            units = []
        noop = folder / "noop.tsv"
        command([args.scratch / "meter", rustc, noop, cargo, *CHECK],
                src, env, folder / "noop.log")
        assert not read_counts(noop), (i, "unexpected recompilation")
        if i >= 18:
            save(folder / "state.json", cache_state(fixed / "target"))
        if args.audit and units:
            compare_fresh(cargo, src, env, folder)
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
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--release", type=Path)
    parser.add_argument("--current", type=Path)
    parser.add_argument("--intermediate", type=Path)
    parser.add_argument("--second", type=Path)
    parser.add_argument("--pair", type=int)
    parser.add_argument("--audit-role", choices=["control", "candidate"], default="candidate")
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    args.scratch.mkdir(exist_ok=True, parents=True)
    assert not any(args.scratch.iterdir()), "expected an empty scratch directory"
    calibrate(args.scratch, args.output)
    commits = git(args.uv, "rev-list", "--first-parent", "--max-count=23", HOLDOUT).decode().splitlines()[::-1]
    assert len(commits) == 23 and commits[0].startswith("fdc9403a")
    assert commits[20] == TIP and commits[-1] == HOLDOUT
    cpu = re.search(r"^model name\s*:\s*(.+)$", Path("/proc/cpuinfo").read_text(), re.M)[1]
    summary = dict(cpu=cpu, kernel=platform.release(), jobs=args.jobs, commits=commits,
                   command=["cargo", *CHECK], first=args.first,
                   boot=sha(Path("/proc/sys/kernel/random/boot_id")))
    roles = [args.first, "candidate" if args.first == "control" else "control"]
    if args.pair is not None:
        # Rotating the initial positions and reversing each adjacent pair
        # means each two-way comparison runs each arm first three times.
        roles = [r for r in ("release","control","current","intermediate","second","candidate")
                 if getattr(args,r)]
        offset = (args.pair-1)//2
        roles = roles[offset:] + roles[:offset]
        if args.pair % 2 == 0:
            roles.reverse()
        summary["first"] = next(r for r in roles if r in ("control","candidate"))
        summary["order"] = roles
    if args.audit:
        roles = [args.audit_role]
    if args.probe:
        roles = ["candidate"]
    for role in roles:
        summary[role] = run(args, commits, role)
        assert summary[role]["total"] > 0
    if args.audit:
        save(args.output / "audit-summary.json", summary)
        return
    if args.probe:
        save(args.output / "probe-summary.json", summary)
        return
    summary["reduction_pct"] = 100 * (1 - summary["candidate"]["total"] / summary["control"]["total"])
    print(summary["reduction_pct"], flush=True)
    save(args.output / "summary.json", summary)


if __name__ == "__main__":
    main()
