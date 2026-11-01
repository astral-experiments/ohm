"""Reproduce the Darwin Diesel PGO workload on the old package and integrated compiler."""

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from graphs import clone, put, require, sha, tables

HOST = 'aarch64-apple-darwin'
OLD = '556a8364f1485a03be31b1a50c250d63198a943d'
NEW = '1bc7b35699479d5899a2935d79392b7bdaf7497d'
PERF = '0a054b0ead56e41a4584bfab6fdc1a5fad2aedc3'
STAGE0 = '88d9e12ae178fab0fb5cc050a94da85685d449ea'
CARGO = '32156236e76773728b3e7655d64d32ea8c3023b165f25a2754c7e5c50669f366'
ASSERTION = 'node_header.node().kind != DepKind::Null && node.kind == DepKind::Null'
Q = Path('src/query_dsl/mod.rs')
PERF_DATA = Path('collector/compile-benchmarks/diesel-2.2.10')


def text(argv, **kw):
    return subprocess.check_output(argv, text=True, **kw).strip()


def run_record(folder, cmd, *, cwd, env):
    folder.mkdir(parents=True, exist_ok=False)
    put(folder / 'command.json', {'argv': list(map(str, cmd)), 'cwd': str(cwd)})
    with (folder / 'stdout').open('wb') as stdout, (folder / 'stderr').open('wb') as stderr:
        code = subprocess.run(cmd, cwd=cwd, env=env, stdout=stdout, stderr=stderr).returncode
    (folder / 'exit').write_text(f'{code}\n')
    return code


def clean_env():
    keep = ('PATH', 'HOME', 'USER', 'LANG', 'LC_ALL', 'SHELL', 'SDKROOT', 'DEVELOPER_DIR', 'MACOSX_DEPLOYMENT_TARGET', 'TMPDIR')
    return {**{k: os.environ[k] for k in keep if k in os.environ}, 'TERM': 'dumb', 'RUST_BACKTRACE': '1', 'RUSTC_BOOTSTRAP': '1'}


def original(w, root):
    prefix = ['gh','api','repos/astral-experiments/ohm/actions/']
    def api(endpoint):
        return subprocess.check_output([*prefix[:2], prefix[2]+endpoint])
    run = json.loads(api('runs/41256793646'))
    job = json.loads(api('jobs/124701560586'))
    artifact = json.loads(api('artifacts/13065158467'))
    head = '8b2c911b32b7cad9442b7ddced987c5a1b0a62e5'
    require((run['head_sha'],run['run_attempt'],run['conclusion'])==(head,1,'failure') and
            (job['run_id'],job['run_attempt'],job['head_sha'],job['conclusion'])==(41256793646,1,head,'failure'), 'different original attempt')
    require(artifact['workflow_run']['id']==run['id'] and artifact['workflow_run']['head_sha']==head and
            artifact['name']=='integrated-source-aarch64-apple-darwin' and artifact['size_in_bytes']==31639, 'different original artifact')
    p=root/'reports/original-13065158467.zip'
    p.write_bytes(api('artifacts/13065158467/zip'))
    require(sha(p) == 'bd1e051d996a50f818bd6e572e50197bd6f8ac480c7240c91f9598f807586402' == artifact['digest'].removeprefix('sha256:'), 'different original ZIP')
    with zipfile.ZipFile(p) as z:
        log = z.read('optimized-dist.log').decode()
        source = json.loads(z.read('integrated-source.json'))
    require(source['commits']['rust']==NEW and all(t in log for t in (ASSERTION, 'benchmark/mod.rs:527', 'diesel-2.2.10',
            'aarch64-apple-darwin', PERF, '"-Zincremental-verify-ich"')), 'different native failure')
    put(root/'reports/original.json',{'run':run['id'],'job':job['id'],'archive':artifact,'source':source})


