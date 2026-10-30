"""Compute paired effects directly from raw native process starts, stops, and original time -l."""
import argparse
from collections import defaultdict
from hashlib import sha256
import itertools
import json
import math
from pathlib import Path
import re
from statistics import mean,median
from zipfile import ZipFile

def derive(archive,study,stage):
    n={'screen':2,'confirmation':12}[stage]
    code={'rust':257,'cargo':428}[study]
    sets=list(itertools.combinations(range(12),6))
    roles=['PC','CP'] if n==2 else ['PC' if i in sets[code] else 'CP' for i in range(12)]
    root={'rust':'objc2-clock-','cargo':'release-clock-'}[study]+stage+'/'
    rows=defaultdict(list);cpus=defaultdict(list);previous=0
    with ZipFile(archive) as z:
        for i,visit in enumerate(roles,1):
            each={}
            for r in visit:
                window={};each[r]=window
                for step in ('edit','repeat-1','repeat-2'):
                    base=f'{root}pair-{i:02d}/{r}/{step}/'
                    t=json.loads(z.read(base+'result.json'))['cargo']
                    start,stop=t['start_ns'],t['stop_ns']
                    assert previous<start<stop and stop-start==t['ns'];previous=stop
                    time=z.read(base+'time.txt').splitlines()[0].decode()
                    real,user,system=map(float,re.fullmatch(r'\s*([0-9.]+) real\s+([0-9.]+) user\s+([0-9.]+) sys',time).groups())
                    assert abs(real-(stop-start)/1e9)<.1 and (user,system)==(t['user'],t['system'])
                    window[step]=[stop-start,user+system]
                window['edit+repeat-1']=[sum(window[k][p] for k in ('edit','repeat-1')) for p in (0,1)]
            for k in each['P']:
                rows[k].append([each[r][k][0] for r in 'PC'])
                cpus[k].append([each[r][k][1] for r in 'PC'])
    out={}
    for k,part in rows.items():
        ratios=[a/b for a,b in part];sort=sorted(ratios)
        q={'ns':part,'tree_cpu_seconds':cpus[k],'P':median(i[0] for i in part)/1e9,'C':median(i[1] for i in part)/1e9,
           'ratio':median(ratios),'n_above_2':sum(a>2*b for a,b in part),'range':[min(ratios),max(ratios)]}
        if n==12:
            oriented=[math.log(a/b/2)*(1 if d=='PC' else -1) for (a,b),d in zip(part,roles)]
            actual=mean(math.log(a/b/2) for a,b in part)
            q['ci_96.14']=[sort[2],sort[9]]
            q['one_sided_p_2x']=sum(sum(v if idx in trial else -v for idx,v in enumerate(oriented))/12>=actual-1e-12 for trial in sets)/924
        out[k]=q
    return dict(study=study,stage=stage,order=roles,derived=out)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive',type=Path);p.add_argument('study',choices=('rust','cargo'));p.add_argument('stage',choices=('screen','confirmation'));p.add_argument('output',type=Path)
    a=p.parse_args();x=derive(a.archive,a.study,a.stage)
    output=(json.dumps(x,sort_keys=True,indent=2)+'\n').encode()
    if a.output.exists():assert a.output.read_bytes()==output
    else:a.output.write_bytes(output)
    print(sha256(output).hexdigest(), {k:{key:v for key,v in q.items() if key not in ('ns','tree_cpu_seconds')} for k,q in x['derived'].items()})
if __name__=='__main__':main()
