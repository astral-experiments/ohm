"""Check all 18 observed Darwin parent, child and grandchild calibration readings."""
from hashlib import sha256
from statistics import median
import itertools,json,re,struct

def scope(v):
    report=v.js('calibration/result.json');source=v.raw('calibration/burn.c');prog=v.raw('calibration/burn')
    h=lambda p:sha256(p).hexdigest()
    assert h(source)==report['source']=='74d733c1acec5419d94182f71879e78cec89b97210a9d36ef3bf60fff37bc838'
    assert h(prog)==report['toy'] and struct.unpack_from('<4I',prog)[:2]==(0xfeedfacf,0x100000c) and struct.unpack_from('<I',prog,12)[0]==2
    rows={};expected={(rep,depth,n) for rep,depth,n in itertools.product(range(3),range(3),(0,200000000))}
    for r in report['rows']:
        rep,dep,n = (r[k] for k in ('rep','depth','iters'));key=(rep,dep,n)
        raw=v.raw(f'calibration/time-{rep}-{dep}-{n}.txt');assert key in expected and key not in rows and h(raw)==r['time_raw']
        times=re.findall(rb'^\s*([.\d]+) real\s+([.\d]+) user\s+([.\d]+) sys\s*$',raw,re.M)
        assert len(times)==1 and list(map(float,times[0]))==[r[k] for k in ('wall','user','system')]
        ir=[int(a) for a in re.findall(rb'^\s*(\d+)\s+instructions retired\s*$',raw,re.M)]
        assert ir==([r['instructions']] if 'instructions' in r else [])
        rows[key]=(r['user'],ir[0] if ir else None)
    assert set(rows)==expected
    def dif(depth,idx):
        arcs=[[rows[rep,depth,n][idx] for rep in range(3)] for n in (0,200000000)]
        if any(x is None for ls in arcs for x in ls):return None
        return median(arcs[1])-median(arcs[0])
    ir={str(d):dif(d,1) for d in range(3)};cpu={str(d):dif(d,0) for d in range(3)}
    assert report['expected_delta']==400000000 and (ir,cpu)==(report['retired_deltas'],report['user_seconds_deltas'])
    plausible=lambda x:x is not None and 360000000<=x<=440000000
    if all(plausible(x) for x in ir.values()):count_scope='whole-tree-calibrated'
    elif plausible(ir['0']) and all(x is not None and abs(x)<=20000000 for x in (ir['1'],ir['2'])):count_scope='direct-process-only'
    else:count_scope='unavailable-or-inconclusive'
    tree=cpu['0']>=.01 and all(x>=cpu['0']*.45 for x in cpu.values())
    assert (count_scope,tree)==(report['retired_instruction_scope'],report['tree_CPU_calibrated'])
    host=report['host'];assert host['machine']=='arm64' and 'Xcode 16' in host['xcode']
    return {'retired':count_scope,'tree_cpu':tree,'cpu_deltas':cpu,'retired_deltas':ir,'source':h(source),'toy':h(prog),'attempts':18}
