"""Reopen original Cargo stdout, unscaled counters, raw physical metadata and ELF bodies."""
from collections import Counter
from functools import lru_cache
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import metadata
import output_binding

REG=json.loads((HERE/'registration.json').read_bytes())
PORT=json.loads((HERE/'port.json').read_bytes())
def need(ok,reason):
    if not ok:raise ValueError(reason)
def read(p):return json.loads(p.read_bytes())
def digest(value):return hashlib.sha256(value).hexdigest()
def file_sha(p):
    with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def semantic(d):return (d['public'],d['stable'],d['global_hash'],d['rows'])


def block(base):
    worker=read(base/'worker.json')
    need(worker['source']==REG and worker['port']==PORT,'different enrollment')
    need(worker['order']==(REG['pilot_order'] if worker['phase']=='pilot' and worker['block']==0 else REG['confirm_orders'][worker['block']-1]),'wrong order')
    current={state:file_sha(base/'source'/(state+'.rs')) for state in ('fixed','buggy','invalid')}
    need(all(current[s]==PORT[s] for s in ('fixed','buggy')) and
         (base/'source/invalid.rs').read_bytes()==(base/'source/fixed.rs').read_bytes()+b'\nconst OHM_INVALID_CHECK_SENTINEL: u32 = "invalid";\n','different source evidence')
    for how in ('thread','child'):
        records=[read(base/(f'pmu-{how}-{mode}.json')) for mode in (0,1)]
        need(all(a['status']==0 and a['enabled']==a['running']>0 for a in records) and records[1]['instructions']>records[0]['instructions']+10_000_000,'hardware inheritance control')
    members=base/'members'
    @lru_cache(maxsize=None)
    def reopen_meta(key,name,version):
        fn=members/(key+'.rmeta.zst');raw=subprocess.check_output(['zstd','-dcq',fn])
        need(digest(raw)==key,'different original rmeta')
        actual=metadata.table(raw,name,version,REG['edition'])
        frozen=members/(key+'.rows.json.gz')
        need(json.loads(gzip.decompress(frozen.read_bytes()))==actual,'different physical RDR/definition/dependency table')
        return dict(**actual['header'],rows=digest(json.dumps(actual['rows'],sort_keys=True).encode()),definitions=len(actual['rows']),compressed=file_sha(fn),decoded=file_sha(frozen))
    def orig_folder(folder):return read(folder/'check.json')
    role_data={}
    for role in worker['order']:
        folder=base/role;kit=read(folder/'kit.json')
        need(kit['config']['source']==worker['factory']['source'][role]==REG['matched_sources'][role]['revision'] and kit['driver']==kit['config']['driver']==read(base/'factory-safety.json')[role]['driver_sha256'],'different role')
        version=kit['rustc_version'].splitlines()[0]+' (Ohm metadata 3)'
        data={}
        phases=['buggy-cold','buggy-idle1','buggy-idle2','edited','fixed-idle1','fixed-idle2']
        for stage in [p+'-'+s for p in ('ordinary','kernel') for s in phases]+['reverse','restore-fixed','invalid','repair','empty-edit']:
            d=folder/stage; got=orig_folder(d)
            rows=[json.loads(x) for x in (d/'stdout').read_bytes().splitlines()]
            valid=stage!='invalid'
            state='invalid' if stage=='invalid' else 'buggy' if 'buggy-' in stage or stage=='reverse' else 'fixed'
            need(got['source']==current[state], 'source did not match registered phase')
            need([r['success']for r in rows if r['reason']=='build-finished']==[valid],'original Cargo exit')
            arts=[r for r in rows if r['reason']=='compiler-artifact']
            dirty=sorted([[r['target']['name'],r['target']['kind'][0]]for r in arts if not r['fresh']])
            need(dirty==got['dirty'] and (not valid or len(arts)==REG['unit_count']),'original typed roster')
            cmd=read(d/'command.json')
            need(cmd['exit']==(0 if valid else 101) and cmd['argv'][-len(REG['cargo_check']):]==REG['cargo_check'],'unexpected command/exit')
            count=None;physical=None
            if stage.startswith('ordinary-'):
                need(got['method']=='pmu' and Path(cmd['argv'][0]).name=='whole-count' and len(cmd['argv'])==len(REG['cargo_check'])+3,'counter scope')
                h=read(d/'hardware.json')
                need(h['status']==0 and h['enabled']==h['running']>0 and h['instructions']==got['instructions']>0,'bad physical counter')
                count=h['instructions']
            if got['method']=='trace':
                tr=folder/(stage+'-observer');table=read(tr/'native-execs.json')
                need(table['rustc']==kit['rustc'],'wrong physical frontend')
                actual=[]
                found=set()
                for trace in tr.glob('trace.*.gz'):
                    tid=trace.name.split('.')[1]
                    with gzip.open(trace,'rt')as lines:
                        for ln in lines:
                            if '"--crate-name"' not in ln or not ln.startswith('execve(') or not ln.rstrip().endswith(' = 0'):continue
                            exe=re.match(r'execve\("([^"]+)"',ln)[1]
                            if Path(exe).name=='rustc' and (('toolchains/ohm/bin/rustc' in exe) or exe==kit['physical']['frontend']['path']):
                                need(tid not in found,'duplicate native exec');found.add(tid)
                need(found==set(table['actual']),'unreported actual rustc exec')
                for tid,item in table['actual'].items():
                    raw=gzip.decompress((tr/('trace.'+tid+'.gz')).read_bytes()).decode().splitlines()
                    need(item['argv'] in raw and int(tid)>0 and item['inode']==kit['physical']['frontend']['ino'] and item['dev']==kit['physical']['frontend']['dev'] and Path(item['program']).name=='rustc','unbound compiler PID')
                    mapped=read(tr/('driver-'+tid+'.json'))
                    need(mapped['sha256']==kit['driver'] and mapped['pid']==int(tid) and all(x in raw and kit['physical']['driver']['path'] in x and 'PROT_EXEC' in x for x in mapped['maps']) and bool(mapped['maps']),'different live driver')
                    kind=re.search(r'"--crate-type", "(lib|bin|proc-macro|rlib)"',item['argv'])
                    need(kind and '"--crate-name", "'+item['crate']+'"' in item['argv'],'bad physical argv')
                    actual.append([item['crate'],kind[1]])
                physical=sorted(actual)
                before,after=[read(tr/('outputs-'+t+'.json')) for t in ('before','after')]
                different=output_binding.reconcile(dirty,physical,before,after,not valid)
                for crate,kind in different:
                    k=crate+'/'+kind
                    row,=[r for r in arts if r['target']['name']==crate and r['target']['kind']==[kind]]
                    meta,=[Path(f) for f in row['filenames'] if f.endswith('.rmeta')]
                    witness=after[k]
                    need(str(meta)==witness['rmeta']['path'] and str(meta.with_name(meta.name.removeprefix('lib')).with_suffix('.d'))==witness['dep-info']['path'],'reported retained paths differ from Cargo')
                    if valid and kind=='lib':need(witness['rmeta']['sha256']==got['metadata'][crate]['sha256'],'retained library metadata differs from raw snapshot')
                    output_binding.check_stored(members,{k:before[k]})
                need(got['physical']==physical and read(tr/'nominal-and-physical.json')==dict(cargo_dirty=dirty,rustc=physical,dirty_without_rustc=different),'different physical compiler membership')
                if 'idle' in stage:need(not physical,'unchanged invocation of rustc')
            if not valid:
                errors=[r['message'] for r in rows if r['reason']=='compiler-message' and r['message']['level']=='error']
                need(len(errors)==1 and (errors[0].get('code') or {}).get('code')=='E0308' and any(s['is_primary'] and REG['path']==s['file_name'] and 'OHM_INVALID_CHECK_SENTINEL' in str(s['text']) for s in errors[0]['spans']),'different physical invalid verdict')
            snapshots={}
            for name,q in got['metadata'].items():
                m=reopen_meta(q['sha256'],name,version); snapshots[name]=m
                need(m['compressed']==q['archive'] and m['decoded']==q['decoded'],'foreign archived body')
                if got['method']!='pmu':
                    show=read(folder/(q['sha256']+'.display.json'))
                    need(show=={'body':q['sha256'],'raw_public':m['public'],'native':'Public hash: '+bytes.fromhex(m['public'])[::-1].hex()},'different native public hash display')
            need(set(snapshots)==(set(REG['observed_targets']) if valid else set()),'missing snapshots')
            data[stage]=dict(dirty=dirty,physical=physical,instructions=count,meta=snapshots)
        for state,labels in [('buggy',['buggy-cold','buggy-idle1','buggy-idle2']),('fixed',['edited','fixed-idle1','fixed-idle2'])]:
            ref=data['ordinary-'+labels[0]]
            for name in ('ordinary-','kernel-'):
                for label in labels:
                    obj=data[name+label]
                    need(all(semantic(v)==semantic(ref['meta'][n]) for n,v in obj['meta'].items()),'ordinary/traced metadata disagreement')
                    need(obj['dirty']==(ref['dirty'] if label==labels[0] else []),'two clean no-op or observer discrepancy')
                # Source-generated metadata remains identical between repeated unchanged commands.
                same=[{n:v['full'] for n,v in data[name+label]['meta'].items()}for label in labels]
                need(same[0]==same[1]==same[2],'settled bytes changed')
        for label,ref in [('empty-edit','ordinary-edited'),('repair','ordinary-edited'),('restore-fixed','ordinary-edited'),('reverse','ordinary-buggy-cold')]:
            need(all(semantic(v)==semantic(data[ref]['meta'][k]) for k,v in data[label]['meta'].items()),'semantic reference mismatch '+label)
            need(data[label]['meta']['ruff_linter']['full']==data[ref]['meta']['ruff_linter']['full'],'different same-source producer rmeta '+label)
        native={}
        for key,state in [('native-buggy','buggy'),('native-edited','fixed'),('native-reverse','buggy'),('native-repair','fixed'),('native-empty-edit','fixed')]:
            n=read(folder/key/'native.json');f=members/(n['sha256']+'.elf.zst');need(file_sha(f)==n['compressed'] and n['state']==state,'wrong stored ELF')
            with subprocess.Popen(['zstd','-dcq',f],stdout=subprocess.PIPE) as proc:
                md=hashlib.sha256();size=0
                while b:=proc.stdout.read(1<<20):
                    if not size:need(b.startswith(b'\x7fELF'),'wrong binary format')
                    md.update(b);size+=len(b)
                need(proc.wait()==0 and md.hexdigest()==n['sha256'] and size==n['bytes'],'incomplete native body')
            need(set(n['probes'])=={'attr-field','attr-attributes','both-warn','both-clean'},'missing native lint')
            for k,p in n['probes'].items():
                wanted=int(k=='both-warn' or k==('attr-field' if state=='buggy' else 'attr-attributes'))
                args={'attr-field':('attr.define','attr.field(factory=list)'),'attr-attributes':('attr.attributes','list()'),'both-warn':('attr.define','list()'),'both-clean':('attr.define','[] if False else 1')}
                deco,expr=args[k];need(p['input']==f'import attr\n@{deco}\nclass Example:\n    value: list[int] = {expr}\n','wrong probe source')
                diag=json.loads(p['stdout'])
                need(p['code']==wanted and not p['stderr'] and [m['code']for m in diag]==['RUF009']*wanted,'native verdict')
                if wanted:need(diag[0]['location']=={'row':4,'column':24} and diag[0]['end_location']=={'row':4,'column':24+len(expr)} and diag[0]['message']=='Do not perform function call `'+expr.split('(')[0]+'` in dataclass defaults','span/message')
            native[key]=n
        need(native['native-edited']==native['native-empty-edit']==native['native-repair'] and native['native-buggy']==native['native-reverse'] and native['native-buggy']['sha256']!=native['native-edited']['sha256'],'different same-role full CLI or dynamic probe')
        baseline,edited=[data[n]['meta']['ruff_linter']for n in ['ordinary-buggy-cold','ordinary-edited']]
        need(baseline['private']!=edited['private'],'source body was not compiled')
        tables=[json.loads(gzip.decompress((members/(v['full']+'.rows.json.gz')).read_bytes()))for v in (baseline,edited)]
        diff=metadata.compare(*tables)
        role_data[role]=dict(source=kit['config']['source'],driver=kit['driver'],dirty=data['ordinary-edited']['dirty'],physical=data['kernel-edited']['physical'],cost={s:data['ordinary-'+s]['instructions'] for s in phases},
            public=[baseline['public'],edited['public']],row_count=[baseline['definitions'],edited['definitions']],changed_rows=len(diff),row_changes_sha256=digest(json.dumps(diff,sort_keys=True).encode()),native={k:v['sha256']for k,v in native.items()},
            equivalence={label:{n:v['full']==data['ordinary-edited']['meta'][n]['full']for n,v in data[label]['meta'].items()} for label in ('repair','empty-edit')})
    p,c=role_data['P'],role_data['C']
    need(p['source']==REG['rust_parent'] and p['driver']!=c['driver'],'unmatched compiler pair')
    need(p['native']==c['native'],'cross-role complete native products differ; require independent classification')
    ds=lambda data:set(map(tuple,data['physical']))
    skipped=sorted(ds(p)-ds(c))
    shape=(p['dirty']==p['physical']==REG['observed_terminal_targets'] and set(map(tuple,c['dirty']))<=set(map(tuple,p['dirty'])) and ds(c)<=ds(p) and ('ruff_linter','lib')in ds(c) and any(tuple(s)!=('ruff_linter','lib') for s in skipped))
    reduction=1-c['cost']['edited']/p['cost']['edited']
    return dict(worker=worker,roles=role_data,physical_skipped=skipped,eligible_shape=shape,reduction=reduction,pilot_admits=shape and reduction>=REG['gates']['pilot_edited_reduction_min'])


