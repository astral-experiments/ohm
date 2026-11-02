"""Join each real host profile, current query graph and literal foreign metadata by exact identities."""
import collections
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import sys
import zipfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from measureme import need,parse_profile
from rows import definitions,entries,fingerprints,rmeta
schema=json.loads((HERE/'query-graph-schema.json').read_bytes())
assert hashlib.sha256((HERE/'query-graph-schema.json').read_bytes()).hexdigest()=='cb5c047c8140f856bca2ff679cc3882369bfec2e5e64acf716cca73627128c2c'
KINDS=schema['names'];NO_HASH=set(json.loads((HERE/'no-hash.json').read_bytes()))
assert len(KINDS)==len(set(KINDS))==365 and KINDS[5]=='CompileCodegenUnit'
ZERO='0'*32

def sha(value):return hashlib.sha256(value).hexdigest()
def stable(raw):return ''.join(f'{x:016x}' for x in struct.unpack('<QQ',raw))

def leb(data,p,limit):
    value=0
    for shift in range(0,70,7):
        assert p<limit;c=data[p];p+=1;value|=(c&127)<<shift
        if c<128:return value,p
    raise ValueError('invalid LEB')

def graph(data,stamp):
    assert data[:6]==b'RSIC'+struct.pack('<H',schema['format']) and data[-13:]==b'rust-end-file'
    p=7+data[6];ver=data[7:p].decode();need(stamp.startswith('rustc '+ver),('wrong graph reader compiler',ver,stamp))
    end=len(data)-13;mx,count,nedges=struct.unpack_from('<QQQ',data,end-24);graph_end=end-24
    seek=end>=48 and data[end-32:end-24]==b'OHMIDX01'
    if seek:
        start,roots=struct.unpack_from('<QQ',data,end-48);assert roots<=count and start+mx*8+roots*4==end-48
        graph_end=start
    assert 0<count<=mx<=2**31 and p+8+count*38<=graph_end
    args=data[p:p+8].hex();p+=8;rows={};kinds=[0]*len(KINDS);n=0
    for _ in range(count):
        offset=p;assert p+38<=graph_end
        head,idx=struct.unpack_from('<HI',data,p);kind=head&511;width=((head>>9)&3)+1;num=(head>>11)-1
        key=stable(data[p+6:p+22]);val=stable(data[p+22:p+38]);p+=38
        if num<0:num,p=leb(data,p,graph_end)
        assert kind in range(1,len(KINDS)) and idx<mx and idx not in rows and p+width*num<=graph_end
        if seek:assert struct.unpack_from('<Q',data,graph_end+8*idx)[0]==offset
        rows[idx]=(KINDS[kind],key,val,p,width,num);kinds[kind]+=1;n+=num;p+=width*num
    for expected in kinds:
        got,p=leb(data,p,graph_end);assert got==expected
    session,p=leb(data,p,graph_end);assert p==graph_end and n==nedges
    return rows,dict(nodes=count,edges=n,high=mx,version=ver,args=args,session=session,seek_index=seek)

def unpack(z,p,label,rec):
    raw=z.read(p+label+'.gz');assert sha(raw)==rec[label]['gzip_sha256']
    n=rec[label]['bytes'];assert 0<n<=128*(1<<20)
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:
        data=f.read(n+1);assert len(data)==n and sha(data)==rec[label]['sha256']
    return raw if label=='profile' else data

