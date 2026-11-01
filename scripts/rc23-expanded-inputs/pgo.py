"""Retain the outcome of the untouched production command before any diagnostic execution."""

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from materialize import REG, checkout, git, need, save, sha

BENCHES = {
    "externs": False,
    "ctfe-stress-5": False,
    "cargo-0.87.1": True,
    "token-stream-stress": False,
    "match-stress": False,
    "tuple-stress": True,
    "diesel-2.2.10": True,
    "bitmaps-3.2.1": True,
    "serde-1.0.219-new-solver": None,
}
SECTION = "Stage 1 (rustc + rustdoc + cargo + clippy + rustfmt PGO) > Gather rustc profiles"
COVERED = "verified executed PGO profile coverage for rustc, rustdoc, Cargo, Clippy, rustfmt, and cargo-fmt"


def training_command(line, host, build=None):
    text = re.fullmatch(r".*?opt_dist::exec\] Executing `([^`]+) \[at ([^\]]+)\]`", line)
    need(text, "unrecognized native training command")
    cwd = Path(text[2])
    root = cwd.parent.parent
    need(
        cwd.is_absolute() and cwd == root / "opt-artifacts/rustc-perf" and (build is None or root == build),
        "foreign native training root",
    )
    stage = root / host
    variables = {
        "LLVM_PROFILE_FILE": str(root / "opt-artifacts/rustc-pgo/default_%m_%p.profraw"),
        "RUSTC": str(stage / "stage0/bin/rustc"),
        "RUSTC_BOOTSTRAP": "1",
    }
    args = shlex.split(text[1])
    need(
        sorted(args[:3]) == sorted(k + "=" + v for k, v in variables.items()),
        "different training environment",
    )
    expected = [
        str(stage / "stage0/bin/cargo"),
        "run",
        "-p",
        "collector",
        "--bin",
        "collector",
        "--",
        "profile_local",
        "eprintln",
        str(stage / "stage2/bin/rustc"),
        "--id",
        "Test",
        "--cargo",
        str(stage / "stage2-tools-bin/cargo"),
        "--profiles",
        "Check,Debug,Opt",
        "--scenarios",
        "All",
        "--exact-match",
        ",".join(BENCHES),
        "--jobs",
        "4",
    ]
    need(args[3:] == expected, "different compiler, Cargo, collector, or training arguments")
    return {"argv": expected, "env": variables, "cwd": str(cwd)}


def roster(log, host, build=None):
    mark = chr(96) + SECTION + chr(96)
    (start,) = [i for i, l in enumerate(log) if l.endswith("Section " + mark + " starts")]
    (end,) = [
        i
        for i, l in enumerate(log)
        if re.search(r"Section " + re.escape(mark) + r" ended: OK \([\d.]+s\)" + chr(96) + r"$", l)
    ]
    need(start < end, "misordered PGO training")
    group = log[start : end + 1]
    (cmd,) = [
        l
        for l in group
        if " --bin collector -- profile_local eprintln " in l and " --profiles Check,Debug,Opt " in l
    ]
    native = training_command(cmd, host, build)
    have = sorted(l for l in group if l.startswith("Running ") and "FrontendThreads(" in l)
    target = "X86_64UnknownLinuxGnu" if host.startswith("x86_64") else "AArch64UnknownLinuxGnu"
    want = []
    for name, patched in BENCHES.items():
        states = ["Full"]
        if patched is not None:
            states += ["IncrFull", "IncrUnchanged"]
        if patched:
            states += ["IncrPatched"]
        for profile in ("Check", "Debug", "Opt"):
            want.append(
                f"Running {name}: {profile} + [{', '.join(states)}] + Llvm + {target} + FrontendThreads(1)"
            )
    need(have == sorted(want), ("different native collector scenario roster", set(have) ^ set(want)))
    done = [r.groups() for l in group if (r := re.fullmatch(r"Finished benchmark ([^ ]+) \(([1-9])/9\)", l))]
    need(
        len(done) == 9
        and {a for a, _ in done} == set(BENCHES)
        and {int(b) for _, b in done} == set(range(1, 10)),
        "incomplete nine-benchmark training",
    )
    return {
        "command": cmd,
        "invocation": native,
        "rows": have,
        "finished": done,
        "begin": log[start],
        "end": log[end],
    }


