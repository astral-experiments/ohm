"""Execute and gate the full Ruff CLI study using settled allocated bytes only."""
import collections
import gzip
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import shutil
import stat
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent),str(HERE.parent/'harness')]
import study as kit
import disk
import native
import outputs
import stable_sdk
from omission import publish,require,sha

ROOT,OUT,WORK,TREE=kit.ROOT,kit.OUT,kit.WORK,kit.TREE
BITS=('first-B','return-A','return-B','unchanged-B')
VISITS=(('empty-A','A'),('first-B','B'),('return-A','A'),('return-B','B'),('unchanged-B','B'),('invalid','B'),('repair','B'))
CARGO=['cargo','+ohm','build','-p','ruff','--bin','ruff','--locked','--offline','-j4','--message-format=json']
CLEAN=OUT/'full-cli-clean';BODIES=ROOT/'private-full-cli-clean-binaries';BUNDLE=OUT/'full-cli-binaries'


def load(p):return json.loads(gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes())

def commit(value):return hashlib.sha256((json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()).hexdigest()

def schedule(stage):
    if stage=='screen':return [kit.ARMS,tuple(reversed(kit.ARMS))]
    require(stage=='confirm','unexpected cohort');orders=list(itertools.permutations(kit.ARMS));random.Random(0x283350D1).shuffle(orders);return orders


def calibration():
    target=OUT/'full-cli-calibration';target.mkdir()
    with tempfile.TemporaryDirectory(dir=WORK,prefix='owned-full-fixture-') as temp:
        home=Path(temp);a,b=home/'target',home/'build';a.mkdir();b.mkdir();file=a/'native.o';file.write_bytes(bytes(range(256))*6500);os.link(file,b/'same object');(b/'dir alias').symlink_to(a,target_is_directory=True);(a/'dangling').symlink_to('absent')
        sparse=a/'sparse';handle=sparse.open('wb');handle.seek(2**25);handle.write(b'end');handle.close()
        q=target/'aliases';q.mkdir();first=disk.allocated(a,b,q);require(first['shared_inodes']==1 and first['bytes_aliased_between_roots']==file.stat().st_blocks*512 and first['allocated']<sparse.stat().st_size,'hardlink and sparse calibration failed')
        (b/'same object').unlink();z=target/'removed';z.mkdir();second=disk.allocated(a,b,z);require(second['shared_inodes']==0 and abs(second['allocated']-first['allocated'])<65536,'removing an alias lost native data')
    publish(target/'calibration.json',{'four_readers':True,'sparse':True,'cross_root_hardlink':True,'directory_links_not_followed':True})


def roster(messages, tree=None):
    units=[m for m in messages if m.get('reason')=='compiler-artifact'];require(len(units)==375,'not the full historical 375-unit Ruff graph')
    rows=[];dirty=[];path_prefix=(TREE if tree is None else tree).as_uri()
    for m in units:
        identifier=m['package_id'];portable=identifier.replace(path_prefix,'file:///__public_ruff_source__')
        require(not identifier.startswith('path+') or portable!=identifier,('unexpected workspace package outside Ruff',identifier))
        row={'id':portable,'name':m['target']['name'],'kind':m['target']['kind'],'crate_types':m['target']['crate_types'],'features':m['features'],'profile':m['profile']}
        rows.append(row)
        if not m['fresh']:dirty.append(row)
    key=lambda c:json.dumps(c,sort_keys=True,separators=(',',':'))
    rows.sort(key=key);dirty.sort(key=key)
    return rows,dirty


def trace_read(path, arm, phase, where):
    rows=outputs.native_execs(path,kit.SDK)
    rustcs=[m for m in rows['rustcs'] if '--out-dir' in m['argv']]
    for m in rustcs:
        if m['crate'] not in {'ruff','ruff_python_ast','ruff_python_parser'}:continue
        args=m['argv'];require('-Zohm-check-relink-inputs' in args and ('-Zohm-branch-cache=yes' in args)==(arm!='Off'),('unexpected actual compiler options',phase,m['crate']))
    native_summary={'rustcs':sorted(m['crate'] for m in rustcs),'wild':rows['wild'],'native_cargo':rows['real_cargo']}
    require(rows['real_cargo']==1,'wrong actual Cargo')
    if phase=='unchanged-B':require(not rustcs and not rows['wild'],'unchanged CLI unexpectedly built')
    else:require(rustcs and rows['wild']>=1 and 'ruff' in native_summary['rustcs'],'missing full native Rust executable or linker')
    publish(where/'native-execs.json.gz',rows)
    with path.open('rb') as src,(where/'exec.raw.gz').open('xb') as f:
        with gzip.GzipFile(fileobj=f,mode='wb',compresslevel=2,mtime=0) as target:shutil.copyfileobj(src,target)
    path.unlink();return native_summary


def run_visit(arm, phase, branch, env, where, *, reference=False, trace=False):
    where.mkdir();require(shutil.disk_usage(WORK).free>512*2**20,'insufficient owned work space')
    require(shutil.disk_usage(OUT).free>1500*2**20,'insufficient QA receipt space')
    kit.source('recovery' if phase=='repair' else phase,branch)
    prefix=['strace','-f','-qq','--seccomp-bpf','-s','65535','-e','trace=execve','-o',where/'exec.raw'] if trace else []
    res=native.run([*prefix,*CARGO],env,TREE,where/'cargo',101 if phase=='invalid' else 0);msg=list(map(json.loads,res.stdout.splitlines()));require(msg[-1]=={'reason':'build-finished','success':phase!='invalid'},'missing final Cargo success or expected rejection')
    if phase=='invalid':
        diagnostics=[m['message'] for m in msg if m.get('reason')=='compiler-message'];require(any(m.get('code') and m['code']['code']=='E0308' and any('ohm_branch_switch_invalid' in t['text'] for s in m['spans'] for t in s['text']) for m in diagnostics),'wrong invalid-body failure');publish(where/'invalid.json',{'error':'E0308','exit':101});return {'invalid':True}
    native_path=stable_sdk.output_directory(msg,'tikv-jemalloc-sys')
    actual=trace_read(where/'exec.raw',arm,phase,where) if trace else None
    rows,dirty=roster(msg);publish(where/'roster.json.gz',{'members':rows,'dirty':dirty})
    if reference or phase=='empty-A':require(len(dirty)==375,'cold build reused existing Cargo output')
    if phase in ('first-B','return-A','return-B'):
        require(0<len(dirty)<len(rows) and {'ruff','ruff_python_ast','ruff_python_parser'}<={r['name'] for r in dirty},('unexpected historical edit set',len(dirty),[r['name'] for r in dirty]))
    if phase=='unchanged-B':require(not dirty,'unchanged CLI was recompiled')
    storage=disk.allocated(WORK/'target',WORK/'build',where);require(min(storage['roots'].values())>0 and storage['all_inodes']>1000,'missing full target or shared-build tree')
    if reference or phase=='empty-A':require(storage['packed_files']==0,'packing on a cold branch')
    if phase in BITS:require((storage['packed_files']>0)==(arm=='Packed'),('unexpected old object file count',phase,arm,storage['packed_files']))
    obs,paths=native.observed(msg,branch,kit.REVS[branch],env,ROOT,TREE,WORK,where)
    ref=CLEAN/f'{arm}-{branch}.json.gz'
    if reference:
        for name,path in paths.items():native.preserve(path,obs[name],BODIES,BUNDLE)
        publish(ref,{'native':obs,'graph':commit(rows),'graph_rows':rows,'jemalloc_out_dir':native_path})
    expected=load(ref);require(commit(rows)==expected['graph'] and rows==expected['graph_rows'],'typed graph differs from own fresh reference')
    require(expected['jemalloc_out_dir']==native_path,'actual native output directory differs from own clean')
    reference_data=expected['native']
    for name,path in paths.items():native.same_file(path,obs[name],reference_data[name],BODIES,where)
    require({k:v for k,v in obs.items() if k not in paths}=={k:v for k,v in reference_data.items() if k not in paths},'native behavior differs from own empty reference')
    result={'arm':arm,'phase':phase,'branch':branch,'source':kit.REVS[branch],'artifact_count':len(rows),'jemalloc_out_dir':native_path,'graph':commit(rows),'dirty':len(dirty),'dirty_digest':commit(dirty),'actual_execs':actual,'allocation':storage['allocated'],'roots':storage['roots'],'cross_root_alias_bytes':storage['bytes_aliased_between_roots'],'older_exclusive_bytes':storage['older_exclusive_bytes'],'packed_count':storage['packed_files'],'packed_bytes':storage['packed_bytes'],'cli':obs['cli']['whole'],'reader':obs['reader']['whole'],'behavior':commit({k:v for k,v in obs.items() if k not in paths})}
    publish(where/'visit.json',result);return result


def qualify():
    require(kit.git('rev-parse',kit.REVS['B']+'^')==kit.REVS['A'] and len(kit.git('diff','--name-status',kit.REVS['A'],kit.REVS['B']).splitlines())==169,'not the historic 169-path edit');calibration();stable_sdk.prepare();stable_sdk.check_namespaces();CLEAN.mkdir();BODIES.mkdir()
    for arm in kit.ARMS:
        for branch in ('A','B'):
            env=stable_sdk.select(arm,'clean-'+arm+'-'+branch);run_visit(arm,'cold-'+branch,branch,env,CLEAN/f'{arm}-{branch}',reference=True,trace=branch=='A')
    comparison={}
    for branch in ('A','B'):
        controls={arm:load(CLEAN/f'{arm}-{branch}.json.gz') for arm in kit.ARMS};base=controls['Off'];result={}
        for arm,ref in controls.items():
            require(base['graph_rows']==ref['graph_rows'],'across-option 375-unit graph mismatch');a,b=base['native'],ref['native'];require(a['reader']==b['reader'] and a['cli_cases']==b['cli_cases'] and a['fstring_cases']==b['fstring_cases'],'across-option native behavior mismatch')
            require(a['cli']['executable']==b['cli']['executable'] and a['cli']['loads']==b['cli']['loads'],'executable or executable-load bytes differ across options')
            result[arm]={'raw':b['cli']['whole'],'differing_sections':sorted(name for name in a['cli']['sections'].keys()|b['cli']['sections'].keys() if a['cli']['sections'].get(name)!=b['cli']['sections'].get(name))}
        comparison[branch]=result
    full_names={arm:load(CLEAN/f'{arm}-A.json.gz')['jemalloc_out_dir'] for arm in kit.ARMS}
    for arm in kit.ARMS:require(full_names[arm]==load(CLEAN/f'{arm}-B.json.gz')['jemalloc_out_dir'],('full CLI chose different native namespace on the two cold branches',arm))
    from provider import native_controls
    for arm in kit.ARMS:native_controls(arm,stable_sdk.select(arm,'provider-'+arm),ROOT,OUT)
    publish(OUT/'full-cli-controls.json',{'branches':comparison,'input_root':str(TREE),'full_native_paths':full_names,'sdk_path':str(kit.SDK),'scored_clock':False,'raw_products':'full-cli-binaries','provider_arms':list(kit.ARMS)})


def install(arm,path):
    path.mkdir();label=path.parent.name+'-'+path.name;env=stable_sdk.select(arm,label);publish(path/'sdk.json',load(stable_sdk.USES/(label+'.json')));result={}
    for phase,branch in VISITS:
        result[phase]=run_visit(arm,phase,branch,env,path/phase,trace=phase in ('return-A','return-B','unchanged-B'))
    require(result['return-A']['cli']!=result['return-B']['cli'],'wrong executable after returning to the other branch');publish(path/'complete.json',result);return result


def cohort(stage):
    require((OUT/'full-cli-controls.json').is_file(),'unqualified native/storage controls')
    if stage=='confirm':require(load(OUT/'screen/result.json')['admitted'],'unqualified screen')
    folder=OUT/stage;folder.mkdir();orders=schedule(stage);publish(folder/'orders.json',orders);data=[]
    for i,order in enumerate(orders,1):
        group={}
        for arm in order:
            group[arm]=install(arm,folder/f'triplet-{i:02}-{arm}');print(stage,i,arm,'full CLI and physical allocation qualified',flush=True)
        data.append(group)
    contrasts={};admitted=True
    for phase in BITS:
        comparisons=[]
        for group in data:
            totals={a:group[a][phase]['allocation'] for a in kit.ARMS};off,full,packed=(totals[a] for a in kit.ARMS);saving=full-packed;ok=saving>=32*2**20 and saving*100>=full;admitted&=ok
            require(len({group[a][phase]['dirty_digest'] for a in kit.ARMS})==1,'typed dirty unit set differs across options')
            if phase.startswith('return') or phase=='unchanged-B':require(group['Off'][phase]['actual_execs']==group['Full'][phase]['actual_execs']==group['Packed'][phase]['actual_execs'],'native work graph differs across options')
            comparisons.append({'absolute_bytes':totals,'packed_minus_off_bytes':packed-off,'full_minus_off_bytes':full-off,'saved_vs_full_bytes':saving,'meets_gate':ok})
        contrasts[phase]=comparisons
    publish(folder/'result.json',{'cohort':stage,'orders':orders,'admitted':bool(admitted),'units':'settled uniquely allocated target + shared-build bytes','minimum_bytes':32*2**20,'minimum_percent':1,'contrasts':contrasts,'scored_wall_times':False});print(stage,'disk criterion',admitted,flush=True)


if __name__=='__main__':
    action,=sys.argv[1:]
    if action=='qualify':qualify()
    elif action in ('screen','confirm'):cohort(action)
    else:raise SystemExit('unknown full CLI stage')
