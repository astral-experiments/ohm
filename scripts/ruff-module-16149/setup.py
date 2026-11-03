"""Bind the exact historical Ruff patch, source-built SDKs, and locked third-party graph."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'ruff-linter-check-attribution'))
import scope_matched
import worker as w

REG = json.loads((HERE / 'registration.json').read_bytes())
OLD, EDIT, FIX = [REG[k] for k in ('root', 'edit', 'repair')]
BRANCH = 'charlie/qa-ruff-16149-visibility-20261103'
CHECK = ['cargo', '+ohm', 'check', '-p', 'ruff', '--bin', 'ruff', '--locked', '--offline', '-j4', '--message-format=json']
BUILD = [*CHECK[:2], 'build', *CHECK[3:]]
FILES = [
    'crates/ruff_linter/src/rules/flake8_self/rules/private_member_access.rs',
    'crates/ruff_linter/src/rules/pylint/helpers.rs',
    'crates/ruff_linter/src/rules/pylint/mod.rs',
]
w.ROOT = Path(os.environ['RUNNER_TEMP']).resolve(strict=True) / 'ohm-ruff16149'
w.OUT, w.SDK, w.STATE = (w.ROOT / k for k in ('receipt','sdk','state'))
BASE_OUT = w.OUT
w.BRANCH, w.OLD, w.NEW, w.FILES, w.SOURCE = BRANCH, OLD, EDIT, FILES, FILES[1]
need, save, sha, git = w.need, w.save, w.sha, w.git
GIB = 1 << 30


def source(rev):
    spec = REG['sources'][rev]
    need(git(w.SRC,'rev-parse','HEAD') == rev and git(w.SRC,'rev-parse','HEAD^{tree}') == spec['tree'], 'Ruff source tree')
    need(not git(w.SRC,'status','--porcelain','--untracked-files=all') and sha(w.SRC/'Cargo.lock') == REG['lock']['sha256'], 'Ruff lock or working changes')
    need(git(w.SRC,'rev-parse', EDIT+'^') == OLD and git(w.SRC,'rev-parse',FIX+'^') == EDIT, 'historical transitions')
    need(git(w.SRC,'diff','--name-only',OLD,EDIT).splitlines() == FILES and git(w.SRC,'diff','--name-only',EDIT,FIX).splitlines()==[FILES[1]], 'original patch scope')


w.source = source


def env():
    result = w.environment()
    result.update(CARGO_BUILD_JOBS='4', CARGO_NET_GIT_FETCH_WITH_CLI='true')
    return result


def api(path):
    return json.loads(subprocess.check_output(w.gh(path)))


def acquire():
    w.checked_head()
    source(FIX)
    w.ROOT.mkdir()
    BASE_OUT.mkdir()
    w.resources()
    need(shutil.disk_usage(w.ROOT).free > 75*GIB, 'initial disk reserve')
    run = int(os.environ['GITHUB_RUN_ID'])
    info = api(f'actions/runs/{run}')
    jobs = api(f'actions/runs/{run}/attempts/1/jobs?per_page=100')
    job, = jobs['jobs']
    need(jobs['total_count']==1 and info['head_sha']==os.environ['REVIEWED_HEAD'] and info['head_branch']==BRANCH and info['run_attempt']==1 and info['event']=='workflow_dispatch' and job['name']=='Historical Ruff scope edit' and job['runner_name']==os.environ['RUNNER_NAME'] and job['runner_id']>0,'actual worker custody')
    save(BASE_OUT/'worker.json',dict(run=run,head=info['head_sha'],job=job['id'],runner=job['runner_name'],runner_id=job['runner_id'],boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),resources=w.resources(),sources=REG['sources']))
    scope_matched.acquire('scope-adt-factory.json')
    need(set(json.loads((BASE_OUT/'scope-sdks.json').read_text()))=={'inline-P','inline-C'},'matched compiler roles')
    proxies=w.ROOT/'proxies';proxies.mkdir()
    system=Path(shutil.which('rustup')).resolve(strict=True)
    shutil.copy2(system,proxies/'rustup');need(sha(system)==sha(proxies/'rustup'),'rustup proxy')
    for name in ('cargo','rustc','rustdoc'):(proxies/name).symlink_to('rustup')
    for d in ('home','temp','rustup/toolchains','cargo'):(w.ROOT/d).mkdir(parents=True)
    (w.ROOT/'rustup/toolchains/ohm').symlink_to(w.SDK)
    (w.ROOT/'rustup/settings.toml').write_text('version = "12"\nprofile = "minimal"\n')
    print('Acquired both authenticated compiler roles and pinned all three historical Ruff trees.',flush=True)


def activate(role):
    need(role in ('P','C'),'unknown physical SDK')
    record=json.loads((BASE_OUT/'scope-sdks.json').read_text())['inline-'+role]
    if w.SDK.exists():
        need(w.SDK.parent==w.ROOT and w.SDK.is_dir() and not w.SDK.is_symlink(),'private SDK path')
        shutil.rmtree(w.SDK)
    subprocess.run(['cp','-a','--reflink=auto',record['sdk'],w.SDK],check=True)
    driver,=list((w.SDK/'lib').glob('librustc_driver-*.so'))
    need(sha(driver)==record['driver'],'physical driver hash')
    rs=subprocess.check_output(['rustc','+ohm','-vV'],env=env(),text=True)
    ag=subprocess.check_output(['cargo','+ohm','-Vv'],env=env(),text=True)
    actual=subprocess.check_output(['rustc','+ohm','--print','sysroot'],env=env(),text=True).strip()
    need(Path(actual).samefile(w.SDK) and 'host: x86_64-unknown-linux-gnu' in rs and 'host: x86_64-unknown-linux-gnu' in ag,'host or physical sysroot')
    return dict(config=record, active=str(w.SDK),driver=sha(driver),rustc=sha(w.SDK/'bin/rustc'),cargo=sha(w.SDK/'bin/cargo'),rustc_version=rs,cargo_version=ag,sysroot=actual)


def prefetch():
    w.checked_head();source(FIX);actual=activate('P');fresh=env();fresh.pop('CARGO_NET_OFFLINE')
    w.run(['cargo','+ohm','fetch','--locked'],fresh,BASE_OUT/'fetch',timeout=1800)
    lock=tomllib.loads((w.SRC/'Cargo.lock').read_text())['package']
    wanted={p['name']+'-'+p['version']+'.crate':p['checksum'] for p in lock if p.get('source','').startswith('registry+')}
    need(len(wanted)==REG['lock']['registry_crates'],'locked registry closure')
    cache,=[p for p in (w.ROOT/'cargo/registry/cache').iterdir() if p.is_dir()]
    missing=[]
    for package in lock:
        if not package.get('source','').startswith('registry+'):continue
        name,version=package['name'],package['version'];filename=f'{name}-{version}.crate';dest=cache/filename
        if dest.exists():continue
        need(re.fullmatch(r'[a-zA-Z0-9_-]+',name) and re.fullmatch(r'[0-9A-Za-z.+-]+',version),'unexpected registry source path')
        with urllib.request.urlopen(f'https://static.crates.io/crates/{name}/{filename}',timeout=45) as response:
            raw=response.read(64*2**20+1)
        need(0<len(raw)<=64*2**20 and hashlib.sha256(raw).hexdigest()==wanted[filename],'supplementary locked archive')
        with dest.open('xb')as stream:stream.write(raw)
        missing.append(filename)
    files=sorted((w.ROOT/'cargo/registry/cache').glob('*/*.crate'));received={f.name:sha(f)for f in files}
    need(len(files)==len(received) and received==wanted,'full 424-crate lock/checksum collection')
    trees={}
    for d in (w.ROOT/'cargo/git/checkouts').glob('*/*/.git'):
        src=d.parent;oid=git(src,'rev-parse','HEAD');tree=git(src,'rev-parse','HEAD^{tree}')
        need(not git(src,'diff','HEAD','--') and set(git(src,'status','--porcelain','--untracked-files=all').splitlines()) <= {'?? .cargo-ok'}, 'git dependency contains unpublished source')
        need(oid not in trees,'duplicated Git source');trees[oid]=tree
    expected={url.rsplit('#',1)[1]:v['tree'] for url,v in REG['lock']['git'].items()}
    need(trees==expected,'two external Git source trees')
    save(BASE_OUT/'registry.json',dict(archives=received,supplemented=missing,git=trees,roles=REG['lock']['git'],sdk=actual))
    for cmd,mode in ((CHECK,'check'),(BUILD,'build')):
        dest=BASE_OUT/('graph-'+mode)
        w.run(cmd+['-Zunstable-options','--unit-graph'],env(),dest,timeout=300)
        graph=json.loads((dest/'stdout').read_bytes()); units=graph['units'];root,=[units[i]for i in graph['roots']]
        need(root['target']['name']=='ruff' and root['target']['kind']==['bin'] and root['mode']==mode,'ordinary graph root')
        selected={u['target']['name']:u for u in units if u['target']['kind']==['lib'] and u['target']['name'] in REG['expected_root_roster'] and u['mode']==mode}
        need(set(selected)==set(REG['expected_root_roster']),'missing declared dependent packages')
        for pkg,u in {'ruff':root, **selected}.items():
            if pkg!='ruff_linter':
                deps={units[d['index']]['target']['name']for d in u['dependencies']}
                need('ruff_linter' in deps,'missing actual direct linter dependency for '+pkg)
        save(dest/'accepted.json',dict(root=root['pkg_id'],role=mode,units=len(units),watched={k:v['pkg_id']for k,v in selected.items()}))
    (w.ROOT/'cargo').rename(w.ROOT/'prefetched-cargo')
    print('Both ordinary graphs bound to the full registry and pinned Git roots.',flush=True)


if __name__=='__main__':
    {'acquire':acquire,'prefetch':prefetch}[sys.argv[1]]()
