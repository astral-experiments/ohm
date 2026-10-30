"""Reopen root rustc link recipes, every physical input and a full signed native image."""
import gzip
import hashlib
import io
import json
from pathlib import PurePosixPath as Path
import struct
from canonical import canonical

h=lambda b:hashlib.sha256(b).hexdigest()
j=lambda v:json.dumps(v,sort_keys=True,separators=(',',':')).encode()

def decode(buf):
    f=io.BytesIO(buf)
    def take(n):
        b=f.read(n);assert len(b)==n;return b
    def num():
        got=[]
        for _ in range(5):
            b=take(1)[0];got.append(b & 127)
            if b<128:
                assert len(got)==1 or got[-1]!=0
                return sum(n << (7*k) for k,n in enumerate(got))
        raise ValueError('oversized length')
    def string():
        n=num();assert n<262145;v=take(n).decode();assert take(1)==bytes([193]) and '\x00' not in v;return v
    def option(get):
        mark=take(1);assert mark in (b'\x00',b'\x01');return get() if mark==b'\x01' else None
    def module(kind):
        name=string();assert take(1)==bytes([kind]);parts=[option(string) for _ in range(6)]
        assert parts[0] and not any(parts[1:])
        cnt=num();assert cnt<=2048;links=[string() for _ in range(cnt)]
        return name,kind,parts[0]
    assert take(12)==b'rustlink\0\0\0\1'
    stamp=string();assert stamp.startswith('1.99.0')
    count=num();assert 0<count<=2048
    result=[module(0) for _ in range(count)]
    a=option(lambda:module(1))
    if a:result.append(a)
    assert len({x[0] for x in result})==len(result)==len({x[2] for x in result}) and f.tell()<len(buf)
    return stamp,result


class Images:
    def __init__(self,view):
        self.view=view;self.objs={};self.recipes={};self.paths={}
    def raw(self,kind,key):
        extension='.macho.gz' if kind=='edge-images' else '.gz'
        b=self.view.gz(kind+'/'+key+extension);assert h(b)==key;return b
    def proof(self,phase,kind,*,prior=None):
        v=self.view
        if v.exists(phase+'/prior-cgu-proof.json'):
            q=v.js(phase+'/prior-cgu-proof.json');item=prior[q['raw']]
            assert q['recipe']==item['recipe'] and q['observed_link']==item['argv'] and q['raw']==item['raw']
            p=dict(item,source='unchanged-raw-from-prior-physical-link')
            self.paths[phase]=p;return p
        q=v.js(phase+'/cgu-proof.json');raw=self.raw(kind,q['raw']);recipe=q['recipe']
        if recipe not in self.recipes: self.recipes[recipe]=decode(self.raw('cgu-inputs/recipes',recipe))
        ver,modules=self.recipes[recipe];assert ver==q['version']
        out=q['output'];owner=Path(out).with_suffix('.rlink-objects');actual={}
        for name,kindnum,path in modules:
            d=q['physical'][path];sha=d['sha256']
            assert Path(path).is_absolute() and Path(path).parent==owner and (name,kindnum)==(d['module'],d['kind'])
            if sha not in self.objs:
                b=self.raw('cgu-inputs/objects',sha)
                assert b[:8]==bytes.fromhex('cffaedfe0c000001') and struct.unpack_from('<I',b,12)[0]==1
                self.objs[sha]=len(b)
            assert d['bytes']==self.objs[sha];actual[name]=sha
        assert set(p for _,_,p in modules)==set(q['physical']) and actual==q['modules']
        source=q['source']; ref={}
        if source=='kernel-xcode-ld+rustc-recipe':
            ev=json.loads(v.gz(phase+'/exec.json.gz'))
            link,=[e for e in ev if Path(e['path']).name in ('ld','ld-prime','ld64','ld-classic') and e['argv'].count('-o')==1 and e['argv'][e['argv'].index('-o')+1]==out]
            args=link['argv'];argsha=h(json.dumps(args,separators=(',',':')).encode())
            assert argsha==q['linker_argv'] and '/Xcode' in link['path'] and link['pid']>0 and link['cdhash']
            objs=[i for i in args if Path(i).parent==owner and i.endswith('.o')]
            assert len(objs)==len(set(objs)) and set(objs)==set(q['physical'])
            normalized,c=canonical(raw,out,args,incremental=True)
            assert h(normalized)==q['cross_path_image'] and c['paths']==q['debug_paths']
            ref={'argv':argsha,'pid':link['pid'],'cdhash':link['cdhash'],'cross':q['cross_path_image'],
                 'cross_ledger':h(j(c['paths']))}
        else:
            assert source=='saved-rustc-recipe' and not v.exists(phase+'/exec.json.gz')
            args=[*(p for _,_,p in modules),'-o',out]
        norm,desc=canonical(raw,out,args,incremental=True,namespace=False)
        assert h(norm)==q['same_path_image'] and desc['code_pages']==q['code_pages'] and desc['nonce_objects']==q['nonce_objects']
        changes=desc['nonce_objects'];assert all(x['path'] in q['physical'] for x in changes)
        p={'raw':q['raw'],'output_sha':h(out.encode()),'norm':h(norm),'recipe':recipe,'source':source,
           'modules_sha':h(j(actual)),'module_count':len(actual),'changed_paths':len(changes),
           'code_pages':desc['code_pages'],'physical_bytes':sum(self.objs[s] for s in actual.values()),**ref}
        self.paths[phase]=p
        if prior is not None:prior[p['raw']]=p
        return p
    @staticmethod
    def same(a,b):return all(a[k]==b[k] for k in ('output_sha','norm','modules_sha','module_count'))
    def comparable(self,phase,product,prior=None):
        p=self.proof(phase,'crc-programs',prior=prior)
        assert product['raw']==p['raw']
        return {'product':{k:v for k,v in product.items() if k!='raw'},'image':p['norm'],'modules':p['modules_sha'],'output':p['output_sha']}