def refused_dependency_dir(lines, at, rustc):
    """Return the workspace named by a matched rustc-fake denial and its Cargo error."""
    # rustc-fake prints Rust Debug tool and argv immediately before its refusal.
    if at < 2 or at + 4 >= len(lines):
        return None
    marker = json.dumps(str(rustc)) + " "
    if not lines[at - 1].startswith(marker):
        return None
    try:
        args = json.loads(lines[at - 1][len(marker) :])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            return None
        if args.count("--crate-name") != 1 or args.count("--out-dir") != 1 or any(a.startswith("--out-dir=") for a in args):
            return None
        crate = args[args.index("--crate-name") + 1]
        output = args[args.index("--out-dir") + 1]
        before = re.fullmatch(r"stderr=\s*(?:Checking|Compiling) ([A-Za-z0-9_-]+) v[^\s]+(?: .*)?", lines[at - 2])
        if not before or before[1].replace("-", "_") != crate:
            return None
        package = before[1]
        if lines[at + 1 : at + 4] != [f"error: could not compile `{package}` (lib)", "", "Caused by:"]:
            return None
        failed = re.fullmatch(r"  process didn't exit successfully: `([^`]+)` \(exit status: 1\)", lines[at + 4])
        if not failed:
            return None
        outer = shlex.split(failed[1])
    except (ValueError, IndexError):
        return None
    wrapper = rustc.parents[3] / "opt-artifacts/rustc-perf/target/debug/rustc-fake"
    appended = ["-Zthreads=1", "-Adeprecated", "-Aunknown-lints", "-Zincremental-verify-ich"]
    if not outer or outer[0] != str(wrapper) or outer[1:] + appended != args:
        return None
    if {"--wrap-rustc-with", "--skip-this-rustc", "-vV", "--print=file-names", "--print=sysroot"} & set(args):
        return None
    path = Path(output)
    if not path.is_absolute() or str(path) != output or ".." in path.parts:
        return None
    # Only the TempDir itself goes to the existing trusted-parent and no-symlink gate.
    roots = [p.parent for p in path.parents if p.name == "target" and re.fullmatch(r"\.tmp[A-Za-z0-9]+", p.parent.name)]
    return str(roots[0]) if len(roots) == 1 else None


def reported_temps(lines, temp, rustc=None):
    paths = set()
    for i, l in enumerate(lines):
        if rustc is not None and l == "exiting -- non-wrapped rustc":
            candidate = refused_dependency_dir(lines, i, rustc)
            if candidate:
                paths.add(candidate)
        if l.startswith("stderr=") and (
            m := re.search(r"\bCompiling [^\s]+ v[^\s]+ \((/[^\n]+/\.tmp[A-Za-z0-9]+)\)$", l)
        ):
            paths.add(m[1])
        if l.startswith("command did not complete successfully: "):
            for arg in shlex.split(l.partition(": ")[2]):
                if arg.startswith("incremental=/") and arg.endswith("/incremental-state"):
                    paths.add(str(Path(arg.partition("=")[2]).parent))
        if "rustc-ice-" in l:
            for candidate in re.findall(r"(/[^\x27\x60\x22\s]+/\.tmp[A-Za-z0-9]+)/rustc-ice-", l):
                paths.add(candidate)
    found = {}
    for p in sorted(paths):
        path = Path(p)
        need(
            path.is_absolute()
            and re.fullmatch(r"\.tmp[A-Za-z0-9]+", path.name)
            and path.parent.resolve() == temp,
            ("unowned collector path", p),
        )
        # macOS reports /var and /private/var for one retained TempDir.
        # Resolve only its trusted parent so a symlink at the leaf still refuses.
        found.setdefault(temp / path.name, []).append(str(path))
    return found


