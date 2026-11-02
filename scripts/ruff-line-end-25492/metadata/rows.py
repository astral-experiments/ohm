"""Decode the native #253 producer's keyed public metadata; schema.json binds its source."""
import functools
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent))
from slots import Cursor, extract, need
SCHEMA=json.loads(Path(__file__).with_name("schema.json").read_text())
tables=SCHEMA["tables"]; keys=SCHEMA["defkey"]
class D(Cursor):
    def __init__(self,data,pos):super().__init__(data,pos);self.root=pos;self.prev=None
    def ptr(self):
        n=self.unsigned(); p=self.root-n if self.prev is None else self.prev+n
        need(1<=p<=self.root,'bad position');self.prev=p;return p
    def array(self):
        n=self.unsigned();return (n,self.ptr() if n else 1)
    def table(self):
        w,n=self.unsigned(),self.unsigned();return (self.ptr(),w,n)
def rmeta(data):
    old=extract(data);d=D(data,old['root'])
    need(d.unsigned()==0 and d.string()=='x86_64-unknown-linux-gnu','target');d.take(32)
    need(d.symbol()==old['owner'] and d.flag()==d.flag()==0,'wrong owner')
    need(d.string()==old['filename'] and d.take(8).hex()==old['stable_id'],'crate identity')
    if d.flag():need(d.unsigned() in range(3),'required panic')
    need(d.unsigned() in range(3) and d.unsigned() in range(5),'panic or edition')
    for _ in range(4): d.flag()
    for _ in range(13):d.array()
    need(d.unsigned() in (0,1),'impl kind');d.array();d.array();d.array()
    need(not d.flag(),'proc-macro');[d.array() for _ in range(5)];d.flag()
    t={name:d.table() for name in [*tables,'syntax_contexts','expn_data','expn_hashes']}
    d.ptr();t['source_map']=d.table();d.array();d.array()
    for _ in range(6):d.flag()
    need(d.unsigned() in range(3),'mangling');d.flag()
    need(d.flag()==d.flag()==1,'missing RDR')
    t['local']=d.table();t['expn']=d.table();gp=d.pos;d.take(16)
    need(d.take(13)==b'rust-end-file' and d.pos==len(data),'bad trailing CrateRoot')
    return t,gp,old
def entries(data,t):
    start,packed,n=t; w=packed&127
    need(n==0 or w>0,'empty nonzero-length table')
    if not packed&128:return {i:(start+i*w,data[start+i*w:start+(i+1)*w]) for i in range(n)}
    p=start+12*((n+63)//64);ret={};seen=0
    for bucket in range((n+63)//64):
        h=start+12*bucket;bm=int.from_bytes(data[h:h+8],'little');prev=int.from_bytes(data[h+8:h+12],'little')
        need(seen==prev and not bm>>min(64,n-64*bucket),'bad sparse index')
        for b in range(64):
            if (bm>>b)&1:
                ret[64*bucket+b]=(p+seen*w,data[p+seen*w:p+(seen+1)*w]);seen+=1
    return ret
def fingerprints(data,t):
    ret={}
    for i,(p,r) in entries(data,t).items():
        if any(r):
            need(len(r)==17 and r[0]==1,'invalid present fingerprint tag/width')
            ret[i]=(p+1,r[1:].hex())
    return ret
def definitions(data,t,crate):
    dt=entries(data,t['def_keys']);ht=entries(data,t['def_path_hashes'])
    @functools.lru_cache(None)
    def info(idx):
        val=int.from_bytes(dt[idx][1],'little');need(val>0,'zero DefKey');d=Cursor(data,val)
        parent=d.unsigned() if d.flag() else None;kind,name=keys[d.unsigned()]
        sym=d.symbol() if name else None
        dis=d.unsigned();part=sym[1] if sym and sym[0]=='str' else ('<sym:'+str(sym[1])+'>' if sym else '{'+kind+'}')
        if dis:part+='#'+str(dis)
        if parent is None:need(kind=='CrateRoot' and idx==0,'root key');path=crate
        else:need(parent!=idx,'self-parent');path=info(parent)[0]+'::'+part
        return (path,kind,val,data[val:d.pos].hex(),ht[idx][1].hex())
    return info,dt
