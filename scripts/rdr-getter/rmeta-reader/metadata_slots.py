"""Locate the exact dependency-hash slots of the enrolled signed compiler's native rmeta."""
import collections
import hashlib
import re
import struct

MAGIC=b'rust\0\0\0\x0a'
END=b'rust-end-file'

def need(value,message):
    if not value:
        raise ValueError(message)

class Cursor:
    def __init__(self,data,pos):
        self.data=data;self.pos=pos
    def take(self,n):
        end=self.pos+n
        need(0<=self.pos<=end<=len(self.data),'truncated metadata')
        b=self.data[self.pos:end];self.pos=end
        return b
    def byte(self):
        return self.take(1)[0]
    def unsigned(self):
        start=self.pos;value=0
        for shift in range(0,70,7):
            x=self.byte()
            value|=(x&127)<<shift
            if not x&128:
                need(value<2**64 and (self.pos==start+1 or x!=0),'noncanonical ULEB')
                return value
        raise ValueError('overflow')
    def string(self):
        raw=self.take(self.unsigned())
        need(self.byte()==0xc1,'invalid rust opaque string terminator')
        return raw.decode()
    def flag(self):
        v=self.byte();need(v in (0,1),'invalid bool or Option');return v
    def symbol(self):
        tag=self.byte()
        if tag==0:return ('str',self.string())
        if tag==1:
            end=self.pos-1;pos=self.unsigned();need(0<pos<end,'invalid symbol backreference')
            return ('str',Cursor(self.data,pos).string())
        need(tag==2,'unknown symbol encoding')
        return ('predefined',self.unsigned())

def extract(data):
    need(data.startswith(MAGIC) and data.endswith(END),'not native rustc metadata')
    root=struct.unpack_from('<Q',data,8)[0]
    version=Cursor(data,16)
    stamp=version.string()
    need(stamp.startswith('rustc 1.99.0') and '(Ohm metadata 1)' in stamp,'unexpected rustc schema')
    need(version.pos<=root<len(data)-len(END),'invalid root pointer')
    h=Cursor(data,root)
    need(h.unsigned()==0 and h.string()=='x86_64-unknown-linux-gnu','nonbuiltin GNU target')
    values={}
    def svh(d,name):
        at=d.pos;val=d.take(16);values[name]=(at,val.hex())
    svh(h,('self','private'));svh(h,('self','public'))
    owner=h.symbol()
    need(h.flag()==h.flag()==0,'proc macro or stub metadata')
    filename=h.string();stable=h.take(8).hex()
    if h.flag():need(h.unsigned() in (0,1,2),'invalid panic strategy')
    need(h.unsigned() in (0,1,2) and h.unsigned() in range(5),'invalid panic or edition')
    tuple(h.flag() for _ in range(4))
    previous=None
    def array():
        nonlocal previous
        n=h.unsigned()
        if n==0:return (n,0)
        off=h.unsigned()
        where=root-off if previous is None else previous+off
        need(version.pos<=where<=root,'lazy array out of bounds')
        previous=where
        return n,where
    array()
    count,dep_start=array()
    need(0<count<10_000,'empty or implausible dependency table')
    d=Cursor(data,dep_start)
    roster=[]
    for number in range(1,count+1):
        name=d.symbol()
        svh(d,('dep',number,name))
        host=d.take(16).hex() if d.flag() else None
        kind=d.unsigned();need(kind in (0,1,2),'unknown crate dep kind')
        suffix=d.string();private=d.flag()
        roster.append((number,name,host,kind,suffix,private))
    need(dep_start<=d.pos<=root,'dependency table overlaps root')
    return {'stamp':stamp,'root':root,'owner':owner,'filename':filename,'stable_id':stable,'roster':roster,
            'table_range':(dep_start,d.pos),'fields':values}

def compare(a,b):
    x,y=extract(a),extract(b)
    for k in ('stamp','owner','filename','stable_id','roster'):
        need(x[k]==y[k],('different producer, crate graph or protocol',k))
    for k in ('root','table_range'):
        need(x[k]==y[k],('structurally different bounds',k))
    need(len(a)==len(b),'changed metadata length')
    ranges={}
    changes=[]
    for name,(offset,old) in x['fields'].items():
        end=offset+16
        other,new=y['fields'][name]
        need(other==offset,'moved or reclassified hash slot')
        need(not any(p in ranges for p in range(offset,end)),'overlapping fields')
        ranges.update((p,name) for p in range(offset,end))
        if old!=new:changes.append({'field':name,'at':offset,'old':old,'new':new})
    unmatched=[]
    differing=0
    for i,(old,new) in enumerate(zip(a,b)):
        if old==new:continue
        differing+=1
        if i not in ranges:
            if unmatched and unmatched[-1][1]==i:unmatched[-1][1]=i+1
            else:unmatched.append([i,i+1])
    return {'bytes':len(a),'sha256':[hashlib.sha256(q).hexdigest() for q in (a,b)],'crate':x['owner'],
            'different_bytes':differing,'changed_fields':changes,'unmatched_ranges':unmatched,
            'hash_fields_only':not unmatched,'dependency_rows':len(x['roster']),'dep_table_range':x['table_range']}
