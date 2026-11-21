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
           PATH=str(Path.home() / ".cargo/bin") + ":" + os.environ["PATH"],
           CARGO_HOME=str(registry), CARGO_BUILD_JOBS="8", CARGO_TARGET_DIR=str(target),
           RUSTUP_HOME=str(rustup), RUSTUP_TOOLCHAIN="ohm", CARGO_TERM_COLOR="never")
toolchain = rustup / "toolchains/ohm"
toolchain.parent.mkdir(parents=True)
toolchain.symlink_to(sdk)


def run(*args, **kw):
    return subprocess.run(list(map(str, args)), check=True, **kw)


def install(role):
    if role=="control" and os.environ.get("REPLAY_MODE")in ("stock-codex", "startup-stock"):
        # Use an isolated copy of the official pinned distribution.
        original=Path(subprocess.check_output(["rustup","which","--toolchain","1.100.0","rustc"],text=True).strip()).parent.parent
        shutil.copytree(original,root / role,symlinks=True)
        result["stock"]={tool:history.sha(original/"bin"/tool) for tool in ["rustc","cargo","clippy-driver","rustfmt"]}
        result["stock"]["version"]=subprocess.check_output([original/"bin/rustc","-vV"],text=True)
        return
    tag = "3" if role == "control" and os.environ.get("REPLAY_MODE") != "startup-linker" else "4"
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
    # Exercise normal rustup toolchain selection and Cargo’s compiler path.
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
        profile, p = count("compile", ["cargo","+ohm",*cmd[1:]], directory)
        (directory / "build.log").write_bytes(p.stderr)
        size = int(subprocess.check_output(["du", "-sb", target]).split()[0])
        cache = [f.stat().st_size for f in target.rglob("llvmcache-*") if f.is_file()]
        row = dict(rev=where, lock=lock, command=list(map(str,cmd)), target_bytes=size,
                   identities=sum(1 for f in target.rglob(".ohm-checked-objects-v1")), llvmcache_bytes=sum(cache), llvmcache_files=len(cache), **profile)
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
# An additional controlled comparison isolates the complete production LLVM
# library, keeping every other file in the production -4 SDK byte-identical.
if os.environ.get("REPLAY_MODE") == "llvm-only":
    assert record["kind"] == "llvm"
    stock = root/"control"
    produced = root/"candidate"
    so = Path("lib/libLLVM.so.23.1-rust-dev")
    image = root/"previous-llvm.so"
    (stock/so).rename(image)
    shutil.rmtree(stock)
    shutil.copytree(produced, stock, symlinks=True, copy_function=os.link)
    image.replace(stock/so)
    unchanged = 0
    for file in produced.rglob('*'):
        rel = file.relative_to(produced)
        if file.is_symlink():
            assert os.readlink(file) == os.readlink(stock/rel)
        elif file.is_file() and rel!=so:
            assert os.path.samefile(file, stock/rel)
            unchanged += 1
    result["llvm_only"] = dict(base=result["archive"]["candidate"],control=history.sha(stock/so),
                               candidate=history.sha(produced/so),identical_files=unchanged)

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
    components={'llvm':'lib/libLLVM.so.23.1-rust-dev','cargo':'bin/cargo'}
    env['CARGO_TERM_VERBOSE']='true'
    if kind=='compiler':
        a=root/'control'; b=root/'candidate'
        for file in (a/'bin').iterdir():
            if file.name!='rustc' and (b/'bin'/file.name).exists():shutil.copyfile(b/'bin'/file.name,file)
        file=Path('lib/libLLVM.so.23.1-rust-dev')
        shutil.copyfile(b/file,a/file)
    if kind=='two':
        for role in order:
            (root/role/'lib/librustc_driver-extra.so').touch()
    if kind=='nomono':
        env['RUSTFLAGS']='-Zohm-incremental-mono-partitions=no'
    if kind in components:
        a=root/'control'; b=root/'candidate'; name=components[kind]
        (a/name).rename(root/'kept')
        shutil.rmtree(a)
        shutil.copytree(b,a,symlinks=True,copy_function=os.link)
        (root/'kept').replace(a/name)
        result["swapped"]=name
    work=root/'disk/artifacts'
    env.update(CARGO_TARGET_DIR=str(work/'target'),CARGO_BUILD_BUILD_DIR=str(work/'shared-build'),
               CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST='all',CARGO_HOME=str(root/'disk/registry'))
    if kind in ('noshared','neither'):env.pop('CARGO_BUILD_BUILD_DIR')
    if kind in ('notrust','neither'):env.pop('CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST')
    if kind in ('force3','force4'):
        v=root/('control' if kind=='force3' else 'candidate')/'bin/rustc'
        env['RUSTC_FORCE_RUSTC_VERSION']=subprocess.check_output([v,'--version'],text=True).strip().removeprefix('rustc ')
    if kind=='random':env['RUSTC_FORCE_RUSTC_VERSION']='probe'
    if kind=='untrust':env['CARGO_BUILD_BUILD_DIR']=str(work/'cache')
    if kind=='clone':
        # Both roles use the candidate version but normal Cargo metadata still
        # refers to the compiler's version output. Change only the output path.
        env['CARGO_TARGET_DIR']=str(work/'results')
    if kind=='profile':
        env['CARGO_TERM_VERBOSE']='true'
        perf=next(p for p in [shutil.which('perf'),*Path('/usr/lib/linux-tools').glob('*/perf')]if p and subprocess.run([p,'--version'],capture_output=True).returncode==0)
    result['settings']={k:v for k,v in env.items() if k in ['RUSTC_FORCE_RUSTC_VERSION','CARGO_BUILD_BUILD_DIR','CARGO_TARGET_DIR']}
    # Normalize source once before comparing the two builds.
    (root/'candidate').rename(sdk)
    if not kind.startswith('kit') and kind!='compiler':
        history.command([cargo,*cfg['commands']['fmt']],source,env,out/'fmt.log')
    result['baseline_diff_sha256']=hashlib.sha256(git('diff','--binary').encode()).hexdigest()
    sdk.rename(root/'candidate')
    for role in order:
        (root/role).rename(sdk)
        if work.exists():shutil.rmtree(work)
        folder=out/role
        folder.mkdir()
        history.command([cargo,'fetch','--locked'],source,env,folder/'fetch.log')
        rows={}
        phases=['build','warmup'] if kind=='forward' else ['warmup','first','build','last']
        if kind=='warm':
            orig=cfg['edits']['direct']
            path=source/orig['path'].removeprefix('codex-rs/')
            original=path.read_text()
            history.command([cargo,*cfg['commands']['build'],'--offline'],source,env|{'CARGO_TARGET_DIR':str(work/'prime')},folder/'prime.log')
            shutil.rmtree(work/'prime')
            phases+=['editcheck','editbuild']
        for phase in phases:
            if kind=='nocheck' and phase=='first':continue
            command='build' if phase in ('build','editbuild') else 'check'
            if phase=='editcheck':
                assert original.count(orig['before'])==1
                path=source/orig['path'].removeprefix('codex-rs/')
                path.write_text(original.replace(orig['before'],orig['after']))
            receipt=folder/(phase+'.tsv')
            start_cmd=['cargo','+ohm']if kind=='proxy'else [cargo]
            cmd=[*start_cmd,*cfg['commands'][command],'--offline']
            prior=resource.getrusage(resource.RUSAGE_CHILDREN)
            start=time.perf_counter()
            base=[meter,rustc,receipt,*cmd]
            trace=work/'perf.data'
            if kind=='profile' and phase=='build':
                base=[perf,'record','-e','instructions:u','-c','1000003','-m','128','-o',trace,'--',*base]
            history.command(base,source,env,folder/(phase+'.log'))
            duration=time.perf_counter()-start
            post=resource.getrusage(resource.RUSAGE_CHILDREN)
            if phase in ('build','warmup','editcheck','editbuild'):entries=history.read_counts(receipt)
            else:entries=[]
            n,en,ru=map(int,Path(str(receipt)+".tree").read_text().split())
            assert n and en*.995<=ru<=en
            if kind=='profile' and phase=='build':
                file=folder/'samples'
                with file.open('w')as f:
                    run(perf,'script','-i',trace,'-F','comm,pid,ip,sym,dso',stdout=f)
                run('gzip',file)
                trace.unlink()
            allocated=int(subprocess.check_output(['du','-sB1',work]).split()[0])
            rows[phase]=dict(total=n,en=en,ru=ru,units=entries,wall=duration,
                             user=post.ru_utime-prior.ru_utime,kernel=post.ru_stime-prior.ru_stime,
                             outblock=post.ru_oublock-prior.ru_oublock,minor=post.ru_minflt-prior.ru_minflt,
                             allocated=allocated)
            if phase in ('warmup','build'):
                graphs={}
                for path in work.glob('target/debug/incremental/**/uv-*/s-*/*'):
                    if path.name.endswith('dep-graph.bin'):
                        with path.open('rb') as inp:buf=inp.read(512)
                        pos=7+buf[6]
                        graphs[str(path.relative_to(work))]=[buf[pos:pos+8].hex(),buf[pos+8:pos+16].hex(),path.stat().st_size]
                rows[phase]['graphs']=graphs
            print(role,phase,len(entries),n,duration,flush=True)
        if kind=='warm':
            import shlex
            editpath=source/orig['path'].removeprefix('codex-rs/')
            editpath.write_text(original)
            hashed={}
            suppressed=set()
            for phase in ('prime','warmup','build'):
                text=(folder/(phase+'.log')).read_text()
                suppressed.update(re.findall(r'-Zpublic-api-hash=no --crate-name ([a-zA-Z0-9_]+)',text))
                if phase=='prime':continue
                lib=project.replace('-','_')
                lines=[s for s in text.splitlines() if (' --crate-name '+lib+' ') in s and 'Running 'in s]
                if not lines:continue
                args=shlex.split(lines[-1].split(chr(96))[1])
                files=[b.split('=',1) for a,b in zip(args,args[1:])if a=='--extern' and '=' in b]
                hashed[phase]={}
                for dep,artifact in files:
                    if dep in suppressed and artifact.endswith(('.rmeta','.rlib')) and Path(artifact).is_file():
                        info=subprocess.check_output([rustc,'-Zls=root',artifact],env=env,text=True)
                        hashed[phase][dep]=next((s for s in info.splitlines()if s.startswith(('private hash ','hash '))),None)
            history.save(folder/'hashes.json',dict(suppressed=sorted(suppressed),hashes=hashed))
        result[role]=rows
        history.save(out/"result.json",result)
        sdk.rename(root/role)
    raise SystemExit(0)


