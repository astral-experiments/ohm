"""Validate native public-hash SCCs and replay only the recorded restricted-root edges."""
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import argparse, gzip, hashlib, json, re, runpy, struct
MASK=(1<<128)-1
MODES=('native','visibility_only','optimistic')
def need(x,why):
    if not x:raise ValueError(why)
def fp(s):
    need(re.fullmatch('[0-9a-f]{32}',s),'invalid fingerprint')
    return int(s,16)
def ordered(ids,n):
    need(ids==sorted(set(ids)) and all(0<=i<n for i in ids),'invalid ordered indices')
    return ids
@dataclass(slots=True)
class Node:
    kind:str;local:int;identity:int;weight:int;scc:int;value:int;origin:int;edges:list
@dataclass(slots=True)
class Graph:
    nodes:list;nscc:int;root:int;roots:list;retained:list;roots_hash:int
def read_graph(path):
    need(0<path.stat().st_size<=2<<30,'trace size');linecap=32<<20
    with (gzip.open(path,'rt',encoding='ascii') if path.suffix=='.gz' else path.open('rt',encoding='ascii'))as f:
        def get():
            s=f.readline(linecap+1);need(0<len(s)<=linecap and s.endswith('\n'),'truncated trace row');return s.rstrip('\n').split()
        h=get();need(len(h)==5 and h[0]=='OHRDR1','header')
        n,nscc,root=map(int,h[1:4]);need(0<nscc<=n<=2_000_000 and 0<=root<n,'graph shape');rh=fp(h[4])
        seeds=[]
        for tag in ('R','T'):
            z=get();need(z[0]==tag and int(z[1])==len(z)-2,'seed counts');seeds.append(ordered(list(map(int,z[2:])),n))
        need(root in seeds[0],'crate root absent from semantic roots')
        nodes=[];total=0
        for i in range(n):
            z=get();need(len(z)>=10 and z[0]=='N' and int(z[1])==i,'node order')
            k=z[2];own=int(z[3]);ident=fp(z[4]);wt=fp(z[5]);c=int(z[6]);value=fp(z[7]);origin=int(z[8])
            need(len(k)==1 and k in 'LDEXYPSCAM' and ((k in ('L','E') and own>=0)or(k not in ('L','E')and own==-1)),'node kind/index')
            need(0<=c<nscc and 0<=origin<=3 and int(z[9])==len(z)-10,'native SCC, mask or degree')
            adj=ordered(list(map(int,z[10:])),n);total+=len(adj);need(total<=24_000_000,'edge limit')
            need(bool(origin)==(root in adj) and (not(origin&1) or k=='L'),'unattributed or phantom root edge')
            nodes.append(Node(k,own,ident,wt,c,value,origin,adj))
        need(get()==['END']and not f.read(1),'trailing/truncated trace')
    need(nodes[root].kind=='L' and nodes[root].local==0,'physical root mismatch')
    return Graph(nodes,nscc,root,*seeds,rh)
def projected(g,mode):
    need(mode in MODES,'projection')
    return [([v for v in n.edges if v!=g.root]if (mode=='visibility_only' and n.origin==1)or(mode=='optimistic' and n.origin&1)else n.edges)for n in g.nodes]
def all_live(edges,seeds):
    seen=bytearray(len(edges));stack=list(seeds)
    while stack:
        j=stack.pop()
        if not seen[j]:seen[j]=1;stack.extend(edges[j])
    return all(seen)
def kosaraju(edges):
    n=len(edges);rev=[[]for _ in edges];seen=bytearray(n);order=[]
    for a,vs in enumerate(edges):
        for b in vs:rev[b].append(a)
    for i in range(n):
        if seen[i]:continue
        seen[i]=1;stack=[(i,iter(edges[i]))]
        while stack:
            v,it=stack[-1];u=next(it,None)
            if u is None:order.append(v);stack.pop()
            elif not seen[u]:seen[u]=1;stack.append((u,iter(edges[u])))
    comps=[-1]*n;size=0
    for v in reversed(order):
        if comps[v]!=-1:continue
        stack=[v];comps[v]=size
        while stack:
            u=stack.pop()
            for a in rev[u]:
                if comps[a]==-1:comps[a]=size;stack.append(a)
        size+=1
    return comps,size
def run(g,mode):
    edges=projected(g,mode)
    need(all_live(edges,g.roots+g.retained),'projection changes the native live vertex set')
    comp,size=kosaraju(edges);sums=[0]*size;cond=[set()for _ in sums]
    for i,n in enumerate(g.nodes):
        a=comp[i];sums[a]=(sums[a]+n.weight)&MASK
        for j in edges[i]:
            b=comp[j]
            if a!=b:need(a<b,'incorrect independent DAG order');cond[a].add(b)
    for a in reversed(range(size)):sums[a]=(sums[a]+sum(sums[b]for b in cond[a]))&MASK
    vals=[sums[a]for a in comp]
    if mode=='native':
        need(size==g.nscc and len({(n.scc,a)for n,a in zip(g.nodes,comp)})==size,'native SCC partition differs')
        need(len({n.scc for n in g.nodes})==size and all(vals[i]==n.value for i,n in enumerate(g.nodes)),'native SCC weighting differs')
    members=[i for i,v in enumerate(comp)if v==comp[g.root]]
    return {'scc_count':size,'edges':sum(map(len,edges)),'root_scc_all_nodes':len(members),'root_scc_local_defs':sum(g.nodes[i].kind=='L'for i in members),'root_local_fingerprint':f'{vals[g.root]:032x}'},vals
