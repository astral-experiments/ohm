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
expected_sdk = {'control': '46b6bd8ccc4a776b348832ee6b5ecf04c38886719efbe1a5dafb100744cf7c88', 'candidate': 'a7478c768cb329d97dca35bc1fd8cd463780d0ed7432ef6310383ed383625079'}
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
    tag = "9" if role == "control" else "10"
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


for role in order:
    install(role)
# Use the frozen sessions with no counter or command wrapper.
def tui_session():
    import replay_sessions as r
    import dataclasses,resource
    fetch()
    base="74004b5397b24662a87a5264a6ae80664168c7f3"
    tip="3d7bb2dd2e834b4d26cf29a7c0163dd4fb5afb70"
    git("checkout","-q","--detach",base)
    git("update-ref","refs/heads/edits",tip)
    crate=root/"allocative.crate"
    run("curl","-fsSL","--retry","4","https://static.crates.io/crates/allocative/allocative-0.3.6.crate","-o",crate)
    fixture=wd/"scripts/session_replays/codex-rust-1.100.json"
    helper=fixture.parent/"helpers/codex-1.100/prepare.py"
    p=subprocess.check_output(["python3",helper,"--benchmark-root",root,"--codex-source",src,"--archive",crate])
    (out/"prepare.json").write_bytes(p)
    assert history.sha(fixture)=="f2d9c9b29ca5e81f39a3683aefe8e541c50e1100a0b43c32c9f8ac157e276084"
    (_,hard)=resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE,(min(hard,65536),hard))
    tmp=Path('/tmp/o100pa')
    tmp.mkdir(mode=0o700)
    os.environ.update(env)
    os.environ.update(TMPDIR=str(tmp),CARGO_HOME=str(root/'disk/registry'))
    where=root/"disk/sessions"
    mode=os.environ.get("REPLAY_MODE")
    class Timed(r.Replay):
        def environment(self,*args,**kwargs):
            env=super().environment(*args,**kwargs)
            self.policy=dict(macro=env.get('CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST'),
                             native=env.get('CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST'),
                             shared=bool(env.get('CARGO_BUILD_BUILD_DIR')))
            return env

    for role in order:
        (root/role).rename(sdk)
        number='9' if role=='control' else '10'
        upstream=role=="control" and os.environ.get("REPLAY_MODE")in ("stock-codex", "startup-stock")
        lane="stock" if upstream else "ohm"
        selector="1.100.0" if upstream else "ohm-1.100.0-"+number
        if mode=="startup-linker":selector="ohm-1.100.0-4-"+role
        (toolchain.parent/selector).symlink_to(sdk)
        folder=out/role
        folder.mkdir()
        os.environ['RUSTUP_TOOLCHAIN']=selector
        history.command([cargo,"fetch","--locked"],src/"codex-rs",os.environ,folder/"fetch.log")
        args=['--upstream','1.100.0','--ohm',selector,'--jobs','8','--minimum-free-gb','1',
                '--output-dir',str(where),'--project','codex','--repetitions','1','--offline',
                '--scenario',str(fixture),'--source-path','codex='+str(src)]
        if case=='codex-tui-time':args+=['--require-idle']
        study=Timed(r.parser().parse_args(args))
        scenario=study.scenarios[0]
        assert scenario.steps[-2]['args'][0]=='clippy'
        if case=="codex-tui":scenario=dataclasses.replace(scenario,steps=scenario.steps[:-1])
        study.toolchains=((lane,selector),)
        dest=study.prepare_source(scenario)
        run('git','-C',dest,'config','--local','user.email','charlie.r.marsh@gmail.com')
        run('git','-C',dest,'config','--local','user.name','Charlie Marsh')
        study.sources['codex']=dest
        study.persist()
        try:
            sample=study.run_session(scenario,lane,selector,0)
        finally:
            if (where/'logs').exists():shutil.copytree(where/'logs',folder/'logs')
        co=Path(sample['worktree'])
        run('git','-C',co,'add','-A')
        tree=subprocess.check_output(['git','-C',co,'write-tree'],text=True).strip()
        assert tree=='110e0e8c2bcbab10e2429262c697d071d50fdfe5',tree
        result[role]=dict(sample=sample,tree=tree,fixture=history.sha(fixture),
            head=history.git(co,'rev-parse','HEAD').decode().strip(),
            lock=history.sha(co/('codex-rs/Cargo.lock' if case=='codex-tui-time' else 'Cargo.lock')),
            policy=study.policy,cargo=history.sha(cargo),rustc=history.sha(rustc))
        history.save(out/'result.json',result)
        if mode.startswith('startup-'):
            import elfprobe
            result[role]["binary"]=elfprobe.capture(where,role,root)
            history.save(out/'result.json',result)
        shutil.rmtree(where)
        sdk.rename(root/role)
    if mode.startswith('startup-'):
        result['process']=elfprobe.times(root)
        history.save(out/'result.json',result)

