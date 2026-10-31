"""Install the original distribution, then reproduce its registry fixture in a linked checkout."""

import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import installed
import worktree
from media import CFG, HERE, locations, need, save, sha


def installation(root, target, name, receipt):
    session = root / "sessions" / name
    smoke = session / "ohm-smoke.worktree"
    smoke.mkdir(parents=True)
    for d in ("cargo-home", "rustup-home", "temp", "home"):
        (smoke / d).mkdir()
    env = {
        k: os.environ[k]
        for k in ("PATH", "USER", "LANG", "LC_ALL", "SDKROOT", "DEVELOPER_DIR", "MACOSX_DEPLOYMENT_TARGET")
        if k in os.environ
    }
    prefix = smoke / "toolchain"
    env.update(
        RUNNER_TEMP=str(session),
        HOME=str(smoke / "home"),
        TMPDIR=str(smoke / "temp"),
        CARGO_HOME=str(smoke / "cargo-home"),
        RUSTUP_HOME=str(smoke / "rustup-home"),
        RUSTUP_AUTO_INSTALL="0",
        OHM_QA_TARGET=target,
        OHM_QA_PY=sys.executable,
        OHM_QA_TOOLS=str(HERE),
        OHM_QA_RECEIPTS=str(receipt),
    )
    script = root / "release/ohm-installer.sh"
    need(sha(script) == CFG["global_files"]["ohm-installer.sh"], "unexpected original installer")
    with (receipt / "installer.log").open("xb") as log:
        subprocess.run(
            ["sh", script],
            cwd=smoke,
            env=env | {"OHM_INSTALL_DIR": str(prefix), "OHM_DOWNLOAD_URL": (root / "release").as_uri()},
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    before = installed.inspect(root, target, prefix, "packaged")
    for label in (CFG["release"], "ohm"):
        for binary in ("cargo", "rustc", "rustdoc"):
            actual = Path(
                subprocess.check_output(
                    ["rustup", "which", "--toolchain", label, binary], env=env, text=True
                ).strip()
            )
            need(actual.samefile(prefix / "bin" / binary), "installer picked a different binary")
    save(receipt / "original-install.json", before)
    return smoke, prefix, env


def registry_fixture(smoke, env, receipt):
    registered = HERE.parent / "smoke-test-release.sh"
    need(sha(registered) == CFG["outer_sha256"], "unexpected registry fixture source")
    text = registered.read_text()
    donor = smoke / "registry-crate"
    (donor / "src").mkdir(parents=True)
    for name in ("Cargo.toml", "src/main.rs"):
        marker = f'cat > "$registry_crate/{name}" <<' + "'EOF'\n"
        need(text.count(marker) == 1, "ambiguous original source")
        body = text.split(marker)[1].split("\nEOF\n", 1)[0] + "\n"
        (donor / name).write_text(body)
    env = dict(
        env,
        PATH=worktree.registry_path(env["PATH"]),
        CARGO_BUILD_BUILD_DIR=str(smoke / "shared-build"),
        CARGO_TARGET_DIR=str(smoke / "registry-target"),
    )
    cmd = [
        "cargo",
        "+" + CFG["release"],
        "build",
        "--manifest-path",
        str(donor / "Cargo.toml"),
        "--message-format=json",
        "-v",
    ]
    proc = subprocess.run(cmd, cwd=donor, env=env, capture_output=True, timeout=180)
    for n, b in (("stdout", proc.stdout), ("stderr", proc.stderr)):
        (receipt / f"parent-{n}.gz").write_bytes(gzip.compress(b, mtime=0))
    need(proc.returncode == 0, "parent registry build failed")
    events = [json.loads(l) for l in proc.stdout.splitlines()]
    need(events[-1] == {"reason": "build-finished", "success": True}, "incomplete parent")
    (itoa,) = [r for r in events if r.get("target", {}).get("name") == "itoa"]
    actual = {f: sha(Path(f)) for f in itoa["filenames"]}
    need(
        not itoa["fresh"]
        and actual
        and all(Path(f).is_relative_to(smoke / "shared-build/debug/build/registries") for f in actual),
        "fresh parent did not produce shared itoa",
    )
    (exe,) = [r["executable"] for r in events if r.get("executable")]
    need(
        Path(exe).samefile(smoke / "registry-target/debug/ohm-registry-smoke")
        and subprocess.check_output([exe], env=env).strip() == b"42",
        "wrong parent native program",
    )
    save(
        receipt / "parent.json",
        {
            "argv": cmd,
            "PATH": env["PATH"],
            "original_fixture": {n: sha(donor / n) for n in ("Cargo.toml", "src/main.rs")},
            "registry_owners": actual,
            "executed": 42,
        },
    )
    return env


def main():
    root, target = locations()
    role = sys.argv[1]
    need(role in ("packaged", "fourfix") and shutil.disk_usage(root).free > 8 << 30, "focus admission")
    r = root / "receipts" / role / "focus"
    r.mkdir(parents=True)
    smoke, prefix, env = installation(root, target, role, r)
    env["OHM_QA_ROLE"] = role
    if role == "fourfix":
        subprocess.run([sys.executable, "-IB", HERE / "installed.py", "swap", prefix], env=env, check=True)
    subprocess.run([sys.executable, "-IB", HERE / "installed.py", "final", prefix], env=env, check=True)
    env = registry_fixture(smoke, env, r)
    subprocess.run([sys.executable, "-IB", HERE / "worktree.py", prefix, smoke, r], env=env, check=True)
    save(r / "terminal.json", {"role": role, "exit": 0, "scope": "one real parent and one linked checkout"})
    shutil.rmtree(smoke)


if __name__ == "__main__":
    main()
