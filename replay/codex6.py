"""Replay four landed Codex diffs with each SDK in a fresh Linux workspace."""

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import runpy
import shutil
import subprocess as sp
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from history import calibrate, command, git, link_or_copy, read_counts, save, sha

EDITS = {
    "core": {
        37939: "41ece455b7fa7166f4fc38522952afdaa2604e18",
        38078: "f317dc8a17d30d8feb2c79add1d9d565be0402bf",
        38084: "52d92184240bd0946e3e15b3a568f8014a9e0b97",
        38358: "80ceab7aaa25068aee26a52353c0d63039c93b29",
    },
    "tui": {
        38657: "5186e2ccc305ab54a2bb1239fda3656d8b4ab950",
        39057: "796325f1e584e6171abb7b282b62a37777bc51e4",
        39077: "e92627bf7e5f1aa87254b8eedc4a2d19f614452a",
        39864: "9ab176f488f5da100984a005688f041d49e06bdb",
    },
}
BASE = {"core": EDITS["core"][38084], "tui": "c909d1bc0462d0b8bfd4525264cce938fd2475e8"}
UNDO = {"core": [38084, 38078, 37939], "tui": []}
REPO = "https://github.com/openai/codex.git"


def prepare(root, part):
    # Only the listed changes enter the seeded checkout, not intervening commits.
    repo = root / "codex"
    repo.mkdir()
    git(repo, "init", "-q")
    tips = sorted(set(EDITS[part].values()) | {BASE[part]})
    git(repo, "fetch", "-q", "--depth=2", "--no-tags", REPO, *tips)
    git(repo, "checkout", "--quiet", "--detach", BASE[part])
    for pr, commit in EDITS[part].items():
        patch = git(repo, "diff", "--binary", "--full-index", commit + "^", commit)
        (root / f"{pr}.diff").write_bytes(patch)

    helper = HERE.parent / "scripts/session_replays/helpers/codex-1.100/prepare.py"
    support = runpy.run_path(str(helper))
    archive = root / (support["CRATE"] + ".crate")
    sp.run(["curl", "--retry", "4", "-fsSLo", archive,
            "https://static.crates.io/crates/allocative/" + archive.name], check=True)
    crate = support["prepare_crate"](archive, root)
    (root / ".cargo").mkdir()
    (root / ".cargo/config.toml").write_text("paths = " + json.dumps([str(crate)]) + "\n")
    return {
        "source": REPO, "base": BASE[part], "revert_before_seed": UNDO[part],
        "lock": sha(repo / "codex-rs/Cargo.lock"), "allocative_fix": support["UPSTREAM_FIX"],
        "edits": [dict(pr=pr, commit=commit, sha256=sha(root / f"{pr}.diff"))
                  for pr, commit in EDITS[part].items()],
    }


def preflight(root, out, env, role, case):
    # Include rmake.rs verbatim. The shim supplies just the std-based command and
    # file helpers used by these fixtures so a full Rust bootstrap is unnecessary.
    test = root / "preflight"
    test.mkdir()
    cases = json.loads((HERE / "placement6.json").read_text())
    revision = cases[role]["revision"]
    for name, data in cases[role]["cases"][case].items():
        (test / name).write_text(data)
    (test / "shim.rs").write_text(cases["shim"] + '\ninclude!("rmake.rs");\n')
    env = env | {"RUSTC_BOOTSTRAP": "1"}
    with (out / "fixture.log").open("w") as log:
        for cmd in (["rustc", "--edition=2024", "shim.rs"], ["./shim"]):
            p = sp.run(cmd, cwd=test, env=env, stdout=log, stderr=sp.STDOUT)
            if p.returncode:
                break
    return dict(case=case, revision=revision, passed=p.returncode == 0)


def measure(root, rustc, argv, src, env, receipt):
    command([root / "meter", rustc, receipt, *argv], src, env, receipt.with_suffix(".log"))
    jobs = read_counts(receipt)
    tree, enabled, running = map(int, Path(str(receipt) + ".tree").read_text().split())
    rustc_instructions = sum(j["instructions"] for j in jobs)
    assert tree >= rustc_instructions and 0 < enabled * .995 <= running <= enabled
    return {"instructions": tree, "rustc": rustc_instructions, "jobs": jobs}


def cache_sizes(target, part):
    # Cargo's artifact layout varies. Find the local library session by its
    # rustc incremental directory name and report the largest session.
    sessions = []
    for p in (target / "debug").rglob(f"codex_{part}-*"):
        if p.is_dir():
            for q in p.glob("s-*/query-cache.bin"):
                objs = [f.stat().st_size for f in q.parent.glob("*.o")]
                sessions.append(dict(query_cache=q.stat().st_size, objects=len(objs),
                                     largest=max(objs, default=0), total=sum(objs)))
    return max(sessions, key=lambda s: s["query_cache"], default=None)


