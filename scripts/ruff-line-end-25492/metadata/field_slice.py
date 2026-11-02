"""Compare named, physically decoded source coordinates from the three real providers."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from rows import Cursor, definitions, entries, fingerprints, rmeta

OLD='a8d0fffc4d72da193b2a2ae4c53277fdf1f1794d'
NEW='88d851449d2345e11da991794f3e9bfbbd666719'
METHODS={'LineRanges','line_end','full_line_end','UniversalNewlines','UniversalNewlineIterator','with_offset','full_end','universal_newlines','line_end_exclusive'}
FILES={'newlines':'newlines.rs','line_ranges':'line_ranges.rs','line_index':'line_index.rs','{Impl}':'lib.rs'}
FIELDS=('def_span','def_ident_span')
def sha(raw):return hashlib.sha256(raw).hexdigest()

def span(data,ptr):
    cursor=Cursor(data,ptr);tag=cursor.byte()
    if tag&3==3:
        width=tag>>3
        if not 1<=width<=8:raise ValueError('invalid indirect width')
        distance=int.from_bytes(cursor.take(width),'little')
        ptr=ptr-distance if tag&4 else distance
        if not 0<ptr<len(data):raise ValueError('invalid indirect span reference')
        cursor=Cursor(data,ptr);tag=cursor.byte()
    if tag&3 or not tag&4:return {'refused':f'nonlocal or nonroot tag {tag:#04x}'}
    lo=cursor.unsigned();n=tag>>3
    length=cursor.unsigned() if n==31 else n
    return {'lo':lo,'hi':lo+length,'metadata_file_index':cursor.unsigned()}

def select(data,root,rev):
    t,g,h=rmeta(data);defs,idx=definitions(data,t,'ruff_source_file')
    tables={n:entries(data,t[n]) for n in (*FIELDS,'def_kind')};rdr=fingerprints(data,t['local'])
    source={}
    for mod in (*FILES.keys(),):
        f='crates/ruff_source_file/src/'+FILES[mod]
        source[mod]=subprocess.check_output(['git','-C',str(root),'show',rev+':'+f])
    out={}
    for i in rdr:
        name,kind,_,_,key=defs(i);parts=name.split('::')
        if parts[-1] not in METHODS or len(parts)<3 or parts[1] not in FILES:continue
        f=source[parts[1]];v={}
        for n in FIELDS:
            field=tables[n].get(i)
            if field is None or not any(field[1]):v[n]={'refused':'no field'};continue
            point=span(data,int.from_bytes(field[1],'little'))
            if 'refused' not in point:
                if point['hi']>len(f):raise ValueError((name,n,point,len(f)))
                excerpt=f[point['lo']:point['hi']]
                if n=='def_ident_span' and excerpt.decode()!=parts[-1]:raise ValueError((name,n,point,excerpt[:100]))
                point.update(file=FILES[parts[1]],range_sha256=sha(excerpt))
            v[n]=point
        v.update(path=name,key=key,definition_kind=kind,def_kind=tables['def_kind'].get(i,(None,b''))[1].hex(),public_hash=rdr[i][1],file_sha256=sha(f))
        out[key]=v
    return out

def compare(a,b):
    assert a.keys()==b.keys()
    def coordinate(v):
        if 'refused' in v:return None
        return v['file'],v['lo'],v['hi'],v['range_sha256']
    rows={}
    for k in a:
        x,y=a[k],b[k];assert x['path']==y['path']
        rows[x['path']]={'def_kind_equal':x['def_kind']==y['def_kind'],'rdr_equal':x['public_hash']==y['public_hash'],
                         'source_equal':x['file_sha256']==y['file_sha256']}
        for name in FIELDS:
            points=[coordinate(q[name]) for q in (x,y)]
            rows[x['path']][name+'_equal']=points[0]==points[1] if all(points) else None
    return rows

def reopen(z,checkout):
    states={case:select(z.read('meta-25492/'+case+'.rmeta'),checkout,OLD if case=='old' else NEW) for case in ('old','edit','clean')}
    return dict(states=states,old_edit=compare(states['old'],states['edit']),edit_clean=compare(states['edit'],states['clean']))
if __name__=='__main__':
    with zipfile.ZipFile(sys.argv[1]) as z:print(json.dumps(reopen(z,Path(sys.argv[2])),sort_keys=True,indent=2))
