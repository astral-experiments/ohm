"""Exercise real rustc's incremental header admission, including two recorded compiler roles."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

STAMP = "ohm-trait-origin-common-native-version"
EXPECTED_DIAGNOSTIC = "Wrong HEADER_FORMAT_VERSION"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def visit(directory, compiler, epoch, state, mismatch):
    directory.mkdir(exist_ok=True)
    source = directory / "library.rs"
    source.write_text("pub fn source_value() -> usize { 43 }\n")
    argv = [str(compiler), str(source), "--crate-name", "origin_probe", "--crate-type", "lib", "--emit=metadata",
            "--out-dir", str(directory), "-Cincremental=" + str(directory / "incremental"),
            "-Zassert-incr-state=" + state, "-Zincremental-info"]
    env = {"PATH": "/usr/bin:/bin", "HOME": str(directory), "LC_ALL": "C", "RUSTC_BOOTSTRAP": "1",
           "RUSTC_FORCE_RUSTC_VERSION": STAMP}
    result = subprocess.run(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    log = result.stderr.decode()
    if result.returncode:
        raise RuntimeError(log[-3800:])
    diagnostics = [line.strip() for line in log.splitlines() if EXPECTED_DIAGNOSTIC in line]
    assert bool(diagnostics) == mismatch, (state, diagnostics)
    files = {}
    for path in (directory / "incremental").rglob("*.bin"):
        data = path.read_bytes()
        assert data[:4] == b"RSIC" and int.from_bytes(data[4:6], "little") == epoch, path
        assert data[7:7 + data[6]].decode() == STAMP, path
        assert path.name not in files
        files[path.name] = {"sha256": sha(data), "bytes": len(data)}
    assert {"dep-graph.bin", "query-cache.bin", "work-products.bin"} <= files.keys()
    product = directory / "liborigin_probe.rmeta"
    assert product.is_file() and product.stat().st_size > 0
    return {"version": subprocess.check_output([compiler, "-vV"], text=True, env=env).splitlines()[2],
            "epoch": epoch, "expected_state": state, "diagnostics": diagnostics,
            "stderr_sha256": sha(result.stderr), "files": files, "product_sha256": sha(product.read_bytes())}


def check(root, roles):
    result = {}
    for name, compiler, epoch, other, other_epoch in roles:
        work = root / name
        first = visit(work, compiler, epoch, "not-loaded", False)
        reused = visit(work, compiler, epoch, "loaded", False)
        assert first["product_sha256"] == reused["product_sha256"]
        if other is None:
            # Change only the two schema bytes in files produced just now by this SDK.
            for path in (work / "incremental").rglob("*.bin"):
                with path.open("r+b") as stream:
                    assert stream.read(6) == b"RSIC" + epoch.to_bytes(2, "little")
                    stream.seek(4)
                    stream.write(other_epoch.to_bytes(2, "little"))
            rejected = visit(work, compiler, epoch, "not-loaded", True)
            assert reused["product_sha256"] == rejected["product_sha256"]
        else:
            rejected = visit(work, other, other_epoch, "not-loaded", True)
            accepted = visit(work, other, other_epoch, "loaded", False)
            assert accepted["product_sha256"] == rejected["product_sha256"]
        result[name] = {"first": first, "reused": reused, "other_epoch_rejected": rejected}
    return result


def main():
    root, destination = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    primary, p_epoch = Path(sys.argv[3]).resolve(), int(sys.argv[4])
    other_epoch = int(sys.argv[5])
    assert p_epoch != other_epoch and not destination.exists() and primary.is_file()
    roles = [("same-sdk-change-header", primary, p_epoch, None, other_epoch)]
    if len(sys.argv) == 7:
        other = Path(sys.argv[6]).resolve()
        assert other.is_file() and primary != other
        roles += [("parent-to-candidate", primary, p_epoch, other, other_epoch),
                  ("candidate-to-parent", other, other_epoch, primary, p_epoch)]
    assert root.is_dir() and shutil.disk_usage(root).free > 80 * (1 << 20)
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        result = check(Path(tmp), roles)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("verified", ", ".join(result))


if __name__ == "__main__":
    main()
