"""Reopen the finalized signed reachability graph, its actual metadata and partial typed encoder observations."""
from collections import Counter,defaultdict
from pathlib import Path
import hashlib,json,re,struct,subprocess,sys,zipfile
legacy=Path(__file__).resolve().parent;sys.path.insert(0,str(legacy));import scope_rdr as md
sha=lambda v:hashlib.sha256(v).hexdigest();sy=(legacy/'schema/compiler/rustc_span/src/symbol.rs').read_bytes();sd=(legacy/'schema/compiler/rustc_metadata/src/rmeta/mod.rs').read_bytes();assert sha(sy)=='b432282257901159c6e2758caa570feb305f01c82b1fa67a19cf6616c6ed1b0d'and sha(sd)=='939927ea4e04ceeae1cbd63a7be80a91d213f594dafdce596ac0e7815ce8ca2c'
symbols=md.decode_symbols(sy.decode());tables=re.findall(r'^    (\w+): Table<',sd.decode().split('define_tables! {',1)[1].split('\n}',1)[0],re.M);assert len(tables)==88 and len(symbols)==2314
ver='rustc 1.99.0-dev (f5a51d8cc 2026-11-03) (ohm-1.99.0-24) (Ohm metadata 3)'
def rawmeta(z,prefix):
 r=json.loads(z.read(prefix+'/selected.json'));b=subprocess.check_output(['zstd','-qdc'],input=z.read('metadata/'+r['meta_sha']+'.zst'));assert sha(b)==r['meta_sha']and len(b)==r['bytes'];d={};m=md.decode(b,symbols,tables,'ruff',ver,typed=d);return m,d
def u(x,pos=0,n=4):return int.from_bytes(x[pos:pos+n],'little')
def key(x):
 t=u(x)
 if t in (15,16,18):return(t,x[4:12])
 if t==17:return(t,x[4:8])
 if t==19:return(t,x[8:16])
 return(t,x[:24])
def scc(edges):
 n=len(edges);rev=[[]for _ in range(n)];seen=set();done=[]
 for i,es in enumerate(edges):
  for e in es:rev[e].append(i)
  if i in seen:continue
  seen.add(i);stack=[(i,iter(es))]
  while stack:
   p,it=stack[-1];j=next(it,None)
   if j is None:done.append(p);stack.pop()
   elif j not in seen:seen.add(j);stack.append((j,iter(edges[j])))
 c=[-1]*n;groups=[]
 for x in reversed(done):
  if c[x]!=-1:continue
  i=len(groups);group=[];groups.append(group);todo=[x];c[x]=i
  while todo:
   v=todo.pop();group.append(v)
   for e in rev[v]:
    if c[e]==-1:c[e]=i;todo.append(e)
 assert min(c)>=0;return c,groups
