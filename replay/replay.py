"""Replay fixed upstream changes with two complete Linux SDKs."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig

wd = Path.cwd()
sys.path.insert(0, str(wd / "replay"))
import history

case, pair = sys.argv[1].split("/")
root = Path(os.environ["RUNNER_TEMP"])
out = wd / "counts"
out.mkdir(exist_ok=True)
record = json.loads((wd / "replay/cases.json").read_text())[case]
baseline = "7fc3d21a5efad6bff7be654b14e0e60aa2fbbfd11db198582788f3cc4bcf7591"
order = ["control", "candidate"] if int(pair) % 2 else ["candidate", "control"]
src = root / "source"
target = root / "target"
sdk = root / "installed"
cargo = sdk / "bin/cargo"
rustc = sdk / "bin/rustc"
meter = root / "meter"
registry = root / "registry"
rustup = root / "rustup"
result = dict(case=case, pair=pair, record=record, order=order, archive={},
              cpu=re.search(r"^model name\s*:\s*(.+)$", Path("/proc/cpuinfo").read_text(), re.M)[1],
              boot=history.sha(Path("/proc/sys/kernel/random/boot_id")), kernel=platform.release())
env = dict(HOME=str(Path.home()), USER=os.environ["USER"], LANG="C.UTF-8",
           PATH=str(sdk / "bin") + ":" + os.environ["PATH"],
           CARGO_HOME=str(registry), CARGO_BUILD_JOBS="8", CARGO_TARGET_DIR=str(target),
           RUSTUP_HOME=str(rustup), RUSTUP_TOOLCHAIN="ohm", CARGO_TERM_COLOR="never")
toolchain = rustup / "toolchains/ohm"
toolchain.parent.mkdir(parents=True)
toolchain.symlink_to(sdk)


def run(*args, **kw):
    return subprocess.run(list(map(str, args)), check=True, **kw)


def install(role):
    tag = "3" if role == "control" else "4"
    kit = wd / "kits" / tag
    archive, = kit.rglob("*.tar.gz")
    h = history.sha(archive)
    result["archive"][role] = h
    if tag == "3":
        assert h == baseline
    else:
        checksum, = kit.rglob("*.tar.gz.sha256")
        assert checksum.read_text().strip().split()[0] == h
    run("tar", "xzf", archive, "-C", root)
    tree = root / "rust-1.100.0-dev-x86_64-unknown-linux-gnu"
    run("sh", tree / "install.sh", "--prefix=" + str(root / role),
        "--disable-ldconfig", "--without=rust-docs", stdout=subprocess.DEVNULL)
    shutil.rmtree(tree)


def git(*args):
    return history.git(src, *args).decode().strip()


def fetch():
    run("git", "init", "-q", src)
    remote = "https://github.com/" + record["repo"] + ".git"
    tips = list(dict.fromkeys(rev.rstrip("^") for rev in record["revs"]))
    depth = 41 if record["kind"] == "history" else 4
    if case == "serc-1239-1240":
        depth = 5
    run("git", "-C", src, "fetch", "-q", "--depth=" + str(depth), remote, *tips)
    # Keep a named ref for the history driver's local clone.
    git("update-ref", "refs/heads/workload", tips[-1])


def run_history():
    control = root / "control"
    candidate = root / "candidate"
    sys.argv = [sys.argv[0], "--source", str(src), "--project", record["app"],
                "--window", record["window"], "--output", str(out),
                "--control", str(control), "--candidate", str(candidate),
                "--cargo", str(control / "bin/cargo"),
                "--candidate-cargo", str(candidate / "bin/cargo"),
                "--first", order[0], "--scratch", str(root / "study")]
    os.environ["CARGO_HOME"] = str(registry)
    history.main()
    result["history"] = json.loads((out / "summary.json").read_text())


def count(name, command, directory, allowed=(0,)):
    receipt = directory / (name + ".tsv")
    p = subprocess.run([meter, rustc, receipt, *command],
                       cwd=src, capture_output=True, env=env)
    if p.returncode not in allowed:
        print(p.stdout[-800:].decode(errors="replace"), p.stderr[-2800:].decode(errors="replace"), flush=True)
        raise RuntimeError((command, p.returncode))
    counts = history.read_counts(receipt)
    total = int(Path(str(receipt) + ".tree").read_text().split()[0])
    return dict(instructions=total, jobs=len(counts), rustc=sum(c["instructions"] for c in counts)), p


def probe(binary, directory):
    app = record["app"]
    if app == "ruff":
        commands = [["check", "--isolated", "--no-cache", "--select", "ALL",
                     "--output-format", "json", str(corpus)],
                    ["format", "--isolated", "--no-cache", "--diff", str(corpus)]]
    elif app == "ty":
        commands = [["check", "--output-format", "concise", str(corpus)]]
    else:
        listing = subprocess.check_output([binary, "--list"], cwd=src, env=env, text=True)
        names = [line[:-6] for line in listing.splitlines() if line.endswith(": test")]
        assert names, listing[:160]
        commands = [["--list"], ["--test-threads=1", "--exact", *names[:12]]]
    rows = []
    for i, args in enumerate(commands):
        profile, p = count("runtime-" + str(i), [binary, *args], directory, (0, 1))
        output = p.stdout + b"\0" + p.stderr
        if app == "ruff" and i == 0:
            assert len(json.loads(p.stdout)) > 10
        if app == "ty":
            assert b"invalid-assignment" in output, output[-1000:]
        if app == "ty_python_semantic":
            assert p.returncode == 0
            output = re.sub(rb"finished in [\d.]+s", b"finished", output)
        rows.append(dict(command=args, status=p.returncode, sha256=hashlib.sha256(output).hexdigest(),
                         length=len(output), **profile))
    return rows


def replay(role):
    (root / role).rename(sdk)
    if target.exists():shutil.rmtree(target)
    folder = out / role
    folder.mkdir()
    app = record["app"]
    if record["kind"] == "check":
        cmd = [cargo, "check", "--locked", "--offline", "-p", app]
    elif app == "ty_python_semantic":
        cmd = [cargo, "test", "--no-run", "--locked", "--offline", "--lib", "-p", app]
    else:
        cmd = [cargo, "build", "--locked", "--offline", "-p", app, "--bin", app]
    rows = []
    prev = None
    for i, rev in enumerate(record["revs"]):
        where = git("rev-parse", rev)
        print(role, i, where, flush=True)
        git("checkout", "-q", "--detach", where)
        lock = history.sha(src / "Cargo.lock")
        if lock != prev:
            history.command([cargo, "fetch", "--locked", "--target", "x86_64-unknown-linux-gnu"],
                            src, env, folder / ("fetch-" + str(i) + ".log"))
        prev = lock
        directory = folder / str(i)
        directory.mkdir()
        profile, p = count("compile", cmd, directory)
        (directory / "build.log").write_bytes(p.stderr)
        size = int(subprocess.check_output(["du", "-sb", target]).split()[0])
        cache = [f.stat().st_size for f in target.rglob("llvmcache-*") if f.is_file()]
        row = dict(rev=where, lock=lock, command=list(map(str,cmd)), target_bytes=size,
                   llvmcache_bytes=sum(cache), llvmcache_files=len(cache), **profile)
        if record["kind"] != "check":
            if app == "ty_python_semantic":
                matches = re.findall(rb"Executable unittests .*? \((.*?)\)", p.stderr)
                assert len(matches)==1, p.stderr[-600:]
                binary = src / matches[0].decode()
            else:
                binary = target / "debug" / app
            row["binary"] = history.sha(binary)
            row["runtime"] = probe(binary, directory)
        rows.append(row)
        print(row["jobs"], row["instructions"], row["llvmcache_bytes"], flush=True)
        history.save(folder / "rows.json", rows)
    sdk.rename(root / role)
    return rows


for role in order:
    install(role)
history.save(out / "inputs.json", result)
if case == "correctness":
    from correctness import verify
    for role in order:
        (root / role).rename(sdk)
        result[role] = verify(root, out / role, cargo, env)
        sdk.rename(root / role)
    history.save(out / "result.json", result)
    if result["archive"]["candidate"] != baseline:
        assert all(result["candidate"].values()), result["candidate"]
elif record["kind"] == "history":
    fetch()
    run_history()
else:
    fetch()
    history.calibrate(root, out)
    corpus = root / "corpus"
    corpus.mkdir()
    for name in ["ast", "pathlib", "tokenize", "typing"]:
        source = Path(sysconfig.get_path("stdlib")) / (name + ".py")
        if source.exists():shutil.copy(source, corpus / ("sample_" + name + ".py"))
    (corpus / "sample_error.py").write_text('value: str = 123\n')
    assert len(list(corpus.iterdir())) >= 3
    for role in order:
        result[role] = replay(role)
    history.save(out / "result.json", result)
    for r,s in zip(result["control"],result["candidate"],strict=True):
        assert (r["rev"],r["lock"]) == (s["rev"],s["lock"])
        for x,y in zip(r.get("runtime",[]),s.get("runtime",[]),strict=True):
            assert (x["status"],x["sha256"]) == (y["status"],y["sha256"]), (x,y)
history.save(out / "result.json", result)
