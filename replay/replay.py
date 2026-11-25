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
baseline = "46b6bd8ccc4a776b348832ee6b5ecf04c38886719efbe1a5dafb100744cf7c88"
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


import time
for role in order:install(role)
pilot=result['archive']['control']==result['archive']['candidate']
history.save(out/"result.json",result)
def probes():
    run(sys.executable,wd/'replay/cargocases10.py',pair,root/'control',root/'candidate',out,
        env=dict(os.environ,PILOT=str(int(pilot))))
def locktest(role):
    home=root/(role+"-lock")
    env['CARGO_BUILD_BUILD_DIR']=str(home/'build')
    consumer=home/'consumer'
    for p in [src,consumer]:
        (p/'src').mkdir(parents=True,exist_ok=True)
        (p/'Cargo.toml').write_text('[package]\nname="'+p.name+'"\nversion="0.1.0"\nedition="2024"\n[dependencies]\nadler2="=2.0.1"\n')
        (p/'src/lib.rs').write_text('pub use adler2::Adler32;')
    (src/'build.rs').write_text('fn main(){std::fs::write("started","").unwrap(); std::thread::sleep(std::time::Duration::from_secs(5)); if std::env::var_os("BREAK_BUILD").is_some(){panic!("deliberate")} }')
    for p in [src,consumer]:run(cargo,"fetch",env=env,cwd=p)
    rows=[]
    for fail in (False,True):
        started=src/"started";started.unlink(missing_ok=True)
        suffix=str(int(fail))
        shared=dict(env,CARGO_BUILD_BUILD_DIR=str(home/("shared"+suffix)))
        folder=out/role/suffix;folder.mkdir(parents=True)
        producer_env=shared|{"CARGO_TARGET_DIR":str(home/("producer"+suffix))}
        if fail:producer_env['BREAK_BUILD']='yes'
        args=["build","--locked","--offline","-v","--message-format=json"]
        with open(folder/'producer','w') as output, open(folder/'producer.log','w') as err:
            p=subprocess.Popen([cargo,*args],env=producer_env,cwd=src,stdout=output,stderr=err)
            now=time.monotonic()
            while not started.exists() or '"name":"adler2"' not in (folder/'producer').read_text():
                if p.poll()!=None or time.monotonic()-now>40:raise AssertionError((folder/'producer.log').read_text())
                time.sleep(.02)
            a=time.monotonic()
            c=run(cargo,*args,env=shared|{"CARGO_TARGET_DIR":str(home/("user"+suffix))},cwd=consumer,capture_output=True,text=True,timeout=45)
            elapsed=time.monotonic()-a
            overlap=p.poll() is None
            code=p.wait(timeout=20)
            assert code==(101 if fail else 0)
        (folder/'consumer.log').write_text(c.stdout+c.stderr)
        one,=[row for row in map(json.loads,c.stdout.splitlines()) if row.get('target',{}).get('name')=='adler2']
        assert one['fresh'], (role,c.stderr)
        if role=='candidate' and not pilot:assert overlap,(role,c.stderr)
        rows.append(dict(fail=fail,elapsed=elapsed,overlap=overlap,fresh=one['fresh']))
    print(role,rows,flush=True)
    return rows
def sequence(role,variant):
    if target.exists():shutil.rmtree(target)
    folder=out/variant;folder.mkdir(exist_ok=True)
    opt=(variant=="opt" and not pilot)
    if opt: env['CARGO_UNSTABLE_OHM_TERMINAL_CHECKS']="true"
    else:env.pop("CARGO_UNSTABLE_OHM_TERMINAL_CHECKS",None)
    app=record['package']
    rows=[]
    def launch(phase,args):
        cmd=["cargo","+ohm",*args,"--locked","--offline"]
        start=time.perf_counter()
        numbers,p=count(phase,cmd,folder)
        elapsed=time.perf_counter()-start
        (folder/(phase+'.log')).write_bytes(p.stderr)
        row=dict(name=phase,command=cmd,wall=elapsed,rev=rev,lock=lock,
            output=hashlib.sha256(p.stdout).hexdigest(),
            warnings=sorted(l for l in p.stderr.decode().splitlines()if l.startswith("warning:")),
            only="-Zohm-check-only --emit=dep-info" in p.stderr.decode(),**numbers)
        rows.append(row)
        history.save(folder/'partial.json',rows)
        print(variant,phase,numbers,row["only"],flush=True)
        return p
    previous=''
    for i,rev in enumerate(record["revs"]):
        git("checkout","-q","--detach",rev)
        assert git("rev-parse","HEAD")==rev
        lock=history.sha(src/"Cargo.lock")
        if lock!=previous:run(cargo,"fetch","--locked",cwd=src,env=env,stderr=subprocess.DEVNULL)
        previous=lock
        phase="cold"if not i else "edit"+str(i)
        launch(phase,["check","-v","-p",app])
        if not i:assert rows[-1]["only"]==opt,(variant,phase,rows[-1])
        if i and record["request"]and (record["request"]=="repeat"or i==2):
            launch("request"+str(i),["rustc","--profile","check","--lib","-v","-p",app])
            launch("noop"+str(i),["check","-v","-p",app])
    if app=="ruff_linter":
        for i in range(3):
            launch("metadata"+str(i),["metadata","--format-version=1"])
    launch("final",["check","--lib","-p",app,"--message-format=json"])
    assert any(target.rglob("lib"+app+"*.rmeta"))
    return rows
if case=='cargo-probes':
    probes()
elif case=='cargo-lock':
    for role in order:
        (root/role).rename(sdk)
        result[role]=locktest(role)
        sdk.rename(root/role)
else:
    run("git","init","-q",src)
    run("git","-C",src,"fetch","-q","--depth=2","https://github.com/"+record['repo']+".git",*dict.fromkeys(record["revs"]))
    history.calibrate(root,out)
    variants=['control','candidate','opt'][::1 if int(pair)%2 else -1]
    for variant in variants:
        role='candidate' if variant=='opt' else variant
        (root/role).rename(sdk)
        result[variant]=sequence(role,variant)
        sdk.rename(root/role)
        history.save(out/"result.json",result)
    for x,y,z in zip(*(result[k] for k in variants),strict=True):
        for k in ('command','rev','lock','warnings','name'):
            assert x[k]==y[k]==z[k],(case,k,x[k],y[k],z[k])
        if x['name'].startswith('metadata'):assert x['output']==y['output']==z['output']
history.save(out/'result.json',result)