if case.startswith("exp-"):
    import resource
    _, project, mode = case.split("-")
    _, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(hard,65536),hard))
    fetch()
    source=src
    if project=="codex":
        tar=root/"allocative-0.3.6.crate"
        run("curl","-fsSL","--retry","4","https://static.crates.io/crates/allocative/allocative-0.3.6.crate","-o",tar)
        helper=wd/"scripts/session_replays/helpers/codex-1.100/prepare.py"
        prep=json.loads(subprocess.check_output(["python3",helper,"--benchmark-root",root,"--codex-source",src,"--archive",tar]))
        assert prep["codex_command_commit"]=="b2159a7308ea2380e3a9d2ca2a7a79218820d21e"
        source=Path(prep["codex_command_source"])/"codex-rs"
        project="codex-core"
        result["prepare"]=prep
    else:
        git("checkout","-q","--detach",record["revs"][0])
    history.calibrate(root,out)
    if mode=="policy":
        file=wd/"keys"/"candidate.tar.zst"
        path=root/"keys"
        path.mkdir()
        run("tar","xf",file,"-C",path)
        desktop=path/"candidate"
        run("sha256sum","-c","manifest.sha256","--quiet",cwd=desktop)
        dest=root/"candidate"
        for f in (dest/"lib").glob("librustc_driver-*.so"):f.unlink()
        shutil.rmtree(dest/"lib/rustlib/x86_64-unknown-linux-gnu/lib")
        shutil.copytree(desktop,dest,dirs_exist_ok=True)
        result["kit"]=history.sha(file)
        result["patch"]=history.sha(dest/"compiler.patch")
    else:assert mode in ("shipped", "reverse")
    work=root/"disk/target"
    env.update(CARGO_TARGET_DIR=str(work),CARGO_HOME=str(root/"disk/registry"))
    for role in order:
        start=root/("candidate" if mode=="policy" else role)
        start.rename(sdk)
        if work.exists():shutil.rmtree(work)
        folder=out/role
        folder.mkdir()
        if mode=='policy':
            env.pop('OHM_ALWAYS_CHECK_KEYS',None)
            if role=='control':env['OHM_ALWAYS_CHECK_KEYS']='1'
            example=fixture(env)
            print(json.dumps(example),flush=True)
            history.save(folder/'fixture.json',example)
        history.command([cargo,"fetch","--locked"],source,env,folder/"fetch.log")
        rows={}
        for phase in (("check","build") if mode=="reverse" else ("build","check")):
            receipt=folder/(phase+".tsv")
            cmd=["cargo","+ohm",phase,"-p",project,"--lib","--locked","--offline"]
            history.command([meter,rustc,receipt,*cmd],source,env,folder/(phase+".log"))
            entries=history.read_counts(receipt)
            n,en,ru=map(int,Path(str(receipt)+".tree").read_text().split())
            assert n and en*.995<=ru<=en
            rows[phase]=dict(total=n,en=en,ru=ru,units=entries)
            print(role,phase,n,flush=True)
        result[role]=rows
        history.save(out/"result.json",result)
        sdk.rename(start)
    raise SystemExit(0)