def trial(root, out, kit, role, part, pair, args):
    fixed = root / "arm"
    sdk = fixed / "sdk"
    shutil.copytree(kit, sdk, symlinks=True, copy_function=link_or_copy)
    cargo, rustc = sdk / "bin/cargo", sdk / "bin/rustc"
    driver, = (sdk / "lib").glob("librustc_driver-*.so")
    tool = fixed / "rustup/toolchains/ohm"
    tool.parent.mkdir(parents=True)
    tool.symlink_to(sdk)
    target = fixed / "target"
    env = dict(HOME=os.environ["HOME"], LANG="C.UTF-8", CARGO_HOME=str(root / "registry"),
               CARGO_TARGET_DIR=str(target), CARGO_TERM_COLOR="never",
               RUSTUP_HOME=str(fixed / "rustup"), RUSTUP_TOOLCHAIN="ohm",
               PATH=str(sdk / "bin") + ":" + os.environ["PATH"])
    out.mkdir()
    row = {"rustc": sha(rustc), "driver": sha(driver), "cargo": sha(cargo),
           "version": sp.check_output([rustc, "-Vv"], env=env, text=True), "edits": {}}
    if pair == 1:
        case = "caller-local-codegen" if part == "core" else "ohm-cgu-version-stability"
        try:
            row["preflight"] = preflight(fixed, out, env, role, case)
        except Exception as exc:
            row["preflight"] = dict(case=case, passed=False, error=str(exc))
        save(out / "preflight.json", row["preflight"])

    repo = root / "codex"
    src = repo / "codex-rs"
    for pr in UNDO[part]:
        git(repo, "apply", "--index", "--reverse", root / f"{pr}.diff")
    row["seed_tree"] = git(repo, "write-tree").decode().strip()
    print(part, role, "prime", row["seed_tree"], flush=True)
    command([cargo, "fetch", "--locked", "--target", "x86_64-unknown-linux-gnu"],
            src, env, out / "fetch.log")
    cmd = [cargo, *args]
    command(cmd, src, env, out / "prime.log")
    row["prime_bytes"] = cache_sizes(target, part)
    for pr in EDITS[part]:
        git(repo, "apply", "--index", root / f"{pr}.diff")
        rec = measure(root, rustc, cmd, src, env, out / f"{pr}.tsv")
        assert any(j["name"] == f"codex_{part}" for j in rec["jobs"]), (pr, rec)
        rec["tree"] = git(repo, "write-tree").decode().strip()
        rec["cache_bytes"] = cache_sizes(target, part)
        row["edits"][pr] = rec
        save(out / "results.json", row)
        print(part, role, pr, rec["instructions"], "instructions", flush=True)
    row["noop"] = measure(root, rustc, cmd, src, env, out / "noop.tsv")
    assert not row["noop"]["jobs"], row["noop"]
    exe = "codex-tui" if part == "tui" else "codex-write-config-schema"
    help_text = sp.check_output([target / "debug" / exe, "--help"], cwd=src, env=env, timeout=30)
    assert b"Usage:" in help_text
    row["help"] = hashlib.sha256(help_text).hexdigest()
    row["total"] = sum(r["instructions"] for r in row["edits"].values())
    row["rustc_total"] = sum(r["rustc"] for r in row["edits"].values())
    save(out / "results.json", row)
    # Restore only the tracked edits in this private checkout. Reuse the same
    # source and absolute target paths with fresh artifacts for the other SDK.
    git(repo, "restore", "--source=HEAD", "--staged", "--worktree", ".")
    assert not git(repo, "status", "--porcelain", "--untracked-files=no")
    shutil.rmtree(fixed)
    return row


def main():
    part, pair = sys.argv[1], int(sys.argv[2])
    control, candidate, out = [Path(p).resolve() for p in sys.argv[3:]]
    assert part in EDITS and pair in (1, 2)
    order = [("control", control), ("candidate", candidate)][::1 if pair == 1 else -1]
    out.mkdir(parents=True, exist_ok=True)
    args = ["build", "--locked", "--offline", "-j12", "-p", "codex-" + part]
    cpu = re.search(r"^model name\s*:\s*(.+)$", Path("/proc/cpuinfo").read_text(), re.M)[1]
    report = dict(project="codex-" + part, cpu=cpu, kernel=platform.release(), pair=pair,
                  command=["cargo", *args], order=[r for r, _ in order])
    with tempfile.TemporaryDirectory(dir=os.getenv("RUNNER_TEMP")) as tmp:
        root = Path(tmp).resolve()
        calibrate(root, out)
        report.update(prepare(root, part))
        for role, kit in order:
            report[role] = trial(root, out / role, kit, role, part, pair, args)
    a, b = report["control"], report["candidate"]
    assert a["help"] == b["help"] and a["seed_tree"] == b["seed_tree"]
    assert all(a["edits"][p]["tree"] == b["edits"][p]["tree"] for p in EDITS[part])
    report["reduction_pct"] = 100 * (1 - b["total"] / a["total"])
    report["edits_pct"] = {p: 100 * (1 - b["edits"][p]["instructions"] / a["edits"][p]["instructions"])
                           for p in EDITS[part]}
    save(out / "summary.json", report)
    print(part, "whole-command savings (%)", report["reduction_pct"], report["edits_pct"])
    if pair == 1:
        for role, _ in order:
            print(role, "preflight", report[role]["preflight"])
            if not report[role]["preflight"]["passed"]:
                raise RuntimeError(f"{role} placement fixture failed. See {role}/fixture.log.")


if __name__ == "__main__":
    main()
