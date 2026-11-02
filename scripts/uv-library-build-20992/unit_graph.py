"""Prove entire Cargo unit-graph equality under an explicit, bounded permutation of unit numbers."""
import json,itertools,collections,math,hashlib
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def prove(a,b):
 assert set(a)==set(b)=={'version','units','roots'} and a['version']==b['version']==1
 x=a['units'];y=b['units'];assert len(x)==len(y)==575;N=len(x)
 def groups(rows):
  out=collections.defaultdict(list)
  for n,u in enumerate(rows):
   assert 'dependencies'in u and all(isinstance(d['index'],int)and 0<=d['index']<N for d in u['dependencies'])
   out[json.dumps({k:v for k,v in u.items()if k!='dependencies'},separators=(',',':'),sort_keys=True)].append(n)
  return out
 A=groups(x);B=groups(y);assert A.keys()==B.keys()and all(len(A[k])==len(B[k])for k in A)
 mapping=[None]*N;amb=[]
 for g,ids in A.items():
  if len(ids)==1:mapping[ids[0]]=B[g][0]
  else:amb.append((ids,B[g]))
 assert math.prod(math.factorial(len(p[0]))for p in amb)<=4096
 for lists in itertools.product(*(itertools.permutations(yv)for xv,yv in amb)):
  for (ids,_),dest in zip(amb,lists,strict=True):
   for i,n in zip(ids,dest,strict=True):mapping[i]=n
  assert set(mapping)==set(range(N))
  if [mapping[r]for r in a['roots']]!=b['roots']:continue
  for i,row in enumerate(x):
   deps=[dict(d,index=mapping[d['index']])for d in row['dependencies']]
   if deps!=y[mapping[i]]['dependencies']:break
  else:
   return dict(stored_rows=N,ordered_dependency_rows=sum(len(u['dependencies'])for u in x),material_groups=len(A),roots=a['roots'],applied_permutation=[[i,j]for i,j in enumerate(mapping)if i!=j],araw=digest(a),braw=digest(b))
 raise ValueError('no complete, label- and edge-preserving bijection for the registered Cargo units')

