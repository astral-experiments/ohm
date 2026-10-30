"""Compact the output of the independent, original-file reopener; hash all six unabridged reductions."""
from pathlib import Path
import gzip,hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify import checks
h=lambda b:hashlib.sha256(b).hexdigest()
def project(p):
    all={}
    for n in ('matrix.json','provider-rows.json.gz','migration-rows.json.gz','named.json','registry.json','legacy.json.gz'):
        b=(p/n).read_bytes();all[n]=(h(b),json.loads(gzip.decompress(b) if n.endswith('.gz') else b))
    m=all['matrix.json'][1];legacy=all['legacy.json.gz'][1];named=all['named.json'][1]
    old={}
    for role,rc in legacy['native'].items():
        rows=[]
        for label,phases in sorted(rc.items()):
            place,policy=label.split('-')
            for phase,one in sorted(phases.items()):
                flat=lambda a:{'code':a['status'],'answer':a['answer'],'raw':a['raw'],'full':a['full'],'links':a['ld']}
                rows.append({'placement':place,'policy':policy,'phase':phase,'warm':flat(one['warm']),'clean':flat(one['empty']),'same_native_product':one['clean'],'source':one['source']})
        old[role]=rows
    source=m['subjects'];families={name:{'commands':a['commands'],'required_failures':sum(len(j['required_failed']) for j in a['judgments'].values()),'disabled_unwatched':sum(len(j['opt_out_unwatched']) for j in a['judgments'].values()),'code_signing':a['kernel_cargo'],'actual_receipt_hits':a['prior_seal_hits'],'distinct_complete_programs':a['complete_images'],'rust_rows':a['true_producer_rows']} for name,a in m['families'].items()}
    count=lambda groups:sum(len(rows) for cases in groups.values() for rows in cases.values())
    reg={n:{stage:{name:k['physical'] for name,k in row['producer'].items()} for stage,row in phases.items()} for n,phases in all['registry.json'][1].items()}
    x={'run':41110754345,'archive':{'id':13005066644,'bytes':151308988,'sha256':m['archive'],'members':14658},'rust':source['rust']['C'],'legacy_rust':legacy['legacy_producer'],'integrated':{k:source['cargo']['aware'][k] for k in ('source','sha')},'versioned':families,'old':old,'transfers':m['transitions'],'registry':reg,'literal_v1':count(legacy['named']),'literal_v2':count(named),'raw_v1_depfiles':legacy['raw_v1_depfiles'],'raw_projection_hashes':{n:q[0] for n,q in all.items()},'observations':1596,'ordinary_ty_clocks':0}
    checks(x);return gzip.compress((json.dumps(x,sort_keys=True,separators=(',',':'))+'\n').encode(),mtime=0)
if __name__=='__main__':
    dest=Path(sys.argv[2]);p=project(Path(sys.argv[1]));assert not dest.exists() or dest.read_bytes()==p;dest.write_bytes(p)