# Additional matched PMU run of the exact Codex Clippy edit sequence.
def codex_clippy():
    import benchmark
    import resource
    (_,hard)=resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE,(min(hard,65536),hard))
    fetch()
    archive = root/"allocative-0.3.6.crate"
    run("curl","-fsSL","--retry","4","https://static.crates.io/crates/allocative/allocative-0.3.6.crate","-o", archive)
    helper = wd/"scripts/session_replays/helpers/codex-1.100/prepare.py"
    prep=json.loads(subprocess.check_output(["python3",helper,"--benchmark-root",root,"--codex-source",src,"--archive",archive]))
    assert prep["codex_command_commit"]=="b2159a7308ea2380e3a9d2ca2a7a79218820d21e"
    source=Path(prep["codex_command_source"])
    history.save(out/"prepare.json",prep)
    run("just","--version",env=env)
    history.calibrate(root,out)
    workload = benchmark.WORKLOADS["codex-core"]
    cmd = ["just","clippy","-p","codex-core","--locked","--offline"]
    driver=sdk/"bin/clippy-driver"
    if case in ("codex-test","codex-transition"):
        driver=rustc
        cmd=["just","test","-p","codex-core","--lib","--locked","--offline","--no-tests","fail",workload.selected_test]
        env.update(CARGO_TARGET_DIR=str(root/"disk/target"),CARGO_HOME=str(root/"disk/registry"))
    result["command"]=cmd
    for role in order:
        (root / role).rename(sdk)
        env.pop('CARGO_NET_OFFLINE',None)
        work=Path(env["CARGO_TARGET_DIR"])
        if work.exists():shutil.rmtree(work)
        folder=out/role
        folder.mkdir()
        history.command([cargo,"fetch","--locked"],source/"codex-rs",env,folder/"fetch.log")
        env['CARGO_NET_OFFLINE']='true'
        entries=[]
        def capture(phase,iteration):
            label=f"{phase}-{iteration}"
            receipt=folder/(label+".tsv")
            proc=subprocess.run([meter,driver,receipt,*cmd],cwd=source,capture_output=True,env=env)
            log=proc.stdout+proc.stderr
            (folder/(label+".log")).write_bytes(log)
            if proc.returncode:print(log[-2900:].decode(errors="replace"),flush=True)
            assert proc.returncode==0
            units=history.read_counts(receipt)
            count,enabled,running=map(int,Path(str(receipt)+".tree").read_text().split())
            assert count and 0<.995*enabled<=running<=enabled
            stats=dict(phase=phase,i=iteration,total=count,driver=sum(u['instructions'] for u in units),codex_core=sum(u['instructions']for u in units if u['name']=='codex_core'),units=units)
            print(role,label,len(units),stats["total"],flush=True)
            entries.append(stats)
        if case=="codex-transition":
            orig = source
            source=source/"codex-rs"
            cmd=["cargo","+ohm","build","-p","codex-core","--lib","--locked","--offline"]
            capture("build",0)
            cmd[2]="check"
            capture("check",0)
            result[role]=entries
            result["command"]=cmd
            source=orig
            sdk.rename(root/role)
            continue
        capture("cold",0)
        for i in range(3):capture("noop",i)
        for phase,n in [('dependency',7),('direct',5)]:
            if phase=="direct":capture("warmup",0)
            with benchmark.reversible_edit(source,getattr(workload,phase)) as edit:
                for i in range(n):
                    edit(i%2==0)
                    capture(phase,i)
        result[role]=entries
        sdk.rename(root/role)
    history.save(out/"result.json",result)
