"""Install the assembled package in a literal path, then race its two real prefixes."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify


def need(value, message):
    if not value:
        raise ValueError(message)


def record(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def private_env(work, marker):
    for name in ("home", "rustup/toolchains", "cargo", "tmp with spaces"):
        (work / name).mkdir(parents=True)
    (work / "rustup/settings.toml").write_text('version = "12"\nprofile = "minimal"\n')
    env = {k: os.environ[k] for k in ("PATH", "SDKROOT", "DEVELOPER_DIR", "MACOSX_DEPLOYMENT_TARGET") if k in os.environ}
    env.update(HOME=str(work / "home"), RUSTUP_HOME=str(work / "rustup"), CARGO_HOME=str(work / "cargo"),
               TMPDIR=str(work / "tmp with spaces"), RUSTUP_AUTO_INSTALL="0", LC_ALL="C", OHM_QA_MARKER=str(marker))
    return env


def command(reports, name, argv, env):
    proc = subprocess.run(argv, env=env, cwd=env["HOME"], capture_output=True, timeout=1200)
    (reports / (name + ".stdout")).write_bytes(proc.stdout)
    (reports / (name + ".stderr")).write_bytes(proc.stderr)
    record(reports / (name + ".json"), {"argv": list(map(str, argv)), "status": proc.returncode})
    return proc


def aliases(sdk, env, reports, label):
    """Exercise the real rustup selection and executable through each actual symlink."""
    found = {}
    for alias in (verify.TOOLCHAIN, "ohm"):
        link = Path(env["RUSTUP_HOME"]) / "toolchains" / alias
        need(link.is_symlink() and link.samefile(sdk), "rustup registration points elsewhere")
        for tool in ("rustc", "cargo"):
            expected_path = sdk / "bin" / tool
            selected = command(reports, f"{label}-{alias}-{tool}-which", ["rustup", "which", "--toolchain", alias, tool], env)
            selected.check_returncode()
            need(selected.stdout.endswith(b"\n"), "unexpected rustup which output")
            path = Path(os.fsdecode(selected.stdout[:-1]))
            need(path.samefile(expected_path), "wrong selected tool")
            proc = command(reports, f"{label}-{alias}-{tool}-version", ["rustup", "run", alias, tool, "-vV"], env)
            proc.check_returncode()
            revision = verify.SOURCES["rust" if tool == "rustc" else tool]
            need(f"commit-hash: {revision}".encode() in proc.stdout.splitlines(), "different native revision")
            found[tool] = verify.digest(expected_path)
    return found


def run(args):
    release, normal = args.release.resolve(strict=True), args.installed.resolve(strict=True)
    # Sum regular installed files. The archive, its extraction and the staged install can coexist.
    size = sum(s.st_size for p in normal.rglob("*") if stat.S_ISREG((s := p.lstat()).st_mode))
    archive = release / f"{verify.TOOLCHAIN}-{args.target}.tar.gz"
    need(shutil.disk_usage(args.work_parent).free > (4 << 30) + 2 * (size + archive.stat().st_size),
         "insufficient room for a second real installation")
    exercise(args, release, normal, archive)


def exercise(args, release, normal, archive):
    args.reports.mkdir()
    with tempfile.TemporaryDirectory(prefix="ohm-literal-", dir=args.work_parent) as tmp:
        root = Path(tmp).resolve(strict=True)
        marker = root / "unexpected-shell-execution"
        odd = root / "line\n.." / "$(touch${IFS}$OHM_QA_MARKER)" / "sdk"
        env = private_env(root / "first", marker) | {"OHM_DOWNLOAD_URL": "file://" + str(release), "OHM_INSTALL_DIR": str(odd)}
        argv = ["sh", str(release / "ohm-installer.sh")]
        command(args.reports, "fresh-literal-install", argv, env).check_returncode()
        need(not marker.exists() and not marker.is_symlink(), "a literal shell fragment executed")
        need(odd.is_dir() and not odd.is_symlink() and not odd.samefile(normal), "missing independent installation")
        native = aliases(odd, env, args.reports, "literal")
        need(all(digest == verify.digest(normal / "bin" / name) for name, digest in native.items()), "different installed bytes")

        race = private_env(root / "race", marker) | {"OHM_DOWNLOAD_URL": "file://" + str(release)}
        processes = []
        outcomes = []
        try:
            for role, prefix in (("normal", normal), ("literal", odd)):
                out = args.reports / (role + "-race.stdout")
                err = args.reports / (role + "-race.stderr")
                with out.open("xb") as stdout, err.open("xb") as stderr:
                    proc = subprocess.Popen(argv, cwd=race["HOME"], env=race | {"OHM_INSTALL_DIR": str(prefix)},
                                            stdout=stdout, stderr=stderr)
                processes.append((role, prefix, proc))
            need(all(p.poll() is None for _, _, p in processes), "installer processes did not overlap")
            linked = {}
            for role, prefix, proc in processes:
                code = proc.wait(timeout=1200)
                outcomes.append({"role": role, "pid": proc.pid, "prefix": str(prefix), "status": code})
                if code == 0:
                    linked[role] = prefix
                else:
                    stderr = (args.reports / (role + "-race.stderr")).read_bytes()
                    phrases = (b"refusing to replace an existing immutable rustup toolchain:", b"could not register immutable rustup toolchain:")
                    need(code == 1 and any(phrase + b" " + verify.TOOLCHAIN.encode() in stderr for phrase in phrases),
                         "concurrent loser failed for an unrelated reason")
            need(len(linked) == 1, "two prefixes claimed the same immutable name")
            role, winner = next(iter(linked.items()))
            need(aliases(winner, race, args.reports, "race-winner") == native, "registered winner changed the tools")
            need(not marker.exists() and not marker.is_symlink(), "a literal prefix executed during registration")
        finally:
            for _, _, proc in processes:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
            record(args.reports / "race-processes.json", outcomes)
        record(args.reports / "complete.json", {"target": args.target, "staging": verify.COORDINATOR,
               "native_builder": verify.BUILDERS[args.target], "installer_sha256": verify.digest(release / "ohm-installer.sh"),
               "archive_sha256": verify.digest(archive), "native": native, "marker_absent": True, "race_winner": role})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("release", "installed", "work-parent", "reports"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--target", choices=verify.TARGETS, required=True)
    run(parser.parse_args())
