"""Compute the upper bound after authenticating exec ancestry and PMU raw tuples separately."""
import json, sys
def ratio(whole, front):
    if not 0<=front<whole: raise ValueError('invalid removable share')
    return whole/(whole-front)
def compute(rows):
    pairs=rows["examples"]
    if len(pairs)!=12 or len({r["name"] for r in pairs})!=12:raise ValueError("requires 12 distinct qualified example roles")
    full=cc=ld=0
    for r in pairs:
        a,b,c=(r[k] for k in ("rustc_tree","cc_tree","wild_tree"))
        if not (isinstance(a,int) and isinstance(b,int) and isinstance(c,int) and a>b>=c>0):raise ValueError('inconsistent inclusive nested counters')
        full+=a;cc+=b;ld+=c
    w,u=rows['traced_whole'],rows['untraced_whole'];f=full-cc
    if min(w,u)<=0 or full>w:raise ValueError('impossible disjoint sum')
    if abs(w-u)/min(w,u)>.08:raise ValueError('observer changes whole count')
    return {'whole_traced':w,'whole_untraced':u,'rustc_including_links':full,'pure_rustc_upper_instructions':f,'cc_including_wild':cc,'wild_nested_attribution_only':ld,'outside_example_rustc':w-full,'ideal_traced':ratio(w,f),'ideal_low':ratio(max(w,u),f),'ideal_high':ratio(min(w,u),f)}
if __name__=='__main__':
    if sys.argv[1:] == ['--self-test']:
        fake={'examples':[{'name':str(i),'rustc_tree':1000,'cc_tree':400,'wild_tree':340} for i in range(12)],'traced_whole':14000,'untraced_whole':14200}
        out=compute(fake); assert out['pure_rustc_upper_instructions']==7200 and out['outside_example_rustc']==2000 and abs(out['ideal_high']-14000/6800)<1e-10
        for k in ('rustc_tree','cc_tree','wild_tree'):
            bad=json.loads(json.dumps(fake));bad['examples'][3][k]=1 if k!='wild_tree' else 999
            try:compute(bad)
            except ValueError:continue
            raise AssertionError(k)
        print('nested arithmetic and negative cases passed')
    else:print(json.dumps(compute(json.load(sys.stdin)),sort_keys=True))
