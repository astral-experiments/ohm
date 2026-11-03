"""Run the independent ordinary, process-observed, native and hardware histories."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from case import BASE, BUILD, CHECK, ERROR, PORT, REG, ROOT, env, fresh_state, need, observer, old, save, sha, source, w
import metadata

MEMBERS=BASE/'members'


def write_once(path, body):
    if not path.exists():
        with path.open('xb') as stream:stream.write(body)


def typed_rows(out, ok):
    rows=[json.loads(line) for line in (out/'stdout').read_bytes().splitlines()]
    need([r['success'] for r in rows if r['reason']=='build-finished']==[ok],'Cargo terminal verdict')
    messages=[r['message'] for r in rows if r['reason']=='compiler-message']
    errors=[m for m in messages if m['level']=='error']
    if ok:need(not errors,'unexpected rustc error')
    else:
        need(len(errors)==1 and (errors[0].get('code') or {}).get('code')=='E0308' and
             any(s['is_primary'] and s['file_name']==REG['path'] and 'OHM_INVALID_CHECK_SENTINEL' in str(s['text']) for s in errors[0]['spans']), 'missing source-bound E0308')
    need(b'internal compiler error' not in (out/'stderr').read_bytes().lower(),'rustc ICE')
    return [r for r in rows if r['reason']=='compiler-artifact']


def snap(arts, version, environment, display):
    binds={}
    for name in REG['observed_targets']:
        r,=[v for v in arts if v['target']['name']==name and v['target']['kind']==['lib']]
        f,=[Path(n) for n in r['filenames'] if n.endswith('.rmeta')]
        need(Path(r['manifest_path']).samefile(w.SRC/'crates'/name/'Cargo.toml') and r['target']['edition']==REG['edition'], 'different local crate')
        info=observer.capture(f); key=info['sha256']; tab=MEMBERS/(key+'.rows.json.gz')
        if not tab.exists():
            raw=f.read_bytes();need(hashlib.sha256(raw).hexdigest()==key,'rmeta changed during capture')
            body=metadata.table(raw,name,version,REG['edition'])
            write_once(tab,gzip.compress(json.dumps(body,sort_keys=True,separators=(',',':')).encode(),compresslevel=2,mtime=0))
        witness=w.OUT/(key+'.display.json')
        if display and not witness.exists():
            shown=subprocess.check_output(['rustc','+ohm',f,'-Zls=public_hash'],env=environment,text=True).strip()
            pub=json.loads(gzip.decompress(tab.read_bytes()))['header']['public']
            need(shown=='Public hash: '+bytes.fromhex(pub)[::-1].hex(),'independent raw and rustc public hash')
            save(witness,{'body':key,'raw_public':pub,'native':shown})
        binds[name]=dict(**info,decoded=sha(tab))
    return binds


def check(label,state,environment,version,method='ordinary',invalid=False):
    source(state)
    dest=w.OUT/label
    argv=CHECK
    if method=='trace':
        trace=w.OUT/(label+'-observer');trace.mkdir()
        argv=['/usr/bin/strace','-ff','-qq','-yy','-s','260000','-e','trace=execve,openat,mmap','-o',str(trace/'trace'),*CHECK]
    elif method=='pmu':
        argv=[ROOT/'whole-count',dest/'hardware.json',ROOT/'proxies/cargo',*CHECK]
    else:need(method=='ordinary','unknown measurement')
    f=w.SRC/REG['path'];original=f.read_bytes()
    if invalid:f.write_bytes(original+ERROR)
    try:
        w.run(argv,environment,dest,101 if invalid else 0,timeout=2400)
        arts=typed_rows(dest,not invalid)
    finally:
        if invalid:f.write_bytes(original)
    source(state)
    dirty=sorted([[r['target']['name'],r['target']['kind'][0]] for r in arts if not r['fresh']])
    expected=dirty+([['ruff_linter','lib']] if invalid else [])
    if method=='trace':
        actual=observer.traced(trace,[name.replace('-','_') for name,kind in expected])
        native=json.loads((trace/'native-execs.json').read_bytes())
        kernel=[]
        for tid,v in native['actual'].items():
            line=v['argv']
            kind=re.search(r'"--crate-type", "(lib|bin|proc-macro|rlib)"',line)
            need(kind and ('"--emit=dep-info,metadata"' in line), 'different physical dirty rustc invocation')
            driver,=(w.SDK/'lib').glob('librustc_driver-*.so')
            with gzip.open(trace/('trace.'+tid+'.gz'),'rt') as stream:
                maps=[ln.strip() for ln in stream if ln.startswith('mmap(') and 'PROT_EXEC' in ln and ('<'+str(driver)+'>') in ln and re.search(r' = 0x[0-9a-f]+$',ln.rstrip())]
            need(maps, 'live executable driver mapping was not opened by '+tid)
            save(trace/('driver-'+tid+'.json'),dict(crate=v['crate'],pid=int(tid),sha256=sha(driver),maps=maps))
            kernel.append([v['crate'],kind[1]])
        need(sorted(kernel)==sorted(expected),('wrong per-target physical cargo roster',kernel,expected))
    instructions=None
    if method=='pmu':
        hw=json.loads((dest/'hardware.json').read_bytes())
        need(hw['status']==0 and hw['enabled']==hw['running']>0 and hw['instructions']>0,'partial inherited PMU count')
        instructions=hw['instructions']
    if not invalid:
        need(len(arts)==REG['unit_count'],'different ordinary unit inventory')
        bindings=snap(arts,version,environment,method!='pmu')
    else:bindings={}
    roster=sorted([[r['package_id'],r['target']['name'],r['target']['kind'],sorted(r['features']),r['profile']['test']]for r in arts])
    data=dict(state=state,dirty=dirty,source=hashlib.sha256(original+(ERROR if invalid else b'')).hexdigest(),units=roster,metadata=bindings,method=method,invalid=invalid,instructions=instructions)
    save(dest/'check.json',data)
    return data


def core(prefix,mode,e,v):
    changes={}
    fresh_state()
    labels=[('buggy-cold','buggy'),('buggy-idle1','buggy'),('buggy-idle2','buggy'),('edited','fixed'),('fixed-idle1','fixed'),('fixed-idle2','fixed')]
    for label,state in labels:
        method='ordinary' if mode=='trace' and label=='buggy-cold' else mode
        c=check(prefix+'-'+label,state,e,v,method)
        if 'idle' in label:need(c['dirty']==[],('settled ordinary control',label,c['dirty']))
        if label=='edited':need(['ruff_linter','lib'] in c['dirty'],'no actual producer')
        changes[label]=c
    return changes


PROBES=(('attr-field','attr.define','attr.field(factory=list)',1,0),
        ('attr-attributes','attr.attributes','list()',0,1),
        ('both-warn','attr.define','list()',1,1),
        ('both-clean','attr.define','[] if False else 1',0,0))


def native(label,state,environment):
    source(state);dest=w.OUT/label
    w.run(BUILD,environment,dest,timeout=3600)
    arts=typed_rows(dest,True)
    cli,=[r for r in arts if r['target']['name']=='ruff' and r['target']['kind']==['bin']]
    exe=Path(cli['executable'])
    with exe.open('rb') as f:need(f.read(4)==b'\x7fELF','missing native Ruff executable')
    key=sha(exe); saved=MEMBERS/(key+'.elf.zst')
    if not saved.exists():
        with saved.open('xb') as out:subprocess.run(['zstd','-q','-3','-c',exe],stdout=out,check=True)
    probes={}
    for name,decorator,expr,bug,fix in PROBES:
        payload=f'import attr\n@{decorator}\nclass Example:\n    value: list[int] = {expr}\n'
        cmd=[exe,'check','--isolated','--no-cache','--select','RUF009','--output-format=json','--stdin-filename=case.py','-']
        res=subprocess.run(cmd,cwd=w.SRC,env=environment,input=payload.encode(),capture_output=True,timeout=30)
        d=json.loads(res.stdout);want=fix if state=='fixed' else bug
        expect_message='Do not perform function call `'+expr.split('(')[0]+'` in dataclass defaults'
        need(res.returncode==want and not res.stderr and [m['code']for m in d]==['RUF009']*want,'different native RUF009 diagnostic')
        if want:
            need(d[0]['message']==expect_message and d[0]['location']=={'row':4,'column':24} and d[0]['end_location']=={'row':4,'column':24+len(expr)},'wrong diagnostic or underline')
        probes[name]={'input':payload,'code':res.returncode,'stdout':res.stdout.decode(),'stderr':res.stderr.decode()}
    data=dict(state=state,sha256=key,bytes=exe.stat().st_size,compressed=sha(saved),probes=probes)
    save(dest/'native.json',data)
    return data


def run(role):
    w.checked_head()
    e=env();w.OUT=BASE/role;w.OUT.mkdir()
    aid=old.activate(role)
    driver,=(w.SDK/'lib').glob('librustc_driver-*.so')
    aid['physical']={}
    for name,path in [('frontend',w.SDK/'bin/rustc'),('cargo',w.SDK/'bin/cargo'),('driver',driver)]:
        stat=path.stat()
        aid['physical'][name]={'path':str(path.resolve()),'dev':stat.st_dev,'ino':stat.st_ino,'sha256':sha(path)}
    save(w.OUT/'kit.json',aid)
    need(aid['rustc']==aid['config']['rustc'] and aid['cargo']==aid['config']['cargo'],'wrong executing kit')
    for relative,key in aid['config']['files'].items():
        need(sha(w.SDK/relative)==key,'changed installed member: '+relative)
    version=subprocess.check_output(['rustc','+ohm','--version'],env=e,text=True).strip()+' (Ohm metadata 3)'
    measured=core('ordinary','pmu',e,version)
    observed=core('kernel','trace',e,version)
    for stage in measured:
        m,t=measured[stage],observed[stage]
        need(m['units']==t['units'] and m['dirty']==t['dirty'],'the observer changed Cargo work')
        # Inspect all complete A/A metadata separately; public/row equality is verified by the independent reader.
    check('reverse','buggy',e,version,'trace')
    check('restore-fixed','fixed',e,version,'trace')
    check('invalid','fixed',e,version,'trace',True)
    check('repair','fixed',e,version,'trace')
    fresh_state();check('empty-edit','fixed',e,version)
    fresh_state()
    for label,state in [('native-buggy','buggy'),('native-edited','fixed'),('native-reverse','buggy'),('native-repair','fixed')]:
        native(label,state,e)
    fresh_state();native('native-empty-edit','fixed',e)
    save(w.OUT/'completed.json',dict(role=role,source=aid['config']['source'],driver=aid['driver'],edited=measured['edited']['instructions']))


if __name__=='__main__':
    worker=json.loads((BASE/'worker.json').read_bytes())
    for role in worker['order']:run(role)
