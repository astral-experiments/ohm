"""Build and freeze two genuine stage1 compilers on one nonrelease QA worker."""

import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from capsule import HOST, REG, need, reopen, save, seal, sha

BRANCH = "charlie/qa-indexed-check-matched-stage-20261102"
BASE = "00f4192b5507f8c028898ce5bd66958d20f341c5"


def git(repo, *args):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", repo, *args], text=True).strip()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bundle(repo):
    packet, entry = HERE / "candidate.bundle", REG["bundle"]
    need(
        packet.stat().st_size == entry["bytes"] and sha(packet) == entry["sha256"],
        "different compiler source packet",
    )
    parent, candidate = (REG["roles"][k] for k in ("P", "C"))
    p, c = parent["revision"], candidate["revision"]
    need(
        git(repo, "bundle", "list-heads", str(packet)) == c + " " + entry["branch"],
        "more than one candidate ref",
    )
    git(repo, "bundle", "verify", str(packet))
    git(repo, "fetch", "--no-tags", "--no-recurse-submodules", str(packet), entry["branch"])
    need(
        git(repo, "rev-parse", "FETCH_HEAD", c + "^").splitlines() == [c, p]
        and git(repo, "rev-list", c, "^" + p).splitlines() == [c],
        "not the single prepared compiler commit",
    )
    need(
        git(repo, "rev-list", "--reverse", p, "^" + entry["prerequisite"]).splitlines()
        == entry["baseline_commits"],
        "wrong packaging pin history between the prepared source and the parent",
    )
    changed = sorted(REG["changed_sources"])
    need(
        git(repo, "diff", "--name-status", "--no-renames", p, c).splitlines()
        == [("M" if REG["changed_sources"][path]["P"] else "A") + "\t" + path for path in changed],
        "different treatment paths",
    )
    for role, entry in REG["roles"].items():
        rev = entry["revision"]
        need(git(repo, "rev-parse", rev + "^{tree}", rev + ":compiler").splitlines()
             == [entry["tree"], entry["compiler"]], "different pinned compiler tree")
        for path in changed:
            oid = REG["changed_sources"][path][role]
            expected = "" if oid is None else "100644 blob " + oid + "\t" + path
            need(git(repo, "ls-tree", rev, "--", path) == expected, ("different source blob", role, path))


def control(workspace, root):
    qa = workspace / "qa-code"
    need(
        os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
        and os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
        and os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"] == git(qa, "rev-parse", "HEAD")
        and HERE == qa / "scripts/ruff-matched-stage",
        "incorrect nonrelease receiver",
    )
    need(not git(qa, "status", "--porcelain", "--untracked-files=all"), "modified builder checkout")
    changed = git(qa, "diff", "--name-only", BASE, "HEAD").splitlines()
    need(
        changed
        and all(
            p == ".github/workflows/ci.yml" or p.startswith("scripts/ruff-matched-stage/") for p in changed
        ),
        "unexpected packaging changes",
    )
    reg = json.loads((qa / "scripts/rc23-expanded-inputs/registration.json").read_bytes())
    need(
        git(workspace, "rev-parse", "HEAD") == reg["coordinator"]
        and git(workspace / "packed", "rev-parse", "HEAD") == REG["kit"]["commit"],
        "incorrect pinned coordinator or capsule helper",
    )
    source = workspace / "packed/scripts/ohm-packed-ruff"
    for file in ("runtime.py", "prepare.sh"):
        need(sha(source / file) == REG["kit"][file], "unreviewed bootstrap or capsule helper")
    need(
        platform.machine() == "x86_64" and len(os.sched_getaffinity(0)) >= 8, "requires eight x86-64 GNU CPUs"
    )
    root.mkdir()
    (root / "logs").mkdir()
    save(root / "logs/registration.json", REG)
    save(
        root / "logs/host.json",
        {
            "reviewed": git(qa, "rev-parse", "HEAD"),
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "kernel": platform.uname()._asdict(),
            "cpus": sorted(os.sched_getaffinity(0)),
            "cpuinfo": Path("/proc/cpuinfo").read_text(),
            "source_coordinator": reg["coordinator"],
            "source_assembler": sha(qa / "scripts/rc23-expanded-inputs/materialize.py"),
            "git": git(qa, "--version"),
            "python": sys.version,
            "tools": {
                n: subprocess.check_output(
                    [n, "--version"], text=True, stderr=subprocess.STDOUT
                ).splitlines()[0]
                for n in ("cc", "c++", "ld", "cmake", "ninja", "rustup", "zstd")
            },
        },
    )


