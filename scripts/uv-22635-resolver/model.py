"""Compare real Cargo unit plans and emitted artifacts, including every feature and dependency edge."""
from collections import Counter
from pathlib import Path
import hashlib,json,re
from urllib.parse import unquote

def require(value,msg):
    if not value: raise ValueError(msg)
def digest(b):return hashlib.sha256(b).hexdigest()
def dump(x):return json.dumps(x,sort_keys=True,separators=(',',':')).encode()
def common(pkg,t,features):
    base,frag=pkg.rsplit('#',1)
    name,ver=frag.rsplit('@',1)if '@'in frag else(unquote(base.rsplit('/',1)[1]),frag)
    require(name and ver and isinstance(features,list),'package identity')
    path=t['src_path'];disk=Path(path);require(disk.is_absolute()and '..'not in disk.parts,'source path')
    if base.startswith('path+file://'):
        root=Path(unquote(base.removeprefix('path+file://')));require(disk.is_relative_to(root),'workspace target not owned')
        src=disk.relative_to(root).as_posix();source='workspace'
    else:
        require(base=='registry+https://github.com/rust-lang/crates.io-index','unexpected package registry')
        token='/'+name+'-'+ver+'/';before,sep,after=path.partition(token);require(sep and '/registry/src/' in before and after, 'package source archive path');src=after;source='registry'
    return [source,name,ver,t['name'],t['kind'],src,sorted(features)]
def graph(data):
    require(data['version']==1 and len(data['roots'])==1,'unit graph roots');units=data['units']
    ids=[];modes=[];refs=[]
    for u in units:
        c=common(u['pkg_id'],u['target'],u['features']);ids.append(c)
        modes.append([c,u['mode'],u['platform']]);refs.append([c,u['mode'],u['platform'],u['profile'],{k:v for k,v in u['target'].items()if k!='src_path'}])
    require(modes[data['roots'][0]][0][1:5]==['uv-resolver','0.0.93','uv_resolver',['lib']]and modes[data['roots'][0]][1]=='check','foreign terminal')
    projected=[]
    for i,u in enumerate(units):
        deps=[]
        for edge in u['dependencies']:
            j=edge['index'];require(0<=j<len(units),'dangling edge');deps.append([modes[j],{k:v for k,v in edge.items()if k!='index'}])
        projected.append([modes[i],sorted(deps,key=dump)])
    return {'portable':digest(dump(sorted(projected,key=dump))),'native_profiles':digest(dump(sorted(refs,key=dump))),'units':len(units),'modes':dict(Counter(u['mode']for u in units)),'compile':sorted([c for c,u in zip(ids,units)if u['mode']!='run-custom-build'],key=dump),'scripts':sorted([[c[0],c[1],c[2]]for c,u in zip(ids,units)if u['mode']=='run-custom-build'],key=dump),'root':modes[data['roots'][0]],'complete_profile_roster':sorted(refs,key=dump)}
def events(raw,g,verbose):
    art=[];executed=[];messages=[];tagged=set();tail=False
    for l in raw.decode().splitlines():
        require(not tail,'data after final event')
        if not l.startswith('{'):
            m=re.fullmatch(r'\[([^\s\]]+) ([^\s\]]+)\](?: .*)?',l);require(verbose and m,'unattributed source tool stdout');tagged.add(m.groups());continue
        r=json.loads(l);reason=r['reason']
        if reason=='compiler-artifact':art.append(r)
        elif reason=='build-script-executed':
            base,frag=r['package_id'].rsplit('#',1);n,v=frag.rsplit('@',1)if '@'in frag else(unquote(base.rsplit('/',1)[1]),frag);executed.append(['workspace'if base.startswith('path+file://')else'registry',n,v])
        elif reason=='compiler-message':messages.append(r)
        else:require(r=={'reason':'build-finished','success':True},'unknown or failing signed Cargo event');tail=True
    require(tail,'missing native end')
    require(sorted([common(r['package_id'],r['target'],r['features'])for r in art],key=dump)==g['compile'],'incomplete or unexpected actual compile roster')
    require(sorted(executed,key=dump)==g['scripts']and tagged<={tuple(row[1:])for row in executed},'wrong actual script set')
    return art,messages