if case in ("codex-clippy","codex-test","codex-transition"):
    sys.path.insert(0,str(wd/"scripts"))
    codex_clippy()
    raise SystemExit(0)


# PMU counts for the two Codex TUI compiler commands.
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
    history.calibrate(root,out)
    run("cc","-O2","replay/pmuv.c","-o",wd/"meter")
    (_,hard)=resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE,(min(hard,65536),hard))
    tmp=Path('/tmp/o100p4')
    tmp.mkdir(mode=0o700)
    os.environ.update(env)
    os.environ.update(TMPDIR=str(tmp),CARGO_HOME=str(root/'disk/registry'),MEASURE_CLIPPY=str(sdk/"bin/clippy-driver"))
    where=root/"disk/sessions"
    mode=os.environ.get("REPLAY_MODE")
    class Study(r.Replay):
        def environment(self,scenario,label,selector,repetition):
            e=super().environment(scenario,label,selector,repetition)
            if mode=="startup-linker":
                e["CARGO_UNSTABLE_OHM_LINKER"]="lld" if role=="control" else "wild"
            return e
        def command(self,step,selector,directory):
            cmd=super().command(step,selector,directory)
            if step['program']=='cargo' and case=='codex-tui':
                receipt=folder/(step['args'][0]+".tsv")
                return [str(wd/'meter'),str(rustc),str(receipt),*cmd]
            return cmd
    for role in order:
        (root/role).rename(sdk)
        number='3' if role=='control' else '4'
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
        study=Study(r.parser().parse_args(args))
        scenario=study.scenarios[0]
        assert scenario.steps[-2]['args'][0]=='clippy'
        if case=="codex-tui":scenario=dataclasses.replace(scenario,steps=scenario.steps[:-1])
        study.toolchains=((lane,selector),)
        dest=study.prepare_source(scenario)
        run('git','-C',dest,'config','--local','user.email','benchmark@users.noreply.github.com')
        run('git','-C',dest,'config','--local','user.name','Ohm benchmark fixture')
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
        result[role]=dict(sample=sample,tree=tree)
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
    tmp=Path('/tmp/o100p4')
    tmp.mkdir(mode=0o700)
    os.environ.update(env)
    os.environ.update(TMPDIR=str(tmp),CARGO_HOME=str(root/'disk/registry'),MEASURE_CLIPPY=str(sdk/"bin/clippy-driver"))
    where=root/"disk/sessions"
    for role in order:
        (root/role).rename(sdk)
        number='3' if role=='control' else '4'
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
        study=r.Replay(r.parser().parse_args(args))
        scenario=study.scenarios[0]
        study.toolchains=(('ohm',selector),)
        dest=study.prepare_source(scenario)
        run('git','-C',dest,'config','--local','user.email','benchmark@users.noreply.github.com')
        run('git','-C',dest,'config','--local','user.name','Ohm benchmark fixture')
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
        result[role]=dict(sample=sample,tree=tree)
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
