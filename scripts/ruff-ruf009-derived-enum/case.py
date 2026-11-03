"""Fixed-source, independently empty Ruff RUF009 check experiment."""
from pathlib import Path
import hashlib
import json
import os
import re
import urllib.request
import shutil
import subprocess
import sys
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'ruff-module-16149'))
import artifacts
import historical
import setup as old
import study as observer

w, need, sha, save = old.w, old.need, old.sha, old.save
REG = json.loads((HERE / 'registration.json').read_bytes())
PORT = historical.PORT
require_bytes = lambda data: hashlib.sha256(data).hexdigest()
ROOT = Path(os.environ['RUNNER_TEMP']).resolve(strict=True) / 'ohm-ruf009'
BASE = ROOT / 'receipt'
w.ROOT, w.OUT, w.SDK, w.STATE = ROOT, BASE, ROOT/'sdk', ROOT/'state'
w.BRANCH, w.SOURCE, w.FILES = REG['qa_branch'], REG['path'], [REG['path']]
observer.REG = REG | {'expected_root_roster':REG['observed_targets']}
old.BASE_OUT = BASE
observer.MEMBERS = BASE/'members'
CHECK = REG['cargo_check']
BUILD = [*CHECK[:2], 'build', *CHECK[3:]]
ERROR = b'\nconst OHM_INVALID_CHECK_SENTINEL: u32 = "invalid";\n'
env = old.env


def source(state=None):
    return historical.state(w.SRC, state)


def fresh_state():
    w.fresh_state()
    for name in ('home','temp'):
        directory=ROOT/name
        need(directory.parent==ROOT and directory.is_dir() and not directory.is_symlink(),'unsafe private history')
        shutil.rmtree(directory)
        directory.mkdir()


def check_native_release():
    notice = json.loads((HERE / 'sete-prerequisites.json').read_bytes())
    expected = {'ordinary-native': (41625608181, 'success'), 'literal-first': (41623623166, 'failure'),
                'parked-and-alias': (41624199212, 'success')}
    need(set(notice) == set(expected), 'missing native acquisition')
    for name, (run, conclusion) in expected.items():
        sealed = notice[name]
        info = old.api(f'actions/runs/{run}')
        need(info['status'] == 'completed' and info['conclusion'] == conclusion and info['run_attempt'] == 1
             and info['head_sha'] == sealed['head'] and sealed['run'] == run, 'wrong native run or role')
        asset = old.api(f"actions/artifacts/{sealed['artifact']}")
        need(asset['workflow_run']['id'] == run and asset['digest'] == 'sha256:' + sealed['artifact_sha256'],
             'wrong native raw archive')
        projected = HERE / 'native-prerequisites' / (name + '.json')
        need(sha(projected) == sealed['proof_sha256'], 'wrong independent native projection')
        data = json.loads(projected.read_bytes())
        need(data['passed'] is True and data['scope'] == name, 'native prerequisite refused')


