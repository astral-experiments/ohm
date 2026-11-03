"""Join all the ordinary Ron serializations by stable definition and expansion data."""
from pathlib import Path
import collections,hashlib,json,itertools,gzip,sys,types
import os
root=Path(os.environ['RON_CONTROL_WORK']);br=Path(__file__).resolve().parent/'schema';r=types.ModuleType('ron_reader');r.__file__=str(br/'scope_rdr.py');sys.path.insert(0,str(br));src=Path(r.__file__).read_text();anchor='assert [r.var() for _ in range(7)]==[0,0,3,0,0,0,0]';assert src.count(anchor)==1;src=src.replace(anchor,anchor.replace('0,0,3,','0,0,2,'))
exec(compile(src,r.__file__,'exec'),r.__dict__)
s=json.loads(gzip.decompress((br/'rdr-identity-edges/schema-actual-pair.json.gz').read_bytes()))
p=root/'history';seen={};dec={};raw={};report={};typed={};extras=['syntax_contexts','expn_hashes','expn_data','source_map','rdr_expn','rdr_local']
for f in sorted(p.glob('events/*/*.rmeta')):
 v=f.read_bytes();h=hashlib.sha256(v).hexdigest();seen.setdefault(h,[]).append(f.parent.name)
 if h not in raw:
  raw[h]=v;typed[h]={}
  dec[h]=r.decode(v,s['symbols'],s['tables'],'ron','rustc 1.99.0-dev (d57fd1515 2026-11-02) (ohm-1.99.0-23) (Ohm metadata 3)',typed=typed[h],selected_tables=extras)
for h,samp in seen.items():
 a=next(iter(raw));left=raw[a];right=raw[h];aa,bb=dec[a],dec[h];diff=[i for i,(x,y)in enumerate(zip(left,right))if x!=y];runs=[[g[0],g[-1]+1]for _,grp in itertools.groupby(enumerate(diff),lambda elem:elem[1]-elem[0])if(g:=[x[1]for x in grp])]
 spans=[];rows={}
 for k in extras:
  ta,tb=[typed[x]['selected_tables'][k]for x in (a,h)]
  rows[k]=dict(slots=len(ta),widths=sorted({len(v)for v in ta.values()}),changed_slots=[idx for idx in sorted(set(ta)|set(tb))if ta.get(idx)!=tb.get(idx)])
  if k in ('expn_data','expn_hashes','source_map','syntax_contexts'):
   for owner,v in ta.items():
    j=int.from_bytes(v,'little')
    spans.append((j,k,owner))
 owners=[]
 for start,end in runs:
  block=max((row for row in spans if row[0]<=start),default=None)
  owners.append(dict(start=start,end=end,nearest_prior_table_payload=block))
 table_slots={i:dict(before=typed[a]['path_by_index'][i],after=typed[h]['path_by_index'][i])for i in typed[a]['path_by_index']if typed[a]['path_by_index'][i]!=typed[h]['path_by_index'][i]}
 if table_slots:print('index moves',table_slots)
 report[h]=dict(different_physical_indices=table_slots,samples=samp,size=len(right),diff_offsets=len(diff),diff_ranges=runs,nearest_pointer=owners,hash_fields={k:(aa[0][k],bb[0][k])for k in aa[0]if aa[0][k]!=bb[0][k]},tables={k:dict(different=len([key for key in set(x)|set(y)if x.get(key)!=y.get(key)]),same_multiset=collections.Counter(map(str,x.values()))==collections.Counter(map(str,y.values())),size=len(y))for k,x,y in zip(('definitions','local','expns','deps'),aa[1:],bb[1:])},reported_tables=rows)
 print(samp,len(right),len(diff),list(report[h]['hash_fields']),[(k,v['different'])for k,v in report[h]['tables'].items()],[(k,len(v['changed_slots']))for k,v in rows.items()])
(p/'metadata-comparison.json').write_text(json.dumps(report,indent=2)+'\n')
