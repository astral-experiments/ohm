"""Exercise the five real #318 incremental visits using an installed compiler."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory


H = Path(__file__).resolve().parent
M = runpy.run_path(str(H / "capture.py"))
files = M["load"](H / "captured.json")["prs"]["318"]["paths"]
DIR = "tests/run-make/rdr-public-hash-ctfe-literal-identity/"
ENV = {"LC_ALL": "C", "PATH": "/usr/bin:/bin", "RUSTC_BOOTSTRAP": "1"}


def sha(path):
    with path.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest()


def main(install, commit, out):
    rc = install.resolve() / "bin/rustc"
    actual = subprocess.check_output([rc, "-vV"], env=ENV, text=True)
    assert "commit-hash: " + commit + "\n" in actual
    original = {}
    for name in ("rmake.rs", "right.rs", "lib.rs", "main.rs"):
        oid = files[DIR + name]["sha"]
        original[name] = M["object_data"](("blobs", oid))
    visits = {}
    with TemporaryDirectory(prefix="ohm-ctfe-") as tmp:
        wd = Path(tmp)
        for name, data in original.items():
            (wd / name).write_bytes(data)
        def visit(name, reuse, output):
            commands = []
            def call(args):
                result = subprocess.run(args, cwd=wd, env=ENV, capture_output=True)
                assert result.returncode == 0, (name, result.returncode, result.stderr[:1200])
                commands.append({"argv": list(map(str, args)), "exit": result.returncode,
                                 "out": result.stdout.decode(), "err": result.stderr.decode()})
                return result.stdout
            call([rc, "lib.rs", "--crate-name", "dep", "--crate-type=rlib", "-Cincremental=cache",
                  "-Copt-level=1", "-Zpublic-api-hash", "-Zassert-incr-state=" + reuse])
            call([rc, "main.rs", "--extern", "dep=libdep.rlib"])
            assert call([wd / "main"]) == output
            value = call([rc, "-Zls=public_hash", "libdep.rlib"])
            assert value.strip()
            visits[name] = {"commands": commands, "linked_binary_sha256": sha(wd / "main"),
                            "rlib_sha256": sha(wd / "libdep.rlib"), "public_hash": value.decode()}
            return value
        left = wd / "left.rs"
        left.write_bytes(original["right.rs"])
        before = visit("A-cold", "not-loaded", b"Or Or true 17\n")
        data = left.read_bytes()
        assert data.count(b"FloorDiv,") == data.count(b"Operator::Or") == 1
        left.write_bytes(data.replace(b"FloorDiv,", b"FloorDiv, LShift,").replace(b"Operator::Or", b"Operator::LShift"))
        warm = visit("B-first-warm", "loaded", b"LShift Or true 17\n")
        (wd / "cache").rename(wd / "retained-first-cache")
        cold = visit("B-independent-cold", "not-loaded", b"LShift Or true 17\n")
        ptr = b"[&FIRST, &FIRST, &SECOND]"
        assert original["lib.rs"].count(ptr) == 1
        (wd / "lib.rs").write_bytes(original["lib.rs"].replace(ptr, b"[&FIRST, &SECOND, &SECOND]"))
        switched = visit("C-first-warm", "loaded", b"LShift Or false 17\n")
        (wd / "cache").rename(wd / "retained-second-cache")
        fresh = visit("C-independent-cold", "not-loaded", b"LShift Or false 17\n")
        checks = {"B_warm_equals_cold": warm == cold, "C_warm_equals_cold": switched == fresh,
                  "A_differs_from_B": before != cold, "pointer_switch_changes_public_hash": cold != switched}
    data = {"source_commit": commit, "rustc_verbose": actual, "rustc_launcher_sha256": sha(rc),
            "source_blobs": {n: files[DIR+n]["sha"] for n in original}, "visits": visits, "checks": checks,
            "matches_official_regression": all(checks.values())}
    assert not out.exists()
    M["save"](out, (json.dumps(data, sort_keys=True, indent=2) + "\n").encode())
    print(commit[:9], checks, sha(out))


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]))