def enroll(phase, block):
    w.checked_head()
    check_native_release()
    need(not ROOT.exists() and len(REG['confirm_orders'])==8, 'previous worker state')
    ROOT.mkdir()
    BASE.mkdir()
    observer.MEMBERS.mkdir()
    need(w.resources()[1] > 75*(1<<30), 'entry disk reserve')
    need(sha(HERE/'historical-source.json') == REG['source_sha256'], 'historical source registration')
    historical.enter(w.SRC)
    (BASE/'source').mkdir()
    for tag in ('fixed','buggy','fixed'):
        source(tag)
        (BASE/'source'/(tag+'.rs')).write_bytes((w.SRC/REG['path']).read_bytes())
    (BASE/'source'/'invalid.rs').write_bytes((w.SRC/REG['path']).read_bytes()+ERROR)
    order = REG['pilot_order'] if phase=='pilot' and block==0 else REG['confirm_orders'][block-1] if phase=='confirmation' and 1<=block<=8 else None
    need(order in ('PC','CP'), 'unregistered stage or block')
    bind=json.loads((HERE/'factory.json').read_bytes())
    need(bind['source']=={k:v['revision']for k,v in REG['matched_sources'].items()} and bind['branch']==REG['factory_branch'],'wrong experimental Rust versions')
    if phase=='confirmation':
        save(BASE/'pilot-gate.json',artifacts.pilot_gate(ROOT))
    run = int(os.environ['GITHUB_RUN_ID'])
    info = old.api(f'actions/runs/{run}')
    jobs = old.api(f'actions/runs/{run}/attempts/1/jobs?per_page=100')
    job, = [j for j in jobs['jobs'] if j['name']==f'{phase}-{block}' and j['runner_name']==os.environ['RUNNER_NAME']]
    need(info['event']=='workflow_dispatch' and info['head_sha']==os.environ['REVIEWED_HEAD'] and info['head_branch']==w.BRANCH and info['run_attempt']==1 and job['runner_id']>0,'unregistered physical runner')
    save(BASE/'worker.json',dict(run=run,job=job['id'],runner=job['runner_id'],phase=phase,block=block,order=order,boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),sha=info['head_sha'],source=REG,port=PORT,factory=bind,recipe=artifacts.recipe()))
    kit=old.scope_matched.kit('ruf009',bind)
    builder=w.WS/'scope-ruf009/scripts/ruff-matched-stage'
    req=json.loads((builder/'registration.json').read_bytes())
    need(req['roles']==REG['matched_sources'] and req['signed_cargo']==REG['matched_signed_cargo'],'wrong compiler source tree or signed Cargo/ld')
    import zipfile
    guards={}
    with zipfile.ZipFile(ROOT/'scope-kit-ruf009/receipts.zip') as z:
        log=z.read('run-make-C.log');proof=(builder/'build.py').read_text()
        need('"tests/run-make/rdr-public-hash-private-native-derive"]' in proof and 'guarded(run_make, rust, env, run_make_log, root)' in proof and b'Testing stage1 with compiletest suite=run-make mode=run-make' in log and b'running 1 tests' in log and b'1 passed; 0 failed; 0 ignored' in log,'missing real product run-make')
        for k,label in [('P','parent'),('C','candidate')]:
            for name in ('consumed','sete'):
                record = z.read('run-make-' + name + '-' + k + '.log')
                need(b'running 1 tests' in record and b'1 passed; 0 failed; 0 ignored' in record, 'missing common native/checksum run-make')
            g=json.loads(z.read('scope-guard-'+label+'.json'));ph=g['phases']
            need(g['role']==label and len(ph)==12 and sorted(ph['private-edit']['dirty']) in ([['dep'],['app','dep']] if k=='C' else [['app','dep']]) and
                 g['kernel']['old']['kernel']==['app','dep'] and g['kernel']['unchanged']['kernel']==[] and g['kernel']['edit']['kernel']==['app','dep'] and
                 require_bytes(z.read('scope-evidence-'+label+'.tar.gz'))==bind['guard_archives'][k] and
                 ph['generated-edit']['dirty']==['dep','app'] and ph['opaque-raw-pointer']['errors']==['E0277'] and not ph['opaque-repair-unchanged']['dirty'] and
                 ph['empty-private-edit']['provider_public']==ph['private-edit']['provider_public'],'missing provider, generated trait, error/repair or cold gate')
            guards[k]=g
    client=historical.cargo_client(ROOT,BASE,artifacts)
    roles={}
    for role,name in [('P','normal'),('C','defer')]:
        sdk=Path(kit['arms'][name]['root'])
        driver,=(sdk/'lib').glob('librustc_driver-*.so')
        need(guards[role]['driver_sha256']==sha(driver),'safety ran a different driver')
        view, files=historical.with_client(sdk,ROOT,name,client,kit['arms'][name]['files'])
        roles['inline-'+role]=dict(source=bind['source'][role],sdk=str(view),driver=sha(driver),rustc=sha(sdk/'bin/rustc'),cargo=sha(client),files=files)
    need(roles['inline-P']['driver']!=roles['inline-C']['driver'] and roles['inline-P']['cargo']==roles['inline-C']['cargo'],'not a matched Rust-only capsule')
    save(BASE/'scope-sdks.json',roles)
    save(BASE/'factory-safety.json',guards)
    (ROOT/'proxies').mkdir()
    rustup=Path(shutil.which('rustup')).resolve(strict=True)
    shutil.copy2(rustup,ROOT/'proxies/rustup')
    need(sha(rustup)==sha(ROOT/'proxies/rustup'),'proxy mismatch')
    for name in ('cargo','rustc','rustdoc'):(ROOT/'proxies'/name).symlink_to('rustup')
    for name in ('home','temp','cargo','rustup/toolchains'):(ROOT/name).mkdir(parents=True)
    (ROOT/'rustup/toolchains/ohm').symlink_to(w.SDK)
    (ROOT/'rustup/settings.toml').write_text('version = "12"\nprofile = "minimal"\n')
    old.activate('P')
    # Only locked source archives and verified Git checkouts enter a fresh history.
    state=env();state.pop('CARGO_NET_OFFLINE')
    w.run(['cargo','+ohm','fetch','--locked'],state,BASE/'fetch')
    pkgs=tomllib.loads((w.SRC/'Cargo.lock').read_text())['package']
    want={p['name']+'-'+p['version']+'.crate':p['checksum'] for p in pkgs if p.get('source','').startswith('registry+')}
    cache,=[p for p in (ROOT/'cargo/registry/cache').iterdir() if p.is_dir()]
    for pkg in pkgs:
        if not pkg.get('source','').startswith('registry+'):continue
        name,ver=pkg['name'],pkg['version'];file=name+'-'+ver+'.crate'
        if (cache/file).exists():continue
        need(re.fullmatch(r'[a-zA-Z0-9_-]+',name) and re.fullmatch(r'[0-9A-Za-z.+-]+',ver),'unexpected lock path')
        with urllib.request.urlopen(f'https://static.crates.io/crates/{name}/{file}',timeout=45)as stream:
            raw=stream.read(64*2**20+1)
        need(0<len(raw)<=64*2**20 and require_bytes(raw)==want[file],'invalid supplemental locked crate')
        with (cache/file).open('xb')as out:out.write(raw)
    paths=list((ROOT/'cargo/registry/cache').glob('*/*.crate'));actual={p.name:sha(p) for p in paths}
    need(len(paths)==len(want)==REG['lock']['registry_archives'] and want==actual,'locked archive custody')
    locked_git={p['name']:p['source'] for p in pkgs if p.get('source','').startswith('git+')}
    need(locked_git==REG['lock']['git'],'unregistered Git inputs')
    git_inputs=historical.git_sources(ROOT/'cargo',locked_git)
    need(git_inputs==REG['git_checkouts'],'different physically checked-out locked Git inputs')
    save(BASE/'git-inputs.json',git_inputs)
    save(BASE/'registry.json',actual)
    (ROOT/'cargo').rename(ROOT/'prefetched-cargo')
    need(sha(HERE/'whole_count.c')==REG['counter_sha256'],'unregistered whole counter')
    subprocess.run(['/usr/bin/cc','-O2','-Wall','-Wextra','-Werror',HERE/'whole_count.c','-o',ROOT/'whole-count'],check=True)
    calibrations={}
    for how in ('thread','child'):
        for work in (0,1):
            loop='sum(range(6000000))' if work else 'None'
            code=("import threading;t=threading.Thread(target=lambda:"+loop+");t.start();t.join()" if how=='thread'
                  else "import subprocess,sys;subprocess.run([sys.executable,'-IB','-c',"+repr(loop)+"],check=True)")
            dest=BASE/(f'pmu-{how}-{work}.json')
            subprocess.run([ROOT/'whole-count',dest,'/usr/bin/python3','python3','-IB','-c',code],check=True)
            obs=json.loads(dest.read_bytes())
            need(obs['status']==0 and obs['enabled']==obs['running']>0 and obs['instructions']>0,'hardware admission')
            calibrations[how,work]=obs['instructions']
        need(calibrations[how,1]>calibrations[how,0]+10_000_000,'hardware lost a real '+how)



if __name__=='__main__':
    enroll(sys.argv[1],int(sys.argv[2]))
