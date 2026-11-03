from pathlib import Path
import gzip,hashlib,json,sys,zlib
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'ruff-module-16149'))
import lens

def table(raw, owner, version, edition):
    header, definitions, published, _, required = lens.scope_rdr.decode(raw, lens.SCHEMA['symbols'], lens.SCHEMA['tables'], owner, version, edition=edition)
    return {'header':header,'requires':{k:list(v) for k,v in required.items()},'rows':{k:[definitions[k][0],v] for k,v in sorted(published.items())}}

def compare(old,new):
    a,b=old['rows'],new['rows']
    return [{'id':i,'old':a.get(i),'new':b.get(i)} for i in sorted(a.keys()|b.keys()) if a.get(i)!=b.get(i)]
