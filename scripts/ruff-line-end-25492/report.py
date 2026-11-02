"""Print the authenticated, compact readback and generate a review-sized summary."""
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from reopen import compact, get

RUN=41468593729
HEAD='f2e03c1e9957d94c8b254b0816efd908f0e56a78'
ART=13154446386
DIGEST='d25511aba2e879420c8969f93d8080c0ab7c16fb3dc031a1f4c4ed9515ed5677'
SIZE=147043


def summary(a,d,r):
    n=a['samples'];assert n==sum(a['class_exclusive_leaf'].values())==sum(a['class_disjoint_deepest_recognized_stack'].values())
    tables={'leaf':a['class_exclusive_leaf'],'deepest':a['class_disjoint_deepest_recognized_stack'],'any_frame':a['inclusive_union_per_class_do_not_sum']}
    groups={cat:[table.get(cat,0) for table in tables.values()] for cat in sorted(set().union(*tables.values()))}
    files=Counter();kinds=Counter();units=[];changed_edges={};material=[]
    for unit in d['delivered']:
        name,kind,features,_=unit['unit']
        deliveries=[]
        for file in unit['artifacts']:
            filename=file['name'];ext=Path(filename).suffix or 'ELF';oe=file['old_edit_equal'];ec=file['edit_clean_equal']
            files[ext,oe,ec]+=1
            deliveries.append([ext,oe,ec])
            if 'different_native_payloads' in file:
                first,_,last=file['embedded_rmeta']
                material.append([name,filename,features,file['canonical_native_members'][0],*file['different_native_payloads'],first!=last,file['embedded_rmeta'][0]!=file['embedded_rmeta'][1],file['embedded_rmeta'][1]!=file['embedded_rmeta'][2]])
        kinds[tuple(kind),all(o for _,o,_ in deliveries),all(c for _,_,c in deliveries)]+=1
        units.append([name,kind,features,deliveries])
    for name,edges in d['offered_changed_edges_by_consumer'].items():
        changed_edges[name]=[[operand,filename,changed] for _flag,operand,_provider,filename,changed in edges]
    evidence={'accepted_run':RUN,'accepted_artifact':ART,'accepted_sha256':DIGEST,'profile_producer':41466356507,
              'ordinary':41460616635,'clock':a['profiled_clock'],'ordinary_clock':a['ordinary_clock'],'samples':n,'period':a['period'],
              'sample_coverage':a['coverage_fraction'],'leaf_deepest_any_frame':groups,
              'unknown_leaf':a['unknown_leaf_by_owner'],'stack_depths':a['stack_depth'],'owners':a['owner_samples'],
              'owner_deepest':a['by_owner_disjoint_stack'],'owner_leaf_symbols':a['top_owner_leaf_functions'][:32],
              'class_top_leaf':a['top_leaf_by_exclusive_stack_class'],
              'phases':{p:[v[k] for k in ('products','dirty','rustc','wild')] for p,v in r['phases'].items()},
              'tool_count':r['tool_identity_count'],'boot':r['admission']['boot'],
              'files_by_type_old_edit_edit_clean':[[*k,v] for k,v in sorted(files.items())],
              'units_by_kind_old_edit_edit_clean':[[list(k),o,c,v] for (k,o,c),v in sorted(kinds.items())],
              'deliveries':units,'rlib_native_payloads':material,'consumer_offered_edges':changed_edges}
    return evidence


def main():
    run=get(f'runs/{RUN}')
    assert (run['status'],run['conclusion'],run['head_sha'],run['run_attempt'])==('completed','success',HEAD,1)
    x,=get(f'runs/{RUN}/artifacts')['artifacts']
    assert (x['id'],x['digest'],x['size_in_bytes'],x['name'])==(ART,'sha256:'+DIGEST,SIZE,'ruff-line-end-25492-readback')
    raw=subprocess.check_output(['gh','api',f'repos/astral-experiments/ohm/actions/artifacts/{ART}/zip'])
    assert len(raw)==SIZE and hashlib.sha256(raw).hexdigest()==DIGEST
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert z.testzip() is None and set(z.namelist())=={'attribution.json','delivery.json','readback.json'}
        e=summary(*(json.loads(z.read(n+'.json')) for n in ('attribution','delivery','readback')))
    print('BEGIN_VERIFIED_EVIDENCE')
    for key,v in e.items():print(key,compact(v))
    print('END_VERIFIED_EVIDENCE')
    Path(os.environ['RUNNER_TEMP'],'summary.json').write_text(json.dumps(e,sort_keys=True,indent=2)+'\n')


if __name__=='__main__':main()
