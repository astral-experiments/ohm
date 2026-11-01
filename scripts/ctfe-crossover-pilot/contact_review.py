"""Verify one original contact independently, or acquire its official ZIP before admitting a fresh pilot."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import re
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import ctfe_pilot_registration as reg
import source_guard
import reopen as native

require = reg.require
D = native.dataset

def fixtures(z, base, repo):
    prefix = 'scripts/branch-return-execstop'
    source_guard.tree(repo,reg.OBSERVER,prefix)
    source_guard.tree(repo,reg.OBSERVER,'scripts/branch-return-pmu')
    script = repo/prefix/'group_fixtures.py'
    require(reg.sha(repo/prefix/'SHA256SUMS') == reg.OBSERVER_MANIFEST, 'unregistered fixture source manifest')
    require(reg.sha(repo/prefix/'kernel/read_events.py') == reg.READER and
            reg.sha(repo/prefix/'kernel/observe.c') == reg.SOURCE, 'different reviewed observer')
    members = [p for p in z.infolist() if p.filename.startswith(base+'/') and not p.is_dir()]
    names = [p.filename[len(base)+1:] for p in members]
    require(0 < len(names) <= 144 and len(set(names)) == len(names) and
            sum(p.file_size for p in members) <= 12*2**20, 'fixture inventory or byte budget')
    with tempfile.TemporaryDirectory(prefix='ctfe-v3-fixtures-') as d:
        out = Path(d)
        for name,item in zip(names,members,strict=True):
            file = out/name
            require(file.resolve().is_relative_to(out) and '' not in name.split('/') and
                    all(c not in ('.','..') for c in name.split('/')) and
                    0 <= item.file_size <= 4*2**20 and
                    (not (item.external_attr >> 16)&0o170000 or stat.S_ISREG(item.external_attr >> 16)),
                    'unsafe or oversized fixture member')
            file.parent.mkdir(parents=True,exist_ok=True)
            with z.open(item) as src,file.open('xb') as dst:
                shutil.copyfileobj(src,dst)
        stdout = subprocess.check_output([sys.executable,'-IB',script,'reopen',out],timeout=120)
        require(stdout == (out/'group-v2/qualified.json').read_bytes(), 'host fixture original is not reproducible')
    return json.loads(stdout)

def host_guards(z, pos):
    zr = D(z,'resource/resources.json')
    minimum = zr['minimum']
    require(zr['exit'] == 0 and zr['refusal'] is None and minimum['work'] >= 4*2**30 and
            minimum['receipts'] >= 6*2**30 and minimum['effective'] >= 8*2**30, 'real resource guard refused')
    h = D(z,'host.json')
    observed = dict(boot=h['raw_system']['/proc/sys/kernel/random/boot_id'], affinity=h['affinity'],
                    machine=h['platform']['machine'], release=h['platform']['release'])
    reg.host(observed)
    require(h['platform']['system'] == 'Linux' and pos['host'] == observed and pos['boot'] == observed['boot']
            and pos['hardware_gate'] == reg.hardware_gate(), 'different host receipt or previous hardware gate')
    return minimum

def read(zip_path, meta, repo):
    require(meta['mode'] == 'contact' and len(meta['files']) == 1 and meta['files'][0]['position'] == '01', 'not a contact')
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        require(len(names) == len(z.infolist()) and all(not Path(n).is_absolute() and '..' not in n.split('/') for n in names)
                and 'failure.txt' not in names, 'refused, duplicate or unsafe contact')
        pos = D(z,'position.json')
        require((pos['mode'],pos['position'],pos['order'],int(pos['run']),pos['head'],pos['command'],pos['plan']) ==
                ('contact','01',['Eon'],meta['run'],meta['head'],native.CARGO,reg.sha(HERE/'PLAN.md')), 'different contact enrollment')
        resource = host_guards(z,pos)
        boot = pos['boot']
        binding = native.kernel_binding(z,boot,'contact',repo,None)
        sdk = native.sdk_pair(z)
        refs, stages, bodies, checked_files = {}, {}, {}, {}
        visit_paths, traced_paths, helpers, compiler_groups = set(), set(), {}, {}
        env = None
        for lane, route, phases in [('clean','reference',native.REFS),('structural','return',native.PHASES[:4])]:
            top = lane+'-'+route+'-Eon'
            cert,root = native.active(z,top,'Eon',sdk['E']['files'])
            require(binding['observer'] == str(root/'kernel-qualification/tools/observe'), 'wrong current recorder path')
            require(env is None or env == cert['env'], 'contact Cargo environment changed')
            env = cert['env']
            for phase in phases:
                prefix = top+'/'+phase
                r = native.read_phase(z,prefix,phase,lane,route,'Eon',cert,root,bodies)
                visit_paths.add(prefix+'/visit.json')
                if lane == 'clean':
                    refs[phase] = r
                else:
                    ref=refs[r['reference']]
                    require(r['native'] == ref['native'] and r['graph'] == ref['graph'], 'warm and own empty native/typed verdict differ')
                if phase in ('X-B','comment'):
                    traced_paths.add(prefix+'/kernel.tsv.gz')
                    helpers[phase] = r['wild_helpers']
                    compiler_groups[phase] = r['compiler_groups']
                stages[phase] = {k:r[k] for k in ('status','graph','dirty','cli','reader','allocated')}
                if 'kernel' in r:
                    stages[phase].update(kernel=r['kernel'], native_roster=native.digest(z.read(prefix+'/native-execs.json.gz')),
                                         full_units=r['full_units'], link_units=r['link_units'])
                checked_files[phase] = {name:native.digest(z.read(prefix+'/'+name)) for name in
                                         ('source.json','visit.json','cargo.json.gz','cargo.stdout.gz','cargo.stderr.gz','native.json.gz')}
        require(any(compiler_groups.values()), 'no real installed compiler needed group-exit protection')
        require(refs['clean-A']['cli'] != refs['clean-B']['cli'] and any(helpers.values()), 'no actual inherited Wild fork-group or historical CLI difference')
        require(visit_paths == {n for n in names if n.endswith('/visit.json')} and
                traced_paths == {n for n in names if n.endswith('/kernel.tsv.gz')} and
                {n.removesuffix('/kernel.tsv.gz') for n in traced_paths} ==
                {n.removesuffix('/compiler-groups.json') for n in names if n.endswith('/compiler-groups.json')} and
                not any(n.endswith('/clock.json') or n in ('meter-ready.json','pilot.json','observer.json') or
                        n.startswith(('measured-','calibration/')) for n in names), 'extra visits, trace or PMU command in contact')
        require(D(z,'contact.json') == dict(qualified=True,mode='contact',boot=boot,scored_commands=0,
                visits=list(native.PHASES[:4]),helpers=helpers,compiler_groups=compiler_groups,schema=3,issues=[]), 'different host contact conclusion')
        return dict(qualified=True, schema=3, official=meta, head=pos['head'], boot=boot, kernel=pos['host']['release'],
                    observer_source=reg.OBSERVER, observer_sha256=binding['observer_sha256'], fixture=binding['group_fixtures_sha256'],
                    historical_readers=reg.hardware_gate(), resource=resource, helpers=helpers, compiler_groups=compiler_groups, visits=stages,
                    original_receipts=checked_files, checked_elfs=len(bodies), scored_commands=0)

def from_official(archive, catalog, run, head, repo):
    meta = reg.official(catalog,run,head,'contact',[archive])
    return read(archive,meta,repo)

def encoded(result):
    return (json.dumps(result,sort_keys=True,separators=(',',':'))+'\n').encode()

def acquire(run, digest, expected_readback, head, repo, output):
    require(not output.exists() and run>0 and all(re.fullmatch('[0-9a-f]{64}',v) for v in (digest,expected_readback)), 'invalid sealed contact input')
    with tempfile.TemporaryDirectory(prefix='ctfe-v3-intake-') as tmp:
        t=Path(tmp)
        for name,url in [('run.json',f'actions/runs/{run}'),('jobs.json',f'actions/runs/{run}/attempts/1/jobs?per_page=100'),
                         ('artifacts.json',f'actions/runs/{run}/artifacts?per_page=100')]:
            (t/name).write_bytes(subprocess.check_output(['gh','api',f'repos/{reg.REPO}/{url}']))
        original, = reg.official(t,run,head,'contact')['files']
        require(original['sha256'] == digest, 'different reviewed official contact ZIP')
        with (t/'contact.zip').open('xb') as f:
            subprocess.run(['gh','api',f"repos/{reg.REPO}/actions/artifacts/{original['artifact']}/zip"],stdout=f,check=True)
        result = from_official(t/'contact.zip',t,run,head,repo)
    data = encoded(result)
    require(hashlib.sha256(data).hexdigest() == expected_readback, 'different independently approved contact readback')
    with output.open('xb') as f:
        f.write(data)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    for cmd in ('offline','acquire'):
        q=sub.add_parser(cmd)
        q.add_argument('--run',type=int,required=True);q.add_argument('--head',required=True)
        q.add_argument('--observer-source',type=Path,required=True)
        if cmd=='offline':
            q.add_argument('--official',type=Path,required=True);q.add_argument('archive',type=Path)
        else:
            q.add_argument('--sha256',required=True);q.add_argument('--readback-sha256',required=True);q.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.command=='acquire':
        acquire(a.run,a.sha256,a.readback_sha256,a.head,a.observer_source.resolve(),a.output)
    else:
        sys.stdout.buffer.write(encoded(from_official(a.archive,a.official,a.run,a.head,a.observer_source.resolve())))