def aggregate(rows):
    need(len(rows)==8 and {r['worker']['block']for r in rows}==set(range(1,9)) and all(r['worker']['phase']=='confirmation' for r in rows),'need eight separate confirmation blocks')
    rows=sorted(rows,key=lambda x:x['worker']['block'])
    for key in ('boot','job'):need(len({r['worker'][key]for r in rows})==8,'duplicated physical '+key)
    need(len({r['worker']['recipe']for r in rows})==1 and len({r['worker']['sha']for r in rows})==1 and len({r['worker']['run']for r in rows})==1 and
         all(r['worker']['factory']==rows[0]['worker']['factory'] for r in rows),'changed experiment/factory')
    need([r['worker']['order']for r in rows]==REG['confirm_orders'] and all(r['eligible_shape']for r in rows),'wrong order or input roster')
    logs=[math.log(r['roles']['P']['cost']['edited']/r['roles']['C']['cost']['edited'])for r in rows]
    diffs=[v if r['worker']['order']=='PC' else -v for v,r in zip(logs,rows)]
    actual=sum(logs)
    non_ties=sum(v!=0 for v in logs)
    perms=[sum(v if i in pc else -v for i,v in enumerate(diffs))for pc in itertools.combinations(range(8),4)]
    favorable=sum(v>0 for v in logs); reductions=[r['reduction']for r in rows]
    return dict(paired_counts=[{k:r['roles'][k]['cost'] for k in ('P','C')}for r in rows],ratios=[math.exp(v)for v in logs],reductions=reductions,median_reduction=statistics.median(reductions),
        positive=favorable,non_ties=non_ties,one_sided_sign_p=sum(math.comb(non_ties,i)for i in range(favorable,non_ties+1))/(2**non_ties),
        randomization_p=sum(x>=actual-1e-12 for x in perms)/70,admit=favorable==8 and statistics.median(reductions)>=REG['gates']['confirmation_edited_median_reduction_min'])


if __name__=='__main__':
    if sys.argv[1]=='aggregate':result=aggregate([read(Path(s))for s in sys.argv[2:]])
    else:result=block(Path(sys.argv[1]))
    print(json.dumps(result,indent=1,sort_keys=True))
