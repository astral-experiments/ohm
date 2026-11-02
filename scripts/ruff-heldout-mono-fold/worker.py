"""One hosted, nonrelease Old-only qualification using the frozen ordinary Cargo probe."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import old_probe as probe

REPO = 'astral-experiments/ohm'
BRANCH = 'charlie/qa-heldout-mono-fold-27470-20261102'
SDK_DONOR = 'bd7b58765ae44b21a1c9273b3ff0be8e923adc47'
PROBE_HASH = 'ac77015f2ba4fc8c8dc7e3709d3fe40bf48d242590c0209ce459bdbc142de950'
need, sha = probe.need, probe.sha
ROOT = Path(os.environ['RUNNER_TEMP']).resolve(strict=True) / 'ohm-ruff27470-old'
WORKSPACE = Path(os.environ['GITHUB_WORKSPACE']).resolve(strict=True)
OUT, SDK, SRC = ROOT/'receipt', ROOT/'sdk', WORKSPACE/'ruff'
PROXY, REG = ROOT/'proxies', ROOT/'prefetch/cargo/registry'


def save(file, obj):
    file.write_text(json.dumps(obj, sort_keys=True, indent=1) + '\n')


def git(folder, *args):
    return subprocess.check_output(['git','--no-optional-locks','-C',folder,*args],text=True).strip()


def gh(path, *options):
    return ['gh','api',*options,'repos/'+REPO+'/'+path]


def checks():
    need(os.environ['GITHUB_REPOSITORY']==REPO and os.environ['GITHUB_REF']=='refs/heads/'+BRANCH and os.environ['GITHUB_RUN_ATTEMPT']=='1' and os.environ['GITHUB_EVENT_NAME']=='workflow_dispatch','different hosted event')
    need(git(WORKSPACE/'qa','rev-parse','HEAD')==os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD'] and git(WORKSPACE/'donor','rev-parse','HEAD')==SDK_DONOR,'different QA or acquisition source')
    need(not git(WORKSPACE/'qa','status','--porcelain','--untracked-files=all') and not git(WORKSPACE/'donor','status','--porcelain','--untracked-files=all'),'dirty diagnostic source')
    probe.source(SRC);need(sha(HERE/'old_probe.py')==PROBE_HASH,'different preregistered probe')


def acquire():
    checks();ROOT.mkdir();OUT.mkdir();log=OUT/'acquisition';log.mkdir()
    need(shutil.disk_usage(ROOT).free>22*probe.GB and probe.available()>9*probe.GB,'insufficient worker headroom')
    donor=WORKSPACE/'donor/scripts/ruff-default-owner-pmu';sys.path.insert(0,str(donor));import acquire as signed
    run_id=int(os.environ['GITHUB_RUN_ID']);workflow=json.loads(subprocess.check_output(gh(f'actions/runs/{run_id}')));jobs=json.loads(subprocess.check_output(gh(f'actions/runs/{run_id}/attempts/1/jobs?per_page=100')))
    need(jobs['total_count']==len(jobs['jobs'])==1 and workflow['run_attempt']==1 and workflow['event']=='workflow_dispatch' and workflow['head_branch']==BRANCH and workflow['head_sha']==os.environ['REVIEWED_HEAD'],'different enrollment')
    job,=jobs['jobs'];need(job['runner_name']==os.environ['RUNNER_NAME'] and job['id']>0 and job['runner_id']>0 and job['name']=='Signed Old ruff_db library test','different hosted worker')
    save(log/'worker.json',dict(repo=REPO,run=run_id,job=job['id'],runner_id=job['runner_id'],runner=job['runner_name'],boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),head=workflow['head_sha'],donor=SDK_DONOR,source=probe.OLD,source_tree=probe.TREE,lock=sha(SRC/'Cargo.lock'),probe=PROBE_HASH))
    expected=signed.c.SDK['asset'];remote=json.loads(subprocess.check_output(gh('releases/assets/'+str(expected['id']))));need((remote['id'],remote['name'],remote['size'],remote['digest'])==(expected['id'],expected['name'],expected['size'],'sha256:'+expected['sha256']),'different release asset')
    save(log/'asset.json',expected);archive=ROOT/expected['name']
    with archive.open('xb')as f:subprocess.run(gh('releases/assets/'+str(expected['id']),'-H','Accept: application/octet-stream'),stdout=f,check=True,timeout=600)
    identity=signed.extract(archive,SDK);need(len(identity)==79,'incomplete SDK');save(log/'sdk.json',identity);archive.unlink()
    PROXY.mkdir();rustup=Path(shutil.which('rustup')).resolve(strict=True);shutil.copy2(rustup,PROXY/'rustup');need(sha(PROXY/'rustup')==sha(rustup),'bad rustup shim')
    for name in ('cargo','rustc','rustdoc'):(PROXY/name).symlink_to('rustup')
    save(log/'rustup.json',dict(binary=sha(rustup),source=str(rustup)));print('Authenticated one worker and all 79 signed SDK members',flush=True)


def prefetch():
    checks();root=ROOT/'prefetch';log=OUT/'prefetch';log.mkdir()
    for part in ('home','cargo','rustup/toolchains','target','build','temp'):(root/part).mkdir(parents=True)
    (root/'rustup/settings.toml').write_text('version = "12"\nprofile = "minimal"\n');(root/'rustup/toolchains/ohm').symlink_to(SDK)
    env={'HOME':str(root/'home'),'RUSTUP_HOME':str(root/'rustup'),'RUSTUP_AUTO_INSTALL':'0','PATH':str(PROXY)+':/usr/bin:/bin','CARGO_HOME':str(root/'cargo'),'CARGO_TARGET_DIR':str(root/'target'),'CARGO_BUILD_BUILD_DIR':str(root/'build'),'TMPDIR':str(root/'temp'),'LC_ALL':'C','CARGO_TERM_COLOR':'never','CARGO_CACHE_AUTO_CLEAN_FREQUENCY':'never'}
    sdk=probe.sdk_identity(SDK,env);cfg=subprocess.check_output(['rustc','+ohm','--print','cfg'],env=env,text=True).splitlines();need('target_arch="x86_64"' in cfg and 'target_pointer_width="64"' in cfg,'not bound Linux x86_64 target');save(log/'compiler.json',dict(inputs=sdk,target_cfg=cfg))
    argv=[arg for arg in probe.CMD if arg!='--offline']+['-Zunstable-options','--unit-graph']
    with (log/'unit-graph.json').open('xb')as out,(log/'source-fetch.stderr').open('xb')as err:r=subprocess.run(argv,env=env,cwd=SRC,stdout=out,stderr=err,timeout=900)
    need(r.returncode==0 and probe.plan_id((log/'unit-graph.json').read_bytes())==probe.PLAN,'online preparation could not resolve the frozen normal closure')
    lock=tomllib.loads((SRC/'Cargo.lock').read_text());wanted={p['name']+'-'+p['version']+'.crate':p['checksum']for p in lock['package'] if p.get('source','').startswith('registry+')};archives=sorted((REG/'cache/index.crates.io-1949cf8c6b5b557f').glob('*.crate'));need(100<len(archives)<350,'source archive inventory')
    actual={f.name:sha(f) for f in archives};need(all(wanted.get(k)==v for k,v in actual.items()),'a registry archive differs from the historical lock');save(log/'archives.json',actual);save(log/'command.json',dict(argv=argv,plan=probe.PLAN));print(f'Prepared {len(actual)} authenticated archives with no native build',flush=True)


def run():
    checks();subprocess.run([sys.executable,'-IB',str(HERE/'old_probe.py'),'--src',SRC,'--sdk',SDK,'--registry',REG,'--proxies',PROXY,'--state',ROOT/'state','--out',OUT/'old'],check=True)


def native_copy(path,dest,limit):
    need(path.resolve(strict=True).is_relative_to((ROOT/'state').resolve(strict=True)) and 0<path.stat().st_size<limit,'unowned or oversized product')
    h=hashlib.sha256();size=0
    with path.open('rb') as src,dest.open('xb') as disk,gzip.GzipFile(filename='',mode='wb',fileobj=disk,compresslevel=3,mtime=0) as out:
        for chunk in iter(lambda:src.read(1<<20),b''):size+=len(chunk);h.update(chunk);out.write(chunk)
    return dict(path=str(path),bytes=size,sha256=h.hexdigest(),compressed_sha256=sha(dest))


def seal():
    if not OUT.is_dir():return
    output=OUT/'physical';output.mkdir();old=OUT/'old';result={}
    try:
        rows=[json.loads(line) for line in (old/'cargo.stdout').read_bytes().splitlines() if line];products=[r for r in rows if r.get('reason')=='compiler-artifact'];test,=[r for r in products if r['target']['name']=='ruff_db' and r['profile']['test'] and r['target']['kind']==['lib']];provider,=[r for r in products if r['target']['name']=='annotate_snippets' and r['target']['kind']==['lib']];exe=Path(test['executable']);rlib,=(Path(f) for f in provider['filenames'] if f.endswith('.rlib'))
        with exe.open('rb') as f:header=f.read(64)
        need(header[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',header,18)[0]==62,'not x86_64 ELF');result['test_elf']=native_copy(exe,output/'test.elf.gz',512<<20);result['renderer_rlib']=native_copy(rlib,output/'renderer.rlib.gz',32<<20)
        graph,=[p for p in (ROOT/'state').rglob('dep-graph.bin') if p.parent.parent.name.startswith('ruff_db-') and not p.parent.name.endswith('-working')];result['graph']=dict(path=str(graph),sha256=sha(graph),bytes=graph.stat().st_size)
        if not (old/'old-dep-graph.bin.gz').is_file():native_copy(graph,output/'partial-dep-graph.bin.gz',1<<30)
        key=bytes.fromhex('b554b7ef7d0df494d29f9aa667828dea');need(struct.unpack('<QQ',key)==(0x94f40d7defb754b5,0xea8d8267a69a9fd2),'32/64 key confusion');result['enrolled_key_le_wire']=key.hex()
    except Exception as exc:result['partial']=str(exc)
    save(output/'archives.json',result)
    with tarfile.open(ROOT/'heldout-proof.tar','x') as t:t.add(OUT,arcname='receipt',recursive=True)
    print('Sealed receipts including all available native outputs',flush=True)
    if (old/'terminal.json').is_file():need('partial' not in result,'terminal marker lacks physical output custody')


if __name__=='__main__':
    action,=sys.argv[1:];{'acquire':acquire,'prefetch':prefetch,'run':run,'seal':seal}[action]()
