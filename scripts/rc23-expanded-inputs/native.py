"""Run the release regressions on fresh installations of the actual staged distributions."""

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from materialize import REG, checkout, need, save, sha
import media
import epoch

HOSTS = {"Linux": "x86_64-unknown-linux-gnu", "Darwin": "aarch64-apple-darwin"}
OLD_RUST = "008a21ac0d750dc9a1c18b7959d7e7984c03d887"
OLD_CARGO = "ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_room(root):
    need(shutil.disk_usage(root).free > 4 << 30, "less than 4 GiB available")


def patched_diamond(legacy, root):
    root.mkdir()
    seals = json.loads((HERE / "diamond-patch.json").read_bytes())
    for name, (before, _) in seals.items():
        path = legacy / "diamond" / name
        need(sha(path) == before, ("foreign historical native fixture", name))
        shutil.copy2(path, root / name)
    subprocess.run(
        ["git", "apply", "--check", "--whitespace=error", "-p1", str(HERE / "diamond.patch")],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "apply", "--whitespace=error", "-p1", str(HERE / "diamond.patch")], cwd=root, check=True
    )
    for name, (_, after) in seals.items():
        need(sha(root / name) == after, ("different native policy", name))
    (root / "inputs.py").symlink_to(legacy / "diamond/inputs.py")
    return load("joined_diamond_run", root / "run.py"), load("joined_diamond_reopen", root / "reopen.py")


def trait(compiler, root, out):
    root.mkdir()
    out.mkdir()
    case = "trait-impl-bucket-projection"
    for name in ("reader.rs", "roster.rs", "rmake.rs"):
        raw = (HERE / case / name).read_bytes()
        blob = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        need(blob == REG["rust_tail"]["paths"]["tests/run-make/" + case + "/" + name], name)
        (root / name).write_bytes(raw)
    cases = (
        ((), "3 3 3 3 3"),
        (("unrelated",), "3 3 3 3 3"),
        (("unrelated", "matching", "finite"), "7 3 11 13 17"),
        (("unrelated", "moved"), "3 7 3 3 3"),
        (("unrelated",), "3 3 3 3 3"),
        (("unrelated", "moved"), "3 7 3 3 3"),
        (("unrelated", "retired"), "3 3 3 3 3"),
    )
    results = []

    def call(name, argv):
        p = subprocess.run(argv, cwd=root, capture_output=True, timeout=90)
        save(out / (name + ".json"), {"argv": list(map(str, argv)), "rc": p.returncode, "cwd": str(root)})
        (out / (name + ".stdout")).write_bytes(p.stdout)
        (out / (name + ".stderr")).write_bytes(p.stderr)
        p.check_returncode()
        return p.stdout

    for i, (cfgs, value) in enumerate(cases):
        call(
            f"{i}-producer",
            [compiler, "roster.rs", "--crate-type=rlib", *(arg for cfg in cfgs for arg in ("--cfg", cfg))],
        )
        for solver, extra in (("default", []), ("next", ["-Znext-solver"])):
            exe = root / "reader"
            exe.unlink(missing_ok=True)
            name = f"{i}-{solver}"
            call(
                name,
                [
                    compiler,
                    "reader.rs",
                    "--extern",
                    "roster=libroster.rlib",
                    "-Cincremental=" + solver,
                    "-Zincremental-verify-ich",
                    *extra,
                ],
            )
            observed = call(name + "-run", [exe])
            need(observed.strip() == value.encode(), (name, observed, value))
            h = sha(exe)
            body = out / (h + ".native.gz")
            if not body.exists():
                body.write_bytes(gzip.compress(exe.read_bytes(), mtime=0))
            results.append(
                {"phase": i, "cfgs": cfgs, "solver": solver, "native": h, "stdout": observed.decode()}
            )
    save(
        out / "complete.json",
        {"compiler": sha(compiler), "source": REG["rust_tail"]["commit"], "reads": results},
    )


