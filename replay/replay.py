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
expected_sdk = {'control': 'edf11cc5fb3448edc2bcf4a530c46b539d0a3a83c0fac2482cfa8639bdedae66', 'candidate': '154ac544e2b0e3f6d6a123d786f9d72e114a3453b077eccaad62ae03737abac1'}
order = ["control", "candidate"] if int(pair) % 2 else ["candidate", "control"]
src = root / "source"
target = root / "target"
sdk = root / "installed"
cargo = sdk / "bin/cargo"
rustc = sdk / "bin/rustc"
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
    tag = "6" if role == "control" else "7"
    kit = wd / "kits" / tag
    archive, = kit.rglob("*.tar.gz")
    h = history.sha(archive)
    result["archive"][role] = h
    assert h == expected_sdk[role]
    run("tar", "xzf", archive, "-C", root)
    tree = root / "rust-1.100.0-dev-x86_64-unknown-linux-gnu"
    run("sh", tree / "install.sh", "--prefix=" + str(root / role),
        "--disable-ldconfig", "--without=rust-docs", stdout=subprocess.DEVNULL)
    shutil.rmtree(tree)


import time,statistics,runpy
for role in order:
    install(role)
    (rustup / 'toolchains' / ('ohm-'+role)).symlink_to(root/role)
run('git','init','-q',src)
run('git','-C',src,'fetch','--quiet','--depth','1','https://github.com/astral-sh/ruff',record["revision"])
run('git','-C',src,'checkout','-q','--detach',record["revision"])
bench=runpy.run_path("scripts/benchmark_ruff_doctests.py")
assert record["revision"]==bench["RUFF_REVISION"]
env.pop('CARGO_BUILD_JOBS')
env.pop('RUSTUP_TOOLCHAIN')
result['runs']=[]
for role in order:
    run('cargo','+ohm-'+role,'fetch','--locked','--target','x86_64-unknown-linux-gnu',env=env,cwd=src,stderr=subprocess.DEVNULL)
for i in range(5):
    for role in order if i!=2 else reversed(order):
        log=out/f'{role}-{i}.log'
        verbose=i==4
        e=dict(env,CARGO_TARGET_DIR=str(target / role))
        with log.open('wb') as f:
            start=time.perf_counter()
            run("cargo", "+ohm-"+role, *record['cargo_args'], *(['-v'] if verbose else []), env=e, cwd=src, stdout=f, stderr=subprocess.STDOUT)
            duration=time.perf_counter()-start
        text=log.read_text()
        tests=bench["test_inventory"](text)
        sig=hashlib.sha256((json.dumps(tests,indent=2)+'\n').encode()).hexdigest()
        assert sig==record["tests_sha256"],(role,i,sig)
        crate=None; docs=[]
        for line in text.splitlines():
            if m:=re.match(r'\s*Doc-tests (\w+)',line):crate=m[1]
            if 'Running `' in line and re.search(r'(?:/|`)rustdoc\s',line):docs.append(crate)
        result['runs'].append(dict(round=i,role=role,seconds=duration,docs=docs if verbose else None,tests_sha256=sig))
        print(role,i,duration,docs,flush=True)
        history.save(out/'summary.json',result)
for role in order:
    result[role]=statistics.median(x['seconds'] for x in result['runs'] if x['role']==role and x['round'] in [1,2,3])
history.save(out/'summary.json',result)
lines=[]
for outpath in (target/'candidate').rglob('output'):
    if outpath.is_file():
        lines.extend(line for line in outpath.read_text(errors="replace").splitlines() if 'rustc-link-search' in line)
history.save(out/'search.json',lines)
for pkg in bench["PACKAGES"]:
    with (out/(pkg+'.tree')).open('w')as f:
        subprocess.run(['cargo','+ohm-candidate','tree','--locked','--offline','--all-features','-p',pkg,'-e','normal,dev','--prefix','depth'],env=env,cwd=src,stdout=f)