def bootstrap(w, root):
    rust = w / 'source/rust'
    sys.path.insert(0, str(w / 'transport/scripts/rc22-native'))
    import sdk
    rev = text(['git', '-C', rust, 'rev-parse', 'HEAD'])
    require(rev == NEW, 'wrong integrated source')
    cmd = ['./x', '--ci', 'false', '--set', 'build.submodules=false', '--set', 'rust.channel=dev', '--set', 'rust.omit-git-hash=false',
           '--set', 'rust.debug-assertions=false', '--set', 'rust.lto=off', '--set', 'llvm.download-ci-llvm=true',
           'build', '--stage', '1', '-j4', '--host', HOST, '--target', HOST, 'compiler/rustc', 'library', 'src/tools/rustdoc']
    sdk.log_run(cmd, rust, root / 'reports/stage1.log')
    kit = root / 'integrated'
    sdk.freeze(rust / 'build' / HOST / 'stage1', kit, rust, HOST)
    shutil.copy2(root / 'fourfix-cargo', kit / 'bin/cargo')
    require(sha(kit / 'bin/cargo') == CARGO and NEW in text([kit / 'bin/rustc', '-vV']), 'incorrect stage1')
    put(root / 'reports/stage1.json', {'source': rev, 'argv': cmd, 'cargo': CARGO, 'driver': sha(next((kit / 'lib').glob('librustc_driver-*.dylib')))})


def prepare(w, root):
    perf = w / 'perf'
    rust = w / 'source/rust'
    pin = text(['git', '-C', rust, 'rev-parse', NEW + ':src/tools/rustc-perf'])
    require(text(['git', '-C', perf, 'rev-parse', 'HEAD']) == pin == PERF, 'different rustc-perf checkout')
    local = root / 'reports'
    crate = perf / PERF_DATA
    a = crate / Q
    patch = crate / '0-println.patch'
    require(text(['git', 'hash-object', patch]) == '1e577c05e814d01cdfccc777d4338bee19d0afcd' and len(list(crate.glob('*.patch'))) == 1, 'different real Diesel change')
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        alt = Path(tmp) / Q
        alt.parent.mkdir(parents=True)
        shutil.copy2(a, alt)
        subprocess.run(['git', 'apply', patch], cwd=tmp, check=True)
        shutil.copy2(alt, local / 'B.rs')
    shutil.copy2(a, local / 'A.rs')
    shutil.copy2(patch, local / '0-println.patch')
    require(b'println!("testing")' not in a.read_bytes() and b'println!("testing")' in (local/'B.rs').read_bytes(), 'missing exact crate patch')
    c = Path(text(['rustup', 'which', 'cargo', '--toolchain', '1.98.0']))
    rustc = Path(text(['rustup', 'which', 'rustc', '--toolchain', '1.98.0']))
    require(STAGE0 in text([rustc, '-vV']), 'different upstream collector host')
    env = dict(clean_env(), RUSTC=str(rustc))
    subprocess.run([c, 'build', '--locked', '-p', 'collector'], cwd=perf, env=env, check=True)
    actor = perf / 'target/debug/rustc-fake'
    pristine = root / 'pristine-rustc-fake'; shutil.copy2(actor, pristine)
    src = perf / 'collector/src/bin/rustc-fake.rs'
    original = src.read_bytes()
    token = b'                determinism_env(&mut cmd);\n                let status = cmd.status().expect("failed to spawn");\n                if !status.success() {'
    require(original.count(token) == 1, 'different actual Eprintln call')
    changed = token.replace(b'                let status', b'                diesel_witness(&cmd, "before", -1);\n                let status')
    changed = changed.replace(b'                if !status', b'                diesel_witness(&cmd, "after", status.code().unwrap_or(-1));\n                if !status')
    src.write_bytes(original.replace(token, changed) + (HERE / 'witness.rs').read_bytes())
    try:
        subprocess.run([c, 'build', '--locked', '-p', 'collector', '--bin', 'rustc-fake'], cwd=perf, env=env, check=True)
        shutil.copy2(actor, root / 'observed-rustc-fake')
        changed_source = sha(src)
    finally:
        src.write_bytes(original)
        shutil.copy2(pristine, actor)
    require(not text(['git', '-C', perf, 'status', '--porcelain', '--untracked-files=no']), 'collector source changed on the primary lane')
    put(local / 'inputs.json', {'perf': PERF, 'root':text(['git','-C',perf,'rev-parse','HEAD:'+str(PERF_DATA)]),
         'source_hashes': {s: sha(local / f'{s}.rs') for s in ('A', 'B')}, 'patch': sha(patch), 'stage0': STAGE0,
         'collector': sha(perf / 'target/debug/collector'), 'pristine_wrapper': sha(pristine),
         'witness_wrapper': sha(root / 'observed-rustc-fake'), 'witness_source': changed_source,
         'original_release_run': 41256793646, 'graph': ASSERTION, 'host': platform.platform(), 'xcode': text(['xcodebuild','-version'])})


