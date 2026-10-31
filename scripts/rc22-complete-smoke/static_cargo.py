"""Build only the four-fix Cargo binary, with the two release bootstrap settings."""

import base64
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media import CFG, HERE, locations, need, save, sha
import focused

GNU = "x86_64-unknown-linux-gnu"
LOCK = "90ae3bd115646a6978aedbcaaf321aaae35fd8985ee54a448110b09c744358d3"
SOURCE = "7bc72b798b019a9ec0de6eeea3bc22b783917b27"
SEED = "46d28e8bff1c6b52f3e7b7bc13192019e964a7da"
TOOL_BLOB = "17e71f71bb3bc0d41939440fd28e62adf6a8aa5e"
ALLOW_NEEDED = {
    "libc.so.6",
    "libm.so.6",
    "libgcc_s.so.1",
    "libpthread.so.0",
    "libdl.so.2",
    "librt.so.1",
    "ld-linux-x86-64.so.2",
}
VERSION = CFG["fourfix"]


def git(root, *args):
    return subprocess.check_output(["git", "-C", root, *args], text=True).strip()


def policy():
    blobs = json.loads(gzip.decompress((HERE / "bootstrap-policy.json.gz").read_bytes()))
    content = {}
    for oid, (kind, b64) in blobs.items():
        data = base64.b64decode(b64, validate=True)
        need(
            hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest() == oid,
            "wrong Git object",
        )
        content[oid] = (kind, data)
    kind, commit = content[CFG["fixed_rust_pin"]]
    need(kind == "commit", "bootstrap commit")
    oid = commit.splitlines()[0].split()[1].decode()
    for name in ("src", "bootstrap", "src", "core", "build_steps", "tool.rs"):
        kind, data = content[oid]
        need(kind == "tree", "missing source tree")
        entries = {}
        i = 0
        while i < len(data):
            j = data.index(b"\0", i)
            entry = data[i:j].split(b" ", 1)[1].decode()
            need(entry not in entries, "duplicate Git entry")
            entries[entry] = data[j + 1 : j + 21].hex()
            i = j + 21
        oid = entries[name]
    kind, code = content[oid]
    need(
        kind == "blob"
        and oid == TOOL_BLOB
        and len(content) == 8
        and b'cargo.env("LIBZ_SYS_STATIC", "1");' in code
        and b'features.push("all-static".to_string());' in code,
        "bootstrap policy drift",
    )
    cfg = HERE.parents[1] / "release/bootstrap.toml"
    build = tomllib.loads(cfg.read_text())["build"]
    need(
        sha(cfg) == "5822d2ae682a27193ef413f013281b0849797c88c78545607ab563ea48f87684"
        and build["cargo-native-static"] is True
        and build["tool"]["cargo"]["features"] == ["ohm-defaults"],
        "not release config",
    )
    return {"rust": CFG["fixed_rust_pin"], "tool_rs_git_blob": oid, "release_bootstrap_sha256": sha(cfg)}