def gnu(legacy, sdk, host, proxy, out):
    g = legacy / "gnu-defaults"
    sys.path.insert(0, str(g))
    w = load("expanded_default_workers", g / "worker.py")
    from release_smoke import toolchain

    out.mkdir()
    need(os.geteuid() != 0 and host == "x86_64-unknown-linux-gnu", "expected unprivileged native GNU")
    os.umask(0o022)
    # Only the private projection accepts the artificial higher-priority native
    # files. Its Rust compiler, Cargo, driver and stock Wild must match the distro.
    with tempfile.TemporaryDirectory(prefix="ohm-expanded-gnu-", dir="/tmp") as td:
        root = Path(td)
        check_room(root)
        view = root / "rustup/toolchains/ohm"
        toolchain(view, sdk, sdk / "bin/cargo", host, sdk / w.WILD_PATH)
        w.install_file(sdk / "bin/cargo", view / "bin/cargo")
        w.install_file(sdk / w.WILD_PATH, view / w.WILD_PATH)
        (root / "rustup/settings.toml").write_text('version = "12"\nprofile = "minimal"\n')
        for _, (_, path) in media.files(sdk, host).items():
            need(sha(view / path) == sha(sdk / path), ("different enrolled GNU executable/input", path))
        observer = root / "exec-events"
        subprocess.run(
            [
                "/usr/bin/cc",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                g / "exec_events.c",
                "-lcrypto",
                "-o",
                observer,
            ],
            check=True,
        )
        save(
            out / "observer.json",
            {p.name: sha(p) for p in (observer, g / "exec_events.c", g / "events.py", g / "reproduce.sh")},
        )
        w.execute(root, out, view, (view / w.WILD_PATH).parent, proxy, observer)
        check_room(root)
    save(
        out / "complete.json",
        {
            "cases": {n: sha(out / n / "verified.json") for n in w.NAMES},
            "portable": sha(out / "standalone.log"),
        },
    )


def matrix(work, out, legacy, new, old, host, new_media):
    import release_smoke
    import worktree_paths
    import ready_terminal

    work.mkdir()
    out.mkdir()
    save(out / "installed-from-archive.json", new_media)
    proxy = work / "launchers"
    proxies = release_smoke.named_proxies(proxy, shutil.which("rustup"))
    rustdoc = Path(shutil.which("rustup")).absolute().with_name("rustdoc")
    need(rustdoc.is_file() and os.access(rustdoc, os.X_OK), "missing actual named rustdoc launcher")
    (proxy / "rustdoc").symlink_to(rustdoc)
    proxies["rustdoc"] = {"path": str(rustdoc), "sha256": sha(rustdoc)}
    save(out / "launchers.json", proxies)
    diamond, reader = patched_diamond(legacy, work / "diamond-reader")
    public = json.loads((HERE / "published-actors.json").read_bytes())[host]
    old_files = {n: sha(old / p) for n, (_, p) in media.files(old, host).items()}
    need(old_files == public["actors"], "different published native distribution")
    save(out / "published-verified.json", public)
    new_files = {n: r["sha256"] for n, r in new_media["actors"].items()}
    sources = (
        ("corrected", new, REG["rust_tail"]["commit"], REG["cargo_tail"]["commit"], new_files),
        ("published-22", old, OLD_RUST, OLD_CARGO, old_files),
    )
    rgraph = load("source_graph_controls", legacy / "native.py")
    results = {}
    for role, sdk, rust, cargo, hashes in sources:
        check_room(work)
        case = out / role
        case.mkdir()
        temp = work / role
        temp.mkdir()
        (temp / "user").mkdir()
        home = temp / "rustup"
        (home / "toolchains").mkdir(parents=True)
        (home / "toolchains/ohm").symlink_to(sdk, target_is_directory=True)
        (home / "settings.toml").write_text('version = "12"\nprofile = "minimal"\n')
        env = {
            k: os.environ[k]
            for k in ("SDKROOT", "DEVELOPER_DIR", "MACOSX_DEPLOYMENT_TARGET")
            if k in os.environ
        }
        env.update(
            HOME=str(temp / "user"),
            TMPDIR=str(temp),
            CARGO_HOME=str(temp / "cargo"),
            RUSTUP_HOME=str(home),
            RUSTUP_AUTO_INSTALL="0",
            PATH=str(proxy) + os.pathsep + os.environ["PATH"],
        )
        versions = release_smoke.identities(
            sdk, sdk, sdk / "bin/cargo", rust, cargo, host, env, case / "identity"
        )
        need(
            all(versions[k]["sha256"] == hashes[k] for k in ("rustc", "cargo", "driver"))
            and versions["std"] == hashes["std"],
            "wrong actual native tools",
        )
        expected = dict(
            host=host,
            rust_commit=rust,
            cargo_commit=cargo,
            **{k: hashes[k] for k in ("rustc", "rustdoc", "cargo")},
        )
        project = work / "same-diamond-path"
        diamond.run_role(project, case / "diamond", sdk, proxy, role, expected, host)
        proof = reader.reopen(case / "diamond", expected, diamond.BIND, True)
        save(case / "diamond-independent.json", proof)
        need(project.parent == work and project.is_dir() and not project.is_symlink(), project)
        shutil.rmtree(project)
        arg = argparse.Namespace(
            compiler=str(sdk / "bin/rustc"),
            sdk=str(sdk),
            commit=rust,
            prefix=[],
            producer_sdk=None,
            producer_commit=None,
            mode="candidate" if role == "corrected" else "parent",
            work=temp / "graph",
            out=case / "graph",
        )
        rgraph.main(arg)
        graph = json.loads((arg.out / "native.json").read_bytes())
        need(
            graph["complete"] and len(graph["steps"]) == (28 if role == "corrected" else 19),
            "incomplete native graph study",
        )
        if role == "corrected":
            trait(sdk / "bin/rustc", temp / "trait", case / "trait")
            epoch.migrate(temp / "epoch", case / "epoch", host, old, new, REG["epoch"])
            if host.startswith("x86_64"):
                gnu(legacy, sdk, host, proxy, case / "gnu-defaults")
        check_room(work)
        worktree_paths.role(
            temp / "worktrees",
            case / "worktrees",
            sdk,
            proxy,
            versions,
            role == "corrected",
            host.startswith("aarch64"),
        )
        tty = {k: hashes[k] for k in ("rustc", "cargo", "driver")}
        ready_terminal.cases(
            temp / "ready-tests",
            case / "ready-tests",
            env,
            sdk,
            HERE / "ohm_ready_tests.rs",
            dict(tty, rust=rust, cargo_revision=cargo),
            host,
        )
        links = case / "links"
        links.mkdir()
        smoke = release_smoke.smoke(
            legacy / "release-22/smoke-test-relink.sh", role, temp / "links", links, env
        )
        need(
            smoke["code"] == 0 and not smoke["old_refusal"], "product missed declared native linker behavior"
        )
        results[role] = {
            "versions": versions,
            "diamond": sha(case / "diamond-independent.json"),
            "worktree": sha(case / "worktrees/complete.json"),
            "ready": sha(case / "ready-tests/complete.json"),
            "native_graph": sha(arg.out / "native.json"),
            "link": sha(links / (role + ".json")),
        }
        need(
            all(sha(sdk / p) == hashes[n] for n, (_, p) in media.files(sdk, host).items()),
            "packaged tool changed while running",
        )
        check_room(work)
        need(temp.parent == work and temp.is_dir() and not temp.is_symlink(), temp)
        shutil.rmtree(temp)
    need(
        results["published-22"]["versions"]["cargo"]["sha256"]
        != results["corrected"]["versions"]["cargo"]["sha256"],
        "no Cargo treatment",
    )
    save(
        out / "complete.json",
        {
            "host": host,
            "coordinator": REG["coordinator"],
            "run": os.environ["GITHUB_RUN_ID"],
            "qa": os.environ["GITHUB_SHA"],
            "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "old_archive": public["archive"],
            "new_archive": new_media["sha256"],
            "rust": sources[0][2],
            "cargo": sources[0][3],
            "trait": sha(out / "corrected/trait/complete.json"),
            "epoch": sha(out / "corrected/epoch/complete.json"),
            "gnu": sha(out / "corrected/gnu-defaults/complete.json") if host.startswith("x86_64") else None,
            "roles": results,
        },
    )


