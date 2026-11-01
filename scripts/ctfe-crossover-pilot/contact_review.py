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
import wild_fork
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
                ('contact','01',list(native.ROLES),meta['run'],meta['head'],native.CARGO,reg.sha(HERE/'PLAN.md')), 'different contact enrollment')
        resource=host_guards(z,pos)
        boot=pos['boot']
        binding=native.kernel_binding(z,boot,'contact',repo,None)
        stock=wild_fork.stock_fixture(D(z,'kernel-qualification/fixtures/group-v2/qualified.json'))
        sdk=native.sdk_pair(z)
        visit_names,trace_names,selected_names=set(),set(),set()
        products,loaded,scopes,source_selections,closures={},{},{},{},{}
        environment=None
        for arm in native.ROLES:
            scopes[arm]={};source_selections[arm]={};closures[arm]={}
            for line,phases in [('reference',native.REFS),('return',native.PHASES[:5]),('dirty',native.PHASES[:5])]:
                lane='clean' if line=='reference' else 'structural'
                top=lane+'-'+line+'-'+arm
                cert,root=native.active(z,top,arm,sdk[arm[0]]['files'])
                require(binding['observer']==str(root/'kernel-qualification/tools/observe') and
                        (environment is None or environment==cert['env']), 'different CLI roots or flags')
                environment=cert['env']
                visits={}
                for phase in phases:
                    p=top+'/'+phase
                    visits[phase]=v=native.read_phase(z,p,phase,lane,line,arm,cert,root,loaded)
                    visit_names.add(p+'/visit.json')
                    if lane=='clean':
                        products[arm,phase]=v
                        continue
                    want=products[arm,v['reference']]
                    require(v['native']==want['native'] and v['graph']==want['graph'],
                            'different same-arm clean CLI/consumer or graph')
                    if phase in native.TRACED[line]:
                        trace_names.add(p+'/kernel.tsv.gz')
                        ledger=gzip.decompress(z.read(p+'/kernel.tsv.gz'))
                        census=native.kernel.parse(ledger,expected_code=0,expected_schema=3)
                        links=D(z,p+'/native-execs.json.gz')['wild_processes']
                        closures[arm][line+'/'+phase]=wild_fork.finish(ledger,census,links)
                        if phase=='X-B':
                            require(any(x['rustc_crate']=='ruff' for x in links),'real historical change did not link the CLI')
                if lane=='clean':
                    require(products[arm,'clean-A']['cli']!=products[arm,'clean-B']['cli']
                            and products[arm,'clean-semantic']['cli']!=products[arm,'clean-B']['cli'],
                            'historical/private edits must each change the executable')
                    continue
                req=top+'/comment/donor-selected.json'
                selected_names.add(req)
                source_selections[arm][line]=native.donor_history(z,top,arm,sdk[arm[0]])
                c=visits['comment']
                require(visits['unchanged']['source']==c['source'] and visits['unchanged']['cli']==c['cli'],
                        'changed inputs or executable on immediate repeat')
                scopes[arm][line]=dict(visits=list(phases),full=c['compilers'],donor=native.digest(z.read(req)),
                                       cli=c['cli'],native_links=c['links'])
        for phase in native.REFS:
            e,d=(products[arm,phase] for arm in native.ROLES)
            require(e['graph']==d['graph'] and native.behavior(e['native'])==native.behavior(d['native'])
                    and all(e['native'][kind][part]==d['native'][kind][part] for kind in ('cli','reader')
                            for part in ('loads','executable')), 'different native clean reference across compilers')
        require(all(v=={n for n in names if n.endswith('/'+suffix)}
                    for v,suffix in ((visit_names,'visit.json'),(trace_names,'kernel.tsv.gz'),(selected_names,'donor-selected.json')))
                and not any(n.endswith('/clock.json') or n in ('meter-ready.json','pilot.json','observer.json')
                            or n.startswith(('measured-','calibration/')) for n in names), 'unregistered acquisition on the unscored contact')
        registered=dict(qualified=True,schema=3,mode='contact',boot=boot,scored_commands=0,scopes=scopes,issues=[])
        require(D(z,'contact.json')==registered, 'contact reporting differs from reopened originals')
        from collections import Counter
        e,d=(scopes[arm]['return'] for arm in native.ROLES)
        e_full=Counter(n for n,mode in e['full'] if mode=='full')
        d_full=Counter(n for n,mode in d['full'] if mode=='full')
        require(e_full>d_full and d['native_links']<=e['native_links'],
                'no strict reduction of full compilers on the actual CLI or additional Wild links')
        return dict(qualified=True,schema=3,official=meta,head=pos['head'],boot=boot,kernel=pos['host']['release'],
                    observer_source=reg.OBSERVER,observer_sha256=binding['observer_sha256'],fixture=binding['group_fixtures_sha256'],
                    source_qualification=reg.hardware_gate(),resource=resource,scopes=scopes,source_selections=source_selections,
                    wild_fork_exits=closures,stock_wild_fixture=stock,checked_elfs=len(loaded),scored_commands=0)

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