def session_time():
    import replay_sessions as r
    import resource
    fetch()
    git("checkout","-q","--detach",record["head"])
    for i,revision in enumerate(record['revs']):
        git("update-ref","refs/heads/charlie/fixture-"+str(i),revision)
    fixture=wd/"scripts/session_replays"/(record["fixture"]+".json")
    result["fixture"]=history.sha(fixture)
    app=record["app"]
    (_,hard)=resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE,(min(hard,65536),hard))
    tmp=Path('/tmp/o100pa')
    tmp.mkdir(mode=0o700)
    os.environ.update(env)
    os.environ.update(TMPDIR=str(tmp),CARGO_HOME=str(root/'disk/registry'))
    where=root/"disk/sessions"

    class Timed(r.Replay):
        def environment(self,*args,**kwargs):
            env=super().environment(*args,**kwargs)
            self.policy=dict(macro=env.get('CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST'),
                             native=env.get('CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST'),
                             shared=bool(env.get('CARGO_BUILD_BUILD_DIR')))
            return env

    for role in order:
        (root/role).rename(sdk)
        number='9' if role=='control' else '10'
        selector="ohm-1.100.0-"+number
        (toolchain.parent/selector).symlink_to(sdk)
        folder=out/role
        folder.mkdir()
        os.environ['RUSTUP_TOOLCHAIN']=selector
        history.command([cargo,"fetch","--locked"],src,os.environ,folder/"fetch.log")
        args=['--upstream','1.100.0','--ohm',selector,'--jobs','8','--minimum-free-gb','1',
                '--output-dir',str(where),'--project',app,'--repetitions','1','--offline',
                '--scenario',str(fixture),'--source-path',app+'='+str(src)]
        args+=['--require-idle']
        if case=='session-ty':args+=['--compiler-accounting','verbose','--native-tool-trust','all']
        study=Timed(r.parser().parse_args(args))
        scenario=study.scenarios[0]
        study.toolchains=(('ohm',selector),)
        dest=study.prepare_source(scenario)
        run('git','-C',dest,'config','--local','user.email','charlie.r.marsh@gmail.com')
        run('git','-C',dest,'config','--local','user.name','Charlie Marsh')
        study.sources[app]=dest
        study.persist()
        try:
            sample=study.run_session(scenario,'ohm',selector,0)
        finally:
            if (where/'logs').exists():shutil.copytree(where/'logs',folder/'logs')
        co=Path(sample['worktree'])
        run('git','-C',co,'add','-A')
        tree=subprocess.check_output(['git','-C',co,'write-tree'],text=True).strip()
        assert tree==record['expected'],tree
        result[role]=dict(sample=sample,tree=tree,fixture=history.sha(fixture),
            head=history.git(co,'rev-parse','HEAD').decode().strip(),
            lock=history.sha(co/('codex-rs/Cargo.lock' if case=='codex-tui-time' else 'Cargo.lock')),
            policy=study.policy,cargo=history.sha(cargo),rustc=history.sha(rustc))
        history.save(out/'result.json',result)
        shutil.rmtree(where)
        sdk.rename(root/role)

if case.startswith('session-'):
    sys.path.insert(0,str(wd/"scripts"))
    session_time()
    raise SystemExit(0)
if case in ("codex-tui","codex-tui-time"):
    sys.path.insert(0,str(wd/"scripts"))
    tui_session()
    raise SystemExit(0)



raise ValueError(case)
