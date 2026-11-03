"""Unscored source and instruction attribution for the real Ruff #28444 check."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import perf_tools as perf

ROOT, OUT, KITS = perf.ROOT, perf.B, perf.KITS
need, sha, save = perf.need, perf.sha, perf.save
WS = Path(os.environ['GITHUB_WORKSPACE']).resolve(strict=True)
SRC, SDK, STATE = WS/'ruff', ROOT/'sdk', ROOT/'state'
OLD = 'c6c4d38bbeeae91fe59d9c277a78169db8306561'
NEW = '97065696c0e4dbe6ff43a89c73f923bf60ee231a'
TREES = {OLD:'73d8d9bec571b0d054371b2de8eb2dae1389a901', NEW:'9de45dbaa6d3f0f018d62acae836e65716013172'}
SOURCE = 'crates/ruff_annotate_snippets/src/snippet.rs'
FILES = ['crates/ruff_annotate_snippets/src/renderer/render.rs', SOURCE]
SOURCE_HASH = {OLD:'cef48ab7234b39d4c15ad512de6496ce65e45b981fe85a4fbbb3737c73e6568f', NEW:'272e25a6d121c3c57112e53e6ad9de3abc7ff88658008dbf4a9299b3399a7943'}
LOCK = '26d7be8317b0e44be0d60b31f6660dd4e07ed4c19be4e6748124d07068fd7fa7'
RUST = 'd57fd1515986dccecdcece8da85e651bfb4b81f9'
BRANCH = 'charlie/qa-ruff-27470-signed23-20261103'
DONOR = 'bd7b58765ae44b21a1c9273b3ff0be8e923adc47'
REPO = 'astral-experiments/ohm'
CMD = ['cargo','+ohm','check','-p','ty_server','--lib','--locked','--offline','--message-format=json']
FIRST = '`incorrect-blank-line-before-class` (D203) and `{}` (D211) are incompatible. Ignoring `incorrect-blank-line-before-class`.'
SECOND = '`multi-line-summary-first-line` (D212) and `multi-line-summary-second-line` (D213) are incompatible. Ignoring `multi-line-summary-second-line`.'
NATIVE = {OLD:[FIRST.format('no-blank-line-before-class'), SECOND], NEW:[FIRST.format('blank-line-before-class'), SECOND]}
GIB = 1 << 30


def git(folder, *argv):
    return subprocess.check_output(['git','--no-optional-locks','-C',folder,*argv], text=True).strip()


def gh(path, *options):
    return ['gh','api',*options,'repos/'+REPO+'/'+path]


def resources():
    match = re.search(r'^MemAvailable:\s+(\d+) kB$', Path('/proc/meminfo').read_text(), re.M)
    available = int(match[1]) * 1024
    free = shutil.disk_usage(ROOT).free
    need(available >= 8*GIB and free >= 15*GIB, f'headroom floor: RAM {available}, disk {free}')
    return [available, free]


def source(rev):
    need(git(SRC,'rev-parse','HEAD') == rev and git(SRC,'rev-parse','HEAD^{tree}') == TREES[rev], 'source revision or tree')
    need(not git(SRC,'status','--porcelain','--untracked-files=all') and sha(SRC/SOURCE) == SOURCE_HASH[rev] and sha(SRC/'Cargo.lock') == LOCK, 'dirty Ruff input')
    need(git(SRC,'rev-parse',NEW+'^') == OLD and git(SRC,'diff','--name-only',OLD,NEW).splitlines() == FILES, 'historical source transition')


def checked_head():
    need(os.environ['GITHUB_REPOSITORY'] == REPO and os.environ['GITHUB_REF'] == 'refs/heads/'+BRANCH and os.environ['GITHUB_EVENT_NAME'] == 'workflow_dispatch' and os.environ['GITHUB_RUN_ATTEMPT'] == '1', 'worker enrollment')
    need(git(WS/'qa','rev-parse','HEAD') == os.environ['GITHUB_SHA'] == os.environ['REVIEWED_HEAD'] and git(WS/'donor','rev-parse','HEAD') == DONOR, 'QA head or SDK helper')
    for path in (WS/'qa', WS/'donor'):
        need(not git(path,'status','--porcelain','--untracked-files=all'), 'dirty helper checkout')
    need(sha(KITS/'exec_count.c') == '1c80d6640d8bfdad197839552c7c324c3d74be189718e7702cfaa4a1e2f71e43' and sha(KITS/'perf_hook.py') == '67ffd29e3bf97cea39f71e5a3d5fd685b89746402f283e35835ac1fdaeea928b','counter source')


def acquire():
    checked_head(); source(NEW)
    ROOT.mkdir(); OUT.mkdir(); resources()
    need(shutil.disk_usage(ROOT).free > 26*GIB, 'initial storage')
    run = int(os.environ['GITHUB_RUN_ID'])
    info = json.loads(subprocess.check_output(gh(f'actions/runs/{run}')))
    jobs = json.loads(subprocess.check_output(gh(f'actions/runs/{run}/attempts/1/jobs?per_page=100')))
    need(info['head_sha'] == os.environ['REVIEWED_HEAD'] and info['head_branch'] == BRANCH and info['run_attempt'] == 1 and info['event'] == 'workflow_dispatch' and jobs['total_count'] == len(jobs['jobs']) == 1, 'hosted run identity')
    job, = [j for j in jobs['jobs'] if j['runner_name'] == os.environ['RUNNER_NAME'] and j['runner_id'] > 0]
    name = 'Verify the newly released SDK and the actual historical check'
    need(job['name'] == name and job['status']=='in_progress', 'worker identity')
    save(OUT/'worker.json',dict(run=run,job=job['id'],head=info['head_sha'],runner=job['runner_name'],runner_id=job['runner_id'],boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),source=TREES,lock=LOCK,resources=resources()))
    sys.path.insert(0,str(WS/'donor/scripts/ruff-default-owner-pmu'))
    import acquire as signed
    import signed23
    signed23.install(sys.modules[__name__], signed.c.SDK["members"])
    proxy=ROOT/'proxies'; proxy.mkdir(); rustup=Path(shutil.which('rustup')).resolve(strict=True); shutil.copy2(rustup,proxy/'rustup')
    need(sha(proxy/'rustup') == sha(rustup),'different rustup proxy')
    for name in ('cargo','rustc','rustdoc'):
        (proxy/name).symlink_to('rustup')
    for p in (ROOT/'home', ROOT/'temp', ROOT/'rustup/toolchains', ROOT/'cargo'):
        p.mkdir(parents=True)
    (ROOT/'rustup/toolchains/ohm').symlink_to(SDK); (ROOT/'rustup/settings.toml').write_text('version = "12"\nprofile = "minimal"\n')
    print('Authenticated signed GNU SDK and the historical source trees.',flush=True)


def environment():
    return {'HOME':str(ROOT/'home'),'RUSTUP_HOME':str(ROOT/'rustup'),'RUSTUP_AUTO_INSTALL':'0','PATH':str(ROOT/'proxies')+':/usr/bin:/bin','CARGO_HOME':str(ROOT/'cargo'),'CARGO_TARGET_DIR':str(STATE/'target'),'CARGO_BUILD_BUILD_DIR':str(STATE/'build'),'CARGO_BUILD_JOBS':'8','CARGO_NET_OFFLINE':'true','CARGO_CACHE_AUTO_CLEAN_FREQUENCY':'never','TMPDIR':str(ROOT/'temp'),'LC_ALL':'C','CARGO_TERM_COLOR':'never','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'}


def prefetch():
    checked_head(); source(NEW); resources()
    env=environment(); del env['CARGO_NET_OFFLINE']
    v=subprocess.check_output(['rustc','+ohm','-vV'],env=env,text=True)
    need('commit-hash: '+RUST+'\n' in v and 'host: x86_64-unknown-linux-gnu\n' in v,'actual rustc')
    cargo=subprocess.check_output(['cargo','+ohm','-Vv'],env=env,text=True)
    need('7024b0d2dc5f64bba72c0d6d28f537a5cd9707ed' in cargo and RUST in v, 'wrong executing release sources')
    save(OUT/'actual-sdk.json',dict(rustc=v,cargo=cargo,shim=sha(ROOT/'proxies/rustup')))
    argv=[arg for arg in CMD if arg!='--offline']+['-Zunstable-options','--unit-graph']
    with (OUT/'unit-graph.json').open('xb') as out:
        subprocess.run(argv,cwd=SRC,env=env,stdout=out,check=True,timeout=900)
    graph=json.loads((OUT/'unit-graph.json').read_bytes()); roots=[graph['units'][i] for i in graph['roots']]
    need(len(roots)==1 and roots[0]['target']['name']=='ty_server' and roots[0]['target']['kind']==['lib'] and roots[0]['mode']=='check','incorrect ordinary unit graph')
    wanted={p['name']+'-'+p['version']+'.crate':p['checksum'] for p in tomllib.loads((SRC/'Cargo.lock').read_text())['package'] if p.get('source','').startswith('registry+')}
    archives=sorted((ROOT/'cargo/registry/cache').glob('*/*.crate')); actual={p.name:sha(p)for p in archives}
    need(100 < len(archives)==len(actual) <= len(wanted) and all(wanted.get(k)==v for k,v in actual.items()),'registry custody')
    save(OUT/'registry.json',actual)
    (ROOT/'cargo').rename(ROOT/'prefetched-cargo')
    print('Frozen normal unit graph and authenticated',len(actual),'crate archives.',flush=True)


def run(argv,env,out,expected=0,timeout=1500):
    out.mkdir(); start=time.monotonic(); minima=resources()
    with (out/'stdout').open('xb') as stdout,(out/'stderr').open('xb') as stderr:
        child=subprocess.Popen(list(map(str,argv)),env=env,cwd=SRC,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
        try:
            while child.poll() is None:
                need(time.monotonic()-start < timeout,'subprocess budget')
                minima=list(map(min,zip(minima,resources())))
                time.sleep(.35)
        except BaseException:
            os.killpg(child.pid,signal.SIGKILL);child.wait();raise
    save(out/'command.json',dict(argv=list(map(str,argv)),exit=child.returncode,minimum_memory_disk=minima))
    if child.returncode != expected:
        print((out/'stderr').read_text(errors='replace')[-2700:],flush=True)
    need(child.returncode==expected,'unexpected exit at '+out.name)


def cargo_result(out, expected=True):
    records=[json.loads(row)for row in (out/'stdout').read_bytes().splitlines() if row]
    need([r['success']for r in records if r['reason']=='build-finished']==[expected], 'missing terminal Cargo verdict')
    arts=[r for r in records if r['reason']=='compiler-artifact']
    inventory=sorted([[r['package_id'],r['target']['name'],r['target']['kind'],sorted(r['features']),json.dumps(r['profile'],sort_keys=True),sorted(Path(f).name for f in r['filenames']),r['fresh']] for r in arts])
    diagnostics=[r['message']for r in records if r['reason']=='compiler-message']; errs=[r for r in diagnostics if r['level']=='error']; codes=[(r.get('code') or {}).get('code')for r in errs]
    meta_inputs=sorted([[r['package_id'],r['target']['name'],Path(f).name,sha(Path(f))] for r in arts for f in r['filenames'] if Path(f).suffix=='.rmeta'])
    save(out/'cargo.json',dict(inventory=inventory,metadata=meta_inputs,errors=codes))
    need((not errs) if expected else ('E0308' in codes and any(SOURCE in str(r['spans']) and 'OHM_INVALID_CHECK_SENTINEL' in str(r['spans'])for r in errs)), 'different Cargo diagnostics')
    need(b'internal compiler error' not in (out/'stderr').read_bytes().lower(),'compiler ICE')
    if not expected:
        return
    root,=[r for r in arts if r['target']['name']=='ruff_linter' and r['target']['kind']==['lib']]
    meta,=[Path(f) for f in root['filenames'] if Path(f).suffix=='.rmeta']; need(meta.is_file() and meta.stat().st_size>1024,'missing actual metadata')
    dirs=sorted({Path(f).parent for r in arts for f in r['filenames']})
    return inventory, meta, dirs


def native(out,revision,meta,dirs,env):
    body=out/'oracle.o'; exe=out/'oracle'; flags=[arg for p in dirs for arg in ('-L','dependency='+str(p))]
    argv=['rustc','+ohm','--edition=2024','--crate-name','observed_messages','--crate-type=lib','--emit=obj','-Copt-level=1',HERE/'oracle.rs','--extern','ruff_linter='+str(meta),*flags,'-o',body]
    subprocess.run(argv,env=env,cwd=SRC,check=True,timeout=120)
    subprocess.run(['/usr/bin/cc','-O1','-no-pie',HERE/'oracle.c',body,'-o',exe],env=env,check=True,timeout=60)
    messages=subprocess.check_output([exe],env=env,timeout=10).decode().splitlines(); need(messages==NATIVE[revision],'stale or incorrect diagnostic messages')
    digest=sha(meta); store=OUT/'members';store.mkdir(exist_ok=True); saved=store/(digest+'.rmeta.zst')
    if not saved.exists():
        with saved.open('xb')as f:subprocess.run(['zstd','-q','-3','-c',meta],stdout=f,check=True)
    record=dict(metadata=digest,bytes=meta.stat().st_size,member_sha256=sha(saved),native_object=sha(body),executable=sha(exe),messages=messages)
    save(out/'native.json',record); return record


def fresh_state():
    if STATE.exists():
        need(STATE.parent==ROOT and not STATE.is_symlink(),'different sacrificial state');shutil.rmtree(STATE)
    STATE.mkdir()
    # The main paths are identical each time. Only pristine, lockfile-verified
    # registry input is imported. A prior role cannot donate built products.
    cargo=ROOT/'cargo'
    if cargo.exists():
        need(not cargo.is_symlink(),'different sacrificial Cargo home');shutil.rmtree(cargo)
    subprocess.run(['cp','-a','--reflink=auto',ROOT/'prefetched-cargo',cargo],check=True)


def tree_identity(base):
    """Verify every file and symlink at the inherited fixed-path pre-check snapshot."""
    h=hashlib.sha256(); total=0; files=0; links={}
    for folder, dirs, names in os.walk(base, followlinks=False):
        dirs.sort(); names.sort()
        for name in sorted([*dirs,*names]):
            path=Path(folder)/name; rel=path.relative_to(base).as_posix(); stat=path.lstat()
            if path.is_symlink():body=['link',os.readlink(path)]
            elif path.is_file():
                identity=(stat.st_dev,stat.st_ino); first=links.setdefault(identity,rel)
                body=['file',first,stat.st_size,sha(path)];total+=stat.st_size;files+=1
            else:
                need(path.is_dir(),'unexpected Old special file');body=['dir']
            h.update(json.dumps([rel,stat.st_mode,stat.st_mtime_ns,body],separators=(',',':')).encode()+b'\n')
    return dict(sha256=h.hexdigest(),files=files,bytes=total)


def make_snapshot():
    snap=ROOT/'before-edit';snap.mkdir(); parts={}
    for name,src in [('state',STATE),('cargo',ROOT/'cargo'),('home',ROOT/'home'),('temp',ROOT/'temp')]:
        parts[name]=tree_identity(src)
        need(shutil.disk_usage(ROOT).free > 15*GIB+parts[name]['bytes']+2*GIB,'snapshot storage reserve')
        subprocess.run(['cp','-a','--reflink=auto',src,snap/name],check=True)
        need(tree_identity(snap/name)==parts[name],'physical Old snapshot for '+name)
    times={f:(SRC/f).stat().st_mtime_ns for f in FILES};save(OUT/'original-donor.json',dict(source=OLD,parts=parts,source_mtimes=times));return parts,times


def restore_snapshot(parts,times):
    checkout(OLD)
    for name,mtime in times.items():
        path=SRC/name;os.utime(path,ns=(path.stat().st_atime_ns,mtime))
    for name,dst in [('state',STATE),('cargo',ROOT/'cargo'),('home',ROOT/'home'),('temp',ROOT/'temp')]:
        origin=ROOT/'before-edit'/name; need(dst.parent==ROOT and dst.is_dir()and not dst.is_symlink(),'sacrificial restore location')
        shutil.rmtree(dst);subprocess.run(['cp','-a','--reflink=auto',origin,dst],check=True)
        need(tree_identity(dst)==parts[name],'restored prior bytes/mtimes/hardlinks for '+name)


def checkout(revision):
    subprocess.run(['git','-C',SRC,'switch','--detach',revision],check=True,stdout=subprocess.DEVNULL); source(revision)


def setup_perf():
    checked_head(); resources(); env=environment(); path=perf.prepare_perf(); observer=ROOT/'exec-count'
    subprocess.run(['/usr/bin/cc','-O2','-o',observer,KITS/'exec_count.c'],check=True)
    probe=ROOT/'burn.c';probe.write_text('#include <stdint.h>\nint main(void){ volatile uint64_t x=1; for(uint64_t i=0;i<10000000;i++) x=x*33+i; return x==0; }\n')
    runner=ROOT/'burn';subprocess.run(['/usr/bin/cc','-O1','-o',runner,probe],check=True)
    case=OUT/'calibration';case.mkdir();raw=case/'perf.data'; restore=['/usr/bin/env','-i',*(k+'='+v for k,v in env.items())]
    subprocess.run(perf.record(path,raw,[*restore,observer,case,runner,'calibrate'],perf.PERIOD),env=env,check=True,timeout=90)
    count=perf.decode(path,raw,case);need(count>=10,'hardware calibration');raw.unlink()
    save(OUT/'calibration.json',dict(samples=count,period=perf.PERIOD,observer=sha(observer),hook=sha(KITS/'perf_hook.py'),path=str(path)))
    return path,observer


def study():
    checked_head(); source(NEW); path,observer=setup_perf(); env=environment(); summaries={}; saved_epochs={}
    fresh_state();checkout(OLD);out=OUT/'prepare-old';run(CMD,env,out);_,meta,dirs=cargo_result(out);native(out,OLD,meta,dirs,env)
    parts,times=make_snapshot();edit_times={}
    for role in ('ordinary','profiled'):
        restore_snapshot(parts,times);d=OUT/role;d.mkdir(); totals={}
        for stage,rev in (('old',OLD),('old-unchanged',OLD),('edit',NEW),('new-unchanged',NEW)):
            if stage=='edit':
                checkout(NEW)
                if role=='ordinary':
                    edit_times={f:(SRC/f).stat().st_mtime_ns for f in FILES};save(OUT/'changed-source-mtimes.json',edit_times)
                else:
                    for f,t in edit_times.items():
                        file=SRC/f;os.utime(file,ns=(file.stat().st_atime_ns,t))
            out=d/stage; cmd=CMD
            if role=='profiled' and stage=='edit':
                epochs=d/'epochs';epochs.mkdir();raw=d/'edit.perf.data';restore=['/usr/bin/env','-i',*(k+'='+v for k,v in env.items())];cmd=perf.record(path,raw,[*restore,observer,epochs,*CMD],perf.PERIOD)
            run(cmd,env,out); inventory,meta,dirs=cargo_result(out)
            if stage=='edit':need(any(r[1]=='ruff_linter' and not r[-1]for r in inventory),'root genuinely changed')
            if stage=='old' or stage.endswith('unchanged'):need(all(r[-1]for r in inventory),'unexpected unchanged compiler artifact')
            totals[stage]=dict(inventory=inventory,metadata=json.loads((out/'cargo.json').read_bytes())['metadata'],native=native(out,rev,meta,dirs,env))
            if role=='profiled' and stage=='edit':
                need(0<raw.stat().st_size<256<<20,'profile size');count=perf.decode(path,raw,out)
                with (out/'perf.data.zst').open('xb')as f:subprocess.run(['zstd','-q','-3','-c',raw],stdout=f,check=True)
                saved_epochs=dict(samples=count,raw_sha256=sha(raw),bytes=raw.stat().st_size,compressed=sha(out/'perf.data.zst'));save(out/'perf.json',saved_epochs);raw.unlink()
        summaries[role]=totals
    real=(SRC/SOURCE).read_bytes();(SRC/SOURCE).write_bytes(real+b'\nconst OHM_INVALID_CHECK_SENTINEL: u64 = "incorrect";\n')
    try:
        out=OUT/'invalid';run(CMD,env,out,101);cargo_result(out,False)
    finally:
        (SRC/SOURCE).write_bytes(real)
    source(NEW);out=OUT/'repair';run(CMD,env,out);_,meta,dirs=cargo_result(out); repaired=native(out,NEW,meta,dirs,env)
    root_paths=[p for p in STATE.rglob('libruff_linter*.rmeta')if p.is_file()];need(meta in root_paths,'missing selected root before its empty control')
    out=OUT/'remove-root';run(['cargo','+ohm','clean','-p','ruff_linter','--offline','--locked'],env,out)
    need(not any(p.exists()for p in root_paths),'Cargo retained the selected root metadata after clean')
    leftovers=[str(p)for p in STATE.rglob('*')if p.is_file()and p.name in ('dep-graph.bin','work-products.bin','query-cache.bin')and any(bit.startswith('ruff_linter-')for bit in p.parts)]
    save(out/'empty-root.json',dict(removed=[str(p)for p in root_paths],leftovers=leftovers));need(not leftovers,'Cargo retained an incremental root session after clean')
    out=OUT/'pinned-empty-new';run(CMD,env,out);inv,meta,dirs=cargo_result(out);need([r[1]for r in inv if not r[-1]]==['ruff_linter'],'empty root must retain the pinned dependency products');pinned=native(out,NEW,meta,dirs,env)
    fresh_state();out=OUT/'empty-new';run(CMD,env,out);_,meta,dirs=cargo_result(out); clean=native(out,NEW,meta,dirs,env)
    for stage in ('old','old-unchanged','edit','new-unchanged'):
        need(summaries['ordinary'][stage]==summaries['profiled'][stage],'plain versus observed artifact or native mismatch at '+stage)
    need(summaries['ordinary']['edit']['native']==repaired==pinned,'warm, repaired or dependency-pinned clean root mismatch')
    need(all(pinned[k]==clean[k]for k in ('native_object','executable','messages')),'independent complete clean native output mismatch')
    need(summaries['ordinary']['old']['native']['metadata']!=clean['metadata'] and summaries['ordinary']['old']['native']['native_object']!=clean['native_object'],'edit did not change real outputs')
    save(OUT/'admission.json',dict(ordinary=summaries['ordinary'],profile=saved_epochs,repair=repaired,pinned_empty=pinned,independent_empty=clean,scope='Unscored signed compiler attribution from one fixed prior state. Independent all-dependency clean native output checked; its rmeta envelope is recorded independently.',resources=resources()))
    print('Admitted complete original and profiled edit, unchanged controls, E0308 repair and empty native proofs.',flush=True)


if __name__=='__main__':
    {'acquire':acquire,'prefetch':prefetch,'study':study}[sys.argv[1]]()
