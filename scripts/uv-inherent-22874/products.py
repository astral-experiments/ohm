"""Record workspace products by content before gates and by stable definition identity across fresh B."""
import gzip,json,re
from pathlib import Path
import core as c
m=c.m
def stash(directory,data):
    key=m.digest(data);dest=directory/(key+'.gz')
    if not dest.exists():
        with dest.open('xb')as f:f.write(gzip.compress(data,compresslevel=2,mtime=0))
    else:c.guard(m.digest(gzip.decompress(dest.read_bytes()))==key,'content collision')
    return key
def aggregate(target,output,store,parser,lookup):
    paths={};raw={};semantic={};selected=None
    for name,folder in sorted(c.P['workspace_check_libraries'].items()):
        pkg=Path(folder).name
        members=[p for p in (target/'debug/build'/pkg).glob('*/out/lib'+name+'-*.rmeta')if p.is_file()and not p.with_suffix('.rlib').exists()]
        c.guard(len(members)==1,('declared workspace library',name,[str(p)for p in members]));p=members[0]
        c.guard(p.resolve(strict=True)==p and p.is_relative_to(target)and 0<p.stat().st_size<40<<20,'bounded native product')
        data=p.read_bytes();paths[name]=str(p.relative_to(target));raw[name]=[len(data),stash(store,data)]
    sidecars={str(p.relative_to(target)):m.digest(p.read_bytes())for p in sorted(target.rglob('*.public-api-hash'))if p.is_file()}
    m.save(output/'raw-products.json',{'relative_paths':paths,'raw':raw,'public_sidecars':sidecars})
    c.guard(len(raw)==len(c.P['workspace_check_libraries'])==38 and sidecars,'complete workspace/sidecars')
    for name,(n,key)in raw.items():
        data=gzip.decompress((store/(key+'.gz')).read_bytes());c.guard(len(data)==n and m.digest(data)==key,'retained bytes')
        semantic[name]=c.deep.project(parser,data,name)
        if name=='uv_pypi_types':selected=lookup(data,parser)
    c.guard(selected,'source-matched provider missing')
    obj={'relative_paths':paths,'raw':raw,'semantic':semantic,'public_sidecars':sidecars,'provider':selected};m.save(output/'products.json',obj);return obj
def comparable(obj):
    return {k:obj[k]for k in('relative_paths','semantic','public_sidecars','provider')}
def compare(out,one,two,same_seed):
    difference={kind:sorted(k for k in (set(one[kind])|set(two[kind]))if one[kind].get(k)!=two[kind].get(k))for kind in('raw','semantic','relative_paths','public_sidecars','provider')}
    semantic=all(not values for k,values in difference.items()if k!='raw');raw=not difference['raw']
    payload={'same_checkpoint':same_seed,'semantic_equal':semantic,'raw_equal':raw,'differences':difference,'passed':semantic and (raw or not same_seed)}
    m.save(out,payload);return payload['passed']
def identities(data,parse):
    from struct import unpack_from
    hdr,rows,*_=parse(data,'uv_pypi_types');g=parse.__globals__;sig=g['SIG'];root=g['SNAP']['Reader21'](data,unpack_from('<Q',data,8)[0]).read()
    c.guard(hdr['stable_crate_id']==root['stable_crate_id'],'stable crate')
    prefix=int(root['stable_crate_id'],16).to_bytes(8,'little').hex();ids=sig.di.keyed(data,root);indexes={v.hex():i for i,v in enumerate(ids)}
    tables={n:sig.di.rows(data,root['tables'][n])for n in ('inherent_impls','associated_item_or_field_def_ids')}
    def children(n,key):
        v=tables[n][indexes[key]];pos=int.from_bytes(v[::2],'little');num=int.from_bytes(v[1::2],'little')
        c.guard(0<pos<len(data)and 0<num<100,'associated list');reader=sig.Reader(data,pos);return [ids[reader.u()].hex()for _ in range(num)]
    result={}
    for receiver,item in c.P['encoded_methods'].items():
        owners=[k for k,(_,parent,kind,name,slot)in rows.items()if kind=='TypeNs'and name==receiver and slot==0 and rows[parent][3]=='simple_json'];c.guard(len(owners)==1,('receiver',receiver));owner=owners[0]
        matches=[]
        for imp in children('inherent_impls',owner):
            ch=children('associated_item_or_field_def_ids',imp);symbols={str(rows[k][3]):prefix+k for k in ch}
            if set(symbols)==set(item.values()):
                c.guard(rows[imp][2]=='Impl'and all(rows[k][1]==imp and rows[k][2]=='ValueNs'for k in ch),'impl/child relationship');matches.append((imp,symbols))
        c.guard(len(matches)==1,('unique previously source-verified inherent block',receiver));imp,symbols=matches[0]
        result[receiver]={'type_id':prefix+owner,'impl_id':prefix+imp,'slot':rows[imp][4],'methods':{name:symbols[key]for name,key in item.items()}}
    return result
def movement(role,a,b):
    expected=role==c.ROLES[0];rows={}
    for name,block in c.P['predicted'].items():
        l=a[name];r=b[name];c.guard(l['type_id']==r['type_id']and l['methods'].keys()==r['methods'].keys(),'same nominal/methods')
        changed=[n for n in block['pub']if l['methods'][n]!=r['methods'][n]]
        c.guard((l['impl_id']!=r['impl_id'])==expected and set(changed)==(set(block['pub'])if expected else set()),('real candidate gate',role,name))
        c.guard((l['slot'],r['slot'])==(block['old_global'],block['new_global'])if expected else l['slot']==r['slot']>=2**31,'physical impl disambiguation')
        rows[name]=changed
    name='RequiresPythonInterner';c.guard(a[name]==b[name],'unchanged earlier bare-type control')
    return rows
