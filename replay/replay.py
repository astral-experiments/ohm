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
baseline = "154ac544e2b0e3f6d6a123d786f9d72e114a3453b077eccaad62ae03737abac1"
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
    tag = "7" if role == "control" else "8"
    kit = wd / "kits" / tag
    archive, = kit.rglob("*.tar.gz")
    h = history.sha(archive)
    result["archive"][role] = h
    if tag == "7":
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


def count(name, command, directory, allowed=(0,)):
    receipt = directory / (name + ".tsv")
    timecmd = ["/usr/bin/time","-f","%M","-o",receipt.with_suffix(".rss")] if Path("/usr/bin/time").exists() else []
    p = subprocess.run([*timecmd, meter, rustc, receipt, *command],
                       cwd=src, capture_output=True, env=env)
    if p.returncode not in allowed:
        print(p.stdout[-800:].decode(errors="replace"), p.stderr[-2800:].decode(errors="replace"), flush=True)
        raise RuntimeError((command, p.returncode))
    counts = history.read_counts(receipt)
    total = int(Path(str(receipt) + ".tree").read_text().split()[0])
    return dict(instructions=total, jobs=len(counts), rustc=sum(c["instructions"] for c in counts)), p


# Uses the pinned replay bootstrap through count().
import time

def normalize():
    # Older ripgrep manifests repeat their repository URL as a homepage,
    # provoking a manifest warning. Use the upstream-equivalent cleanup.
    if record["app"] == "ripgrep":
        for path in src.rglob("Cargo.toml"):
            before = path.read_text()
            after = re.sub(r'^homepage = "(.*)"\n',
                lambda m: "" if 'repository = "'+m[1]+'"' in before else m[0],
                before, flags=re.M)
            if before != after:
                path.write_text(after)
    return hashlib.sha256(history.git(src,"diff","--binary")).hexdigest()

def metadata():
    return {str(p.relative_to(target)):history.sha(p) for p in target.rglob("lib*.rmeta")
            if re.match(r"lib(?:grep\w*|globset|ignore|rg)-",p.name)}

def warnings(p):
    return sorted(line for line in p.stderr.decode().splitlines() if line.startswith("warning:"))

def replay(role):
    (root / role).rename(sdk)
    if target.exists():shutil.rmtree(target)
    folder = out / role
    folder.mkdir()
    app = record["app"]
    command=["cargo","+ohm","check","--locked","--offline","-p",app]
    if app == "ruff": command+=["--bin",app]
    rows=[]
    prev=None
    for i, rev in enumerate(record["revs"]):
        print(role, i, rev, flush=True)
        git("checkout", "-q", "--detach", rev)
        assert git("rev-parse","HEAD")==rev
        diff=normalize()
        lock = history.sha(src / "Cargo.lock")
        if lock != prev:
            history.command([cargo, "fetch", "--locked", "--target", "x86_64-unknown-linux-gnu"],
                            src, env, folder / ("fetch-" + str(i) + ".log"))
        prev = lock
        directory = folder / str(i)
        directory.mkdir()
        start=time.perf_counter()
        totals,p = count("compile",command,directory)
        elapsed=time.perf_counter()-start
        (directory/"build.log").write_bytes(p.stderr)
        size=int(subprocess.check_output(["du","-sb",target]).split()[0])
        rows.append(dict(rev=rev,lock=lock,command=command,manifest_diff=diff,
                         warnings=warnings(p),target_bytes=size,wall=elapsed,**totals))
        print(totals,elapsed,flush=True)
        history.save(folder/"rows.json",rows)
    counts,p=count("noop",command,folder)
    assert not counts["jobs"],counts
    if app=="ripgrep":
        warm=metadata()
        # Keep precisely the same registry inputs, including proc-macro build
        # outputs. Rebuild every local package from scratch at the same path.
        args=["cargo","+ohm"]
        pkgs=json.loads(subprocess.check_output(
            args+["metadata","--locked","--offline","--no-deps","--format-version=1"],cwd=src,env=env))["packages"]
        run(*args,"clean","--locked","--offline",*(k for pkg in pkgs for k in ("-p",pkg["name"])),cwd=src,env=env)
        assert not metadata(), list(metadata())
        counts,p=count("fresh",command,folder)
        (folder/"fresh.log").write_bytes(p.stderr)
        fresh=metadata()
        assert fresh and warm
        changed=sorted(k for k in fresh if warm.get(k)!=fresh[k])
        print("final workspace metadata differs at",changed,flush=True)
        history.save(folder/"metadata.json",dict(warm=warm,fresh=fresh,changed=changed,clean_workspace=True))
        assert warnings(p)==rows[-1]["warnings"]
    sdk.rename(root / role)
    return rows

for role in order:
    install(role)
history.save(out/"inputs.json",result)
if case=="probes":
    # Install the same pinned third-party autofix frontend once with −7.
    (root/"control").rename(sdk)
    helpers=root/"helpers"
    run("cargo","+ohm","install","--locked","--debug","--version","=0.1.17",
        "--root",helpers,"cargo-fixit",env=env,cwd=root)
    result["fixit_sha256"]=history.sha(helpers/"bin/cargo-fixit")
    run("rustup","toolchain","install","1.100.0","--profile","minimal","--no-self-update",env=env,cwd=root)
    stock=Path(subprocess.check_output(["rustup","which","--toolchain","1.100.0","rustc"],
                                       env=env,cwd=root,text=True).strip())
    result["stock_rustc_sha256"]=history.sha(stock)
    sdk.rename(root/"control")
    run(sys.executable,wd/"replay/probes8.py",pair,root/"control",root/"candidate",out,
        env=dict(os.environ,PROBE_STOCK=str(stock),PATH=str(helpers/"bin")+":"+os.environ["PATH"],TMPDIR=str(root)))
else:
    run("git","init","-q",src)
    remote="https://github.com/"+record["repo"]+".git"
    revs=list(dict.fromkeys(record["revs"]))
    run("git","-C",src,"fetch","-q","--depth=2",remote,*revs)
    history.calibrate(root,out)
    for role in order:
        result[role]=replay(role)
    for r,s in zip(result["control"],result["candidate"],strict=True):
        for key in ("rev","lock","manifest_diff","command","warnings"):
            assert r[key]==s[key],(key,r[key],s[key])
history.save(out/"result.json",result)