def replay(stage, results):
    rows = [json.loads(f.read_bytes()) for f in sorted((results / 'observations').glob('*-before.json'))]
    record, = [r for r in rows if r['source'] == 'B' and r['incremental'] is not None]
    require([r['source'] for r in rows] == ['A','A','A','B'] and
            [r['incremental'] is not None for r in rows] == [False,True,True,True], 'different Opt scenario order')
    require(not rows[1]['tables'] and rows[2]['tables'] and record['tables'], 'missing each incremental generation')
    folder = results / 'controlled-readers'
    folder.mkdir()
    cwd = Path(record['cwd'])
    require(cwd.parent == (stage / 'tmp').resolve() and (stage/'patched-input').is_dir(), 'lost the registered template')
    if cwd.exists():
        cwd.rename(stage / 'parked-completed-observation')
    table_keys = [(t['path'], t['sha256']) for t in record['tables']]
    for name, variant, reuse in [('patched-retry','B',True),('unchanged-reader','A',True),('empty-A','A',False),('empty-B','B',False)]:
        require(not cwd.exists(), 'private replay path already exists')
        clone(stage / 'patched-input', cwd)
        try:
            inc = cwd / 'incremental-state'
            actual = [(r['path'], r['sha256']) for r in tables(inc, results, False)]
            require(actual == table_keys, 'substituted captured input')
            if not reuse:
                shutil.rmtree(inc)
            shutil.copyfile(results.parent / f'{variant}.rs', cwd / Q)
            outputs = Path(record['argv'][record['argv'].index('--out-dir')+1]).resolve()
            require(outputs.is_relative_to(cwd) and outputs.is_dir(), 'direct reader output outside its private clone')
            for p in outputs.glob('libdiesel-*'):
                if p.suffix in ('.rlib','.rmeta'):
                    p.unlink()
            code = run_record(folder / name, record['argv'], cwd=cwd, env=record['env'])
            diag = (folder / name / 'stderr').read_text(errors='replace')
            emitted = {p.name:sha(p) for p in sorted(outputs.glob('libdiesel-*')) if p.is_file() and p.suffix in ('.rlib','.rmeta')}
            if code == 0:
                require({Path(k).suffix for k in emitted} == {'.rlib','.rmeta'}, 'successful direct compiler did not emit both fresh library outputs')
            put(folder / name / 'read.json', {'source':variant, 'source_sha256':sha(cwd / Q),'incoming':actual if reuse else [],
                 'code':code,'exact_decoder_ice':ASSERTION in diag and 'SerializedDepGraph>::decode' in diag,
                 'emitted': emitted})
        finally:
            shutil.rmtree(cwd)
    require((folder/'empty-A/exit').read_text() == (folder/'empty-B/exit').read_text() == '0\n','one independent empty reader failed')