def main(a):
    root = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    checkout(root, REG["coordinator"])
    old = root / "legacy"
    checkout(old, REG["legacy"])
    need(
        a.host == HOSTS[platform.system()]
        and platform.machine() == ("arm64" if platform.system() == "Darwin" else "x86_64"),
        "foreign native worker",
    )
    check_room(a.work.parent)
    legacy = old / "scripts/dep-graph-slots"
    sys.path.insert(0, str(legacy))
    if a.install_published:
        import published

        need(a.archive is None and a.installed is None and a.published is None, "invalid original install")
        published.install(a.work, a.out, a.host)
        return
    need(
        all(p is not None for p in (a.archive, a.installed, a.published))
        and not a.work.exists()
        and not a.out.exists(),
        "missing source, original or nonempty work area",
    )
    new, old_sdk = [p.resolve(strict=True) for p in (a.installed, a.published)]
    need(not new.samefile(old_sdk), "roles have the same installed directory")
    packed = media.compare(a.archive, new, a.host)
    matrix(a.work, a.out, legacy, new, old_sdk, a.host, packed)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--install-published", action="store_true")
    for name in ("installed", "published", "archive", "work", "out"):
        p.add_argument("--" + name, type=Path, required=name in ("work", "out"))
    p.add_argument("--host", required=True, choices=HOSTS.values())
    main(p.parse_args())
