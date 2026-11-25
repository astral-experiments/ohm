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
expected_sdk = {'control': 'a7478c768cb329d97dca35bc1fd8cd463780d0ed7432ef6310383ed383625079', 'candidate': '1a76ab85a726f215ca3a1de0ca0de99ba0fc30625ee6c42e63023922c3c2fd79'}
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
    tag = "10" if role == "control" else "11"
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
import resource
sequence=[(role,policy) for policy in ["audited","all"] for role in ["control","candidate"]]
if int(pair)==2:sequence.reverse()
def cpu():
    res=resource.getrusage(resource.RUSAGE_CHILDREN)
    return res.ru_utime+res.ru_stime
for i in range(7):
    for role,policy in sequence if i%2 else reversed(sequence):
        log=out/f'{role}-{policy}-{i}.log'
        verbose=i==6
        folder=target/(role+'-'+policy)
        e=dict(env,CARGO_TARGET_DIR=str(folder))
        if policy=="all":e["CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST"]="all"
        with log.open('wb') as f:
            c=cpu()
            start=time.perf_counter()
            run("cargo", "+ohm-"+role,*record['cargo_args'], *(['-v'] if verbose else []), env=e,cwd=src,stdout=f,stderr=subprocess.STDOUT)
            seconds=time.perf_counter()-start
            elapsed=cpu()-c
        text=log.read_text()
        tests=bench["test_inventory"](text)
        sig=hashlib.sha256((json.dumps(tests,indent=2)+'\n').encode()).hexdigest()
        assert sig==record["tests_sha256"],(role,i,sig)
        docs=[line for line in text.splitlines() if 'Running 'in line and re.search(r'(?:/|\x60)rustdoc\s',line) and ' --test ' in line]
        size=int(subprocess.check_output(['du','-sb',str(folder)]).split()[0]) if verbose else None
        result['runs'].append(dict(round=i,role=role,policy=policy,seconds=seconds,cpu=elapsed,docs=len(docs) if verbose else None,target_bytes=size,tests_sha256=sig))
        history.save(out/'summary.json',result)
