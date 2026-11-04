"""Read the actual emitted allocation table and classify all stored memory, identity edges, and offsets."""
from pathlib import Path
from collections import Counter,defaultdict
import ast,hashlib,inspect,json,subprocess,sys,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent));import reverse_graph as g
p=Path(g.md.__file__);source=p.read_text();old='    for _ in range(3): array()';assert source.count(old)==1
source=source.replace(old,"    trait_impls,incoherent_impls,allocs=array(),array(),array()\n    typed['interpret_alloc_index']=allocs")
ns=dict(vars(g.md));exec(compile(source,p,'exec'),ns)
parser=Path(__file__).with_name('memory_codec.py')
tree=ast.parse(parser.read_bytes());fns=[x for x in tree.body if isinstance(x,ast.FunctionDef)and x.name in ('read','encode','unpack','pack')];scope={};exec(compile(ast.Module(body=fns,type_ignores=[]),parser,'exec'),scope)
def recover(z,phase,prefix):
 base=prefix+'/'+phase;bind=json.loads(z.read(base+'/selected.json'));meta=subprocess.check_output(['zstd','-qdc'],input=z.read('metadata/'+bind['meta_sha']+'.zst'));assert hashlib.sha256(meta).hexdigest()==bind['meta_sha']
 info={};enc=ns['decode'](meta,g.symbols,g.tables,'ruff',g.ver,typed=info);n,index=info['interpret_alloc_index'];assert 0<n<50000 and 16<index<len(meta)
 decoder=g.md.Reader(meta,g.symbols);decoder.pos=index;offsets=[decoder.var()for _ in range(n)];assert sorted(set(offsets))==offsets and offsets[-1]<index
 assert b''.join(scope['encode'](v)for v in offsets)==meta[index:decoder.pos];limit=offsets[1:]+[index];rows=[meta[a:b]for a,b in zip(offsets,limit)];decoded={};kinds=Counter()
 for i,row in enumerate(rows):
  kinds[row[0]]+=1;assert row[0]in range(5)
  if row[0]==0:
   rec=scope['unpack'](row);assert scope['pack'](rec,range(n))==row and all(0<=idx<n for off,idx,immutable,shared in rec[1]);decoded[i]=rec
 return rows,decoded,dict(kinds),offsets,decoder.pos,enc
def literal(row):
 if row[0]!=0:return None
 size,at=scope['read'](row,2);flags=row[1]
 if flags&128:return None
 buf=row[at:at+size]
 try:return buf.decode('utf8')
 except UnicodeDecodeError:return None
def main(d,prefix):
 z=zipfile.ZipFile(d/'original.zip');a,b=(recover(z,ph,prefix)for ph in ('initial-consumer','producer-OLD'));ra,da,ka,oa,ae,ma=a;rb,db,kb,ob,be,mb=b
 ai=defaultdict(list);bi=defaultdict(list)
 for rs,ds,target in ((ra,da,ai),(rb,db,bi)):
  for i,row in enumerate(rs):
   if i in ds and not ds[i][1]:target[row].append(i)
 fresh={k for k in set(ai)|set(bi)if len(ai[k])!=len(bi[k])}
 result={'phase':prefix,'same_expansions':ma[3]==mb[3],'same_required':ma[4]==mb[4],'old_allocations':len(ra),'restored_allocations':len(rb),'old_discriminants':ka,'restored_discriminants':kb,'sections':[[oa[0],ae],[ob[0],be]],'changed_inert_leaf_multiplicities':[]}
 for row in sorted(fresh):
  data=literal(row);result['changed_inert_leaf_multiplicities'].append(dict(payload=data if data is not None and len(data)<160 else None,bytes=len(row),sha256=g.sha(row),before=ai[row],restored=bi[row],alignment_mutability_storage_flags=row[1]))
 print(prefix,len(ra),len(rb),ka,kb,len(fresh),[(d['payload'],d['bytes'],len(d['before']),len(d['restored']))for d in result['changed_inert_leaf_multiplicities']][:35])
 (d/(prefix+'-allocations.json')).write_text(json.dumps(result,indent=1,sort_keys=True)+'\n')
if __name__=='__main__':
 d=Path(sys.argv[1]);assert hashlib.file_digest((d/'original.zip').open('rb'),'sha256').hexdigest()==(d/'digest').read_text().strip()
 for prefix in sys.argv[2:]:main(d,prefix)
