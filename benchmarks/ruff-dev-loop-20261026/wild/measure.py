#!/usr/bin/env python3
"""Count release-14 Cargo commands after a one-byte edit to a disposable Ruff checkout."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shlex
import shutil
import subprocess


RUFF = "93526150df078af7dd8fc4226cdcc469539d2001"
WORKLOADS = {
    "build": ("crates/ruff/src/main.rs", b'"ruff failed"', b'"Ruff failed"', "ruff", ["build"]),
    "test": (
        "crates/ruff_python_formatter/tests/fixtures.rs",
        b'"Unformatted code to be valid syntax"', b'"unformatted code to be valid syntax"',
        "fixtures", ["test", "--no-run"],
    ),
}
SEEDS = {"build": 3495017, "test": 1453907}
SKIP = "*/rustc,*/rustdoc,*/cc,*/clang,*/ld.bfd,*/build-script-*,*/build_script_*,*/usr/bin/*,*/git"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def profiles(directory, linker):
    """Require one complete Cargo, rustc, Clang and no-fork Wild profile."""
    guests = {}
    commands = {}
    logs = {path.suffix for path in directory.glob("vg.*")}
    for profile in directory.glob("guest.*"):
        logs.remove(profile.suffix)
        command = total = None
        with profile.open() as stream:
            for line in stream:
                if line.startswith("cmd: "):
                    command = line[5:].strip()
                elif line.startswith("summary: "):
                    total = int(line.split()[1])
        assert command and total
        name = Path(command.split()[0]).name
        assert name not in guests, (profile, command)
        log = (directory / f"vg{profile.suffix}").read_text()
        assert log.count(" I refs:") == 1 and "Process terminating" not in log
        guests[name] = total
        commands[name] = command.split()
    assert not logs and set(guests) == {"cargo", "rustc", "clang", "ld.bfd"}, guests
    assert "-Wl,--no-fork" in commands["clang"] and commands["ld.bfd"][0] == str(linker)
    wild = commands["ld.bfd"][1:]
    assert "--no-fork" in wild or (len(wild) == 1 and wild[0].startswith("@"))
    return guests


def cargo(env, repo, command, directory, linker, *, count):
    directory.mkdir()
    args = [
        "valgrind", "--tool=cachegrind", "--cache-sim=no", "--branch-sim=no", "--trace-children=yes",
        *([] if count else [f"--trace-children-skip={SKIP}"]),
        f"--cachegrind-out-file={directory}/guest.%p", f"--log-file={directory}/vg.%p",
        "cargo", "+ohm", *command, "--locked", "--offline", "--message-format=json",
    ]
    with (directory / "stdout.jsonl").open("w") as out, (directory / "stderr").open("w") as err:
        subprocess.run(args, cwd=repo, env=env, stdout=out, stderr=err, check=True)
    records = (json.loads(line) for line in (directory / "stdout.jsonl").read_text().splitlines())
    artifacts = [row for row in records if row["reason"] == "compiler-artifact"]
    graph = sorted((r["package_id"], r["target"]["name"], r["target"]["kind"], r["profile"]["test"])
                   for r in artifacts)
    outputs = {r["executable"]: sha(r["executable"]) for r in artifacts if r["executable"]}
    dirty = [r["target"]["name"] for r in artifacts if not r["fresh"]]
    return (graph, outputs), dirty, profiles(directory, linker) if count else {}


def paths(items):
    entries = {name: Path(path).resolve(strict=True) for name, path in (t.split("=", 1) for t in items)}
    if len(entries) != len(items):
        raise ValueError("arm names must be distinct")
    return entries


def replace(source, path):
    """Change a private executable without adding hard links or varying the driver path."""
    incoming = path.with_suffix(".incoming")
    shutil.copy2(source, incoming)
    if path.exists():
        previous = path.stat()
        assert previous.st_nlink == 1
        os.utime(incoming, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    incoming.replace(path)


def private_cargo(sysroot, output):
    """Reuse the selected Ohm compiler and replace only the measured Cargo program."""
    rustup = output / "rustup"
    (rustup / "toolchains").mkdir(parents=True)
    (rustup / "settings.toml").write_text('version = "12"\nprofile = "minimal"\n')
    private = rustup / "toolchains/ohm"
    (private / "bin").mkdir(parents=True)
    (private / "lib").symlink_to(sysroot / "lib")
    for program in (sysroot / "bin").iterdir():
        if program.name != "cargo":
            (private / "bin" / program.name).symlink_to(program)
    return rustup, private / "bin/cargo"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=WORKLOADS)
    ap.add_argument("ruff", type=Path, help="clean disposable Ruff worktree")
    ap.add_argument("output", type=Path, help="new directory for the driver, plan and counters")
    ap.add_argument("linkers", nargs="+", help="name=/path, baseline first")
    ap.add_argument("--cargo", action="append", default=[], help="name=/path, one per arm to vary Cargo too")
    ap.add_argument("--blocks", type=int, default=12)
    ap.add_argument("--seed", type=int)
    args = ap.parse_args()
    linkers, cargos = paths(args.linkers), paths(args.cargo)
    if args.blocks < 1 or len(linkers) < 2 or (cargos and linkers.keys() != cargos.keys()):
        ap.error("supply at least one block, two distinct arms and the same optional Cargo arms")
    for key in ("CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"):
        if not os.environ.get(key):
            ap.error(f"set {key} to a distinct build directory")
    assert Path(os.environ["CARGO_TARGET_DIR"]).resolve() != Path(os.environ["CARGO_BUILD_BUILD_DIR"]).resolve()
    repo, output = args.ruff.resolve(strict=True), args.output.resolve()
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip() == RUFF
    assert not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo)
    relative, old, new, unit, command = WORKLOADS[args.mode]
    source = repo / relative
    original = source.read_bytes()
    assert original.count(old) == 1 and new not in original
    contents = {"original": original, "changed": original.replace(old, new)}
    output.mkdir(parents=True)
    driver, linker = output / "clang", output / "ld.bfd"
    clang = shutil.which("clang")
    assert clang
    driver.write_text(f'#!/bin/sh\nexec {shlex.quote(clang)} "$@" {shlex.quote(f"--ld-path={linker}")} -Wl,--no-fork\n')
    driver.chmod(0o755)
    env = dict(os.environ, CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=str(driver), CARGO_BUILD_JOBS="4",
               CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST="all", CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST="all",
               CARGO_TERM_COLOR="never", RUSTUP_AUTO_INSTALL="0",
               SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt", SSL_CERT_DIR="/etc/ssl/certs")
    rustc = Path(subprocess.check_output(["rustup", "which", "--toolchain", "ohm", "rustc"],
                                         text=True, cwd=repo).strip()).resolve()
    version = subprocess.check_output(["rustc", "+ohm", "-Vv"], cwd=repo, text=True)
    assert "f1a7cf9d20b2cae39e991b178b56ba06b43dc8fa" in version, version
    sysroot = rustc.parent.parent
    driver_library, = (sysroot / "lib").glob("librustc_driver*.so")

    def compiler_signature():
        stats = [file.stat() for file in (rustc, driver_library)]
        return [(stat.st_dev, stat.st_ino, stat.st_ctime_ns, stat.st_size) for stat in stats]

    compiler = compiler_signature()
    cargo_path = None
    if cargos:
        rustup, cargo_path = private_cargo(sysroot, output)
        env["RUSTUP_HOME"] = str(rustup)
    baseline = next(iter(linkers))
    hashes = {arm: [sha(path), sha(cargos[arm]) if cargos else None] for arm, path in linkers.items()}
    active = None

    def run(label, arm, edit, *, count=False):
        nonlocal active
        if arm != active:
            replace(linkers[arm], linker)
            if cargo_path:
                replace(cargos[arm], cargo_path)
            assert [sha(linker), sha(cargo_path) if cargo_path else None] == hashes[arm]
            active = arm
        data = source.read_bytes()
        assert data in contents.values()
        if data != contents[edit]:
            source.write_bytes(contents[edit])
        assert compiler_signature() == compiler
        record = cargo(env, repo, command, output / label, linker, count=count)
        assert compiler_signature() == compiler
        return record

    rng = random.Random(args.seed if args.seed is not None else SEEDS[args.mode])
    edits = (["original", "changed"] * args.blocks)[:args.blocks]
    rng.shuffle(edits)
    plan = [(edit, rng.sample(list(linkers), len(linkers))) for edit in edits]
    (output / "plan.json").write_text(json.dumps(dict(mode=args.mode, subjects=hashes, compiler=compiler, blocks=plan), indent=2))
    try:
        run("warm", baseline, "original")
        oracles = {}
        for edit in ("changed", "original"):
            result, dirty, _ = run("native-" + edit, baseline, edit)
            assert dirty == [unit], dirty
            oracles[edit] = result
        assert oracles["changed"][0] == oracles["original"][0] and oracles["changed"][1] != oracles["original"][1]
        with (output / "observations.jsonl").open("x", buffering=1) as raw:
            for block, (edit, order) in enumerate(plan):
                other = "original" if edit == "changed" else "changed"
                for position, arm in enumerate(order):
                    label = f"{block:02d}-{position}"
                    assert run(label + "-reset", baseline, other)[0] == oracles[other]
                    result, dirty, counts = run(label, arm, edit, count=True)
                    assert result == oracles[edit] and dirty == [unit], (label, dirty)
                    outputs = sorted((Path(path).name, value) for path, value in result[1].items())
                    encoded = json.dumps(outputs, separators=(",", ":")).encode()
                    row = dict(block=block, edit=edit, arm=arm, units=len(result[0]), executables=len(result[1]),
                               source_sha256=hashlib.sha256(contents[edit]).hexdigest(),
                               outputs_sha256=hashlib.sha256(encoded).hexdigest(),
                               counts=counts, guest_ir=sum(counts.values()))
                    print(json.dumps(row), file=raw)
                    print(label, arm, row["guest_ir"], flush=True)
    finally:
        if source.read_bytes() == contents["changed"]:
            source.write_bytes(original)


if __name__ == "__main__":
    main()