class Graph:
 def __init__(self,z,phase):
  path='observed-ruff/'+phase;self.m,self.typed=rawmeta(z,path);g=z.read(path+'/graph.bin');n=u(g,0,8);assert 100<n<2000000
  self.rows=[g[8+64*i:8+64*(i+1)]for i in range(n)];i=8+64*n;self.kind=[u(r)for r in self.rows];self.ident=[r[48:64].hex()for r in self.rows];self.byid=defaultdict(list);self.nkeys=defaultdict(list)
  for j,b in enumerate(self.rows):self.byid[self.ident[j]].append(j);self.nkeys[key(b[:32])].append(j)
  def vec():
   nonlocal i
   size=u(g,i,8);assert size<=n;i+=8;xs=struct.unpack_from('<'+str(size)+'Q',g,i);i+=8*size;assert all(0<=j<n for j in xs);return xs
  self.roots=vec();self.edges=[vec()for _ in range(n)];assert i==len(g);self.cc,self.groups=scc(self.edges);self.locals={}
  for j,row in enumerate(self.rows):
   if self.kind[j]==15 and u(row,8)==0:
    idx=u(row,4);sid,name=self.typed['path_by_index'][idx];assert sid not in self.locals;self.locals[sid]=j
  assert set(self.locals)==set(self.m[2]),(len(self.locals),len(self.m[2]));gfp=defaultdict(set)
  for sid,j in self.locals.items():gfp[self.cc[j]].add(self.m[2][sid])
  assert all(len(v)==1 for v in gfp.values()),[(t,len(v))for t,v in gfp.items()if len(v)>1][:5]
  saved=defaultdict(set)
  for comp,vs in gfp.items():saved[next(iter(vs))].add(comp)
  self.component_hash_aliases=[list(v)for v in saved.values()if len(v)>1];self.payload=defaultdict(Counter);self.addrs=defaultdict(Counter);self.uncovered=Counter()
  for lab,sz in [('payload',56),('register',72)]:
   raw=z.read(path+'/'+lab+'.bin');assert len(raw)%sz==0
   for off in range(0,len(raw),sz):
    r=raw[off:off+sz];src=self.nkeys.get(key(r[:32]),[]);dst=self.nkeys.get(key(r[32:64]),[])if lab=='register'else None
    if len(src)!=1 or (dst is not None and len(dst)!=1):self.uncovered[lab+'-unresolved']+=1;continue
    if dst is None:self.payload[src[0]][(r[32:48].hex(),u(r,48,8))]+=1
    elif dst[0]in self.edges[src[0]]:self.addrs[src[0],dst[0]][u(r,64,8)]+=1
    else:self.uncovered[lab+'-removed']+=1
 def name(self,j):
  row=self.rows[j];t=self.kind[j]
  if t==15 and u(row,8)==0:return self.typed['path_by_index'][u(row,4)][1]
  if t==15:return f'foreign DefId({u(row,8)}:{u(row,4)})'
  if t==16:return f'ExpnId({u(row,8)}:{u(row,4)})'
  if t==17:return f'SyntaxContext({u(row,4)})'
  return f'node-kind {t}, stable {self.ident[j]}'
 def summary(self):
  return dict(header=self.m[0],nodes=len(self.rows),edges=sum(map(len,self.edges)),public_roots=len(self.roots),components=len(self.groups),public_defs=len(self.locals),distinct_public_hashes=len(set(self.m[2].values())),public_sccs=len({self.cc[i]for i in self.locals.values()}),cross_scc_hash_aliases=len(self.component_hash_aliases),duplicate_stable_node_ids=sum(len(js)>1 for js in self.byid.values()),observed_payload_sites=sum(sum(x.values())for x in self.payload.values()),observed_edge_sites=sum(sum(x.values())for x in self.addrs.values()),partial_or_removed=dict(self.uncovered))
def delta(a,b):
 common=set(a.byid)&set(b.byid);unique=sorted(h for h in common if len(a.byid[h])==len(b.byid[h])==1);result=[];changed={k for k in a.m[2]if a.m[2][k]!=b.m[2].get(k)}
 for h in unique:
  i=a.byid[h][0];j=b.byid[h][0];left={a.ident[e]for e in a.edges[i]};right={b.ident[e]for e in b.edges[j]};ap=a.payload[i];bp=b.payload[j]
  if left!=right or ap!=bp:
   edges=[]
   for g,src,diff in ((a,i,left-right),(b,j,right-left)):
    edges.append([{'name':g.name(e),'stable':g.ident[e],'sites':dict(g.addrs[src,e])}for e in g.edges[src]if g.ident[e]in diff])
   result.append(dict(name=a.name(i),stable=h,kind=a.kind[i],old_unique_edges=edges[0],new_unique_edges=edges[1],old_partial_payload_only=[[v,hex(s),c]for (v,s),c in (ap-bp).items()],new_partial_payload_only=[[v,hex(s),c]for (v,s),c in(bp-ap).items()]))
 return dict(changed_public=len(changed),same_public_crate_requirements=a.m[4]==b.m[4],same_expansion_map=a.m[3]==b.m[3],same_local_definitions=a.m[1]==b.m[1],same_local_indices=a.typed['path_by_index']==b.typed['path_by_index'],unique_join=len(unique),ambiguous_common=len(common)-len(unique),stable_nodes_missing_old=len(set(b.byid)-set(a.byid)),stable_nodes_missing_new=len(set(a.byid)-set(b.byid)),differing_observations=result)
if __name__=='__main__':
 file,digest,out=Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3])
 assert hashlib.file_digest(file.open('rb'),'sha256').hexdigest()==digest
 with zipfile.ZipFile(file)as z:
  phases=[s for s in ('initial-consumer','producer-NEW','producer-REPAIR','producer-OLD') if 'observed-ruff/'+s+'/graph.bin'in z.namelist()];gs={s:Graph(z,s)for s in phases};res={'original':digest,'phases':{s:g.summary()for s,g in gs.items()}}
  if 'producer-OLD'in gs:res['old_to_restored']=delta(gs['initial-consumer'],gs['producer-OLD'])
  out.write_text(json.dumps(res,indent=1,sort_keys=True)+'\n')
  print(phases,[(r['nodes'],r['public_defs'],r['cross_scc_hash_aliases'],r['duplicate_stable_node_ids'])for r in res['phases'].values()],str(res.get('old_to_restored',{}).get('changed_public')))
