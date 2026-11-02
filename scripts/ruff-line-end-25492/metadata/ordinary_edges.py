"""Resolve the source-file guard and the enum directly from unprofiled native compiler graphs."""
from collections import Counter,defaultdict
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from rows import definitions,fingerprints,rmeta
from query_values import NO_HASH,ZERO,graph,stable

def required(z,prefix,name,rec):
    raw=z.read(prefix+name+'.gz');assert hashlib.sha256(raw).hexdigest()==rec['gzip_sha256']
    n=rec['bytes'];assert 0<n<=128*(1<<20)
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:
        data=f.read(n+1);assert len(data)==n and hashlib.sha256(data).hexdigest()==rec['sha256'];return data

def phase(z,case):
    base='host-read-set/'+case+'/'
    original=json.loads(z.read(base+'original.json'))
    process=json.loads(z.read(base+'process.json'))
    hist=json.loads(z.read(base+'history.json'))
    assert original['argv']==process['argv'][:-2] and len(hist['matches'])==1
    assert original['pid']==process['regular_pid']!=process['pid'] and all(v not in original['env'] for v in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','LD_PRELOAD'))
    normal=required(z,base,'regular-graph',original['graph'])
    profiled=required(z,base,'graph',process['graph'])
    provider=required(z,base,'provider',process['provider']);assert process['provider']['sha256']==original['provider_sha256']
    t,g,h=rmeta(provider);idxs,entries=definitions(provider,t,'ruff_source_file');rdr=fingerprints(provider,t['local'])
    keys={};root=target=None
    for idx,(_,position) in entries.items():
        if not any(position):continue
        path,_,_,_,local=idxs(idx);k=stable(bytes.fromhex(h['stable_id']+local));assert k not in keys
        keys[k]=(path,rdr[idx][1] if idx in rdr else None)
        if idx==0:assert path=='ruff_source_file';root=k
        if path=='ruff_source_file::line_index::PositionEncoding':target=k
    assert root and target and root!=target
    sides={}
    for role,data in [('ordinary',normal),('profiled',profiled)]:
        nodes,s=graph(data,h['stamp'])
        guard,=[i for i,r in nodes.items() if r[0:2]==('external_metadata_input_hash',root)]
        enum,=[i for i,r in nodes.items() if r[0:2]==('module_children',target)]
        edges=[];parents=[]
        for i,(kind,key,value,start,width,number) in nodes.items():
            refs=[int.from_bytes(data[p:p+width],'little') for p in range(start,start+width*number,width)]
            if guard in refs:
                name,fp=keys.get(key,(None,None));edges.append({'kind':kind,'key':key,'value':value,'def_path':name,'rdr':fp,'index':i})
            if enum in refs:parents.append({'kind':kind,'key':key,'value':value,'index':i,'def_path':keys.get(key,(None,None))[0]})
        assert any(r['key']==target and r['kind']=='module_children' for r in edges)
        sides[role]={'graph':s,'guard_index':guard,'guard_key':root,'guard_value':nodes[guard][2],'target_index':enum,'target_key':target,'target_value':nodes[enum][2],
                     'direct_guard_reads':edges,'direct_enum_callers':parents}
    return {'source':hist['source'],'regular_pid':original['pid'],'diagnostic_pid':process['pid'],'signed_rustc':process['rustc'],
            'provider':original['provider_sha256'],'ordinary_graph':original['graph'],'profile_graph':process['graph'],'query_profile':process['profile'],'argv_sha':hist['canonical_sha256'],
            'native':{k:v for k,v in json.loads(z.read(base+'native-replayed.json')).items() if k!='members'},
            'native_members':sum(r[0].endswith('.o') for r in json.loads(z.read(base+'native-normal.json'))['members']),
            'rustc_sources':{'stable_provider':h['stable_id'],'producer_global':provider[g:g+16].hex()},'observations':sides}

def compare(a,b):
    def index(rows):
        out=defaultdict(list)
        for r in rows:out[r['kind'],r['key']].append(r)
        return out
    l=index(a);r=index(b);counts=Counter();rdr_counts=Counter();diff=[]
    for k in sorted(l.keys()|r.keys()):
        x,y=l.get(k,()),r.get(k,())
        if not x:status='added'
        elif not y:status='missing'
        elif len(x)!=1 or len(y)!=1:status='duplicate'
        elif k[0] in NO_HASH or ZERO in (x[0]['value'],y[0]['value']):status='unhashable_or_zero'
        else:status='same' if x[0]['value']==y[0]['value'] else 'changed'
        counts[status]+=1
        if len(x)==len(y)==1 and 'rdr' in x[0]:
            fp='missing_rdr' if None in (x[0]['rdr'],y[0]['rdr']) else 'same_rdr' if x[0]['rdr']==y[0]['rdr'] else 'changed_rdr'
            rdr_counts[fp,status]+=1
        if status!='same':diff.append({'kind':k[0],'key':k[1],'status':status,'left':list(x),'right':list(y)})
    return {'counts':{s:counts[s] for s in ('same','changed','added','missing','duplicate','unhashable_or_zero')},
            'rdr':[[a,b,n] for (a,b),n in sorted(rdr_counts.items())],'differences':diff}

def extract(z):
    states={c:phase(z,c) for c in ('old','edit','clean')};summaries={}
    for name,case in states.items():
        a,b=case['observations'].values()
        summaries[name+'_ordinary_profile']=compare(a['direct_guard_reads'],b['direct_guard_reads'])
    for role in ('ordinary','profiled'):
        for x,y in (('old','edit'),('edit','clean'),('old','clean')):
            a,b=(states[c]['observations'][role] for c in (x,y))
            summaries[role+'_'+x+'_'+y]=compare(a['direct_guard_reads'],b['direct_guard_reads'])
            summaries[role+'_'+x+'_'+y+'_enum_callers']=compare(a['direct_enum_callers'],b['direct_enum_callers'])
    return {'states':states,'summaries':summaries}
if __name__=='__main__':
    with zipfile.ZipFile(sys.argv[1]) as z:Path(sys.argv[2]).write_text(json.dumps(extract(z),indent=2,sort_keys=True)+'\n')
