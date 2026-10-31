"""Keep the Ruff, Cargo and toolchain paths fixed while replacing the complete installed SDK."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import tomllib

from kits import HERE, HOST, ENROLL, WILD, WILD_HASH, CARGO, need, sha, write

BAD_PATH = "crates/ty_project/src/lib.rs"
BAD = b'\nconst _: u8 = "OHM_ACTUAL_COMPILER_MIGRATION_E0308";\n'
GEN = ("generated.rs", "generated_alias.rs", "generated_phf.rs")


def payload(path, raw):
    path.write_bytes(gzip.compress(raw, compresslevel=1, mtime=0))


def digest(bytes_):
    return hashlib.sha256(bytes_).hexdigest()


def output(args, **kwargs):
    return subprocess.check_output(args, **kwargs)


def unit_dir(root):
    root.mkdir()
    (root / "receipts").mkdir()
    (root / "slot").mkdir()
    (root / "slot/home").mkdir()
    (root / "slot/tmp").mkdir()
    (root / "installed").mkdir()
    (root / "rustup/toolchains").mkdir(parents=True)
    (root / "rustup/toolchains/ohm").symlink_to(root / "installed/current", target_is_directory=True)
    allowed = sorted(os.sched_getaffinity(0))
    need(len(allowed) >= 8, "need eight native CPUs")
    os.sched_setaffinity(0, allowed[:8])
    need(shutil.disk_usage(root).free > 70 * 2**30, "need 70 GiB free for complete Ruff histories")
    write(
        root / "receipts/host.json",
        {
            "node": os.uname().nodename,
            "available_cpus": allowed,
            "pinned_cpus": sorted(os.sched_getaffinity(0)),
            "free_bytes": shutil.disk_usage(root).free,
            "pmu_paranoid": Path("/proc/sys/kernel/perf_event_paranoid").read_text().strip(),
            "cpuinfo": Path("/proc/cpuinfo").read_text().split("\n\n")[0],
        },
    )


def env(root):
    slot = root / "slot"
    proxy = Path(shutil.which("rustup")).absolute()
    return {
        "HOME": str(slot / "home"),
        "PATH": os.pathsep.join([str(proxy.parent), "/usr/local/bin", "/usr/bin", "/bin"]),
        "USER": os.environ.get("USER", "runner"),
        "RUSTUP_HOME": str(root / "rustup"),
        "RUSTUP_AUTO_INSTALL": "0",
        "CARGO_TARGET_DIR": str(slot / "target"),
        "CARGO_BUILD_BUILD_DIR": str(slot / "shared"),
        "CARGO_HOME": str(slot / "cargo-home"),
        "CARGO_NET_OFFLINE": "true",
        "CARGO_BUILD_JOBS": "8",
        "CARGO_TERM_COLOR": "never",
        "GIT_OPTIONAL_LOCKS": "0",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": str(slot / "tmp"),
    }


def identity_env(root, title):
    # Do not let a version or metadata probe prime Cargo's populated-target rustc-info cache.
    private = root / "identity" / title
    (private / "home").mkdir(parents=True, exist_ok=True)
    return {
        **env(root),
        "CARGO_TARGET_DIR": str(private / "target"),
        "CARGO_BUILD_BUILD_DIR": str(private / "shared"),
        "CARGO_HOME": str(private / "home"),
    }


def roster(dir_):
    files = {}
    for path in sorted(dir_.rglob("*")):
        if not path.is_file():
            continue
        n = str(path.relative_to(dir_))
        s = path.stat()
        files[n] = {
            "sha256": sha(path),
            "size": s.st_size,
            "mode": s.st_mode & 0o777,
            "dev": s.st_dev,
            "ino": s.st_ino,
            "mtime_ns": s.st_mtime_ns,
            "link": os.readlink(path) if path.is_symlink() else None,
        }
    return files


def copy_sdk(root, kits, role, title, reinstall=False):
    parent = root / "installed"
    live = parent / "current"
    staging = parent / "next"
    retained = parent / "previous"
    need(not staging.exists() and not retained.exists(), "previous SDK transaction is not complete")
    donor = kits / role
    need(donor.is_dir(), "missing " + role + " SDK")
    # New regular inodes and fresh timestamps on every install, including the byte-identical sham.
    # Keep the old tree alive until inode verification finishes so inode-number recycling cannot conceal a failed install.
    shutil.copytree(
        donor,
        staging,
        symlinks=True,
        copy_function=shutil.copy,
        ignore=lambda d, n: {"specimen"} if Path(d) == donor and "specimen" in n else set(),
    )
    if role == "signed":
        supplied = staging / "bin/cargo"
        need(
            sha(supplied) == "4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e",
            "wrong signed donor Cargo",
        )
        supplied.unlink()
        shutil.copy(kits / "parent/bin/cargo", supplied)
    timestamp = time.time_ns()
    new = roster(staging)
    old = roster(live) if live.exists() else {}
    need(
        all((staging / n).resolve().is_relative_to(staging.resolve()) for n in new),
        "installed SDK escapes its own root",
    )
    if old:
        need(
            timestamp > max(v["mtime_ns"] for v in old.values() if v["link"] is None),
            "install clock did not advance",
        )
    for name, row in new.items():
        p = staging / name
        if not p.is_symlink():
            os.utime(p, ns=(timestamp, timestamp))
    if old:
        live.rename(retained)
    staging.rename(live)
    new = roster(live)
    need(
        sha(live / "bin/cargo") == CARGO and sha(live / WILD) == WILD_HASH,
        "install changed strict Cargo or Wild",
    )
    if role not in ("signed",):
        manifest = json.loads((kits / (role + ".json")).read_text())["files"]
        expected = {n: tuple(row) for n, row in manifest.items() if not n.startswith("specimen/")}
        need(
            {n: (r["sha256"], r["size"], r["mode"]) for n, r in new.items()} == expected,
            "incomplete source-built installation",
        )
    if old:
        common = set(old) & set(new)
        need(
            all(
                (old[n]["dev"], old[n]["ino"]) != (new[n]["dev"], new[n]["ino"])
                for n in common
                if old[n]["link"] is None and new[n]["link"] is None
            ),
            "shared inodes across whole-SDK installations",
        )
        if reinstall:
            need(
                {n: (v["sha256"], v["mode"]) for n, v in old.items()}
                == {n: (v["sha256"], v["mode"]) for n, v in new.items()},
                "sham changed payload",
            )
    e = identity_env(root, title)
    src = root / "ruff"
    loc = root / "receipts" / title
    loc.mkdir(parents=True)
    rv = output(["rustc", "+ohm", "-vV"], env=e, cwd=src).decode()
    cv = output(["cargo", "+ohm", "-Vv"], env=e, cwd=src).decode()
    rp = Path(output(["rustc", "+ohm", "--print", "sysroot"], env=e, cwd=src).decode().strip())
    need(rp.samefile(live) and "761ea115605c34f11a1cd29afd68812c1e1359dd" in cv, "wrong real SDK")
    if role == "signed":
        (drv,) = (live / "lib").glob("librustc_driver*.so")
        need(
            "c79998a5cd143c445a4b2528f20953b176a65c5d" in rv
            and sha(live / "bin/rustc") == "f7663fb7dec7e5c7ea613a85ff1d6e4c00bf97b8c50534f17e5c95cd599712b9"
            and sha(drv) == "dae4f8dc64b2b2ac9dc04dfe2cfad633d6af1a87da2dfc532e757ffe758680e3",
            "not signed -21",
        )
    coeff = {
        "role": role,
        "stable_path": str(live),
        "sysroot": str(rp),
        "rustc_vv": rv,
        "cargo_vv": cv,
        "install_timestamp_ns": timestamp,
        "members": len(new),
        "old_members": len(old),
        "reinstallation": reinstall,
    }
    payload(loc / "installed.json.gz", json.dumps(new, sort_keys=True, separators=(",", ":")).encode())
    write(loc / "install.json", coeff)
    if retained.exists():
        shutil.rmtree(retained)
    return coeff


def source(root):
    src = root / "ruff"
    src.mkdir()
    subprocess.run(["git", "init", "--template=", "-q", src], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            src,
            "fetch",
            "--depth=1",
            "--no-tags",
            "https://github.com/astral-sh/ruff.git",
            ENROLL["source"],
        ],
        check=True,
    )
    subprocess.run(["git", "-C", src, "checkout", "--quiet", "--detach", ENROLL["source"]], check=True)
    need(
        output(["git", "-C", src, "rev-parse", "HEAD^{tree}"]).decode().strip() == ENROLL["tree"]
        and sha(src / "Cargo.lock") == ENROLL["cargo_lock_sha256"],
        "wrong Ruff checkout",
    )
    prime_patches(root)


def prime_patches(root):
    src = root / "ruff"
    for kind in ("e2e", "migration"):
        with tempfile.TemporaryDirectory(dir=root / "slot/tmp") as tmp:
            git_env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}

            def git(*args, data=None):
                return subprocess.check_output(["git", "-C", src, *args], input=data, env=git_env)

            git("read-tree", "HEAD")
            git("apply", "--cached", "-R", "--check", "-", data=patch(kind))
            git("apply", "--cached", "-R", "-", data=patch(kind))
            need(
                git("write-tree").decode().strip() == ENROLL[kind]["reverse_tree"],
                "different real Ruff reverse patch",
            )
            git("apply", "--cached", "-", data=patch(kind))
            need(git("write-tree").decode().strip() == ENROLL["tree"], "Ruff restoration changed tree")


def patch(kind):
    filename = "notebook.patch.gz" if kind == "e2e" else "ty-project.patch.gz"
    data = gzip.decompress((HERE / "inputs" / filename).read_bytes())
    need(digest(data) == ENROLL[kind]["patch_sha256"], "historical input modified")
    return data


def state(root, kind, mode):
    src = root / "ruff"
    details = ENROLL[kind]
    allowed = set(details["original"]) | ({BAD_PATH} if kind == "migration" else set())

    def git(*args, data=None):
        return subprocess.check_output(["git", "-C", src, *args], input=data)

    dirty = set(git("diff", "--name-only").decode().splitlines())
    need(
        dirty <= allowed and not git("ls-files", "--others", "--exclude-standard"),
        "unexpected workspace changes",
    )
    expected = details["reverse" if mode in ("reversed", "invalid") else "original"].copy()
    if kind == "migration":
        expected[BAD_PATH] = git("rev-parse", "HEAD:" + BAD_PATH).decode().strip()
    for name, oid in expected.items():
        p = src / name
        want = git("cat-file", "blob", oid) if oid else None
        if mode == "invalid" and name == BAD_PATH:
            want += BAD
        actual = p.read_bytes() if p.exists() else None
        if want != actual:
            if want is None:
                p.unlink()
            else:
                p.write_bytes(want)
        need((p.read_bytes() if p.exists() else None) == want, name + " wrong fixture contents")
    changed = set(git("diff", "--name-only").decode().splitlines())
    need(
        changed
        == (set(details["original"]) if mode in ("reversed", "invalid") else set())
        | ({BAD_PATH} if mode == "invalid" else set()),
        "unexpected source shape",
    )
    need(sha(src / "Cargo.lock") == ENROLL["cargo_lock_sha256"], "lockfile was changed")


def seed_registry(root):
    e = env(root)
    home = root / "registry-seed"
    home.mkdir()
    e["CARGO_HOME"] = str(home)
    e.pop("CARGO_NET_OFFLINE")
    subprocess.run(["cargo", "+ohm", "fetch", "--locked"], env=e, cwd=root / "ruff", check=True, timeout=1200)
    locked = {
        f"{p['name']}-{p['version']}.crate": p["checksum"]
        for p in tomllib.loads((root / "ruff/Cargo.lock").read_text())["package"]
        if "checksum" in p
    }
    actual = {p.name: sha(p) for p in home.glob("registry/cache/*/*.crate")}
    need(len(locked) == ENROLL["registry_members"] and actual == locked, "Ruff registry inputs differ")
    write(root / "receipts/registry.json", actual)


def fresh(root, registry=False):
    slot = root / "slot"
    names = ["target", "shared"] + (["cargo-home"] if registry else [])
    for name in names:
        p = slot / name
        need(p.parent == slot and not p.is_symlink(), "unexpected reset target")
        if p.exists():
            shutil.rmtree(p)
    if registry:
        home = slot / "cargo-home"
        home.mkdir()
        for name in ("registry", "git"):
            src = root / "registry-seed" / name
            if src.exists():
                subprocess.run(["cp", "-a", "--reflink=auto", "--", src, home / name], check=True)
    need(all(not (slot / n).exists() for n in ("target", "shared")), "unclean target or build directory")


def storage(root, receipt):
    os.sync()
    seen = {}
    rows = []
    roots = [root / "slot" / i for i in ("target", "shared")]
    existing = [p for p in roots if p.exists()]
    for base in existing:
        for p in [base, *base.rglob("*")]:
            st = p.lstat()
            ident = (st.st_dev, st.st_ino)
            need(ident not in seen or seen[ident] == st.st_blocks, "filesystem changed during census")
            seen[ident] = st.st_blocks
            rows.append(
                [
                    str(p.relative_to(root / "slot")),
                    *ident,
                    st.st_mode,
                    st.st_nlink,
                    st.st_size,
                    st.st_blocks,
                    st.st_mtime_ns,
                    st.st_ctime_ns,
                ]
            )
    total = sum(seen.values()) * 512
    du = output(["du", "--summarize", "--block-size=1", "--", *existing]).decode() if existing else ""
    need(
        sum(int(l.split("\t", 1)[0]) for l in du.splitlines()) == total,
        "du disagrees with hardlink-deduplicated allocation",
    )
    raw = json.dumps(sorted(rows), separators=(",", ":")).encode()
    payload(receipt / "allocated-files.json.gz", raw)
    return {
        "bytes": total,
        "paths": len(rows),
        "unique_inodes": len(seen),
        "du": du,
        "ledger_sha256": digest(raw),
    }
