"""Prepare an immutable Ruff and full two-lock registry donor, entirely outside the measured work."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingress import need, put, sha

RUFF = (
    "93526150df078af7dd8fc4226cdcc469539d2001",
    "03989bfe060d0ed48dd9ea7d0c99a35c12b9c323",
    "68d556d0630ecb8367cf041c3e857aa917799c43",
    "9c53b5de3aae4b1832eb7ee137647dda2466f888",
)


def run(*argv, cwd=None, env=None):
    return subprocess.check_output(list(map(str, argv)), cwd=cwd, env=env)


def remove_private(root, path):
    need(
        path.exists()
        and not path.is_symlink()
        and path.resolve() == path
        and path.is_relative_to(root)
        and path != root,
        "unexpected owned disposable path",
    )
    shutil.rmtree(path)


def prepare(root, receipt, restore):
    seeds = root / "seeds"
    seeds.mkdir()
    ruff = seeds / "ruff.git"
    ruff.mkdir()
    run("git", "init", "--bare", "-q", ruff)
    run(
        "git",
        "-C",
        ruff,
        "fetch",
        "--quiet",
        "--depth=2",
        "--no-tags",
        "--no-recurse-submodules",
        "https://github.com/astral-sh/ruff.git",
        *RUFF,
    )
    for n, rev in enumerate(RUFF):
        need(
            run("git", "-C", ruff, "rev-parse", rev + "^{commit}").decode().strip() == rev,
            "wrong Ruff object",
        )
        run("git", "-C", ruff, "update-ref", "refs/heads/frozen-" + str(n), rev)
    need(
        run("git", "-C", ruff, "rev-parse", RUFF[2] + "^").decode().strip() == RUFF[1],
        "wrong notebook parent",
    )
    repo = seeds / "fetch-workspace"
    run("git", "clone", "--quiet", "--shared", "--no-checkout", ruff, repo)
    sdk = seeds / "sdk"
    restore("P", sdk)
    private = seeds / "rustup"
    alias = private / "toolchains/ohm"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(sdk)
    proxies = Path(shutil.which("rustup")).resolve().parent
    need(
        all(os.path.samefile(proxies / "rustup", proxies / n) for n in ("cargo", "rustc", "rustdoc")),
        "untrusted Rustup proxy directory",
    )
    ch = seeds / "cargo-home"
    ch.mkdir()
    env = {
        "PATH": str(proxies) + ":/usr/local/bin:/usr/bin:/bin",
        "HOME": str(seeds),
        "RUSTUP_HOME": str(private),
        "RUSTUP_AUTO_INSTALL": "0",
        "CARGO_HOME": str(ch),
        "CARGO_TARGET_DIR": str(seeds / "never-used-target"),
        "LC_ALL": "C",
    }
    need(
        Path(run("rustc", "+ohm", "--print", "sysroot", cwd=repo, env=env).decode().strip()).samefile(sdk),
        "seed Cargo uses wrong installation",
    )
    locked = {}
    locks = {}
    for label, rev in [("source-map", RUFF[0]), ("notebook", RUFF[2])]:
        run("git", "checkout", "--quiet", "--detach", rev, cwd=repo)
        lock = repo / "Cargo.lock"
        before = sha(lock)
        with (receipt / ("seed-fetch-" + label + ".log")).open("xb") as fd:
            subprocess.run(
                ["cargo", "+ohm", "fetch", "--locked"],
                cwd=repo,
                env=env,
                stdout=fd,
                stderr=subprocess.STDOUT,
                check=True,
            )
        need(before == sha(lock), "lock changed during acquisition")
        locks[label] = before
        for p in tomllib.loads(lock.read_text())["package"]:
            if "checksum" in p:
                key = (p["name"], p["version"])
                need(locked.setdefault(key, p["checksum"]) == p["checksum"], "inconsistent locked crate")
    need(
        run("git", "-C", ruff, "rev-parse", RUFF[1] + ":Cargo.lock")
        == run("git", "-C", ruff, "rev-parse", RUFF[2] + ":Cargo.lock"),
        "notebook changed registry lock",
    )
    store = ch / "registry"
    indices = [p for p in (store / "cache").iterdir() if p.is_dir()]
    need(len(indices) == 1, "unexpected crates.io source")
    archives = indices[0]
    index = store / "index" / archives.name
    hashes = {}
    for (name, version), want in sorted(locked.items()):
        crate = archives / (name + "-" + version + ".crate")
        prefix = (
            str(len(name))
            if len(name) < 3
            else "3/" + name[0]
            if len(name) == 3
            else name[:2] + "/" + name[2:4]
        )
        ref = index / ".cache" / prefix / name
        need(sha(crate) == want and ref.is_file(), "incomplete crates.io donor: " + name)
        hashes[crate.name] = [want, crate.stat().st_size, sha(ref)]
    put(
        receipt / "source-seed.json",
        {
            "ruff": list(RUFF),
            "locks": locks,
            "verified_union": hashes,
            "total_archive_bytes": sum(v[1] for v in hashes.values()),
            "proxy": {
                n: [str(proxies / n), sha(proxies / n)] for n in ("rustup", "cargo", "rustc", "rustdoc")
            },
        },
    )
    # Keep only the registry bytes an empty enrolled slot imports. Remove never-scored setup SDK/source.
    for path in (repo, sdk, private):
        remove_private(seeds, path)
    if (store / "src").exists():
        remove_private(seeds, store / "src")
    need(not (seeds / "never-used-target").exists(), "registry fetch created a target")
    return ruff, store, proxies
