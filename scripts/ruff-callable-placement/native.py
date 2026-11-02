"""Independent observations of the actual test executable and emitted archive members."""

import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from callable_decision import NATIVE, key


def sha(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def emit(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=1) + "\n")


def root_program(phase, repo, work):
    stderr = (phase / "outer.stderr").read_text(errors="replace")
    choices = re.findall(r"^\s*Executable tests/e2e/main\.rs \((.+)\)$", stderr, re.MULTILINE)
    if len(choices) != 1:
        raise ValueError(("expected one actual ty_server test executable", stderr[-1600:]))
    binary = (repo / choices[0]).resolve(strict=True)
    if not any(binary.is_relative_to(work / root) for root in ("build", "target")):
        raise ValueError(("test executable outside benchmark roots", binary))
    with binary.open("rb") as file:
        if file.read(4) != b"\x7fELF":
            raise ValueError(("not an ELF", binary))
    return binary


def verdict(binary, repo, env, phase, test, expected_failure=False):
    # The standalone test oracle has the two source-built Ohm kits, while the
    # historical Ruff checkout pins a different toolchain for bare cargo metadata.
    # Bind insta to the actual registered checkout used to build the executable.
    snapshot = repo / "crates/ty_server/tests/e2e/snapshots/e2e__signature_help__works_in_function_name.snap"
    snapshot_id = subprocess.check_output(["git", "hash-object", "--no-filters", snapshot], cwd=repo, text=True).strip()
    if snapshot_id != "9e08fa15ea4b4d3232ea3a143d786abf7a65944c":
        raise ValueError("different frozen signature-help snapshot")
    run_env = {**env, "INSTA_UPDATE": "no", "INSTA_WORKSPACE_ROOT": str(repo), "RUST_BACKTRACE": "0"}
    def run(args):
        return subprocess.run([binary, *args], cwd=repo / "crates/ty_server", env=run_env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)

    listed = run(["--list", "--format", "terse"])
    if listed.returncode != 0 or listed.stdout.splitlines().count(test.encode() + b": test") != 1:
        raise ValueError(("missing selected test", listed.returncode, listed.stdout[-800:]))
    (phase / "test-list.txt").write_bytes(listed.stdout)
    executed = run(["--exact", test, "--nocapture", "--test-threads=1"])
    (phase / "selected-test.txt").write_bytes(executed.stdout)
    if expected_failure:
        if not (executed.returncode == 101 and b"OHM_28277_RUNTIME_CHANGED" in executed.stdout
                and b"0 passed; 1 failed" in executed.stdout):
            raise ValueError(("stale or incorrect negative executable", executed.returncode, executed.stdout[-1300:]))
    elif not (executed.returncode == 0 and b"1 passed; 0 failed" in executed.stdout):
        raise ValueError(("wrong signature-help verdict", executed.returncode, executed.stdout[-1300:]))
    return {"binary": sha(binary), "test_list": sha(phase / "test-list.txt"), "exit": executed.returncode}


def debug_sites(binary, path, sites, version, env, phase):
    lines = [site[version] for site in sites]
    # Checking the location associated with the PC catches a debugger returning
    # the requested source line even when no such machine instruction exists.
    program = Path(__file__).with_name("sites.gdb.py")
    cp = subprocess.run(["gdb", "-nx", "-nh", "-batch", "-iex", "set auto-load off", "-ex", f"source {program}", binary],
                        env={**env, "OHM_GDB_SOURCE": path, "OHM_GDB_LINES": json.dumps(lines)},
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    (phase / "gdb.txt").write_bytes(cp.stdout)
    rows = [json.loads(row[len(b"OHM_SITES "):]) for row in cp.stdout.splitlines() if row.startswith(b"OHM_SITES ")]
    if cp.returncode or len(rows) != 1:
        raise ValueError(("debugger refused source observations", cp.returncode, cp.stdout[-1400:]))
    return rows[0]


def archive_objects(phase, rusts, retained, store):
    """Hash the compiler's actual archives after the build, before a clean session replaces them."""
    result = {}
    wanted = {key(member) for member in retained}
    for row in rusts:
        args = row["argv"]
        if row["kind"] != "full" or "--out-dir" not in args or "--crate-type" not in args:
            continue
        if args[args.index("--crate-type") + 1] not in ("lib", "rlib"):
            continue
        if not any(arg.startswith("incremental=") for arg in args):
            continue
        extra = [v.split("=", 1)[1] for i,v in enumerate(args)
                 if i and args[i-1] == "-C" and v.startswith("extra-filename=")]
        if len(extra) != 1:
            continue
        archive = Path(args[args.index("--out-dir") + 1]) / ("lib" + row["name"] + extra[0] + ".rlib")
        if not archive.is_file():
            continue
        members = subprocess.check_output(["ar", "t", archive], text=True).splitlines()
        members = [m for m in members if m.endswith(".rcgu.o")]
        if len(set(members)) != len(members) or any(Path(m).name != m or m.startswith("-") for m in members):
            raise ValueError(("unexpected native member names", archive))
        with tempfile.TemporaryDirectory(dir=phase) as directory:
            if members:
                subprocess.run(["ar", "x", archive, *members], cwd=directory, check=True)
            body = {m: sha(Path(directory) / m) for m in members}
            for member in body:
                if not NATIVE.fullmatch(member) or key(member) not in wanted:
                    continue
                destination = store / (body[member] + ".o.gz")
                if not destination.exists():
                    data = (Path(directory) / member).read_bytes()
                    if len(data) > 32 << 20:
                        raise ValueError(("unbounded admitted object", member, len(data)))
                    destination.write_bytes(gzip.compress(data, compresslevel=4, mtime=0))
        if archive.name in result and result[archive.name] != body:
            raise ValueError(("same archive name has distinct physical owners", archive.name))
        result[archive.name] = body
    return result
