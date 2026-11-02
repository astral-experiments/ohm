"""Reopen keyed public rows, distinct from a whole metadata digest."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).parent))
from rows import SCHEMA, definitions, entries, fingerprints, rmeta


def project(path):
    data=path.read_bytes()
    t,g,h=rmeta(data)
    owner='ruff_source_file'
    assert h['owner']==('str',owner)
    info,_=definitions(data,t,owner)
    local={}
    for idx,(_offset,fingerprint) in fingerprints(data,t['local']).items():
        name,kind,_,_,key=info(idx)
        assert key not in local
        local[key]={'path':name,'kind':kind,'index':idx,'hash':fingerprint}
    exp=fingerprints(data,t['expn'])
    return {'sha256':hashlib.sha256(data).hexdigest(),'size':len(data),'root_offset':h['root'],
            'stamp':h['stamp'],'stable_id':h['stable_id'],'filename':h['filename'],'roster':h['roster'],
            'header':[[k,p,hash_] for k,(p,hash_) in h['fields'].items()],
            'global':data[g:g+16].hex(),'definitions':local,'expansions_by_local_index':{k:v[1] for k,v in exp.items()}}


def delta(old,new):
    assert (old['stable_id'],old['filename'],old['roster'])==(new['stable_id'],new['filename'],new['roster'])
    a,b=(r['definitions'] for r in (old,new))
    shared=sorted(a.keys()&b.keys())
    assert all(a[k]['path']==b[k]['path'] and a[k]['kind']==b[k]['kind'] for k in shared)
    differences=[k for k in shared if a[k]['hash']!=b[k]['hash']]
    loci=Counter()
    for k in shared:
        parts=a[k]['path'].split('::');module=parts[1] if len(parts)>1 else '<root>'
        loci[module,a[k]['hash']==b[k]['hash']]+=1
    return {'definitions':[len(a),len(b)],'common':len(shared),'changed':len(differences),'changed_defkeys':differences,
            'removed':sorted(a.keys()-b.keys()),'added':sorted(b.keys()-a.keys()),'global_changed':old['global']!=new['global'],
            'module_distribution':[[mod,equal,v] for (mod,equal),v in sorted(loci.items())]}


def main(directory):
    states={}
    for ph in ('old','edit','clean'):
        p=directory/(ph+'.rmeta')
        states[ph]=project(p)
    out={'schema':SCHEMA,'phases':states,'old_edit':delta(states['old'],states['edit']),
         'edit_clean':delta(states['edit'],states['clean'])}
    (directory/'rows.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    for pair in ('old_edit','edit_clean'):
        print(pair,'keyed definitions',out[pair]['common'],'changed',out[pair]['changed'],
              'global changed',out[pair]['global_changed'],'modules',out[pair]['module_distribution'],flush=True)


if __name__=='__main__':main(Path(sys.argv[1]))
