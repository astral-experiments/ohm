"""Reopen the complete straced rustc set, both encoded-record inventories and current native identity."""
import argparse,ast,collections,difflib,gzip,hashlib,json,re,sys
sys.path.insert(0,str(__import__("pathlib").Path(__file__).resolve().parent))
import bundle
from pathlib import Path

D=Path(__file__).resolve().parent
def sha(b):return hashlib.sha256(b).hexdigest()
def opt(args,needle):return args[args.index(needle)+1] if needle in args else None
def unit(a):
    return(opt(a,'--crate-name'),opt(a,'--crate-type'),next((f for f in a if f.startswith('metadata=')),None),next((f for f in a if f.startswith('extra-filename=')),None),opt(a,'--out-dir'),tuple(f for f in a if f.endswith('.rs')),next((f for f in a if f.startswith('--emit')),None))
def totals(*parts):
    c=collections.Counter(parts);return dict(sorted(c.items()))
def observed(raw,role,phase,r):
    calls={}
    for path in raw:
        prefix=f'{role}/{phase}/exec.'
        if not path.startswith(prefix) or not raw[path]:continue
        pid=path[len(prefix):];assert pid.isdigit()
        for s in raw[path].splitlines():
            m=re.match(r'^execve\(("[^"]*/rustc"), (\[.*\]), 0x.*\) += 0$',s)
            if not m:continue
            a=ast.literal_eval(m[2]);assert all(isinstance(x,str)for x in a)
            name=opt(a,'--crate-name')
            if name is None:continue
            assert pid not in calls;calls[pid]=a
    assert {p:opt(a,'--crate-name')for p,a in calls.items()}==r['rustcs']
    return calls
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--original',type=Path);ap.add_argument('--output',type=Path)
    opts=ap.parse_args();b=(D/'raw-controls.json.gz').read_bytes();raw=json.loads(gzip.decompress(b))
    if opts.original:assert raw==bundle.from_original(opts.original)
    def j(p):return json.loads(raw[p])
    rr=j('release-results.json');out={};factory=j('release-factories.json')
    for name,(rev,h) in bundle.SOURCES.items():assert (factory[name]['cargo_source'],factory[name]['sha256'])==(rev,h)
    for role in ('signed','release-parent','release-child'):
        rec=rr[role];phases={k:observed(raw,role,k,v)for k,v in rec.items()if k not in ('old','independent-clean-edited')}
        for name,x in rec.items():assert x==j(f'{role}/{name}/result.json')
        counts={k:len(v)for k,v in phases.items()};assert [counts[k]for k in ('edit','edit-unchanged','private-body','invalid','repair')]==[7,1,2,2,7]
        assert rec['invalid']['exit']==101 and rec['invalid']['error_codes']==['E0308'] and all(x['exit']==0 for k,x in rec.items()if k!='invalid')
        assert sorted(rec['edit-unchanged']['rustcs'].values())==['ty_python_semantic'] and len(rec['edit-unchanged-json']['nominal_nonfresh'])==6
        assert rec['private-body']['metadata']['ruff_linter']['public']==rec['edit']['metadata']['ruff_linter']['public']
        outs=[rec['edit']['metadata'][name]['public']==rec['independent-clean-edited']['metadata'][name]['public']for name in rec['edit']['metadata']];assert len(outs)==4 and set(outs)=={role=='release-parent'}
        print(role,counts['edit'],counts['edit-unchanged'],counts['private-body'],rec['invalid']['error_codes'],f'{sum(outs)}/4 independent clean public headers agree')
    for role in ('upgrade-signed','upgrade-pre-reader'):
        phases={p:observed(raw,role,p,row)for p,row in rr[role].items()}
        old=collections.defaultdict(list)
        for a in phases['prior-empty'].values():old[unit(a)].append(a)
        rows=[]
        for pid,a in phases['first-upgraded'].items():
            k=unit(a);candidates=old[k];d={}
            if not candidates:reason='no exactly matched argument identity'
            elif a in candidates:reason='identical arguments'
            else:
                r=min(candidates,key=lambda b:sum(delta[:2]!='  'for delta in difflib.ndiff(b,a)))
                d['added']=[l[2:]for l in difflib.ndiff(r,a)if l.startswith('+ ')]
                d['removed']=[l[2:]for l in difflib.ndiff(r,a)if l.startswith('- ')]
                reason='added checksum flag only'if d=={'added':['-Z','checksum-hash-algorithm=blake3'],'removed':[]}else'other argument delta'
            rows.append(dict(pid=pid,key=k,reason=reason,old_count=len(candidates),**d))
        before=j(role+'/prior-records.json');after=j(role+'/upgraded-records.json');assert before.keys()==after.keys()
        changes=collections.Counter((v['version'],after[k]['version'])for k,v in before.items())
        roots={n:{'prior_vs_new':rr[role]['prior-unchanged']['metadata'][n]['public']==rr[role]['first-upgraded']['metadata'][n]['public'],'settled_vs_new':rr[role]['next-unchanged']['metadata'][n]['public']==rr[role]['first-upgraded']['metadata'][n]['public'],'new_vs_independent':rr['release-child']['independent-clean-edited']['metadata'][n]['public']==rr[role]['first-upgraded']['metadata'][n]['public']}for n in rr[role]['first-upgraded']['metadata']}
        out[role]={'phase_counts':{p:len(v)for p,v in phases.items()},'unit_reasons':totals(*(x['reason']for x in rows)),'file_names':len(before),'record_transition':{str(k):v for k,v in changes.items()},'root_controls':roots,'rows':rows}
        print(role,out[role]['phase_counts'],out[role]['unit_reasons'],out[role]['record_transition'],set(tuple(x.values())for x in roots.values()))
        print('other groups',collections.Counter((tuple(x.get('added',[])),tuple(x.get('removed',[])))for x in rows if x['reason']=='other argument delta').most_common(3))
        signed=role=='upgrade-signed';nr=sum(1 for a in phases['first-upgraded'].values()if opt(a,'--crate-name').startswith('autocfg_'));assert nr==(5 if signed else 0)
        assert [len(phases[k])for k in ('prior-empty','prior-unchanged','first-upgraded','next-unchanged','settled-json')]==[366,1,341 if signed else 35,1,1]
        assert all([opt(a,'--crate-name')for a in phases[p].values()]==['ty_python_semantic']for p in ('prior-unchanged','next-unchanged','settled-json'))
        assert changes==(collections.Counter({(2,2):326,(2,5):2,(4,5):32})if signed else collections.Counter({(2,2):326,(4,5):34}))
        assert out[role]['unit_reasons']==({'identical arguments':42,'added checksum flag only':270,'other argument delta':24,'no exactly matched argument identity':5}if signed else {'identical arguments':11,'other argument delta':24})
        assert all(x.get('added')==['-Zthreads=1'] and x.get('removed')==[] for x in rows if x['reason']=='other argument delta')
        cold=[opt(x,'--crate-name')for x in phases['prior-empty'].values()];assert sum(n.startswith('autocfg_')for n in cold)==5 and cold.count('___')==1
        out[role]['first_cargo_units']=len(rows)-nr;out[role]['first_autocfg_probes']=nr;out[role]['independent_cold_cargo_units']=len(cold)-6
    if opts.output:opts.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