def private_env(root):
    env = {
        k: os.environ[k]
        for k in ("PATH", "HOME", "SSL_CERT_FILE", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")
        if k in os.environ
    }
    env.update(
        LC_ALL="C",
        TZ="UTC",
        SOURCE_DATE_EPOCH=str(REG["source_epoch"]),
        CARGO_INCREMENTAL="0",
        SCCACHE_DISABLE="1",
        CCACHE_DISABLE="1",
        PYTHONDONTWRITEBYTECODE="1",
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_NOSYSTEM="1",
        RUSTUP_AUTO_INSTALL="0",
    )
    env["LD_LIBRARY_PATH"] = str(Path(sys.executable).resolve().parent.parent / "lib")
    for k, n in (
        ("CARGO_HOME", "cargo-home"),
        ("RUSTUP_HOME", "rustup"),
        ("XDG_CACHE_HOME", "xdg"),
        ("TMPDIR", "tmp"),
    ):
        dest = root / n
        dest.mkdir()
        env[k] = str(dest)
    return env


def guarded(argv, cwd, env, log, path):
    need(shutil.disk_usage(path).free >= 12 * 2**30, "insufficient space before stage1")
    floor = 8 * 2**30
    with log.open("xb") as f:
        proc = subprocess.Popen(
            argv, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            while proc.poll() is None:
                mem = next(
                    int(l.split()[1]) * 1024
                    for l in Path("/proc/meminfo").read_text().splitlines()
                    if l.startswith("MemAvailable:")
                )
                cgroup = Path("/sys/fs/cgroup")
                if (cgroup / "memory.max").is_file() and (
                    cap := (cgroup / "memory.max").read_text().strip()
                ) != "max":
                    mem = min(mem, int(cap) - int((cgroup / "memory.current").read_text()))
                need(
                    shutil.disk_usage(path).free >= floor and mem >= floor,
                    "stage1 filesystem or memory floor",
                )
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    pass
            need(proc.returncode == 0, ("stage1 exited", proc.returncode, log))
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()


def signed_tools(root):
    asset = REG["signed_cargo"]["asset"]
    archive = root / "signed-cargo.tar.gz"
    need(
        archive.is_file()
        and not archive.is_symlink()
        and archive.stat().st_size == asset["size"]
        and sha(archive) == asset["sha256"],
        "different original release archive",
    )
    members = REG["signed_cargo"]["members"]
    seen = set()
    with tarfile.open(archive, "r|gz") as tf:
        for m in tf:
            for path, (member, mode, size, key) in members.items():
                if m.name != member:
                    continue
                need(
                    path not in seen and m.isfile() and (m.size, m.mode & 0o777) == (size, mode),
                    "different original Cargo/linker member",
                )
                with tf.extractfile(m) as f, (root / "capsule/objects" / key).open("xb") as out:
                    shutil.copyfileobj(f, out)
                need(sha(root / "capsule/objects" / key) == key, "changed executable from original release")
                seen.add(path)
    need(seen == members.keys(), "incomplete original Cargo/linker")
    return {"asset": asset, "members": members}


def build(workspace, root):
    rust = workspace / "source/rust"
    kit = load("freeze_kit", workspace / "packed/scripts/ohm-packed-ruff/runtime.py")
    layout = load("qa_layout", workspace / "legacy/scripts/dep-graph-slots/layout.py")
    orig = json.loads((root / "logs/source.json").read_bytes())
    need(
        git(rust, "rev-parse", "HEAD") == orig["source"]["rust"] and orig["qa"] == os.environ["GITHUB_SHA"],
        "missing authenticated complete composite",
    )
    bundle(rust)
    reg = json.loads((workspace / "qa-code/scripts/rc23-expanded-inputs/registration.json").read_bytes())
    substitutions = {
        "src/tools/" + n: (reg["sources"][n]["end"], reg["sources"][n]["tree"]) for n in ("clippy", "rustfmt")
    }
    (root / "capsule/objects").mkdir(parents=True)
    original_tools = signed_tools(root)
    env = private_env(root)
    save(
        root / "logs/build-env.json",
        {k: v for k, v in env.items() if k not in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")},
    )
    directory = root / "build"
    os.chdir(rust)
    for role in ("P", "C"):
        desc = REG["roles"][role]
        rev = desc["revision"]
        git(rust, "checkout", "--quiet", "--detach", "--no-recurse-submodules", rev)
        full = json.loads(json.dumps(layout.checked(rust, rev, desc["tree"], substitutions)))
        need(
            full["gitlinks"] == orig["layout"]["gitlinks"]
            and full["authorized_differences"] == orig["layout"]["authorized_differences"],
            "changed nested tool inputs",
        )
        directory.mkdir()
        ino = (directory.stat().st_dev, directory.stat().st_ino)
        argv = [
            sys.executable,
            "-IB",
            str(rust / "x.py"),
            "--build-dir",
            str(directory),
            *REG["bootstrap_flags"],
            "build",
            "--stage",
            "1",
            "-j8",
            "compiler/rustc",
            "library",
        ]
        save(
            root / "logs" / ("inputs-" + role + ".json"),
            {
                "source": desc,
                "checked_layout": full,
                "source_epoch": REG["source_epoch"],
                "bootstrap": git(rust, "rev-parse", rev + ":src/bootstrap"),
                "llvm_gitlink": git(rust, "rev-parse", rev + ":src/llvm-project"),
                "std_tree": git(rust, "rev-parse", rev + ":library"),
                "argv": argv,
                "empty_build_dir": not any(directory.iterdir()),
            },
        )
        print("Starting clean stage1", role, rev, flush=True)
        guarded(argv, rust, env, root / "logs" / ("build-" + role + ".log"), root)
        kit.freeze(directory / HOST / "stage1", role, rev)
        need(
            json.loads(json.dumps(layout.checked(rust, rev, desc["tree"], substitutions))) == full,
            "bootstrap changed enrolled source",
        )
        need(
            not directory.is_symlink() and (directory.stat().st_dev, directory.stat().st_ino) == ino,
            "build root replaced",
        )
        shutil.rmtree(directory)
        print("Froze stage1", role, flush=True)
    capsule = root / "capsule"
    receipt = {
        "schema": "ohm-remat-rustc-capsule-v1",
        "registration": sha(HERE / "registration.json"),
        "source_sha256": sha(root / "logs/source.json"),
        "signed_tools": original_tools,
        "manifests": {k: sha(capsule / (k + ".json")) for k in ("P", "C")},
    }
    save(capsule / "qualified.json", receipt)
    seal(capsule)
    manifest = reopen(capsule, root / "reopened")
    from smoke import smoke

    smoke(root, manifest, env)
    for role in ("P", "C"):
        shutil.copy2(capsule / (role + ".json"), root / "logs" / (role + ".json"))
    for name in ("rustcs.json", "storage.json"):
        shutil.copy2(root / "reopened" / name, root / "logs" / name)
    save(root / "logs/accepted.json", receipt)


if __name__ == "__main__":
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    root = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "ohm-branch-object-qa"
    (mode,) = sys.argv[1:]
    {"preflight": control, "build": build}[mode](workspace, root)
