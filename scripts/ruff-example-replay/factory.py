"""Build both Cargo programs from the authenticated release-22 source on one worker."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SOURCE = "ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770"
TREE = "b4981dc120409cf8eec4321e355071f8abd17a64"
PREVIOUS = "2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c"
OWNER = "src/compiler/fingerprint/mod.rs"
FIXED_BLOB = "2dfadab461c089ccda7dcf6108d07d6de521f511"
LOCK = "90ae3bd115646a6978aedbcaaf321aaae35fd8985ee54a448110b09c744358d3"
HOST = "x86_64-unknown-linux-gnu"


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def git(path, *args, data=None):
    return subprocess.check_output(["git", "-C", path, *args], input=data)


def materialize(root, seed):
    sys.path.insert(0, str(seed / "scripts/cargo-diagnostic-fix"))
    import materialize as old

    src = root / "cargo-source"
    proof = old.tree(src, seed / "scripts/ohm-apple-zmij/cargo293/source.pack")
    need(proof["commit"] == PREVIOUS, "previous source")
    commit = (HERE / "signed-22.commit").read_bytes()
    delta = gzip.decompress((HERE / "signed-22.patch.gz").read_bytes())
    git(src, "apply", "--binary", "--index", "-", data=delta)
    need(git(src, "write-tree").decode().strip() == TREE and
         git(src, "hash-object", "-t", "commit", "-w", "--stdin", data=commit).decode().strip() == SOURCE,
         "signed Cargo source identity")
    with (src / ".git/shallow").open("a") as stream:
        stream.write(SOURCE + "\n")
    git(src, "update-ref", "HEAD", SOURCE)
    need(not git(src, "status", "--porcelain") and sha(src / "Cargo.lock") == LOCK, "source checkout")
    return src


def sdk(root, workspace, out):
    sys.path.insert(0, str(HERE.parent / "ruff-default-owner-pmu"))
    import acquire

    asset = root / "release.tar.gz"
    with asset.open("xb") as dest:
        subprocess.run(["gh", "api", "-H", "Accept: application/octet-stream",
                        "repos/astral-experiments/ohm/releases/assets/698533704"],
                       stdout=dest, check=True, cwd=workspace)
    dest = root / "distribution"
    acquire.extract(asset, dest)
    save(out / "signed-inventory.json", acquire.verify_sdk(dest))
    asset.unlink()
    return dest


def environment(root, sdk):
    home = root / "factory-home"
    home.mkdir()
    toolchains = root / "rustup/toolchains"
    toolchains.mkdir(parents=True)
    (toolchains / "ohm").symlink_to(sdk, target_is_directory=True)
    proxy = Path(shutil.which("rustup")).absolute().parent
    need((proxy / "cargo").is_file(), "original Rustup proxy")
    return {
        "PATH": os.pathsep.join([str(proxy), "/usr/local/bin", "/usr/bin", "/bin"]),
        "HOME": str(home), "USER": os.environ.get("USER", "runner"),
        "RUSTUP_HOME": str(toolchains.parent), "RUSTUP_AUTO_INSTALL": "0",
        "CARGO_HOME": str(root / "factory-registry"), "CARGO_TARGET_DIR": str(root / "factory-target"),
        "CARGO_BUILD_BUILD_DIR": str(root / "factory-build"), "CARGO_BUILD_JOBS": "12",
        "CARGO_TERM_COLOR": "never", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC",
    }


def build(root, workspace, out):
    src = materialize(root, workspace / "seed")
    distribution = sdk(root, workspace, out)
    env = environment(root, distribution)
    need(shutil.disk_usage(root).free > 24 * 2**30, "24 GiB required for hosted matched Cargo build")
    cargo = ["cargo", "+ohm", "-Zohm-defaults=no"]
    subprocess.run([*cargo, "fetch", "--locked", "--target", HOST], env=env, cwd=src, check=True)
    paths = {}
    for arm in ("parent", "candidate"):
        if arm == "candidate":
            git(src, "apply", "--index", HERE / "example.patch")
            need(git(src, "diff", "--cached", "--name-only").decode().splitlines() == [OWNER] and
                 git(src, "hash-object", OWNER).decode().strip() == FIXED_BLOB, "one-line candidate")
        tree = git(src, "write-tree").decode().strip()
        cmd = [*cargo, "build", "--release", "--locked", "--offline", "--bin", "cargo", "--package",
               "cargo", "--features", "ohm-defaults,all-static", "-j12", "--message-format=json"]
        result = subprocess.run(cmd, env=env, cwd=src, capture_output=True, timeout=5400)
        (out / (arm + "-build.stderr.gz")).write_bytes(gzip.compress(result.stderr, mtime=0))
        (out / (arm + "-build.stdout.gz")).write_bytes(gzip.compress(result.stdout, mtime=0))
        need(result.returncode == 0, (arm, "build", result.stderr[-3000:]))
        events = [json.loads(line) for line in result.stdout.splitlines()]
        need(events[-1] == {"reason":"build-finished", "success":True}, "Cargo terminal message")
        leaf, = [r for r in events if r.get("reason") == "compiler-artifact" and r["target"]["kind"] == ["bin"]
                 and r["target"]["name"] == "cargo"]
        need(not leaf["fresh"] and {"all-static", "ohm-defaults"} <= set(leaf["features"]), "built Cargo executable")
        binary = Path(leaf["executable"]).resolve(strict=True)
        need(binary.is_relative_to(root) and binary.is_file(), "private Cargo executable")
        selected = root / ("cargo-" + arm)
        shutil.copy2(binary, selected)
        paths[arm] = selected
        version = subprocess.check_output([selected, "-vV"], cwd=src, env=env).decode()
        save(out / (arm + "-binary.json"), {"arm":arm, "source_commit":SOURCE, "source_tree":tree,
             "fingerprint_blob":git(src, "hash-object", OWNER).decode().strip(),
             "binary":sha(selected), "version":version, "command":cmd, "feature_names":leaf["features"],
             "builder_rustc":sha(distribution / "bin/rustc"), "builder_source_cargo":sha(distribution/"bin/cargo")})
    need(sha(paths["parent"]) != sha(paths["candidate"]), "distinct Cargo executables")
    # The receiver swaps the small Cargo program at one path. Every rustc, Wild, and std
    # byte comes from the one signed distribution in both arms.
    facade = root / "sdk"
    (facade / "bin").mkdir(parents=True)
    for entry in distribution.iterdir():
        if entry.name != "bin":
            (facade / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
    for entry in (distribution / "bin").iterdir():
        if entry.name != "cargo":
            (facade / "bin" / entry.name).symlink_to(entry)
    (root / "rustup/toolchains/ohm").unlink()
    (root / "rustup/toolchains/ohm").symlink_to(facade, target_is_directory=True)
    return paths
