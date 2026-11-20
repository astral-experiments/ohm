"""Measure the two complete qualification SDKs on selected source histories."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from diagnostics import normalize
import codex
from run import calibrate, command, git, read_counts, run as history, save, sha

ROOT = Path(os.environ["RUNNER_TEMP"])
OUT = ROOT / "results"
SOURCE = Path.cwd() / "source"
KITS = ROOT / "sdks"
SCRATCH = ROOT / "work"
TRIAL = SCRATCH / "trial"
CASE = os.environ["WORKLOAD"]
PAIR = int(os.environ["PAIR"])
BASE_RUN = os.getenv('BASE_RUN')
PROBE_RUN = os.getenv('PROBE_RUN')
PROBE = os.getenv('PROBE')
BASELINE = os.environ["BASELINE_ONLY"] == "true"
UPDATE = "99a766b1e1a2d674cae961cefc44c139fa57f12f"
CODEX = json.loads((codex.KIT / "codex-edits.json").read_text())
CLIENT = CASE == 'mixed'
PACKAGE = 'uv-client' if CLIENT else 'codex-tui'
JOBS = 6


def install(role):
    kit = KITS / role
    (archive,) = (ROOT / role).rglob("*.tar.gz")
    sha_file = archive.with_name(archive.name + ".sha256")
    digest = sha(archive)
    assert digest == sha_file.read_text().split()[0], (digest, sha_file)
    if role == "control":
        assert digest == "a6a1621e4581940e93ff7f9720b6102f6589185539650633a4235410f0bbd26d"
    unpack = ROOT / "unpack"
    unpack.mkdir()
    subprocess.run(["tar", "-xzf", archive, "-C", unpack], check=True)
    (prefix,) = unpack.iterdir()
    subprocess.run([prefix / "install.sh", "--disable-ldconfig", f"--prefix={kit}"], check=True)
    shutil.rmtree(unpack)
    archive.unlink()
    bins = [kit / 'bin' / name for name in ('rustc','cargo','clippy-driver')]
    bins.extend((kit / 'lib').glob('librustc_driver*.so'))
    proof = json.loads(next((ROOT / role).rglob('*-provenance.json')).read_text())
    save(OUT / (role + '-sdk.json'), dict(archive=digest,proof=proof,binaries={p.name:sha(p) for p in bins}))


def install_probe(role, name):
    path = ROOT / 'probes' / ('sdk-' + name)
    packed = 'candidate' if BASE_RUN else name
    archive = path / (packed + '.tar.zst')
    subprocess.run(['tar','-xf',archive],cwd=path,check=True)
    kit = KITS / role
    (path / packed).rename(kit)
    subprocess.run(['sha256sum','--check','--quiet','manifest.sha256'],cwd=kit,check=True)
    stock = KITS / 'stock'
    for p in stock.rglob('*'):
        if p.name in ('wild','cargo','rust-lld','rust-wild','ld.lld','gcc-ld') and p.is_file():
            dest = kit / p.relative_to(stock)
            dest.parent.mkdir(exist_ok=True,parents=True)
            shutil.copy2(p,dest)
    rev=(kit/'revision').read_text().strip()
    if BASE_RUN:
        rev={
          'b2b6232d27b9075cfbce01dab3913f6b69fece21b2fbe85f87c3efe41b0a4a38':'940ecb5927a5eaa4c0d557294d6cfd3df4210971',
          'd7f4acb064302903f09ae6bf5fbefda47081411e4e6289f50b09901fffcb0d7a':'5f6e2050215d0863b39669e8b01b982c10c3bfe2',
        }[sha(kit/'compiler.patch')]
    runid=BASE_RUN if BASE_RUN and role=='control' else PROBE_RUN
    save(OUT/(role+'-sdk.json'),dict(probe_run=runid, archive=sha(archive),
         rust=rev, manifest=sha(kit/'manifest.sha256'),
         patch=sha(kit/'compiler.patch'),cargo=sha(kit/'bin/cargo')))
    archive.unlink()


def count(argv, cwd, env, out, metadata=True):
    out.mkdir(parents=True)
    units = out / 'units.tsv'
    runnable = [SCRATCH/'meter', TRIAL/'sdk/bin/rustc', units, *argv]
    begin = time.monotonic()
    with (out/'stderr').open('wb') as log:
        result = subprocess.run(runnable, cwd=cwd, env=env, stdout=subprocess.PIPE,stderr=log)
    seconds = time.monotonic() - begin
    if result.returncode:
        (out/'stdout').write_bytes(result.stdout)
        print((out/'stderr').read_text()[-4000:])
        print(result.stdout.decode()[-1200:])
        result.check_returncode()
    tree = int((out/'units.tsv.tree').read_text().split()[0])
    images = read_counts(units)
    rec = dict(tree=tree, compiler=sum(u['instructions'] for u in images), seconds=seconds)
    assert rec['tree'] >= rec['compiler'],rec
    diag, arts,dirty, binaries = [], {},[],[]
    for item in result.stdout.splitlines():
        if not item.startswith(b'{'):
            continue
        event = json.loads(item)
        if event.get('reason') == 'compiler-message':
            diag.append(json.dumps(event,sort_keys=True))
        if event.get('reason') != 'compiler-artifact':
            continue
        if not event['fresh']:
            dirty.append(event['target']['name'])
        if not metadata:
            continue
        if not Path(event['target']['src_path']).is_relative_to(cwd):
            continue
        if event.get('executable') and event['profile']['test']:
            binaries.append(Path(event['executable']))
        for name in event['filenames']:
            path = Path(name)
            if path.suffix == '.rmeta':
                with path.open('rb') as f:
                    header = f.read(56)
                has_public = header.startswith(b'rust') and header[24:40]!=header[40:56]
                public = header[40:56].hex() if has_public else None
                if CLIENT and PAIR == 1 and path.name.startswith('libuv_client-') and argv[1]=='clippy':
                    shutil.copyfile(path, out/'uv-client.rmeta')
                arts[path.relative_to(TRIAL).as_posix()] = dict(public=public, sha=sha(path))
    rec.update(dirty=sorted(dirty), diags=sorted(diag), metadata=arts)
    if metadata and argv[1] == 'test':
        (exe,) = binaries
        listing = subprocess.check_output([exe, '--list'], cwd=cwd,env=env)
        names = [line[:-6].decode() for line in listing.splitlines() if line.endswith(b': test')]
        assert names
        rec['tests'] = sorted(names)
        # Exercise the compiled library test binary outside the instruction count.
        command([exe, '--test-threads=4'], cwd, env, out/'tests.log')
    if CASE.startswith('codex') and metadata:
        dirs = [p for root in [TRIAL/'target',TRIAL/'shared'] if root.exists()
                for p in root.rglob('codex_tui-*') if p.is_dir() and 'incremental' in p.parts]
        files = {(s.st_dev,s.st_ino):s.st_size for directory in dirs
                 for p in directory.rglob('*') if p.is_file() for s in [p.stat()]}
        rec['tui_incremental_bytes'] = sum(files.values())
    save(out / 'result.json',rec)
    print(out.relative_to(OUT), tree, f'{seconds:.3f}s', len(images), flush=True)
    return rec


def replay(role):
    TRIAL.mkdir()
    kit = TRIAL / 'sdk'
    # The root path and resolved executable paths must match across arms.
    (KITS/role).rename(kit)
    tool = TRIAL / 'rustup/toolchains/ohm'
    tool.parent.mkdir(parents=True)
    tool.symlink_to(kit)
    path = TRIAL / 'source'
    env = dict(HOME=os.environ['HOME'], LANG='C.UTF-8',
               PATH=str(kit/'bin')+':'+os.environ['PATH'],
               CARGO_HOME=os.environ['CARGO_HOME'],
               CARGO_TARGET_DIR=str(TRIAL/'target'),CARGO_BUILD_JOBS=str(JOBS),
               RUSTUP_HOME=str(TRIAL/'rustup'),RUSTUP_TOOLCHAIN='ohm',
               MEASURE_CLIPPY=str(kit/'bin/clippy-driver'))
    if CLIENT:
        path.mkdir()
        subprocess.run(['tar','-x'],input=git(SOURCE,'archive',UPDATE+'^'),cwd=path,check=True)
        cwd = path
        ops = ['check','clippy','test']
        edits = [git(SOURCE,'diff','--binary',UPDATE+'^',UPDATE)]
    else:
        codex.checkout(SOURCE, path, CODEX)
        codex.compatibility(TRIAL)
        cwd = path / 'codex-rs'
        env['CARGO_BUILD_BUILD_DIR'] = str(TRIAL/'shared')
        ops = [CASE.split('-')[1]]
        edits = CODEX['edits']
        drivers = TRIAL/'drivers'
        drivers.mkdir()
        (drivers/'cc').symlink_to(Path('/usr/bin/clang').resolve(strict=True))
        env['PATH'] = str(drivers)+':'+env['PATH']

    def edit(i, forward=True):
        if CLIENT:
            subprocess.run(['git','apply']+([] if forward else ['--reverse']),
                           input=edits[i-1], cwd=path,check=True)
        else:
            codex.apply(path,edits[i-1],forward=forward)

    cargo = str(kit/'bin/cargo')
    def sequence(i,fresh=False):
        folder = OUT / role / (('fresh-' if fresh else '') + str(i))
        folder.mkdir(parents=True)
        if fresh:
            if CLIENT:
                shutil.rmtree(TRIAL/'target')
                (TRIAL/'before-edit').rename(TRIAL/'target')
            else:
                command([cargo,'clean','--offline','-p',PACKAGE],cwd,env,folder/'clean.log')
        elif CLIENT or i == 0:
            command([cargo,'fetch','--locked','--target','x86_64-unknown-linux-gnu'],cwd,env,folder/'fetch.log')
        series = []
        for op in ops:
            args = [cargo,op,'--locked','--offline','-p',PACKAGE,'--message-format=json']
            if CLIENT:
                args.append('--lib')
            if CASE == 'codex-clippy':
                # The archived Codex has deny lints introduced before Clippy 1.100.
                args += ['--','--cap-lints=warn']
            if op == 'test':
                args.append('--no-run')
            rec = count(args,cwd,env,folder/op)
            series.append(rec)
            noop = count(args,cwd,env,folder/(op+'-noop'),metadata=False)
            assert not noop['dirty'],noop['dirty']
        return series

    runs={}
    for i in range(len(edits)+1):
        if i:
            edit(i)
        runs[i]=sequence(i)
        if i == 0 and PAIR == 1 and CLIENT:
            # Reproduce Cargo's unit selection from the mixed prime while
            # discarding every query cache in the fresh arm.
            shutil.copytree(TRIAL/'target', TRIAL/'before-edit', symlinks=True,
                            ignore=shutil.ignore_patterns('incremental'))
    # Rebuild at identical paths with target state cleared. Codex retains the
    # unchanged dependency artifacts and removes the selected package's state.
    if PAIR==1:
        for i in reversed(range(1,len(edits)+1)):
            if i < len(edits):
                edit(i+1,False)
            batch = sequence(i,True)
            for warm,fresh in zip(runs[i],batch,strict=True):
                assert normalize(warm['diags'])==normalize(fresh['diags']), 'diagnostics mismatch'
                assert warm.get('tests')==fresh.get('tests'), 'test list mismatch'
                pub = lambda rec:{p:m['public'] for p,m in rec['metadata'].items()}
                if pub(warm)!=pub(fresh):
                    print('::warning::'+role+' public hash mismatch at step '+str(i),flush=True)
    kit.rename(KITS/role)
    shutil.rmtree(TRIAL)


OUT.mkdir()
KITS.mkdir()
SCRATCH.mkdir()
save(OUT/'config.json',dict(case=CASE, pair=PAIR,boot=sha(Path('/proc/sys/kernel/random/boot_id')),
                           cpu=subprocess.check_output(['lscpu']).decode(), codex=CODEX,uv=UPDATE))
install('control')
if PROBE_RUN:
    (OUT/'control-sdk.json').rename(OUT/'stock-sdk.json')
    (KITS/'control').rename(KITS/'stock')
    install_probe('control','base')
    install_probe('candidate',PROBE)
    if BASE_RUN:
        x,y=KITS/'control',KITS/'candidate'
        for field in ('epoch','bootstrap.toml','bootstrap.patch'):
            assert (x/field).read_bytes()==(y/field).read_bytes()
        std='lib/rustlib/x86_64-unknown-linux-gnu/lib'
        shutil.rmtree(y/std)
        shutil.copytree(x/std,y/std,copy_function=os.link)
        save(OUT/'std.json',{'both':'control'})
    shutil.rmtree(KITS/'stock')
elif not BASELINE:
    install('candidate')
first = 'control' if PAIR%2 else 'candidate'
if CASE in ('history','audit-control','audit-candidate'):
    args = []
    if CASE.startswith('audit-'):
        args=['--audit','--audit-role',CASE.split('-')[1]]
    subprocess.run([sys.executable, Path(__file__).with_name('run.py'),
                    '--uv',SOURCE,'--control',KITS/'control','--candidate',KITS/'candidate',
                    '--scratch',SCRATCH,'--output',OUT,'--first',first,
                    '--cargo',KITS/'control/bin/cargo','--candidate-cargo',KITS/'candidate/bin/cargo',
                    *args],check=True)
else:
    calibrate(SCRATCH,OUT)
    roles = ['control','candidate']
    if BASELINE:
        roles=['control']
    elif first=='candidate':
        roles.reverse()
    for role in roles:
        replay(role)
