"""Read the real A/B VirtualProject -> inherent impl -> associated DefPathHash native metadata tables."""
from pathlib import Path
from struct import unpack_from
from zipfile import ZipFile
import material as m
def one(raw,parser,required):
    header,rows,*_=parser(raw,'uv_workspace');ctx=parser.__globals__;data=ctx['SIG'].ar.payload(raw) if raw.startswith(b'\x7fELF') else raw
    sig,decoder=ctx['SIG'],ctx['SNAP']['Reader21'];root=decoder(data,unpack_from('<Q',data,8)[0]).read()
    assert root['stable_crate_id']==header['stable_crate_id'];prefix=int(root['stable_crate_id'],16).to_bytes(8,'little').hex()
    ids=sig.di.keyed(data,root);keys={key.hex():i for i,key in enumerate(ids)};assert len(keys)==len(ids)
    def actual(table,index):
        field=sig.di.rows(data,root['tables'][table])[index];offset=int.from_bytes(field[::2],'little');length=int.from_bytes(field[1::2],'little')
        assert 0<offset<len(data) and 0<length<100;read=sig.Reader(data,offset);return [ids[read.u()].hex() for _ in range(length)]
    owner,=[k for k,(_raw,parent,kind,name,slot)in rows.items() if kind=='TypeNs' and name=='VirtualProject' and slot==0 and rows[parent][3]=='workspace']
    impl,=actual('inherent_impls',keys[owner]);children=actual('associated_item_or_field_def_ids',keys[impl])
    assert rows[impl][2]=='Impl' and all(rows[k][1]==impl and rows[k][2]=='ValueNs'for k in children)
    names={rows[k][3]:prefix+k for k in children};assert len(names)==len(children)==9 and names.keys()==set(required)
    return {'type':prefix+owner,'impl':prefix+impl,'slot':rows[impl][4],'methods':names,'rmeta_sha256':m.digest(raw)}
def check(role,q,parser):
    ref=m.read(m.HERE/'identity-names.json');shape=m.shape()[1];file,=[k for k,v in shape.items()if v['name']=='uv_workspace']
    vals={}
    for label in ['ordinary-A','A-to-B','cold-B1','cold-B2']:
        with ZipFile(q/label/'workspace-rmeta.zip')as z:raw=z.read(file)
        vals[label]=one(raw,parser,ref['methods'])
    clean=lambda v:{k:x for k,x in v.items() if k!='rmeta_sha256'}
    a,b=vals['ordinary-A'],vals['A-to-B'];assert all(clean(b)==clean(vals[k])for k in ['cold-B1','cold-B2'])and a['type']==b['type']
    shifted=sorted(k for k in a['methods'] if a['methods'][k]!=b['methods'][k])
    if role=='fa7a_stack_ctfe318':assert [a['slot'],b['slot']]==[9,10] and a['impl']!=b['impl'] and shifted==sorted(ref['methods'])
    else:assert role=='fa7a_stack_ctfe318_handwritten' and a['slot']>=2**31 and clean(a)==clean(b) and not shifted
    return {'role':role,'products':vals,'changed_method_ids':shifted,'registered_source_block_sha256':ref['source_block_sha256']}