def profiles(w, root, role, lane):
    require(role in ('parent', 'integrated') and lane in ('primary','observed'), 'unknown role')
    reported = root / 'reports' / (role + '-' + lane); reported.mkdir()
    stage = root / (role + '-' + lane); stage.mkdir()
    tmp = stage / 'tmp'; tmp.mkdir()
    perf = w / 'perf'; kit = root / role
    src = OLD if role == 'parent' else NEW
    version = text([kit/'bin/rustc', '-vV'])
    require(src in version and HOST in version and sha(kit / 'bin/cargo') == CARGO, 'different registered subjects')
    wrapper = root / ('pristine-rustc-fake' if lane == 'primary' else 'observed-rustc-fake')
    shutil.copy2(wrapper, perf / 'target/debug/rustc-fake')
    inputs = json.loads((root/'reports/inputs.json').read_bytes())
    require(sha(perf/'target/debug/rustc-fake') == inputs['pristine_wrapper' if lane=='primary' else 'witness_wrapper'],'wrong actual collector role')
    env = dict(clean_env(), TMPDIR=str(tmp), RUST_LOG='collector::compile::benchmark=debug', OHM_DIESEL_STAGE=str(stage),
               OHM_DIESEL_RESULTS=str(reported), OHM_DIESEL_PYTHON=sys.executable, OHM_DIESEL_OBSERVER=str(HERE / 'graphs.py'))
    env['RUSTC']=text(['rustup','which','rustc','--toolchain','1.98.0'])
    cmd = [perf/'target/debug/collector', 'profile_local','eprintln', kit/'bin/rustc', '--id','Test','--cargo',kit/'bin/cargo',
           '--profiles','Check,Debug,Opt' if lane=='primary' else 'Opt', '--scenarios','All','--exact-match','diesel-2.2.10',
           '--jobs','4','--out-dir',reported/'outputs']
    code = run_record(reported / 'collector', cmd, cwd=perf, env=env)
    log = (reported/'collector/stderr').read_text(errors='replace')+(reported/'collector/stdout').read_text(errors='replace')
    outputs = sorted(p.name for p in (reported/'outputs').glob('eprintln-*'))
    result = {'role':role,'lane':lane,'rustc':version,'cargo':CARGO,'rustc_sha256':sha(kit/'bin/rustc'),
              'driver_sha256':sha(next((kit/'lib').glob('librustc_driver-*.dylib'))),'wrapper':sha(wrapper),'exit':code,
              'same_failure':ASSERTION in log and 'SerializedDepGraph>::decode' in log,'outputs':outputs}
    put(reported/'collector-result.json', result)
    if lane == 'primary':
        # Unmodified rustc-perf retains the input worktree on a BenchError.
        for p in tmp.glob('.tmp*/incremental-state'):
            if (p.parent / Q).is_file():
                put(reported / (p.parent.name + '-tables.json'), {'source':sha(p.parent/Q),'tables':tables(p,reported)})
    else:
        replay(stage, reported)
    require((code == 0 and len(outputs)==(12 if lane=='primary' else 4)) or (code != 0 and result['same_failure']),
            ('unrelated collector failure or missing positive phases',result))


def marked(w, root, role):
    kit = (root / role).resolve()
    work = root / ('smoke-' + role)
    work.mkdir()
    env = dict(clean_env(), RUSTUP_HOME=str(work/'rustup'), CARGO_HOME=str(work/'cargo-home'))
    env.pop('RUSTC_BOOTSTRAP', None)
    subprocess.run(['rustup','toolchain','link','ohm',kit],env=env,check=True)
    smoke = w / 'latest-smoke/scripts/smoke-test-relink.sh'
    require(text(['git','-C',w/'latest-smoke','rev-parse','HEAD'])=='933ca489d20ba0c856d6762fd115a3fad78ff0f8','different release smoke')
    d=root/'reports'/('declared-'+role)
    code=run_record(d,['bash',smoke,'ohm',work/'fixture'],cwd=w,env=env)
    evidence=(d/'stdout').read_bytes()+(d/'stderr').read_bytes()
    expected=b'Expected 0 linker calls for two executables returning 17, observed 2'
    put(d/'result.json',{'script':sha(smoke),'code':code,'exact_two_instead_of_zero':expected in evidence})
    require(code==0 or expected in evidence, 'unrelated declared native control failure')


if __name__ == '__main__':
    w=Path(os.environ['GITHUB_WORKSPACE']).resolve()
    root=Path(os.environ['DIESEL_ROOT']).resolve()
    require(platform.system()=='Darwin' and platform.machine()=='arm64','wrong native host')
    op,*args=sys.argv[1:]
    {'original':original,'bootstrap':bootstrap,'prepare':prepare,'profiles':profiles,'marked':marked}[op](w,root,*args)
