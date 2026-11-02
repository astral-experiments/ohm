"""Decode the non-reexported children returned by rustc for Ruff's PositionEncoding enum."""
import gzip
import json
from pathlib import Path
import subprocess
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from field_slice import OLD,NEW,span
from rows import Cursor,definitions,entries,rmeta

def array(raw):
    encoded=raw.ljust(16,b'\0');assert len(encoded)==16
    return int.from_bytes(encoded[::2],'little'),int.from_bytes(encoded[1::2],'little')

def project(data,repo,rev):
    t,g,head=rmeta(data);names,indices=definitions(data,t,'ruff_source_file')
    target='ruff_source_file::line_index::PositionEncoding'
    row,=[i for i,(_,v) in indices.items() if any(v) and names(i)[0]==target]
    tables={n:entries(data,t[n]) for n in ('module_children_non_reexports','module_children_reexports','def_kind','visibility','def_ident_span')}
    entry=tables['module_children_non_reexports'][row][1];pos,count=array(entry)
    assert pos and 0<count<=16
    ref=tables['module_children_reexports'].get(row,(0,b''))[1]
    _,reexports=array(ref);assert reexports==0
    raw_source=subprocess.check_output(['git','-C',repo,'show',rev+':crates/ruff_source_file/src/line_index.rs'])
    d=Cursor(data,pos);out=[]
    for _ in range(count):
        i=d.unsigned();path,kind,_,_,local=names(i);assert path.startswith(target+'::')
        name=path.split('::')[-1] if kind!='Ctor' else path.split('::')[-2]
        def_kind=tables['def_kind'][i][1].hex()
        ident_pos=int.from_bytes(tables['def_ident_span'][i][1],'little')
        s=span(data,ident_pos);assert 'refused' not in s and raw_source[s['lo']:s['hi']]==name.encode(),(name,s)
        vis_pos=int.from_bytes(tables['visibility'][i][1],'little')
        assert vis_pos>0 and data[vis_pos]==0,('expected Visibility::Public',vis_pos)
        out.append(dict(index=i,stable_local_def=local,name=name,kind=kind,def_kind_wire=def_kind,visibility='Public',reexport_chain=[],
                        span=dict(file='crates/ruff_source_file/src/line_index.rs',lo=s['lo'],hi=s['hi'],file_index=s['metadata_file_index'],syntax_context='root')))
    assert {r['name'] for r in out}=={'Utf8','Utf16','Utf32'}
    return dict(enum=target,stable_crate_id=head['stable_id'],parent_index=row,nonreexports=count,reexports=reexports,children=out)

def read(z,repo,prefix='host-read-set/'):
    states={}
    for phase in ('old','edit','clean'):
        raw=(gzip.decompress(z.read(prefix+phase+'/provider.gz')) if prefix=='host-read-set/' else z.read(prefix+phase+'.rmeta'))
        states[phase]=project(raw,repo,OLD if phase=='old' else NEW)
    a,b,c=(states[k] for k in ('old','edit','clean'))
    def logical(u):return {k:v for k,v in u.items() if k not in ('span','index')}
    assert a['stable_crate_id']==b['stable_crate_id']==c['stable_crate_id'] and [logical(v) for v in a['children']]==[logical(v) for v in b['children']]==[logical(v) for v in c['children']]
    assert [(v['span']['lo'],v['span']['hi']) for v in b['children']]==[(v['span']['lo'],v['span']['hi']) for v in c['children']]
    return states
if __name__=='__main__':
    with zipfile.ZipFile(sys.argv[1]) as z:print(json.dumps(read(z,sys.argv[2]),indent=2,sort_keys=True))
