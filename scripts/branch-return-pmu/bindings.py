"""Shared immutable inputs and role-specific physical SDK admission."""

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
HIST = HERE.parent / "ohm-packed-ruff"
RUNNER = Path(os.environ["RUNNER_TEMP"]).resolve()
ROOT = RUNNER / "ohm-branch-object-qa"
OUT = ROOT / "logs"
WORK = ROOT / "work"
HOME = ROOT / "home"
PROXIES = HOME / ".cargo/bin"
SDK = HOME / ".rustup/toolchains/ohm"
PARK = ROOT / "physical-sdks"
HEADS = {
    "F": "c6fe8ecda65452c105f85367a009af80cbb5efbc",
    "K": "0afbeff303d3658bff52582d8f1a996d59e6c8ce",
}
PLAN = "b22aac0fd37a6903c62103f721c0579a5c114d5ea64de5564d5065ce26f7867b"
CARGO = "761ea115605c34f11a1cd29afd68812c1e1359dd"
CARGO_ELF = "035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4"
WILD = "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
WILD_ELF = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
COMPARE = {
    "F": "1df08b3c45a7e6fa3739a8e753132f707f97896a",
    "K": "b8fa7ed926a6589fb8fd7e913b0eaadc36875611",
}
CAL = "2f413ca94b84af2dbd6d6231bcf8d860c97ebee8"
OBS = "8a659140df8ab27fd6a8cc61f5eb38717b3f8bbc"
DONOR = "ea7d4e23dba715023cb43c82a9e99bec8c8262a4"
REPO = "astral-experiments/ohm"
BRANCH = "charlie/qa-branch-return-pmu-20261031"
ORDERS = {"01": ("Foff", "Fon", "Kon", "Koff"), "02": ("Koff", "Kon", "Fon", "Foff")}
RUNTIME = HERE / "source-kit.json"


