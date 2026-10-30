"""Collect exact hosted pairs and independently recount their retained text evidence offline."""
import argparse
import gzip
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import zipfile

HERE=Path(__file__).resolve().parent
REG=json.loads((HERE/'registered.json').read_text())
ORDERS=REG['twelve_independent_blocks']
REG_HASH='5c14953b1244f1d364c37f817970f49aba88eb97096ec61c95ceca4f9e1d07a8'
ORIGINAL_RUN=41141112097
ORIGINAL_HEAD='7ce6296e7b007c0a7de32a91421831e1829874c5'
BRANCH='charlie/qa-gnu-atomic-ruff-db'
BASE='repos/astral-experiments/ohm/actions/'
GH=shutil.which('gh-auto') or (str(Path.home()/'.local/bin/gh-auto')
                               if (Path.home()/'.local/bin/gh-auto').is_file() else 'gh')
PREFIX='atomic-measurements/'
ARGV=['cargo','+ohm','build','-p','ruff_db','--lib','--target','aarch64-unknown-linux-gnu','--locked','--offline','-j4','--message-format=json']
BOUND='OHM_ATOMIC_DB_MISSING_SYMBOL'
CARGO='9fb29f6abecad05acb6015990615c5fbb435a5907543f0bd33cf88cada4f5826'
DRIVERS={'P':'d38721a8dd46c97d253686d920563654b035f25b6f0687c80871fb0a92401084',
         'C':'45d8737f938d6ed97be5903342718f087d0af6ea710dd3c2416babc8c570d4b7'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def valid_clock(v):
    assert v['code']==0 and v['stop']>v['start'] and v['user_us']+v['system_us']>0
    return v['event_errno']==0 and v['instructions']>0 and v['enabled']>0 and v['running']>=.995*v['enabled']


def calibration(read,doc):
    rows=doc('calibration/summary.json')
    assert len(rows['rows'])==28 and rows['whole_tree_hw']
    tests=[('0','1'),('1','1'),('2','1'),('2','2'),('exec','1'),('thread','1'),('thread','2')]
    actual=[]
    for i,(depth,copies) in enumerate(tests):
        samples=[]
        for off,iters in enumerate((0,80000000,0,80000000)):
            at=i*4+off;raw=read('calibration/'+str(at)+'.json');v=json.loads(raw)
            assert valid_clock(v)
            assert rows['rows'][at]=={'depth':depth,'copies':copies,'iters':iters,'receipt':digest(raw.encode()),'hardware':True}
            samples.append(v)
        def difference(key):
            return statistics.median(map(key,samples[1::2]))-statistics.median(map(key,samples[::2]))
        delta=difference(lambda v:v['instructions']);want=160000000*int(copies)
        assert abs(delta/want-1)<.02
        actual.append({'depth':depth,'copies':copies,'expected':want,'delta':delta,
                       'cpu_delta':difference(lambda v:v['user_us']+v['system_us'])})
    one=actual[0]['cpu_delta']
    cpu=one>7000 and all(.45*one*int(r['copies'])<=r['cpu_delta']<=2.3*one*int(r['copies']) for r in actual)
    assert actual==rows['checks'] and rows['tree_cpu']==cpu
    return cpu


def graph(messages):
    assert messages[-1]=={'reason':'build-finished','success':True}
    units=[m for m in messages if m['reason']=='compiler-artifact']
    assert len(units)==174
    roster=sorted(json.dumps([m[k] for k in ('package_id','target','features','profile')],sort_keys=True) for m in units)
    root,=[u for u in units if u['target']['name']=='ruff_db' and u['target']['kind']==['lib'] and not u['profile']['test']]
    assert [Path(f).name for f in root['filenames'] if f.endswith('.rlib')]==['libruff_db.rlib']
    return {'units':174,'roster':digest('\n'.join(roster).encode()),'dirty':sorted(m['target']['name'] for m in units if not m['fresh'])}


def verify(rows,position,run,head):
    def read(path):return rows[PREFIX+path]
    def doc(path):return json.loads(read(path))
    def lines(path):return [json.loads(l) for l in read(path).splitlines()]
    def sdk(path):return json.loads(rows['atomic-subjects/'+path+'.json'])
    assert digest((HERE/'registered.json').read_bytes())==REG_HASH
    expected=ORDERS[position-1];enroll=doc('enrollment.json');pair=doc('pair.json')
    assert enroll['github_run_id']==str(run) and enroll['workflow_sha']==head
    assert enroll['position']==pair['position']==position and enroll['order']==pair['order']==expected
    assert enroll['argv']==ARGV and enroll['registration_sha256']==REG_HASH and pair['hardware']
    cpu=calibration(read,doc)
    assert enroll['tree_cpu_qualified']==pair['cpu_qualified']==cpu
    parent=sdk('P-sdk');candidate=sdk('C-sdk');identity=sdk('atomic-candidate')
    driver=identity['driver_path']
    base=HERE.parent/'ohm-aarch64-portable-review/source/sdk-members.json'
    manifest=json.loads(base.read_bytes() if base.exists() else subprocess.check_output(
        ['git','show','HEAD:scripts/ohm-aarch64-portable-review/source/sdk-members.json'],cwd=HERE))
    assert manifest['driver_path']==driver and manifest['common']=={n:v for n,v in parent.items() if n!=driver}
    assert len(parent)==len(candidate)==119 and set(parent)==set(candidate)
    assert [n for n in parent if parent[n]!=candidate[n]]==[driver]
    assert parent[driver][0]==DRIVERS['P'] and candidate[driver][0]==DRIVERS['C'] and parent['bin/cargo'][0]==CARGO
    assert identity['driver']==candidate[driver] and identity['parent_driver']==parent[driver] and identity['unchanged_members']==118
    assert identity['source']==REG['source']['candidate']['source'] and identity['parent']==REG['source']['parent']['source']
    origin=sdk('origin')
    if origin.get('mode')=='locally-source-built':
        assert origin['head']==head and origin['parent_enrollment']['run']==origin['run']
        assert origin['parent_enrollment']['source']==REG['source']['parent']['source'] and origin['parent_enrollment']['members']==119
    else:
        assert (origin['run'],origin['head'],origin['artifact'],origin['digest']) == (
            41138808306,'f251bcb417be911fc3ed9c4814b17ffa7b360c28',13018006260,
            'sha256:a6bfc63d174184cf46ef452323c30ef2520f455da866be6998400d55f4d63582')
    arms={}
    for role in 'PC':
        root=role+'/'
        terminal=doc(root+'terminal.json');source=doc(root+'unscored/enrolled.json')
        assert source['compiler']==terminal['source'] and source['cargo_sha']==terminal['cargo']==CARGO
        expected_source=REG['source']['parent' if role=='P' else 'candidate']
        assert source['compiler']==expected_source|{'driver':(parent if role=='P' else candidate)[driver]}
        assert source['cli']==ARGV and source['changed']==['crates/ruff_db/src/parsed.rs']
        assert source['lock_sha256']=='e37036fd781578faeafa15fc0a09b938dd78bd160c8e3be958dfb74eb975f61c'
        clocks={};graphs={};measurements={};products={};objects={}
        for s in ('edit','repeat'):
            d=root+s+'/'
            c=doc(d+'clock.json');assert valid_clock(c)
            clocks[s]=c;graphs[s]=graph(lines(d+'stdout.gz'))
            measurements[s]={'instructions':c['instructions'],'elapsed_ns':c['stop']-c['start'],
                             'tree_cpu_us':c['user_us']+c['system_us']}
            dirty=['portable_atomic','ruff_db','salsa'] if role=='P' else ['ruff_db'] if s=='edit' else []
            assert graphs[s]['dirty']==dirty
        measurements['edit+repeat']={k:measurements['edit'][k]+measurements['repeat'][k] for k in measurements['edit']}
        measurements['edit+repeat']['elapsed_ns']=clocks['repeat']['stop']-clocks['edit']['start']
        assert measurements==terminal['measurements'] and graphs==terminal['graph']
        for name,base in [('old','unscored/old'),('repeat','repeat'),('repair','unscored/repair'),('empty','unscored/independent-empty')]:
            d=root+base+'/'
            proof=doc(d+'checked-product.json'); ar=doc(d+'archive-members.json');sub=doc(d+'downstream/result.json')
            comp=doc(d+'downstream/compile.json');g=graph(lines(d+'stdout.gz'))
            assert g['roster']==proof['roster']==graphs['repeat']['roster']==graphs['edit']['roster']
            if name in ('old','empty'):assert len(g['dirty'])==174
            if name=='repair':assert 'ruff_db' in g['dirty']
            assert ar['raw']==proof['sha256']==comp['archive_sha'] and ar['metadata']==proof['metadata']
            assert set(ar['metadata'])=={'lib.rmeta','lib.rmeta-link'} and len(ar['objects'])==proof['members']==216
            obj=sorted((n,size,h) for n,_,size,h in ar['objects'])
            assert len({n for n,_,_ in obj})==216 and all(n.endswith('.o') and size>0 and len(h)==64 for n,size,h in obj)
            assert sub==proof['consumer'] and proof==terminal['products'][name] and comp['exit']==0
            assert all(len(comp['deps'][key])==2 for key in ('ruff_python_ast','salsa')) and len(comp['root_metadata'])==64
            intended={}
            for count in (1,65):
                for label in (['valid'] if name=='old' else ['valid','past-end']):
                    key=str(count)+'-'+label
                    expected_lines=[f'read {count} distinct packed statements']
                    if label=='past-end':expected_lines.append(f'index out of bounds: the len is {count} but the index is {count}')
                    intended[key]=expected_lines
                    assert read(d+'downstream/'+key+'.stdout.gz').splitlines()==expected_lines
            assert sub['verdicts']==intended and sub['bytes']>0 and len(sub['elf'])==64
            objects[name]=obj;products[name]=sub
        assert objects['repeat']==objects['repair']==objects['empty'] and objects['old']!=objects['empty']
        assert products['repeat']==products['repair']==products['empty'] and products['old']['elf']!=products['empty']['elf']
        shape=doc(root+'unscored/physical-repeat/kernel.json')
        assert shape['cargo'][0]['terminal']==[0] and not shape['link_tools']
        assert [(r['crate'],r['link_only'],r['terminal']) for r in shape['rustcs']]==([('portable_atomic',False,[0])] if role=='P' else [])
        bad=lines(root+'unscored/invalid/stdout.gz')
        assert bad[-1]=={'reason':'build-finished','success':False}
        assert any((m.get('message',{}).get('code') or {}).get('code')=='E0425' and BOUND in m['message']['rendered'] for m in bad)
        assert doc(root+'unscored/invalid/kernel.json')['cargo'][0]['terminal']==[101]
        files=doc(root+'disk-inodes.json.gz');disk=doc(root+'disk.json')
        unique={}; per_root={}
        for name,dev,ino,size,blocks,mode in files:
            prefix=Path(name).parts[0];assert prefix in ('target','shared') and '..' not in Path(name).parts
            elem=(size,blocks,mode)
            assert unique.setdefault((dev,ino),elem)==elem
            per_root.setdefault(prefix,{}).setdefault((dev,ino),elem)
        storage=512*sum(n for _,n,_ in unique.values())
        assert len(files)==disk['entries'] and storage==disk['unique_allocated_bytes']==terminal['target_and_shared_allocated']==pair['storage'][role]
        arms[role]={'measurements':measurements,'roster':graphs['repeat']['roster'],'storage':storage,'unique_inodes':len(unique),
                    'roots':{k:512*sum(n for _,n,_ in v.values()) for k,v in per_root.items()},'consumer':products,
                    'interval_coverage':[clocks[s]['running']/clocks[s]['enabled'] for s in ('edit','repeat')],
                    'object_digest':digest(json.dumps(objects['empty'],sort_keys=True).encode()),'driver_bytes':(parent if role=='P' else candidate)[driver][1]}
    assert arms['P']['roster']==arms['C']['roster'] and arms['P']['consumer']==arms['C']['consumer']
    assert arms['P']['object_digest']==arms['C']['object_digest']
    out={s:{k:[arms[r]['measurements'][s][k] for r in 'PC'] for k in ('instructions','elapsed_ns','tree_cpu_us')}
         for s in ('repeat','edit','edit+repeat')}
    assert out==pair['measurements']
    return {'position':position,'order':expected,'endpoints':out,'arms':arms,'tree_cpu_valid':cpu}


def project(z):
    rows={}
    for name in z.namelist():
        if not (name.startswith(PREFIX) or name.startswith('atomic-subjects/')):continue
        if name.endswith('execs.tar.gz') or not name.endswith(('.gz','.json')):continue
        data=z.read(name)
        if name.endswith('.gz'):data=gzip.decompress(data)
        # Initial and empty source builds produce a large argv for every Rust dependency.
        # Their Cargo results and the separate physical unchanged/invalid/repair processes are retained.
        if name.endswith(('unscored/old/kernel.json','unscored/independent-empty/kernel.json')):continue
        rows[name]=data.decode()
    return rows


def stats(observations):
    assert [r['order'] for r in observations]==ORDERS
    results={}
    for step in ('repeat','edit','edit+repeat'):
        metrics={}
        for key in ('instructions','elapsed_ns','tree_cpu_us'):
            if key=='tree_cpu_us' and not all(row['tree_cpu_valid'] for row in observations):continue
            values=[v['endpoints'][step][key] for v in observations];ratios=[a/b for a,b in values];ranked=sorted(ratios)
            def p(null):
                signed=[math.log(r/null)*(1 if order=='PC' else -1) for r,order in zip(ratios,ORDERS)]
                observed=sum(math.log(r/null) for r in ratios)/12
                scores=[sum(x if i in pos else -x for i,x in enumerate(signed))/12 for pos in itertools.combinations(range(12),6)]
                assert len(scores)==924
                return sum(v>=observed-1e-12 for v in scores)/924
            metrics[key]={'parent_median':statistics.median(a for a,b in values),'candidate_median':statistics.median(b for a,b in values),
                          'ratios':ratios,'paired_median':statistics.median(ratios),'ordered_median_interval_96_14':[ranked[2],ranked[9]],
                          'sharp_1x_one_sided_p':p(1),'sharp_2x_one_sided_p':p(2)}
        results[step]=metrics
    deltas=[v['arms']['C']['storage']-v['arms']['P']['storage'] for v in observations]
    results['storage']={'candidate_minus_parent_bytes':deltas,'median_difference':statistics.median(deltas),
                        'parent_median':statistics.median(v['arms']['P']['storage'] for v in observations),
                        'candidate_median':statistics.median(v['arms']['C']['storage'] for v in observations)}
    return results


def api(path):
    return json.loads(subprocess.check_output([GH,'api',BASE+path]))


def write(path,obj):
    data=(json.dumps(obj,indent=2,sort_keys=True)+'\n').encode()
    if path.exists():assert path.read_bytes()==data
    else:path.write_bytes(data)


def collect(out,run,head):
    r=api('runs/'+str(run))
    assert (r['head_sha'],r['head_branch'],r['event'],r['status'],r['conclusion'])==(head,BRANCH,'workflow_dispatch','completed','success')
    jobs=api('runs/'+str(run)+'/jobs?per_page=100')['jobs']
    got={j['name']:j for j in jobs if j['conclusion']!='skipped'}
    assert set(got)=={f'holdout ({n})' for n in range(1,13)} and all(j['conclusion']=='success' for j in got.values())
    arts=api('runs/'+str(run)+'/artifacts?per_page=100')['artifacts']
    assert {a['name'] for a in arts}=={f'gnu-atomic-db-pair-{n}' for n in range(1,13)} and len(arts)==12
    out.mkdir(parents=True,exist_ok=True);records=[]
    for i in range(1,13):
        a,=[a for a in arts if a['name']==f'gnu-atomic-db-pair-{i}']
        assert not a['expired'] and (a['workflow_run']['id'],a['workflow_run']['head_sha'])==(run,head)
        with os.fdopen(os.memfd_create('atomic-pair'),'w+b') as f:
            subprocess.run([GH,'api',BASE+'artifacts/'+str(a['id'])+'/zip'],stdout=f,check=True)
            f.seek(0);assert hashlib.file_digest(f,'sha256').hexdigest()==a['digest'].split(':')[1]
            with zipfile.ZipFile(f) as z:rows=project(z)
        verify(rows,i,run,head)
        raw=json.dumps(rows,sort_keys=True,separators=(',',':')).encode()
        compressed=subprocess.check_output(['zstd','-q','-9','-c'],input=raw)
        name=f'{i:02}.json.zst';path=out/name
        if path.exists():assert path.read_bytes()==compressed
        else:path.write_bytes(compressed)
        records.append({'position':i,'order':ORDERS[i-1],'artifact':a['id'],'job':got[f'holdout ({i})']['id'],
                        'source_zip':a['digest'],'retained_sha256':digest(compressed),'file':name})
        print('verified',i,len(compressed),flush=True)
    write(out/'manifest.json',{'run':run,'head':head,'registration':REG_HASH,'pairs':records})


def offline(out):
    manifest=json.loads((out/'manifest.json').read_text());assert manifest['registration']==REG_HASH
    rows=[]
    for i,p in enumerate(manifest['pairs'],1):
        assert p['position']==i and p['order']==ORDERS[i-1]
        f=out/p['file'];assert digest(f.read_bytes())==p['retained_sha256']
        text=subprocess.check_output(['zstd','-qdc',f])
        rows.append(verify(json.loads(text),i,manifest['run'],manifest['head']))
    assert len(rows)==12
    summary=stats(rows)
    write(out/'results.json',summary)
    med=summary['repeat']['instructions'];print('Whole-command first unchanged hardware instructions',med)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['collect','verify']);parser.add_argument('out',type=Path)
    parser.add_argument('--run',type=int,default=ORIGINAL_RUN);parser.add_argument('--head',default=ORIGINAL_HEAD)
    cli=parser.parse_args()
    if cli.mode=='collect':collect(cli.out,cli.run,cli.head)
    offline(cli.out)
