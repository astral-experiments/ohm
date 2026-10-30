"""Independently join local environments, native rustc options and real incremental file inventories."""
import gzip
import hashlib
import json
from pathlib import PurePosixPath as Path
from zipfile import ZipFile

HOST = {'HOME','PATH','TMPDIR','USER','LOGNAME','SHELL','LANG','TERM','DEVELOPER_DIR'}
NEED = {'RUSTUP_HOME','CARGO_HOME','CARGO_TARGET_DIR','CARGO_BUILD_BUILD_DIR','CARGO_NET_OFFLINE','CARGO_TERM_COLOR','CARGO_CACHE_AUTO_CLEAN_FREQUENCY','LC_ALL','TZ'}

def h(x):return hashlib.sha256(x).hexdigest()
def j(x):return json.dumps(x,separators=(',',':')).encode()
def env(v):
    assert {'HOME','PATH'}|NEED <= set(v) <= HOST|NEED
    assert all(len(t)==64 and int(t,16)>=0 for t in v.values())
    for k,val in [('CARGO_NET_OFFLINE','true'),('CARGO_TERM_COLOR','never'),('CARGO_CACHE_AUTO_CLEAN_FREQUENCY','never'),('LC_ALL','C'),('TZ','UTC')]:assert v[k]==h(val.encode())
    return sorted(v)

def summarise_cache(c, disk=None):
    root=Path(c['root']); assert root.parts[0] in ('target','shared') and not root.is_absolute() and '..' not in root.parts
    unique={};found={};sizes={}
    for rel,dev,ino,length,blocks,sha in c['files']:
        name=Path(rel);assert rel not in found and name.is_relative_to(root) and name.parent.name.startswith('s-') and not name.parent.name.endswith('-working') and name.parent.parent.name.startswith('ty_vendored-');assert dev and ino>0 and length>=0 and blocks>=0
        if name.name in ('work-products.bin','dep-graph.bin') or name.suffix=='.o':assert len(sha)==64 and int(sha,16)>=0
        else:assert sha is None
        found[rel]=[dev,ino,length,blocks];assert unique.setdefault((dev,ino),(length,blocks))==(length,blocks)
        if disk is not None: assert (dev,ino,length,blocks)==tuple(disk[rel][1:5])
        kind=name.suffix if name.suffix=='.o' else name.name
        if length:sizes[kind]=sizes.get(kind,0)+1
    rb=sum(s for s,b in unique.values());ab=sum(b for s,b in unique.values())*512
    items={'objects':sizes.get('.o',0),'work_products':sizes.get('work-products.bin',0),'dep_graphs':sizes.get('dep-graph.bin',0),'logical':rb,'allocated':ab}
    assert items=={k:c[k] for k in items}
    return {**items,'root_sha':h(str(root).encode()),'files':len(found),'ledger_sha':h(j(c['files']))}

def inspect(z):
    get=lambda k:json.loads(z.read(k)); names=set(z.namelist());out={'native':{},'timed':{},'provider_environments':{}}
    for n in sorted(names):
        if n.startswith('provider-matrix/') and n.endswith('/development-environment.json'):
            out['provider_environments'][n.split('/')[1]]=env(get(n))
    for n in sorted(names):
        if not n.endswith('/local-incremental.json'):continue
        pre=n.rsplit('/',1)[0];q=get(n);scope=env(q['environment']);raw=gzip.decompress(z.read(pre+'/exec.json.gz'));events=json.loads(raw)
        expected=[]
        for e in events:
            a=e['argv'];ex=e['path'];args=list(zip(a,a[1:]))
            if not ex.endswith('/native/bin/rustc') or ('--crate-name','ty_vendored') not in args or '--test' not in a or any('link-only' in x for x in a):continue
            assert any(v.startswith('--emit=') and 'link' in v[7:].split(',') for v in a) or any(k=='--emit' and 'link' in v.split(',') for k,v in args)
            flags=[v[2:] for v in a if v.startswith('-C') and v!='-C']+[v for k,v in args if k=='-C'];paths=[v[12:] for v in flags if v.startswith('incremental=')]
            expected.append({'pid':e['pid'],'compiler':ex,'cdhash':e['cdhash'],'args_sha256':h(j(a)),'incremental':paths})
        assert q['emitters']==expected and len(expected)<=1
        if expected:
            assert len(expected[0]['incremental'])==1 and '/crc-work/' in expected[0]['incremental'][0]
            if q['cache']:assert expected[0]['incremental'][0].endswith('/crc-work/'+q['cache']['root'])
        else:assert q['step'] in ('repeat-1','repeat-2') and q['previous_root']==q['cache']['root']
        cache=summarise_cache(q['cache']) if q['cache'] else None
        if q['step']!='invalid':assert cache and min(cache[k] for k in ('objects','work_products','dep_graphs','allocated'))>0
        out['native'][pre]={'step':q['step'],'actual_emitters':len(expected),'argv_hashes':[e['args_sha256'] for e in expected],'kernel_stream':h(raw),'env_keys':scope,'cache':cache}
    for n in sorted(names):
        if not n.endswith('/local-incremental-final.json'):continue
        pre=n.rsplit('/',1)[0];assert get(pre+'/initial-empty.json')=={'target_entries':0,'shared_entries':0};keys=env(get(pre+'/development-environment.json'))
        disk={row[0]:row for row in json.loads(gzip.decompress(z.read(pre+'/steady-disk/disk-inodes.json.gz')))}
        c=summarise_cache(get(n),disk);assert all(c[k]>0 for k in ('objects','work_products','dep_graphs','allocated'))
        role=pre.rsplit('/',1)[1];assert c['root_sha']==out['native']['crc-clock-before/PC/'+role+'/visits/edit']['cache']['root_sha']
        out['timed'][pre]={'cache':c,'env_keys':keys}
    return out

if __name__=='__main__':
    import sys
    with ZipFile(sys.argv[1]) as z:proof=inspect(z)
    print(json.dumps(proof,sort_keys=True))