def need(condition, reason):
    if not condition:
        raise ValueError(str(reason))


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, data):
    with path.open("x") as f:
        json.dump(data, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")


def git(repo, *args):
    return subprocess.check_output(
        ["git", "--no-optional-locks", "-C", repo, *args], text=True
    ).strip()


def prepare_checkout(repo, head, prefix):
    need(
        git(repo, "rev-parse", "HEAD") == head
        and not git(repo, "status", "--porcelain", "--", prefix),
        ("checkout", repo, head),
    )


def numbers(path):
    s = path.stat()
    return [s.st_dev, s.st_ino, s.st_mode & 0o7777, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def spec():
    data = json.loads(RUNTIME.read_bytes())
    need(
        type(data.get("run")) is int
        and data["run"] > 0
        and data.get("attempt") == 1
        and re.fullmatch("[0-9a-f]{40}", data["head"]),
        "qualified source binding is required",
    )
    need(
        re.fullmatch("[0-9a-f]{64}", data["manifest"])
        and data["jobs"]
        and set(data["artifacts"])
        == {"branch-return-source-sdk", "branch-return-source-observations"},
        "incomplete source evidence",
    )
    for row in data["artifacts"].values():
        need(
            type(row["id"]) is int
            and row["id"] > 0
            and 0 < row["size"] < 4 * 2**30
            and re.fullmatch("[0-9a-f]{64}", row["sha256"]),
            "bad artifact descriptor",
        )
    return data


def acquire(source):
    s = spec()
    prepare_checkout(source, s["head"], "scripts/branch-return-source")
    source_checker = source / "scripts/branch-return-source/locate.py"
    located = json.loads(
        subprocess.check_output(
            [sys.executable, "-IB", source_checker, str(s["run"]), s["head"], "--gh", "gh"]
        )
    )
    need(
        located["run"] == s["run"]
        and located["qa"] == s["head"]
        and located["attempt"] == 1
        and {str(located["job"]): "Exact Full and Packed source, Rust tests and native providers"}
        == s["jobs"],
        "same qualified native CI job and gates",
    )
    expected = {
        name: [row["id"], row["size"], row["sha256"]] for name, row in s["artifacts"].items()
    }
    need(located["artifacts"] == expected, "official native/transfer artifact ID, size or checksum")
    inbox = ROOT / "source-transfer"
    inbox.mkdir()
    packed = inbox / "transfer"
    packed.mkdir()
    custody = {}
    for name, row in s["artifacts"].items():
        zip_path = inbox / (name + ".zip")
        with zip_path.open("xb") as file:
            subprocess.run(
                ["gh", "api", f"repos/{REPO}/actions/artifacts/{row['id']}/zip"],
                stdout=file,
                check=True,
            )
        need(
            zip_path.stat().st_size == row["size"] and sha(zip_path) == row["sha256"],
            "original ZIP changed",
        )
        with zipfile.ZipFile(zip_path) as z:
            infos = z.infolist()
            need(
                len(set(z.namelist())) == len(infos)
                and sum(i.file_size for i in infos) < 7 * 2**30,
                "unexpected source archive size",
            )
            members = {i.filename: [i.file_size, i.CRC] for i in infos}
            need(
                all(
                    not PurePosixPath(p).is_absolute() and ".." not in PurePosixPath(p).parts
                    for p in members
                ),
                "unsafe ZIP member",
            )
            if name.endswith("-sdk"):
                need(
                    set(members) == {"manifest.json", "F-sdk.tar.zst", "K-delta.tar.zst"},
                    ("source SDK archive shape", list(members)),
                )
                for i in infos:
                    with (packed / i.filename).open("xb") as sink, z.open(i) as src:
                        shutil.copyfileobj(src, sink)
            else:
                need(z.testzip() is None, "incomplete source/native QA originals")
        custody[name] = dict(descriptor=row, members=members)
    need(sha(packed / "manifest.json") == s["manifest"], "source/SDK seal")
    manifest = json.loads((packed / "manifest.json").read_bytes())
    need(
        manifest["qualified"] is True
        and {r: v["commit"] for r, v in manifest["roles"].items()} == HEADS
        and {r: v["compiler"] for r, v in manifest["roles"].items()} == COMPARE
        and manifest["strict_cargo"] == CARGO
        and manifest["wild"] == WILD
        and manifest["host"] == "x86_64-unknown-linux-gnu",
        "source role identities",
    )
    out = OUT / "sdk"
    out.mkdir()
    shutil.copy2(packed / "manifest.json", out / "manifest.json")
    save(out / "custody.json", dict(source=s, jobs=s["jobs"], artifacts=custody))
    PARK.mkdir()
    SDK.parent.mkdir(parents=True)
    for role in COMPARE:
        argv = [
            sys.executable,
            "-IB",
            source / "scripts/branch-return-source/restore.py",
            packed,
            PARK / role,
            role,
            "--qa",
            s["head"],
            "--run",
            str(s["run"]),
            "--attempt",
            "1",
            "--manifest",
            s["manifest"],
        ]
        receipt = subprocess.run(argv, capture_output=True)
        (out / (role + "-restore.stdout")).write_bytes(receipt.stdout)
        (out / (role + "-restore.stderr")).write_bytes(receipt.stderr)
        need(receipt.returncode == 0, (role, receipt.returncode, receipt.stderr[-1500:]))
    return install_locations(out, manifest)


def inventory(root):
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        name = str(path.relative_to(root))
        need(path.is_file() and not path.is_symlink(), ("nonregular SDK member", name))
        files[name] = [sha(path), *numbers(path)]
    return files


def install_locations(out, manifest):
    rows = {r: inventory(PARK / r) for r in COMPARE}
    need(set(rows["F"]) == set(rows["K"]) and len(rows["F"]) >= 60, "truncated F/K SDK membership")
    for role, files in rows.items():
        need(
            files["bin/cargo"][0] == CARGO_ELF
            and files[WILD][0] == WILD_ELF
            and "bin/rustdoc" in files,
            "wrong strict Cargo/std Wild or missing rustdoc",
        )
        need(
            {p: [row[0], row[4], row[3]] for p, row in files.items()} == manifest["files"][role],
            ("physically reopened complete SDK differs", role),
        )
        (driver,) = [p for p in files if p.startswith("lib/librustc_driver-") and p.endswith(".so")]
        need(driver == manifest["driver"], "wrong rustc driver")
        need(
            any("/lib/libstd-" in p and p.endswith(".rlib") for p in files)
            and any("/lib/libcore-" in p and p.endswith(".rlib") for p in files),
            "missing std/toolchain closure",
        )
        save(
            out / (role + ".json"),
            dict(
                role=role,
                source_commit=HEADS[role],
                compiler_tree=COMPARE[role],
                driver=driver,
                files=files,
            ),
        )
    changed = [
        p
        for p in rows["F"]
        if (rows["F"][p][0], rows["F"][p][3]) != (rows["K"][p][0], rows["K"][p][3])
    ]
    need(
        any(p.startswith("lib/librustc_driver-") for p in changed)
        and all(
            p in ("bin/rustc", "bin/rustdoc") or p.startswith("lib/librustc_driver-")
            for p in changed
        ),
        ("unexpected role differences", changed),
    )
    PROXIES.mkdir(parents=True)
    shutil.copy2(shutil.which("rustup"), PROXIES / "rustup")
    for name in ("cargo", "rustc", "rustdoc"):
        os.link(PROXIES / "rustup", PROXIES / name)
    save(
        out / "proxy.json",
        dict(
            sha256=sha(PROXIES / "rustup"),
            paths={str(p): numbers(p) for p in PROXIES.iterdir()},
            changed_sdk_members=changed,
        ),
    )
    return rows


def environment(arm):
    need(arm in ORDERS["01"], "unknown arm")
    env = dict(
        HOME=str(HOME),
        PATH=str(PROXIES) + ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        RUSTUP_HOME=str(HOME / ".rustup"),
        RUSTUP_AUTO_INSTALL="0",
        CARGO_HOME=str(HOME / ".cargo"),
        CARGO_TARGET_DIR=str(WORK / "target"),
        CARGO_BUILD_BUILD_DIR=str(WORK / "build"),
        CARGO_NET_OFFLINE="true",
        CARGO_CACHE_AUTO_CLEAN_FREQUENCY="never",
        CARGO_TERM_COLOR="never",
        LC_ALL="C",
        LD_LIBRARY_PATH=str(SDK / "lib"),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    if arm.endswith("on"):
        env["CARGO_ENCODED_RUSTFLAGS"] = "-Zohm-branch-cache=yes"
    return env


def verify_physical(root, desired):
    actual = {
        str(p.relative_to(root)): numbers(p)
        for p in root.rglob("*")
        if not p.is_dir() or p.is_symlink()
    }
    need(
        actual == {p: v[1:] for p, v in desired.items()},
        ("changed, added or missing SDK members", str(root)),
    )


def activate(arm, rows, out):
    role = arm[0]
    old = next((r for r in COMPARE if not (PARK / r).exists()), None)
    if old is not None:
        verify_physical(SDK, rows[old])
    if old != role:
        if old is not None:
            SDK.rename(PARK / old)
        try:
            (PARK / role).rename(SDK)
        except BaseException:
            if old is not None:
                (PARK / old).rename(SDK)
            raise
    record = json.loads((OUT / "sdk" / (role + ".json")).read_bytes())
    files = rows[role]
    verify_physical(SDK, files)
    # Native path, bytes, inode and ctime for the tools Cargo uses to form its context.
    roles = {p: files[p] for p in ("bin/cargo", "bin/rustc", "bin/rustdoc", record["driver"], WILD)}
    need(all(sha(SDK / p) == v[0] for p, v in roles.items()), "active tools differ")
    env = environment(arm)
    versions = {}
    for name in ("rustc", "cargo", "rustdoc"):
        actual = Path(
            subprocess.check_output(
                ["rustup", "which", "--toolchain", "ohm", name], env=env, text=True
            ).strip()
        )
        need(
            actual == SDK / "bin" / name and actual.samefile(SDK / "bin" / name),
            "wrong canonical rustup selection",
        )
        versions[name] = subprocess.check_output([name, "+ohm", "-vV"], env=env, text=True)
    need(
        "commit-hash: " + CARGO in versions["cargo"]
        and Path(
            subprocess.check_output(
                ["rustc", "+ohm", "--print", "sysroot"], env=env, text=True
            ).strip()
        )
        == SDK,
        "wrong source for active compiler/Cargo",
    )
    save(
        out / "arm.json",
        dict(
            arm=arm,
            role=role,
            sdk=str(SDK),
            files=roles,
            versions=versions,
            env=env,
            source_manifest=spec()["manifest"],
        ),
    )
    return env


def fresh_outputs():
    need(
        WORK.resolve() == WORK and (WORK / ".owned-by-packed-study").read_text() == str(ROOT),
        "unowned output roots",
    )
    for name in ("target", "build"):
        path = WORK / name
        if path.exists() or path.is_symlink():
            need(
                path.is_dir()
                and path.resolve() == path
                and not path.is_mount()
                and path.stat().st_dev == WORK.stat().st_dev,
                ("unowned target", path),
            )
            shutil.rmtree(path)
        path.mkdir()
        need(not any(path.iterdir()), "fresh output not empty")


def prepare_inputs(kit, env):
    subprocess.run(["git", "init", "--quiet", "--template=", kit.TREE], check=True)
    kit.git(
        "fetch",
        "--quiet",
        "--no-tags",
        "--depth=2",
        "https://github.com/astral-sh/ruff.git",
        kit.REVS["B"],
    )
    need(
        kit.git("rev-parse", kit.REVS["B"] + "^") == kit.REVS["A"]
        and len(kit.git("diff", "--name-status", kit.REVS["A"], kit.REVS["B"]).splitlines()) == 169,
        "Ruff history",
    )
    for branch, rev in kit.REVS.items():
        need(kit.git("rev-parse", rev + "^{tree}") == kit.TREES[branch], "Ruff tree")
        kit.git("branch", kit.NAMES[branch], rev)
    kit.git("switch", "-q", kit.NAMES["A"])
    shutil.copytree(HIST / "harness", ROOT / "harness")
    lock = kit.TREE / "Cargo.lock"
    need(
        sha(lock) == "839edc8250480bb523619b8d24bd57176a6e1f57c152cca85c5adc61ea5f94eb",
        "Ruff Cargo.lock",
    )
    fetch = ["cargo", "+ohm", "fetch", "--locked"]
    subprocess.run(fetch, cwd=kit.TREE, env=env | {"CARGO_NET_OFFLINE": "false"}, check=True)
    pins = {
        p["name"] + "-" + p["version"] + ".crate": p["checksum"]
        for p in tomllib.loads(lock.read_text())["package"]
        if "checksum" in p
    }
    have = {p.name: sha(p) for p in (HOME / ".cargo/registry/cache").glob("*/*.crate")}
    need(have == pins and len(pins) == 505, "complete 505 archive seed")
    save(
        OUT / "ruff-inputs.json",
        dict(
            commits=kit.REVS,
            trees=kit.TREES,
            changed=kit.git("diff", "--name-status", *kit.REVS.values()).splitlines(),
            lock=sha(lock),
            archives=pins,
        ),
    )
