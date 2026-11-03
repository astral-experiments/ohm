"""Sum Callgrind guest instructions and direct caller/callee arcs from the unmodified raw stream."""
from pathlib import Path
import collections, hashlib,json,re,sys
def read(path):
    names={}; selfcost=collections.Counter(); edge_cost=collections.Counter();edge_calls=collections.Counter();objects=collections.defaultdict(set)
    fn=cf=obj=None; pend=None;positions=1;foreign=[];events=totals=cmd=pid=None
    def symbol(text,domain):
        m=re.fullmatch(r'\((\d+)\)(?: (.*))?',text)
        if not m:return (domain,text)
        key=(domain,int(m[1]))
        if m[2] is not None:
            old=names.setdefault(key,m[2]);assert old==m[2]
        return key
    def resolve(key):return names[key] if isinstance(key[1],int) else key[1]
    with path.open() as f:
        for raw in f:
            l=raw.strip()
            if not l:continue
            if l.startswith('fn='):
                fn=symbol(l[3:],'fn');cf=None
                if obj:objects[fn].add(obj)
            elif l.startswith('cfn='):cf=symbol(l[4:],'fn')
            elif l.startswith('ob='):obj=symbol(l[3:],'ob')
            elif l.startswith('cob='):symbol(l[4:],'ob')
            elif l.startswith('calls='):
                assert pend is None and fn and cf;lft=l[6:].split();pend=(fn,cf);edge_calls[pend]+=int(lft[0])
            elif l[0] in '0123456789+*-':
                fields=l.split();assert len(fields) in (positions,positions+1),l
                ir=int(fields[-1]) if len(fields)>positions else 0
                if pend:edge_cost[pend]+=ir;pend=None
                else:
                    assert fn is not None; selfcost[fn]+=ir
            elif l.startswith('positions:'):positions=len(l.split())-1
            elif l.startswith('events:'):events=l.split()[1:]
            elif l.startswith('totals:'):totals=int(l.split()[1])
            elif l.startswith('cmd:'):cmd=l[4:].strip()
            elif l.startswith('pid:'):pid=int(l.split()[1])
    assert pend is None and events==['Ir'] and sum(selfcost.values())==totals and totals>0 and cmd and pid
    flat=collections.Counter(); costs=collections.Counter(); counts=collections.Counter(); mods=collections.defaultdict(set)
    for k,v in selfcost.items():flat[resolve(k)]+=v
    for a,b in edge_calls:
        key=(resolve(a),resolve(b));costs[key]+=edge_cost[(a,b)];counts[key]+=edge_calls[(a,b)]
    for f,objs in objects.items():mods[resolve(f)].update(resolve(o) for o in objs)
    return {'cmd':cmd,'pid':pid,'Ir':totals},flat,costs,counts,mods

def summary(path):
    meta,flat,costs,calls,objects=read(path)
    driver='librustc_driver-b03bf00bec23bb9a.so'
    named=[n for n,objs in objects.items() if any(Path(o).name==driver for o in objs) and not n.startswith('0x') and n not in ('???','(below main)')]
    selected=lambda n:any(k in n for k in ('fully_expand_fragment','collect_invocations','hir_crate_items','lower_to_hir','expand_crate','expansion::','early_lint_checks'))
    def arcs(items):return [{'caller':c,'callee':d,'calls':calls[c,d],'guest_Ir':v} for (c,d),v in items]
    return {**meta,'flat_sum':sum(flat.values()),'function_names':len(flat),'direct_arcs':len(costs),
        'named_release_driver_functions':len(named),'named_release_driver_self_Ir':sum(flat[n] for n in named),
        'flat':flat.most_common(150),'direct':arcs(costs.most_common(250)),
        'selected_direct':arcs(sorted([((c,d),v) for (c,d),v in costs.items() if selected(c) or selected(d)],key=lambda v:-v[1])[:200])}
if __name__=='__main__':print(json.dumps(summary(Path(sys.argv[1])),indent=2))
