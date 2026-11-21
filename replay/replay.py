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
baseline = "6948ffc7d33b245bf48fdf770b5913cd536e71aec40a0ea280bd0eb33d4524b8"
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
           PATH=str(Path.home() / ".cargo/bin") + ":" + os.environ["PATH"],
           CARGO_HOME=str(registry), CARGO_BUILD_JOBS="8", CARGO_TARGET_DIR=str(target),
           RUSTUP_HOME=str(rustup), RUSTUP_TOOLCHAIN="ohm", CARGO_TERM_COLOR="never")
toolchain = rustup / "toolchains/ohm"
toolchain.parent.mkdir(parents=True)
toolchain.symlink_to(sdk)


def run(*args, **kw):
    return subprocess.run(list(map(str, args)), check=True, **kw)


def install(role):
    tag = "4" if role == "control" else "5"
    kit = wd / "kits" / tag
    archive, = kit.rglob("*.tar.gz")
    h = history.sha(archive)
    result["archive"][role] = h
    if tag == "4":
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
    if case=='uv-shared':os.environ['BENCH_SHARED_ROOT']=str(root/'study-shared')
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
    app = "test" if record["kind"]=="test" else record["app"]
    if app == "ruff":
        commands = [["check", "--isolated", "--no-cache", "--select", "ALL",
                     "--output-format", "json", str(corpus)],
                    ["format", "--isolated", "--no-cache", "--diff", str(corpus)], ["--version"], ["rule","--all"]]
    elif app == "ty":
        commands = [["check", "--output-format", "concise", str(corpus)], ["--version"]]
    else:
        listing = subprocess.check_output([binary, "--list"], cwd=src, env=env, text=True)
        names = [line[:-6] for line in listing.splitlines() if line.endswith(": test")]
        assert names or app == "test", listing[:160]
        commands = [["--list"]] if app=="test" else [["--list"], ["--test-threads=1", "--exact", *names[:12]]]
    rows = []
    for i, args in enumerate(commands):
        profile, p = count("runtime-" + str(i), [binary, *args], directory, (0, 1))
        output = p.stdout + b"\0" + p.stderr
        if app == "ruff" and i == 0:
            assert len(json.loads(p.stdout)) > 10
        if app == "ty" and i==0:
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
    # Exercise normal rustup toolchain selection and Cargo’s compiler path.
    folder = out / role
    folder.mkdir()
    app = record["app"]
    if record["kind"] == "check":
        cmd = [cargo, "check", "--locked", "--offline", "-p", app]
    elif record["kind"] == "macro":
        cmd = [cargo,"build","--lib","--locked","--offline","-p",app]
    elif record["kind"] == "test":
        cmd = [cargo,"test","--no-run","--locked","--offline","--bin",app,"-p",app]
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
        profile, p = count("compile", ["cargo","+ohm",*cmd[1:]], directory)
        (directory / "build.log").write_bytes(p.stderr)
        size = int(subprocess.check_output(["du", "-sb", target]).split()[0])
        cache = [f.stat().st_size for f in target.rglob("llvmcache-*") if f.is_file()]
        row = dict(rev=where, lock=lock, command=list(map(str,cmd)), target_bytes=size,
                   identities=sum(1 for f in target.rglob(".ohm-checked-objects-v1")), llvmcache_bytes=sum(cache), llvmcache_files=len(cache), **profile)
        if record["kind"] not in ("check","macro"):
            if app == "ty_python_semantic" or record["kind"]=="test":
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
if os.environ.get('REPLAY_MODE')=='subset' or os.environ.get('REPLAY_MODE','').startswith('dev-keys'):
    shutil.rmtree(root/'control')
    shutil.copytree(root/'candidate',root/'control',symlinks=True)
    for role in order:
        file=wd/'trial'/role/'candidate.tar.zst'
        path=root/('kit-'+role)
        path.mkdir()
        run('tar','xf',file,'-C',path)
        kit=path/'candidate'
        run('sha256sum','-c','manifest.sha256','--quiet',cwd=kit)
        dest=root/role
        for binary in (dest/'lib').glob('librustc_driver-*.so'):binary.unlink()
        shutil.rmtree(dest/'lib/rustlib/x86_64-unknown-linux-gnu/lib')
        shutil.copytree(kit,dest,dirs_exist_ok=True)
        result['kit-'+role]=history.sha(file)
if case.startswith("exp-dev"):
    import resource,time
    _,part,kind=case.split('-')
    cfg=record['dev']
    env.update(cfg['environment'])
    project=cfg['package']
    source=src
    _,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE,(min(hard,65536),hard))
    fetch()
    if part!='devcodex':git('checkout','-q','--detach',cfg['revision'])
    if part=="devcodex":
        tar=root/"allocative-0.3.6.crate"
        run("curl","-fsSL","--retry","4","https://static.crates.io/crates/allocative/allocative-0.3.6.crate","-o",tar)
        helper=wd/"scripts/session_replays/helpers/codex-1.100/prepare.py"
        prep=json.loads(subprocess.check_output(["python3",helper,"--benchmark-root",root,"--codex-source",src,"--archive",tar]))
        assert prep["codex_command_commit"]=="b2159a7308ea2380e3a9d2ca2a7a79218820d21e"
        source=Path(prep["codex_command_source"])/"codex-rs"
        project="codex-core"
        result["prepare"]=prep
    history.calibrate(root,out)
    work=root/'disk/artifacts'

    env.update(CARGO_TARGET_DIR=str(work/'target'),CARGO_HOME=str(root/'disk/registry'))
    counter=root/'sessionmeter'
    run('cc','-O2',wd/'replay/sessionmeter.c','-o',counter)
    run(counter,out/'complete.count',root/'exercise','10000001',root/'excluded')
    reference=int((out/'calibration-10000001.tsv.tree').read_text().split()[0])
    assert abs(int((out/'complete.count').read_text().split()[0])/reference-1)<.005
    result['tree']=subprocess.check_output(['git','-C',source,'rev-parse','HEAD^{tree}']).decode().strip()
    result['version']=subprocess.check_output(['git','-C',source,'rev-parse','HEAD']).decode().strip()
    assert result['version']==cfg['revision']
    for role in order:
        (root/role).rename(sdk)
        if work.exists():shutil.rmtree(work)
        folder=out/role
        folder.mkdir()
        history.command([cargo,'fetch','--locked'],source,env,folder/'fetch.log')
        rows={}
        for phase in ('build','check'):
            receipt=folder/(phase+'.count')
            cmd=['cargo','+ohm',*cfg['commands'][phase],'--offline']
            start=time.perf_counter()
            history.command([counter,receipt,*cmd],source,env,folder/(phase+'.log'))
            duration=time.perf_counter()-start
            n,en,ru=map(int,receipt.read_text().split())
            assert n>0 and en*.995<=ru<=en
            assert (work/'target/.ohm-built-registry-ready').is_file()
            rows[phase]=dict(instructions=n,wall=duration,enabled=en,running=ru,args=cmd)
            print(role,phase,n,duration,flush=True)
        result[role]=rows
        history.save(out/'result.json',result)
        sdk.rename(root/role)
