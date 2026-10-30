"""Tie an AST test executable to this installation’s kernel-observed linker and rustc CGUs."""
from collections import defaultdict
import gzip
import json
from pathlib import Path

from cgu_inputs import witness
from study import digest,load,need,save


def trace_product(dest,trace,native,output,product):
    data=Path(output).read_bytes();raw=digest(data)
    need(raw==product['raw'],'Cargo test artifact changed after libtest')
    links=[l for l in native['linkers'] if [v for k,v in zip(l['argv'],l['argv'][1:]) if k=='-o']==[output]]
    scoped=vars(trace).setdefault('ast_known_links',{}).setdefault(str(dest.parent),{})
    if not links:
        need(raw in scoped and scoped[raw]['output']==output,'test lacks an earlier physical linker for this body and installation')
        proof=scoped[raw];save(dest/'prior-test-link.json',{'raw':raw,'observed_recipe':proof['recipe'],'observed_argv':proof['linker_argv']})
        return proof
    need(len(links)==1 and links[0]['stock'],'ambiguous Cargo Apple link')
    args=links[0]['argv']
    [event]=[e for e in json.loads(gzip.decompress((dest/'exec.json.gz').read_bytes())) if e['argv']==args]
    output_root=Path(output)
    root=Path(next(p for p in dest.parents if p.name=='receipts')).parent
    proof=witness(root,dest,data,output,linker=args)
    cache=load(dest/'local-incremental.json')['cache'];work_products=defaultdict(list)
    for f in cache['files']:
        if f[0].endswith('.o'):work_products[Path(f[0]).stem].append((f[0],f[3],f[5]))
    owners={}
    for r in proof['nonce_objects']:
        cgu=r['cgu'];obj=proof['physical'][r['path']];files=work_products[cgu]
        need(len(files)==1 and files[0][1:]==(obj['bytes'],obj['sha256']) and cgu not in owners,
             'root linker object differs from its unique incremental CGU')
        owners[cgu]=files[0]
    save(dest/'ast-test-object-owners.json',{'root_object_to_cache':owners,'pid':event['pid'],'seq':event['seq'],
                                             'linker_sha256':links[0]['sha'],'root':str(output_root)})
    scoped[raw]=proof
    return proof


def identity(proof):
    return {k:proof[k] for k in ('output','same_path_image','modules')}
