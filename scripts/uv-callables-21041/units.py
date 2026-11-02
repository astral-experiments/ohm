"""Reconstruct every returned Cargo unit and disambiguate the host and check uv_version products."""
import hashlib,json
from pathlib import Path

def canon(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def unit_rows(events,src,target,regsrc):
    src=Path(src);target=Path(target);regsrc=Path(regsrc)
    rows=[];members={}
    for x in events:
        if x['reason']!='compiler-artifact':continue
        info=x['target'].copy();sp=Path(info['src_path']);pid=x['package_id']
        if sp.is_relative_to(src):
            loc='ws/'+str(sp.relative_to(src));prefix='path+'+src.as_uri()+'/'
            assert pid.startswith(prefix) or pid.startswith('path+'+src.as_uri()+'#'),pid
            pid='ws/'+pid.removeprefix(prefix)
        else:
            rel=sp.relative_to(regsrc);assert len(rel.parts)>=3
            loc='reg/'+str(Path(*rel.parts[1:]));assert pid.startswith('registry+https://github.com/rust-lang/crates.io-index#'),pid
        info['src_path']=loc
        fs=[str(Path(f).relative_to(target))for f in x['filenames']]
        suffixes=[Path(f).suffix for f in fs]
        rows.append({'package_id':pid,'manifest_path':('ws/'+str(Path(x['manifest_path']).relative_to(src)) if loc.startswith('ws/') else 'reg/'+str(Path(*Path(x['manifest_path']).relative_to(regsrc).parts[1:]))),'target':info,'profile':x['profile'],'features':x['features'],'output_suffixes':suffixes,'has_executable':x['executable']is not None})
        if not loc.startswith('ws/'):continue
        metas=[f for f in fs if f.endswith('.rmeta')]
        if not metas:continue
        assert info['kind']==['lib'] and len(metas)==1
        mode='rlib' if '.rlib'in suffixes else 'check';name=info['name'];key=name+'@'+mode
        assert key not in members,(key,fs)
        members[key]={'crate':name,'folder':str(Path(x['manifest_path']).parent.relative_to(src)),'rmeta':metas[0],'mode':mode,'features':x['features'],'target':info,'profile':x['profile']}
    rows.sort(key=canon)
    return {'count':len(rows),'logical_sha256':hashlib.sha256(canon(rows)).hexdigest(),'units':rows,'workspace':members}

def workspace_shape(members):
    return {k:{field:v for field,v in x.items() if field!='rmeta'}for k,x in members.items()}