def phase(z,case,*,require_original=True):
    p='host-read-set/'+case+'/'
    if p+'unobserved.json' in z.namelist():return {'refused':'no profiled invocation','record':json.loads(z.read(p+'unobserved.json'))}
    rec=json.loads(z.read(p+'process.json'));orig=json.loads(z.read(p+'original.json'));hist=json.loads(z.read(p+'history.json'))
    tools=json.loads(z.read('tools.json'))
    assert rec['pid']==int(Path(rec['profile_path']).stem.rsplit('-',1)[1]) and rec['rustc']==tools['sha256']['bin/rustc']
    assert rec['argv'][:-2]==orig['argv'] and rec['argv'][-1]=='-Zself-profile-events=default,query-keys' and rec['argv'][-2].startswith('-Zself-profile=')
    assert hist['case']==case and 'ruff_source_file='+orig['provider_path'] in rec['argv']
    if require_original:assert len(hist['matches'])==1
    provider=unpack(z,p,'provider',rec);assert sha(provider)==orig['provider_sha256']
    t,g,h=rmeta(provider);assert h['owner']==('str','ruff_source_file') and len(h['stable_id'])==16
    stable_id=bytes.fromhex(h['stable_id']);names,dt=definitions(provider,t,'ruff_source_file');rdr=fingerprints(provider,t['local']);actual={}
    for idx,(_,ref) in dt.items():
        if not any(ref):continue
        name,kind,_,_,local=names(idx);assert len(local)==16
        key=stable(stable_id+bytes.fromhex(local));assert key not in actual
        actual[key]={'path':name,'index':idx,'rdr':rdr[idx][1] if idx in rdr else None}
    raw=unpack(z,p,'graph',rec);nodes,stats=graph(raw,h['stamp'])
    prof,mappings,events=parse_profile(io.BytesIO(unpack(z,p,'profile',rec)))
    assert prof['process_id']==rec['pid'] and prof['cmd']==' '.join(rec['argv'])+' '
    def edges(record):
        _,_,_,start,width,num=record
        return [int.from_bytes(raw[i:i+width],'little') for i in range(start,start+width*num,width)]
    anchors=collections.defaultdict(list)
    for idx,n in nodes.items():
        if n[1] not in actual:continue
        for e in edges(n):
            if e in nodes and nodes[e][0]=='external_metadata_input_hash':anchors[e].append((idx,n[0],actual[n[1]]['path'],mappings.get(idx)))
    anchor_summary={i:dict(queries=len(v),distinct_items=len({it for _,_,it,_ in v}),positive_labels=sum(bool(s and 'ruff_source_file' in s) for _,_,_,s in v)) for i,v in anchors.items()}
    roots=set(anchors)
    signed=[i for i,v in anchors.items() if len(v)>=3 and len({it for _,_,it,_ in v})>=2 and any(label and 'ruff_source_file' in label for _,_,_,label in v)]
    # Other dependencies remain explicit, even when no single coarse edge passes this admission.
    root=signed[0] if len(signed)==1 and len(roots)==1 else None
    rootkey=nodes[root][1] if root is not None else None
    keep=[]
    for idx,n in nodes.items():
        name,key,val,*_=n
        identity=actual.get(key);label=mappings.get(idx);pretty=None;conflict=None
        if label:
            parts=label.split('\x1e',1)
            if len(parts)==2 and parts[0]==name:pretty=parts[1]
            else:conflict=label
        all_edges=edges(n);uses=root is not None and root in all_edges
        alternative=name in ('crate_hash','public_api_hash','public_global_hash','external_metadata_input_hash','exported_non_generic_symbols','exported_generic_symbols','native_libraries') and key==rootkey
        if not (identity or uses or alternative or (pretty and 'ruff_source_file' in pretty)):continue
        keep.append(dict(kind=name,key=key,value=val,index=idx,def_id=identity,coarse_edge=uses,crate_wide=alternative,
                         profile=pretty,profile_conflict=conflict,events=events.get(idx,{}),no_hash=name in NO_HASH,zero=val==ZERO,
                         other_crate_inputs=[(nodes[e][0],nodes[e][1]) for e in all_edges if e in nodes and nodes[e][0] in ('crate_hash','public_api_hash','public_global_hash','external_metadata_input_hash') and e!=root]))
    return {'source':hist['source'],'matched_original':len(hist['matches'])==1,'physical':{k:rec[k] for k in ('pid','rustc','graph','profile','provider')},'argc_sha':hist['canonical_sha256'],
            'graph':stats,'stable_crate_id':h['stable_id'],'definitions':len(actual),'with_rdr':len(rdr),'global':provider[g:g+16].hex(),
            'public_hash':h['fields'][('self','public')][1],'anchors':anchor_summary,'selected_guard':root,
            'graph_rows_with_event':sum(i in events for i in nodes),'graph_rows_with_label':sum(i in mappings for i in nodes),'rows':keep}

def compare(a,b):
    if 'rows' not in a or 'rows' not in b:return dict(refused='unobserved input')
    ret={}
    for cohort,accept in [('observed_coarse_edges',lambda r:r['coarse_edge']),('keyed_definitions',lambda r:r['def_id'] is not None),
                          ('crate_wide',lambda r:r['crate_wide']),('profile_names_only',lambda r:r['profile'] and 'ruff_source_file' in r['profile'] and r['def_id'] is None and not r['coarse_edge'])]:
        maps=[]
        for source in (a,b):
            m=collections.defaultdict(list)
            for r in source['rows']:
                if accept(r):m[(r['kind'],r['key'])].append(r)
            maps.append(m)
        x,y=maps;count=collections.Counter();roster=[]
        for kind_key in sorted(x.keys()|y.keys()):
            left,right=x.get(kind_key,[]),y.get(kind_key,[])
            if not left:status='added'
            elif not right:status='removed'
            elif len(left)!=1 or len(right)!=1:status='duplicate'
            elif left[0]['no_hash'] or right[0]['no_hash'] or left[0]['zero'] or right[0]['zero']:status='unhashable_or_zero'
            else:status='same' if left[0]['value']==right[0]['value'] else 'changed'
            count[status]+=1
            r=(left or right)[0]
            roster.append(dict(kind=kind_key[0],key=kind_key[1],name=r['def_id']['path'] if r['def_id'] else r['profile'],status=status,
                               values=[[l['value'] for l in v] for v in (left,right)],rdr=[v[0]['def_id']['rdr'] if len(v)==1 and v[0]['def_id'] else None for v in (left,right)]))
        ret[cohort]={'counts':{v:count[v] for v in ('same','changed','added','removed','duplicate','unhashable_or_zero')},'rows':roster}
    return ret

def extract(z,*,require_original=True):
    states={p:phase(z,p,require_original=require_original) for p in ('old','edit','clean')}
    return dict(states=states,old_edit=compare(states['old'],states['edit']),edit_clean=compare(states['edit'],states['clean']),old_clean=compare(states['old'],states['clean']))
if __name__=='__main__':
    with zipfile.ZipFile(sys.argv[1]) as z:Path(sys.argv[2]).write_text(json.dumps(extract(z),sort_keys=True,indent=2)+'\n')
