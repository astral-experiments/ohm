"""Compare independently cold originals under the signed, generated-key-only variation envelope."""
from pathlib import Path
import collections,gzip,hashlib,json,struct,subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bridge
G=bridge.guard
def product(raw,name,parser,deep):
    m=parser.__globals__;snap=m['SNAP'];s=snap['sig'];at=struct.unpack_from('<Q',raw,8)[0]
    try:h=s.Reader(raw,at).read()
    except(AssertionError,IndexError,struct.error):h=snap['Reader21'](raw,at).read()
    h2,defs,x,ar,rows=parser(raw,name);indices=[v.hex()for v in s.di.keyed(raw,h)]
    G(len(set(indices))==len(indices)==len(defs)and set(indices)==set(defs),'physical vs stable key set')
    r=s.Reader(raw,h['tables']['crate_deps']['position']);deps=[]
    def symbol():
        tag=r.u()
        if tag==0:return ['inline',r.string()]
        if tag==1:
            j=r.u();alt=s.Reader(raw,j);return ['inline',alt.string()]
        G(tag==2,'unexpected dependency-name tag');return ['preinterned',r.u()]
    for i in range(h['tables']['crate_deps']['length']):
        sym=symbol();svh=r.raw(16).hex();opt=r.u();G(opt in(0,1),'host option')
        host=r.raw(16).hex()if opt else None;kind,extra,private=r.u(),r.string(),r.u();G(kind<5 and private in(0,1),'dependency row')
        deps.append([sym,svh,host,kind,extra,private])
    return deep.project(parser,raw,name),indices,{k:v[2]for k,v in defs.items()},deps
def compare(old,new,allowed,proj):
    G(set(old)==set(new),'independent output roster')
    compared={}
    for k in sorted(old):
        x,y=old[k],new[k]
        if x==y:continue
        G(k in allowed,'independent-cold variation outside signed baseline: '+k)
        l,r=proj(k,x),proj(k,y)
        a,ix,dk,dx=l;b,iy,dk2,dy=r
        G(a==b and dk==dk2 and dx==dy,('changed independent cold definitions, ordered allocation stream, dependencies or expansions',k))
        G(set(ix)==set(iy)and len(ix)==len(iy),'keyed inventory')
        kinds=collections.Counter(dk[u]for u,v in zip(ix,iy,strict=True)if u!=v)
        G(kinds and set(kinds)<=set(allowed[k]['classes']),('unexplained independent raw metadata drift',k,dict(kinds)))
        compared[k]={'moved_generated_classes':dict(kinds),'canonical':a,'dependencies':dx,'raws':[x,y]}
    return compared
def main():
    w,tmp,m,_=bridge.load();anc=w/'opening/scripts/uv-root-20991-opening'
    # Every qualification opens its own sealed decoder kit under the real historical source layout.
    import tempfile
    old,new,report=map(Path,sys.argv[1:]);out=w/'trait-results'
    with tempfile.TemporaryDirectory(dir=tmp)as scratch:
        o,api,parser,_=m.readers(anc,Path(scratch));import deep
        def canon(k,s):
            data=gzip.decompress((out/'blobs'/(s[1]+'.gz')).read_bytes());G(len(data)==s[0]and m.digest(data)==s[1],'original raw')
            name=Path(k).name.removeprefix('lib').split('-',1)[0]
            projected=product(data,name,parser,deep)
            sample=Path(scratch)/Path(k).name;sample.write_bytes(data)
            result=subprocess.run([m.SDK/'bin/rustc','-Zls=all',sample],env={'PATH':'/usr/bin:/bin','LC_ALL':'C','RUSTC_BOOTSTRAP':'1'},capture_output=True,timeout=60)
            G(result.returncode==0 and not result.stderr and b'Crate info:'in result.stdout and b'public_hash 'in result.stdout and len(result.stdout)<=64<<20,'incomplete native rustc metadata listing')
            # Preserve every emitted byte and require the independent listing to agree.
            extern=out/'listing-bytes';extern.mkdir(exist_ok=True);key=m.digest(result.stdout);keep=extern/(key+'.gz')
            if not keep.exists():keep.write_bytes(gzip.compress(result.stdout,compresslevel=2,mtime=0))
            projected[0]['native_full_rustc_listing']=key
            return projected
        v=compare(m.read(old),m.read(new),bridge.R['signed_unequal'],canon);m.save(report,{'pass':True,'raw_differences':v,'signed_raw_gate_unchanged':True})
if __name__=='__main__':main()
