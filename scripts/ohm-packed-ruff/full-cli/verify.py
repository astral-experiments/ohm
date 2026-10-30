"""Recompute the portable disk-only result from captured names, Cargo JSON and native witnesses."""
import gzip, hashlib, json, os, stat, subprocess, sys, tempfile
from pathlib import Path

os.environ.setdefault('RUNNER_TEMP',tempfile.gettempdir())
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import full_cli as schema


def read(p):return json.loads(gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes())

def hash_(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def complete_digest(path):
    p=subprocess.Popen(['zstd','-dcq',path],stdout=subprocess.PIPE)
    with p.stdout as f:value=hashlib.file_digest(f,'sha256').hexdigest()
    assert p.wait()==0;return value


def verify_disk(where):
    ledger=read(where/'path-inodes.json.gz');disk=read(where/'storage.json');native=read(where/'allocation-readers.json');rootsets={'target':set(),'build':set()};inodes={};packed=set()
    for path,record in ledger.items():
        relative=Path(path);assert not relative.is_absolute() and '..' not in relative.parts and relative.parts[0] in rootsets
        dev,ino,nlink,mode,blocks,size=record;key=dev,ino
        assert nlink>=1 and blocks>=0 and size>=0 and inodes.setdefault(key,record)==record
        rootsets[relative.parts[0]].add(key)
        if relative.name.startswith('ohm-packed-object-') and stat.S_ISREG(mode):packed.add(key)
    def total(keys):return sum(inodes[k][4]*512 for k in keys)
    assert len(ledger)==disk['all_names'] and len(inodes)==disk['all_inodes']==native['python_inodes']==native['find_inodes']
    assert total(inodes)==disk['allocated']==native['python_bytes']==native['du_bytes']==native['find_bytes']
    assert {name:total(keys) for name,keys in rootsets.items()}==disk['roots']
    shared=rootsets['target']&rootsets['build'];assert len(shared)==disk['shared_inodes'] and total(shared)==disk['bytes_aliased_between_roots']
    assert len(packed)==disk['packed_files'] and total(packed)==disk['packed_bytes']
    assert sorted(p for p in ledger if Path(p).name.startswith('s-') and Path(p).name.endswith('-working') and 'incremental' in Path(p).parts)==disk['failed_sessions']
    return disk


def verify(logs,stage):
    mode=read(logs/'full-cli-controls.json'); assert mode['scored_clock'] is False
    calibr=logs/'full-cli-calibration'; f=verify_disk(calibr/'aliases'); s=verify_disk(calibr/'removed');assert f['shared_inodes']==1 and s['shared_inodes']==0
    physical=read(logs/'full-cli-sdk-identities.json');namespaces=read(logs/'full-cli-stable-cargo.json');seen={}
    for observation in namespaces['checks']:
        arm=observation['arm'];assert seen.setdefault(arm,observation['selected'])==observation['selected']==namespaces['expected'][arm]
    assert len(namespaces['checks'])==6 and set(seen)==set(schema.kit.ARMS)
    for use in (logs/'full-cli-sdk-uses').glob('*.json'):
        item=read(use);assert item['files']==physical[item['role']]
    clean=logs/'full-cli-clean';references={};binaries=set()
    for role in schema.kit.ARMS:
        native_test=read(logs/('provider-'+role)/'result.json');assert [native_test[k]['output'] for k in ('cold-A','first-B','returned-A','repair','empty-repair')]==['17 1','29 2','29 1','29 1','29 1']
        assert native_test['invalid']['exit']==101 and native_test['returned-A']['binary']==native_test['repair']['binary']==native_test['empty-repair']['binary']!=native_test['cold-A']['binary']
        for branch in ('A','B'):
            r=read(clean/f'{role}-{branch}.json.gz');references[role,branch]=r
            use=read(logs/'full-cli-sdk-uses'/f'clean-{role}-{branch}.json');assert use['files']==physical[use['role']] and r['jemalloc_out_dir']==mode['full_native_paths'][role]
            assert len(r['graph_rows'])==375 and r['graph']==schema.commit(r['graph_rows'])
            for label in ('cli','reader'):binaries.add(r['native'][label]['whole'])
    for digest in binaries:assert complete_digest(logs/'full-cli-binaries'/(digest+'.zst'))==digest
    for branch in ('A','B'):
        one=references['Off',branch]['native']
        for arm in schema.kit.ARMS:
            two=references[arm,branch]['native'];assert one['reader']==two['reader'] and one['cli_cases']==two['cli_cases'] and one['fstring_cases']==two['fstring_cases']
            assert one['cli']['executable']==two['cli']['executable'] and one['cli']['loads']==two['cli']['loads']
    folder=logs/stage;orders=read(folder/'orders.json');assert orders==list(map(list,schema.schedule(stage)));groups=[]
    for i,order in enumerate(orders,1):
        group={}
        for arm in order:
            slot=folder/f'triplet-{i:02}-{arm}';use=read(slot/'sdk.json');assert use['arm']==arm and use['files']==physical[use['role']];rows=read(slot/'complete.json');assert set(rows)=={p for p,_ in schema.VISITS};group[arm]={}
            head=read(slot/'return-B'/'watched-git-files.json');assert set(head)=={'HEAD','refs/heads/historical-feature'} and head==read(slot/'unchanged-B'/'watched-git-files.json')
            for phase,branch in schema.VISITS:
                where=slot/phase;events=list(map(json.loads,gzip.decompress((where/'cargo.stdout.gz').read_bytes()).splitlines()));process=read(where/'cargo.json.gz')
                assert events[-1]=={'reason':'build-finished','success':phase!='invalid'} and process['exit']==(101 if phase=='invalid' else 0)
                assert process['stdout_sha256']==hashlib.sha256(gzip.decompress((where/'cargo.stdout.gz').read_bytes())).hexdigest() and process['argv'][-len(schema.CARGO):]==schema.CARGO
                if phase=='invalid':
                    assert any(m.get('message',{}).get('code') and m['message']['code']['code']=='E0308' for m in events)
                    fail=verify_disk(where);observed=read(where/'working.json');assert fail['failed_sessions']==sorted(observed)
                    grace=read(slot/'repair'/'failed-session-grace.json');assert grace['sessions']==observed and all(grace['ready_ns']>=r['created_ns']+11_000_000_000 for r in observed.values());continue
                v=read(where/'visit.json');assert v==rows[phase];r=references[arm,branch];assert v['source']==schema.kit.REVS[branch] and v['phase']==phase
                units,dirty=schema.roster(events,Path(mode['input_root']));roster=read(where/'roster.json.gz');assert roster=={'members':units,'dirty':dirty} and units==r['graph_rows'] and v['dirty_digest']==schema.commit(dirty)
                disk=verify_disk(where);assert disk['allocated']==v['allocation'] and disk['packed_bytes']==v['packed_bytes'] and not disk['failed_sessions']
                assert schema.stable_sdk.output_directory(events,'tikv-jemalloc-sys')==v['jemalloc_out_dir']==r['jemalloc_out_dir']==mode['full_native_paths'][arm]
                obs=read(where/'native.json.gz');assert obs==r['native'] and obs['cli']['whole']==v['cli'] and obs['reader']['whole']==v['reader']
                assert gzip.decompress((where/'reader-run.stdout.gz').read_bytes()).decode().strip()==obs['typed']
                for name,rec in obs['cli_cases'].items():
                    tags={'version':'ruff-version','source':'ruff-version-json','clean':'ruff-clean','warning':'ruff-warning','fixed':'ruff-fix','recheck':'ruff-recheck','invalid':'ruff-invalid'};tag=tags[name]
                    for ext in ('stdout','stderr'):assert hash_(where/(tag+'.'+ext))==rec[ext+'_sha256']
                for name,(rc,stdout,stderr) in obs['fstring_cases'].items():
                    assert read(where/(name+'.json.gz'))['exit']==rc
                    assert hashlib.sha256(gzip.decompress((where/(name+'.stdout.gz')).read_bytes())).hexdigest()==stdout
                if phase in ('return-A','return-B','unchanged-B'):
                    native=read(where/'native-execs.json.gz');assert native['wild']==v['actual_execs']['wild'] and native['real_cargo']==1
                    assert sorted(m['crate'] for m in native['rustcs'] if '--out-dir' in m['argv'])==v['actual_execs']['rustcs']
                group[arm][phase]=v
        groups.append(group)
    run=read(folder/'result.json');ok=True; contrasts={}
    for phase in schema.BITS:
        contrasts[phase]=[]
        for group in groups:
            totals={a:group[a][phase]['allocation'] for a in schema.kit.ARMS};off,full,packed=(totals[a] for a in schema.kit.ARMS);delta=full-packed;passed=delta>=32*2**20 and delta*100>=full;ok&=passed
            contrasts[phase].append({'absolute_bytes':totals,'packed_minus_off_bytes':packed-off,'full_minus_off_bytes':full-off,'saved_vs_full_bytes':delta,'meets_gate':passed})
    assert contrasts==run['contrasts'] and bool(ok)==run['admitted'] and run['scored_wall_times'] is False
    return {'stage':stage,'admitted':bool(ok),'triplets':len(orders),'native_bodies':len(binaries),'source_paths':169,'typed_units_per_success':375,'contrasts':contrasts,'terminal_sha256':hash_(folder/'result.json')}

if __name__=='__main__':print(json.dumps(verify(Path(sys.argv[1]),sys.argv[2]),sort_keys=True,indent=2))