def evidence(a):
    a.out.mkdir()
    root = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    old = root / "legacy"
    checkout(old, REG["legacy"])
    need(
        a.rust.resolve(strict=True) == root / "source/rust"
        and git(a.rust, "rev-parse", "HEAD") == REG["rust_tail"]["commit"]
        and git(a.rust, "rev-parse", "HEAD:src/tools/rustc-perf") == REG["native_subtrees"]["rustc-perf"],
        "unregistered source for capture",
    )
    raw = a.log.read_bytes()
    lines = raw.decode(errors="replace").splitlines()
    build = a.rust / "build"
    stage = build / a.host
    perf = build / "opt-artifacts/rustc-perf"
    paths = [
        stage / "stage2/bin/rustc",
        stage / "stage2-tools-bin/cargo",
        *sorted((stage / "stage2/lib").glob("librustc_driver-*")),
        *(
            perf / "target" / profile / name
            for profile in ("debug", "release")
            for name in ("collector", "rustc-fake")
        ),
    ]
    record = {
        "host": a.host,
        "outcome": a.outcome,
        "log": {"path": str(a.log), "sha256": sha(a.log), "bytes": len(raw)},
        "source": REG["rust_tail"]["commit"],
        "rustc_perf_gitlink": REG["native_subtrees"]["rustc-perf"],
        "job": os.environ["GITHUB_JOB"],
        "run": os.environ["GITHUB_RUN_ID"],
        "qa": os.environ["GITHUB_SHA"],
        "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
    }
    # On success these can be later stages of the same build. Do not label their
    # hashes as the original profiled compiler. The original invocation is in the log.
    record["present_after_build"] = {str(p): [p.stat().st_size, sha(p)] for p in paths if p.is_file()}
    merged = {}
    for name in ("rustc", "rustdoc", "clippy", "rustfmt"):
        p = build / "opt-artifacts" / (name + "-pgo.profdata")
        if p.is_file() and not p.is_symlink():
            merged[name] = {"path": str(p), "bytes": p.stat().st_size, "sha256": sha(p)}
    record["merged"] = merged
    save(a.out / "entry.json", record)
    if a.outcome == "success":
        record["roster"] = roster(lines, a.host, build)
        need(
            COVERED in lines
            and set(merged) == {"rustc", "rustdoc", "clippy", "rustfmt"}
            and all(r["bytes"] for r in merged.values()),
            "missing original covered-function/profile result",
        )
    else:
        # Use the same read-only file/dir/hardlink/mode comparison as the original
        # Darwin escrow. The only writable destination is this new diagnostic directory.
        sys.path.insert(0, str(old / "scripts/darwin-pgo-diesel"))
        from escrow import facts, pack

        captured = []
        missing = []
        different = []
        remaining = 2 << 30
        observed = reported_temps(lines, a.temp.resolve(strict=True), stage / "stage2/bin/rustc")
        record["reported_collector_paths"] = {str(path): names for path, names in observed.items()}
        for i, path in enumerate(observed):
            if path.is_symlink():
                different.append({"path": str(path), "error": "symlink at collector directory"})
                continue
            if not path.exists():
                missing.append(str(path))
                continue
            try:
                need(
                    path.is_dir() and not path.is_symlink() and path.resolve().parent == a.temp.resolve(),
                    ("foreign collector directory", path),
                )
                root_stat = path.stat()
                _, size = facts(path, remaining)
                out = a.out / f"original-{i}.tar.gz"
                row = pack(path, out, remaining)
                after = path.stat()
                need(
                    (root_stat.st_dev, root_stat.st_ino) == (after.st_dev, after.st_ino),
                    "collector root replaced during capture",
                )
                captured.append(
                    dict(
                        row, original=str(path), archive=out.name, dev=root_stat.st_dev, ino=root_stat.st_ino
                    )
                )
                remaining -= size
            except (OSError, ValueError) as exc:
                different.append({"path": str(path), "error": str(exc)})
        record.update(
            captured=captured,
            absent=missing,
            refused=different,
            failure_tail=lines[-100:],
            matched_382=[l for l in lines if "serialized.rs:382" in l],
            failed_collector=[
                l for l in lines if "Failed to profile" in l or "exiting -- non-wrapped rustc" in l
            ],
        )
        save(a.out / "failure.json", record)
        need(not missing and not different, "unable to preserve a reported collector directory")
        need(
            captured or not record["failed_collector"] and not record["matched_382"],
            "collector failed without an attributable retained working directory",
        )
    # An early unrelated distribution failure may predate rustc-perf setup. Save
    # any genuine retained workspace before these additional identity checks.
    pins = json.loads((old / "scripts/darwin-pgo-diesel/collector-members.json").read_bytes())
    source = a.rust / "src/tools/rustc-perf"
    if a.outcome == "success" or (source / ".git").exists():
        need(
            git(source, "rev-parse", "HEAD") == REG["native_subtrees"]["rustc-perf"]
            and all(sha(source / name) == h for name, h in pins.items()),
            "different native collector or Diesel inputs",
        )
        record["collector_inputs"] = pins
    if perf.is_dir():
        present = {name: sha(perf / name) for name in pins if (perf / name).is_file()}
        need(all(pins[n] == h for n, h in present.items()), "different staged native collector source")
        record["collector_inputs_present_after_build"] = present
    save(a.out / "complete.json", record)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("rust", "temp", "out", "log"):
        p.add_argument("--" + k, type=Path, required=True)
    p.add_argument("--outcome", choices=("success", "failure"), required=True)
    p.add_argument("--host", choices=("x86_64-unknown-linux-gnu", "aarch64-apple-darwin"), required=True)
    evidence(p.parse_args())