def source(build):
    workspace = Path(os.environ["GITHUB_WORKSPACE"])
    carrier = workspace / "transport"
    seed = workspace / "cargo-seed"
    need(
        git(carrier, "rev-parse", "HEAD") == SOURCE and git(seed, "rev-parse", "HEAD") == SEED,
        "wrong source carrier",
    )
    lib = carrier / "scripts/rc22-native"
    sys.path.insert(0, str(lib))
    spec = importlib.util.spec_from_file_location("authenticated_transfer", lib / "materialize.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.cargo(build)
    r = build / "cargo-source"
    frozen = json.loads((build / "reports/cargo-source.json").read_bytes())
    need(
        git(r, "rev-parse", "HEAD") == VERSION
        and git(r, "rev-parse", "HEAD^{tree}") == CFG["fourfix_tree"]
        and not git(r, "status", "--porcelain")
        and sha(r / "Cargo.lock") == LOCK
        and frozen["overlay"]["sha256"] == "d4ff57b5fcfe5268e69addeec3dfb63cde1275c2f5f2331f233478329f7012bd",
        "unverified Cargo checkout",
    )
    return r, frozen


def releases(needed, ldd):
    names = re.findall(r"\(NEEDED\).*?\[([^]]+)\]", needed)
    need(
        "libc.so.6" in names and len(names) == len(set(names)) and set(names) <= ALLOW_NEEDED,
        "unapproved shared object in ELF",
    )
    need(
        "not found" not in ldd and not re.search(r"(?:^|\s)lib(?:ssl|crypto|curl|git2|ssh2|z|zstd)[.-]", ldd),
        "nonportable Cargo dependencies",
    )
    return sorted(names)


def archive_identity(path):
    need(
        path.is_file() and not path.is_symlink() and path.read_bytes().startswith(b"!<arch>\n"),
        "missing actual libz archive",
    )
    members = subprocess.check_output(["ar", "t", path], text=True).splitlines()
    syms = subprocess.check_output(["nm", "--defined-only", path], text=True)
    need(
        len(members) >= 8
        and all(
            re.search(r"\bT " + k + r"$", syms, re.M) for k in ("deflate", "inflate", "crc32", "adler32")
        ),
        "wrong libz members/symbols",
    )
    return {"sha256": sha(path), "bytes": path.stat().st_size, "members": members}


def zproof(rows, build, copy_to=None):
    (z,) = [r for r in rows if r.get("reason") == "build-script-executed" and "#libz-sys@" in r["package_id"]]
    need(
        "static=z" in z["linked_libs"] and "z" not in z["linked_libs"] and "dylib=z" not in z["linked_libs"],
        "libz-sys did not request static zlib",
    )
    out = Path(z["out_dir"]).resolve()
    need(out.is_relative_to(build.resolve()), "foreign libz output directory")
    f = out / "lib/libz.a"
    need("native=" + str(f.parent) in z["linked_paths"], "wrong static archive search path")
    verified = archive_identity(f)
    if copy_to is not None:
        shutil.copyfile(f, copy_to)
        need(sha(copy_to) == verified["sha256"], "static archive changed during retention")
    return verified | {"origin": z}


def verify_product(root=None, *, receipt=None):
    p = json.loads((receipt or (root / "receipts/static-product.json")).read_bytes())
    need(
        p["source"] == VERSION
        and p["tree"] == CFG["fourfix_tree"]
        and p["lock"] == LOCK
        and p["policy"] == policy()
        and p["locked_archives"] == 524
        and re.fullmatch(r"[0-9a-f]{64}", p["sha256"])
        and p["sha256"] != CFG["targets"][GNU]["fourfix_sha256"]
        and 1_000_000 < p["bytes"] < 300_000_000,
        "incorrect build provenance",
    )
    need(
        p["builder"] == CFG["cargo"]
        and p["rust"] == CFG["rust"]
        and p["LIBZ_SYS_STATIC"] == "1"
        and p["features"] == ["all-static", "ohm-defaults"]
        and p["static_archive"]["bytes"] > 0
        and "static=z" in p["static_archive"]["origin"]["linked_libs"]
        and p["needed"] == releases(p["dynamic_table"], p["ldd"])
        and "commit-hash: " + VERSION in p["verbose"].splitlines()
        and "host: " + GNU in p["verbose"].splitlines(),
        "static feature, link, or version",
    )
    return p


def build(root, target):
    need(target == GNU and shutil.disk_usage(root).free > 16 << 30, "GNU static builder needs 16 GiB free")
    receipt = root / "receipts/static-build"
    receipt.mkdir()
    pol = policy()
    build = root / "cargo-build"
    build.mkdir()
    repo, frozen = source(build)
    save(receipt / "source.json", frozen)
    _, sdk, env = focused.installation(root, target, "builder", receipt)
    need(
        sha(sdk / "bin/cargo") == CFG["targets"][GNU]["cargo_sha256"], "wrong packaged compiler driver Cargo"
    )
    env.update(
        CARGO_TARGET_DIR=str(build / "target"),
        CARGO_BUILD_BUILD_DIR=str(build / "shared"),
        CFG_RELEASE="1.99.0-dev",
        CFG_RELEASE_CHANNEL="dev",
        LIBZ_SYS_STATIC="1",
        CARGO_TERM_COLOR="never",
    )
    base = ["cargo", "+ohm", "-Zohm-defaults=no"]
    with (receipt / "fetch.log").open("xb") as log:
        subprocess.run(
            base + ["fetch", "--locked"],
            cwd=repo,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=600,
        )
    pkgs = [p for p in tomllib.loads((repo / "Cargo.lock").read_text())["package"] if "checksum" in p]
    need(len(pkgs) == 524, "wrong dependency lock")
    stash = Path(env["CARGO_HOME"]) / "registry/cache"
    crates = {}
    for p in pkgs:
        (f,) = stash.glob("*/" + p["name"] + "-" + p["version"] + ".crate")
        need(
            p["source"] == "registry+https://github.com/rust-lang/crates.io-index"
            and sha(f) == p["checksum"],
            ("wrong crate archive", f.name),
        )
        crates[f.name] = p["checksum"]
    save(receipt / "locked-crates.json", crates)
    n = min(16, len(os.sched_getaffinity(0)))
    cmd = base + [
        "build",
        "--release",
        "--locked",
        "--offline",
        "-p",
        "cargo",
        "--bin",
        "cargo",
        "--features",
        "all-static,ohm-defaults",
        "-j" + str(n),
        "--message-format=json",
    ]
    save(
        receipt / "command.json",
        {
            "argv": cmd,
            "LIBZ_SYS_STATIC": env["LIBZ_SYS_STATIC"],
            "policy": pol,
            "config_release": env["CFG_RELEASE"],
            "config_channel": env["CFG_RELEASE_CHANNEL"],
        },
    )
    paths = [receipt / "cargo.stdout", receipt / "cargo.stderr"]
    with paths[0].open("xb") as stdout, paths[1].open("xb") as stderr:
        proc = subprocess.Popen(cmd, cwd=repo, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            while proc.poll() is None:
                need(shutil.disk_usage(root).free > 6 << 30, "GNU build volume reserve")
                time.sleep(3)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=30)
    for f in paths:
        f.with_suffix(f.suffix + ".gz").write_bytes(gzip.compress(f.read_bytes(), mtime=0))
        f.unlink()
    need(proc.returncode == 0, "Cargo product compile failed")
    rows = [json.loads(l) for l in gzip.decompress((receipt / "cargo.stdout.gz").read_bytes()).splitlines()]
    (cargo,) = [
        r
        for r in rows
        if r.get("reason") == "compiler-artifact"
        and r["target"]["name"] == "cargo"
        and r["target"]["kind"] == ["bin"]
    ]
    actual = Path(cargo["executable"])
    need(
        rows[-1] == {"reason": "build-finished", "success": True}
        and not cargo["fresh"]
        and {"all-static", "ohm-defaults"} <= set(cargo["features"])
        and actual.resolve().is_relative_to((build / "target").resolve())
        and not git(repo, "status", "--porcelain"),
        "wrong actual Cargo output",
    )
    dest = root / "static-cargo"
    shutil.copy2(actual, dest)
    v = subprocess.check_output([dest, "-vV"], env=env, text=True)
    dynamic = subprocess.check_output(["readelf", "-dW", dest], text=True)
    ldd = subprocess.check_output(["ldd", dest], text=True)
    save(
        root / "receipts/static-product.json",
        {
            "source": VERSION,
            "tree": CFG["fourfix_tree"],
            "lock": LOCK,
            "locked_archives": len(crates),
            "policy": pol,
            "builder": CFG["cargo"],
            "rust": CFG["rust"],
            "sha256": sha(dest),
            "bytes": dest.stat().st_size,
            "LIBZ_SYS_STATIC": "1",
            "features": ["all-static", "ohm-defaults"],
            "cargo_artifact": cargo,
            "static_archive": zproof(rows, build, receipt / "libz.a"),
            "dynamic_table": dynamic,
            "ldd": ldd,
            "needed": releases(dynamic, ldd),
            "verbose": v,
        },
    )
    verify_product(root)
    subprocess.run(["zstd", "-T2", "-q", dest, "-o", root / "receipts/static-cargo.zst"], check=True)


if __name__ == "__main__":
    root, target = locations()
    build(root, target)
