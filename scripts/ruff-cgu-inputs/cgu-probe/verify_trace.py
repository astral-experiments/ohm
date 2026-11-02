"""Decode actual -22 signed runtime decisions. Qualify every reported graph edge against the prior disk state."""
from argparse import ArgumentParser
from collections import Counter,defaultdict
from pathlib import Path
import hashlib,json,re,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph

MAX=2**32-1
KEY=re.compile('[a-f0-9]{32}')
PC={'5c662df':'already-red','5c663a7':'unforceable','5c6644f':'unforceable','5c6656a':'unforceable','5c66603':'unforceable','5c6664c':'unforceable','5c667b3':'forced-red','5c66ac4':'force-error','5c66150':'promotion-refused'}
def trace(path):
    order={};finished=set();driver=0;end=None
    for line in path.read_text().splitlines():
        if not line.startswith('CGUR '):continue
        assert end is None,('output after compiler termination',line)
        _,event,*f=line.split()
        if event in ('FD','CLIENT'):continue
        if event=='DRIVER':
            assert len(f)==1 and int(f[0],16)>0;driver+=1;continue
        if event=='END':
            assert len(f)==2;end=tuple(map(int,f));continue
        assert event in list('ENWDGTCVRFX') and f,line
        seq,*f=f;seq=int(seq);assert seq not in finished
        if event=='E':
            assert seq not in order and len(f)==2;order[seq]={'E':list(map(int,f)),'R':[]};continue
        row=order[seq];assert event not in row or event=='R'
        if event=='X':
            assert len(f)==1 and f[0]in ('0','1','2');row[event]=int(f[0]);finished.add(seq)
        elif event=='R':
            assert len(f)>=4;pc,reason,depth,*chain=f;depth=int(depth);assert reason==PC[pc]
            assert len(chain)==depth+(reason!='promotion-refused') and depth>0
            if len(chain)>depth:assert chain[-1].startswith('>');chain[-1]=chain[-1][1:]
            nodes=[]
            for token in chain:
                i,k,h=token.split(':');assert KEY.fullmatch(h);assert int(k)<len(graph.NAMES);nodes.append((int(i),int(k),h))
            row[event].append(dict(pc=pc,reason=reason,depth=depth,nodes=nodes))
        elif event in ('G','W'):
            assert len(f)==(3 if event=='G'else 2)
            h=''.join(f[-2:]);assert KEY.fullmatch(h);row[event]=(int(f[0]),h)if event=='G'else h
        elif event in ('D','C','V'):
            assert len(f)==(1 if event=='D'else 2);row[event]=list(map(int,f))
        elif event=='N':
            assert len(f)==1 and re.fullmatch(r'[A-Za-z0-9_.-]{1,249}',f[0]);row[event]=f[0]
        else:
            assert (event=='T'and not f)or(event=='F'and f==['native']);row[event]=True
    assert driver==1 and end==(len(order),0) and 0<len(order)<=4096
    assert set(order)==finished==set(range(1,len(order)+1))
    return order

