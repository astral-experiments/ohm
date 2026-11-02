"""Reconcile all 37 workspace metadata products, including both real uv-version units."""
from pathlib import Path
import gzip,wire_shape
import core as c
m=c.m
def stash(directory,data):
    key=m.digest(data);p=directory/(key+'.gz')
    if p.exists():c.guard(gzip.decompress(p.read_bytes())==data,'metadata digest collision')
    else:
        with p.open('xb')as f:f.write(gzip.compress(data,compresslevel=2,mtime=0))
    return key
def aggregate(target,output,store,parser):
    paths={};raw={};semantic={};structural={}
    declared=c.P['native_workspace_units'];seen={}
    for name,folder in c.P['workspace_check_libraries'].items():
        pk=Path(folder).name
        for p in sorted((target/'debug/build'/pk).glob('*/out/lib'+name+'-*.rmeta')):
            c.guard(p.resolve(strict=True)==p and p.is_relative_to(target)and 0<p.stat().st_size<40<<20,'bounded real workspace product')
            kind='rlib' if p.with_suffix('.rlib').is_file()else'check';key=name+'@'+kind
            c.guard(key in declared and key not in seen and declared[key]['folder']==folder and declared[key]['crate']==name,('unregistered workspace unit',key,str(p)))
            seen[key]=p
    c.guard(set(seen)==set(declared)and len(seen)==37,'all workspace metadata units')
    for key,p in sorted(seen.items()):
        b=p.read_bytes();paths[key]=str(p.relative_to(target));raw[key]=[len(b),stash(store,b)];decoded=parser(b,declared[key]['crate']);semantic[key]=c.deep.project(lambda *_:decoded,b,declared[key]['crate']);structural[key]=wire_shape.shape(*decoded[:2])
    sidecars={str(p.relative_to(target)):m.digest(p.read_bytes())for p in sorted(target.rglob('*.public-api-hash')) if p.is_file()}
    c.guard(sidecars,'public sidecars absent')
    obj={'relative_paths':paths,'raw':raw,'semantic':semantic,'structural':structural,'public_sidecars':sidecars}
    m.save(output/'products.json',obj);return obj
def comparable(obj):return {k:obj[k]for k in ('relative_paths','semantic','structural','public_sidecars')}
def compare(out,one,two,same_seed):
    diff={k:sorted(v for v in (one[k].keys()|two[k].keys())if one[k].get(v)!=two[k].get(v))for k in ('raw','semantic','structural','relative_paths','public_sidecars')}
    result=all(not v for k,v in diff.items()if k!='raw')and(not same_seed or not diff['raw'])
    m.save(out,{'same_checkpoint':same_seed,'semantic_equal':comparable(one)==comparable(two),'raw_equal':not diff['raw'],'different':diff,'passed':result})
    return result