def unwrap(path):
    with (gzip.open(path,'rb')if path.suffix=='.gz'else path.open('rb'))as f:data=f.read(128*1024*1024+1)
    need(0<len(data)<=128*1024*1024,'rmeta size');return data
def product(path,reader,name):
    m=runpy.run_path(str(reader));s=m['sig'];data=unwrap(path);raw_sha=hashlib.sha256(data).hexdigest()
    if data.startswith(b'\x7fELF'):data=s.ar.payload(data)
    need(data.startswith(b'rust\x00\x00\x00\n'),'bad rmeta header')
    off=struct.unpack_from('<Q',data,8)[0];root=m['Reader21'](data,off).read()
    need(root['crate_name']==name and root['target']=='x86_64-unknown-linux-gnu','wrong rmeta producer')
    tables=root['tables'];rows=lambda key:s.di.rows(data,tables[key])
    ids=[v.hex()for v in s.di.keyed(data,root)];need(len(ids)==len(set(ids)),'duplicate def-path identity')
    expected={}
    for k,field in [('L','local'),('E','expn')]:
        for i,raw in enumerate(rows('rdr_hashes.'+field)):
            if any(raw):
                need(0<len(raw)<=17 and raw[0]==1,'bad item fingerprint tag')
                expected[k,i]=int.from_bytes(raw[1:],'little')
    need(all(k!='L' or i<len(ids)for k,i in expected),'unknown persisted local')
    restricted=set()
    for i,b in enumerate(rows('visibility')):
        pos=int.from_bytes(b,'little')
        if pos:
            r=s.original.Reader(data,pos);tag=r.u();need(tag in (0,1),'unknown visibility')
            if tag and r.u()==0:restricted.add(i)
    head={k:root[k]for k in ('crate_name','target','public_svh','private_svh','stable_crate_id','global_public_hash')}
    return {'sha256':raw_sha,'head':head,'keys':ids,'expected':expected,'restricted':restricted}
def join(g,p):
    locals_={}
    for i,n in enumerate(g.nodes):
        if n.kind in ('L','E'):
            k=n.kind,n.local;need(k not in locals_,'repeated physical metadata index');locals_[k]=i
    need(set(locals_)==set(p['expected']),'definition or expansion membership differs from actual RDR table')
    need(all(g.nodes[v].value==p['expected'][k]for k,v in locals_.items()),'actual rmeta per-index values disagree')
    marked={n.local for n in g.nodes if n.origin&1}
    eligible={k for k in p['restricted']if ('L',k)in locals_}
    need(marked==eligible,('visibility table and native edge provenance differ',len(marked),len(eligible),sorted(marked^eligible)[:20]))
    return locals_
def solve(graph,path,reader,name):
    g=read_graph(graph);p=product(path,reader,name);owners=join(g,p)
    summary={'metadata_sha256':p['sha256'],'metadata':p['head'],'wire_nodes':len(g.nodes),'roots':len(g.roots),'retained_seeds':len(g.retained),'root_list_hash_from_compiler':f'{g.roots_hash:032x}','all_persisted_local_definitions':sum(k=='L'for k,i in owners),'all_persisted_local_expansions':sum(k=='E'for k,i in owners),'root_edge_origin_masks':dict(sorted(Counter(n.origin for n in g.nodes if n.origin).items())),'projections':{}}
    values={}
    for mode in MODES:
        summary['projections'][mode],vals=run(g,mode)
        values[mode]={p['keys'][k[1]]:vals[n]for k,n in owners.items()if k[0]=='L'}
    return summary,values
def compare(a,b):
    shared=set(a['native'])&set(b['native']);native={k for k in shared if a['native'][k]!=b['native'][k]}
    ret={'shared_reachable_definitions':len(shared),'A_only':len(a['native'])-len(shared),'B_only':len(b['native'])-len(shared),'projections':{}}
    for m in MODES:
        changed={k for k in shared if a[m][k]!=b[m][k]}
        ret['projections'][m]={'changed':len(changed),'native_changes_made_stable':len(native-changed),'newly_distinct':len(changed-native)}
    return ret
def main():
    a=argparse.ArgumentParser();a.add_argument('--reader',type=Path,required=True);a.add_argument('--name',default='uv_pypi_types');a.add_argument('files',type=Path,nargs='+');o=a.parse_args();need(len(o.files)in(2,6),'pass TRACE RMETA once or for A, warm B, cold B')
    phases=[solve(o.files[i],o.files[i+1],o.reader,o.name)for i in range(0,len(o.files),2)]
    out={'schema':1,'classification':'reconstructed native graph and fixed-weight counterfactual; no timing or safety claim','products':[p[0]for p in phases]}
    if len(phases)==3:
        out['edit']=compare(phases[0][1],phases[1][1]);out['warm_vs_cold_B']=compare(phases[1][1],phases[2][1])
        need(all(phases[1][1][m]==phases[2][1][m]for m in MODES),'warm/cold B stable keyed forecasts differ')
    print(json.dumps(out,indent=2,sort_keys=True))
if __name__=='__main__':main()