def evidence(old,new,products,rows):
    def refs():
        for row in rows.values():
            for r in row['R']:yield from r['nodes']
            if 'C'in row:yield (row['C'][0],*row['G'])
    nodes=list(set(refs()));indices={i for i,k,h in nodes};keys={(k,h)for i,k,h in nodes}
    keys.update(row['G']for row in rows.values()if'G'in row)
    oh,oldrows=graph.graph(old,indices=indices,keys=keys)if old else ({},{})
    nh,newrows=graph.graph(new,keys=keys)if new else ({},{})
    current=defaultdict(list)
    for r in newrows.values():current[r['kind'],r['key']].append((r['index'],r['value']))
    prior_keys={(r['kind'],r['key'])for r in oldrows.values()}
    wp=graph.work(products)if products else {}
    def node_e(i,k,h):
        out=dict(previous_index=i,kind=k,name=graph.NAMES[k],key=h)
        if old:
            r=oldrows[i];assert r['key']==h and r['kind']==k;out['previous_value']=r['value']
        if new:
            matches=sorted(current.get((k,h),()))
            out['current_candidates']=[{'index':index,'value':value}for index,value in matches]
            if len(matches)==1:out['current_index']=matches[0][0]
            values={value for _,value in matches}
            if len(values)==1:out['current_value']=next(iter(values))
            out['current_match']='absent'if not matches else 'unique'if len(matches)==1 else 'duplicates-agree'if len(values)==1 else 'duplicates-conflict'
        return out
    result=[]
    for seq,row in sorted(rows.items()):
        d=dict(sequence=seq,cgu=row.get('N'),work_product_id=row.get('W'),actual_cgu_reuse=['No','PreLto','PostLto'][row['X']])
        result.append(d)
        if 'N'not in row:
            assert row['X']==0 and not any(k in row for k in ('W','G','D','C','F','V'));d['reason']='incremental-disabled';continue
        assert 'D'in row and row['D']in ([1],[0])
        if products:d['serialized_work_product']=wp.get(row['W'])
        if row['D']==[0]:
            assert row['X']==0 and 'G'not in row and 'F'not in row;d['reason']='no-reconciled-donor';continue
        if products:assert wp.get(row['W'],{}).get('name')==row['N']
        if row.get('F'):
            assert row['X']==0 and 'G'not in row;d['reason']='forced-native';continue
        assert row.get('T') and 'G'in row and row['G'][0]==5 and 'V'in row
        k,h=row['G'];d['root']={'kind':k,'key':h};v,_=row['V'];assert (row['X']!=0)==(v!=MAX)
        if 'C'not in row:
            assert row['X']==0 and (not old or (k,h)not in prior_keys);d['reason']='no-prior-dep-node';continue
        root,color=row['C'];d['root']=node_e(root,k,h);d['initial_color']='unknown'if color==MAX else'red'if color==MAX-1 else'green'
        failures=[]
        for f in row['R']:
            assert f['nodes'][0]==(root,k,h);out=dict(pc=f['pc'],reason=f['reason'],frame_depth=f['depth'],path=[])
            for pos,node in enumerate(f['nodes']):
                child=node_e(*node);out['path'].append(child)
                if pos and old:
                    edges=oldrows[f['nodes'][pos-1][0]]['edges'];positions=[i for i,v in enumerate(edges)if v==node[0]];assert positions
                    if len(positions)==1:child['ordinal_from_parent_0']=positions[0]
                    else:child['possible_ordinals_from_parent_0']=positions
            failures.append(out)
        d['observed_rejections']=failures;direct=[f for f in failures if f['frame_depth']==1]
        if row['X']:
            assert v==root;d['reason']='green';continue
        if color==MAX-1:
            assert not direct;d['reason']='root-already-red';continue
        assert color==MAX and len(direct)==1,('unresolved direct root failure',row)
        d['reason']=direct[0]['reason'];d['direct_failure']=direct[0]
    names=[r['cgu']for r in result if r['cgu']];assert len(set(names))==len(names)
    return dict(prior_graph=oh,current_graph=nh,decisions=result,counts=dict(Counter(r['reason']for r in result)))

def main():
    a=ArgumentParser();a.add_argument('trace',type=Path)
    for n in ('prior-graph','current-graph','work-products','signed-driver','output'):a.add_argument('--'+n,type=Path)
    a=a.parse_args()
    if a.signed_driver:
        assert graph.sha(a.signed_driver)=='4c8ccf0072e8f382a3a3756fd60e46936a2bd206996201c55caffe58d29725db'
        graph.signed_names(a.signed_driver)
    out=evidence(a.prior_graph,a.current_graph,a.work_products,trace(a.trace))
    out['source_sha256']={k:graph.sha(p)for k,p in [('trace',a.trace),('prior_graph',a.prior_graph),('current_graph',a.current_graph),('work_products',a.work_products)]if p}
    payload=json.dumps(out,indent=2,sort_keys=True)+'\n'
    if a.output:a.output.write_text(payload)
    else:print(payload,end='')
if __name__=='__main__':main()
