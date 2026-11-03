"""Canonicalize only the time and lock nonce of named rustc incremental session files."""
import json
from pathlib import Path
import re

SLOT=re.compile(r's-([0-9a-z]+)-([0-9a-z]+)-([0-9a-z]+)')
OWNER=re.compile(r'[a-zA-Z_0-9]+-[a-z0-9]+')

def inventory(raw):
    stable={}
    original={}
    for literal,value in raw.items():
        p=Path(literal)
        assert not p.is_absolute() and '..' not in p.parts
        parts=p.parts
        key=literal
        if len(parts)>=2 and parts[:2]==('debug','incremental'):
            assert len(parts)==5 and OWNER.fullmatch(parts[2]) and parts[4] in ('metadata.rmeta','ohm-check-metadata.rmeta','ohm-build-metadata.rmeta'),literal
            session=SLOT.fullmatch(parts[3]);assert session,literal
            key='/'.join((*parts[:3],'session-crate-hash-'+session[3],parts[4]))
        assert key not in stable,(literal,original.get(key))
        stable[key]=value
        original[key]=literal
    return stable,original

def test(root):
    a=json.loads((root/'first-B/products.json').read_bytes());b=json.loads((root/'kernel-B/products.json').read_bytes())
    assert a!=b and a['workspace']==b['workspace'] and a['public_sidecars']==b['public_sidecars']
    x,xraw=inventory(a['rmeta']);y,yraw=inventory(b['rmeta']);assert x==y
    shifted=[k for k in x if xraw[k]!=yraw[k]]
    assert len(shifted)==2 and {Path(xraw[k]).name for k in shifted}=={'ohm-check-metadata.rmeta','metadata.rmeta'} and all('/uv_cli-'in k for k in shifted)
    k=shifted[0];p=Path(yraw[k]);n=p.parts
    bads={}
    for label,dest,changes in [('crate',Path(*n[:2],n[2]+'x',*n[3:]),False),('final_hash',p.parent.with_name(n[3]+'x')/p.name,False),('output',p.parent/'unknown.rmeta',False),('bad_slot',p.parent.with_name('s-evil')/p.name,False),('one_byte',p,True),('duplicate',p.parent.with_name('s-x-y-'+n[3].rsplit('-',1)[1])/p.name,False)]:
        raw=b['rmeta'].copy();v=raw[str(p)]
        if label!='duplicate':raw.pop(str(p))
        raw[str(dest)]=[v[0],('0'if v[1][0]!='0'else'1')+v[1][1:]] if changes else v
        try:assert inventory(raw)[0]==x
        except AssertionError:bads[label]='refused'
        else:raise ValueError(label)
    return {'full_rmeta':len(x),'workspace':len(a['workspace']),'sidecars':len(a['public_sidecars']),'shifted':{key:[xraw[key],yraw[key],x[key]]for key in shifted},'negatives':bads}
