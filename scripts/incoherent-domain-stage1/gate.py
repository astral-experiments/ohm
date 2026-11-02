import hashlib,json,re,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent

def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def load(path):
    return json.loads(path.read_bytes())

def put(path, value):
    with path.open("x") as handle:
        json.dump(value, handle, sort_keys=True, indent=1)
        handle.write("\n")

def process(argv, work, env, allow_error=False):
    with subprocess.Popen(argv, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        try:
            out, err = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        if not allow_error and proc.returncode:
            raise RuntimeError((argv, proc.returncode, err[:4096]))
        return proc.pid, proc.returncode, out, err

def sdk_identity(sdk, env, source, expected_driver):
    assert (sdk / "bin/rustc").is_file() and (source is None or re.fullmatch("[0-9a-f]{40}", source))
    driver, = sorted((sdk / "lib").glob("librustc_driver-*.so"))
    driver_hash = file_hash(driver)
    assert not expected_driver or driver_hash == expected_driver
    _, _, version, err = process([str(sdk / "bin/rustc"), "-vV"], HERE, env)
    assert not err and b"host: x86_64-unknown-linux-gnu" in version
    _, _, lib, err = process([str(sdk / "bin/rustc"), "--sysroot", str(sdk), "--print", "target-libdir"], HERE, env)
    libdir = Path(lib.decode().strip()).resolve()
    assert not err and libdir.is_relative_to(sdk)
    std = {p.name: file_hash(p) for pattern in ("libcore-*.r*", "libstd-*.r*") for p in sorted(libdir.glob(pattern))}
    assert any(k.startswith("libcore-") for k in std) and any(k.startswith("libstd-") for k in std)
    return {"path": str(sdk), "driver": driver.name, "driver_sha256": driver_hash, "rustc_sha256": file_hash(sdk / "bin/rustc"),
            "rustc_vV": version.decode(), "core_and_std": std, "source_label": source,
            "externally_supplied_driver_sha256": expected_driver}
