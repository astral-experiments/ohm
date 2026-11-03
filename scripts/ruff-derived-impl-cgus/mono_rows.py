"""Read the concrete per-unit item variants accepted by this bounded, versioned decoder."""
import argparse,collections,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from partitions import leb,check
class Decoder:
    def __init__(self,raw,start):self.b=raw;self.p=start
    def u(self):n,self.p=leb(self.b,self.p);return n
    def byte(self):a=self.b[self.p];self.p+=1;return a
    def boolean(self):n=self.byte();check(n in(0,1),'boolean');return n
    def defid(self):r=self.b[self.p:self.p+16];self.p+=16;check(len(r)==16,'def id');return r.hex()
    def symbol(self):
        tag=self.byte()
        if tag==0:
            n=self.u();self.p+=n;check(self.byte()==193,'symbol end')
        elif tag in(1,2):self.u()
        else:raise ValueError(('symbol',tag))
    def region(self):
        n=self.byte()
        if n in(3,6):return
        check(n==1,('region',n))
        index=self.byte();check(index in(0,1),'bound region index')
        if not index:self.u()
        self.u();self.bound_region()
    def arg(self):
        n=self.byte()
        if n==0:self.region()
        elif n==1:self.ty()
        elif n==2:self.const()
        else:raise ValueError(('generic arg',n))
    def seq(self,f):
        n=self.u();check(n<2048,('long sequence',n))
        for _ in range(n):f()
    def reference(self):
        p=self.p;off=self.u()-128;check(0<=off<p,('bad shorthand',off,p))
    def const(self):
        if self.b[self.p]&128:self.reference();return
        n=self.byte();check(n==5,('const',n));self.ty()
        kind=self.byte();check(kind==0,('ValTree',kind))
        # ScalarInt's encoded width precedes its little-endian value.
        width=self.byte();check(0<width<=16,('scalar width',width));self.p+=width
    def adt(self):
        self.defid()
        def variant():
            self.defid()
            if self.boolean():self.byte();self.defid()
            self.symbol()
            tag=self.byte();check(tag in(0,1),'discriminant')
            if tag:self.u()
            else:self.defid()
            def field():
                self.defid();self.symbol()
                if self.boolean():self.defid()
                check(self.byte()==0,'field restriction span');self.boolean()
                if self.boolean():self.defid()
            self.seq(field);check(not self.boolean(),'tainted enum');self.byte()
        self.seq(variant);self.p+=2
        if self.boolean():
            k=self.byte();check(k in(0,1),'integer repr')
            if k:self.byte()
            self.boolean()
        for _ in range(2):
            if self.boolean():self.byte()
        self.byte();check(not self.boolean(),'scalable repr');self.p+=8
    def bound_region(self):
        k=self.byte();check(k in(0,1,2,3),('bound region kind',k))
        if k==1:self.symbol()
        if k==2:self.defid()
    def binders(self):
        def kind():
            k=self.byte();check(k==1,('binder',k));self.bound_region()
        self.seq(kind)
    def dyn(self):
        def pred():
            self.binders();k=self.byte();check(k in(0,1,2),('existential',k));self.defid()
            if k in(0,1):self.seq(self.arg)
            if k==1:
                ty=self.byte();check(ty==0,('projection term',ty));self.ty()
        self.seq(pred);self.region()
    def ty(self):
        if self.b[self.p]&128:self.reference();return
        n=self.byte()
        if n in(0,1,7,21):return
        if n in(2,3,4):self.byte();return
        if n==5:self.adt();self.seq(self.arg);return
        if n==6:self.defid();return
        if n==8:self.ty();self.const();return
        if n==10:self.ty();return
        if n==11:self.ty();self.boolean();return
        if n==12:self.region();self.ty();self.boolean();return
        if n==13:self.defid();self.binders();self.seq(self.arg);return
        if n==14:self.binders();self.seq(self.ty);self.byte();self.byte();return
        if n==16:self.dyn();return
        if n in(17,18,19,20):self.defid();self.seq(self.arg);return
        if n==22:self.seq(self.ty);return
        raise ValueError(('type',n,self.p-1))
    def item(self):
        start=self.p;n=self.byte();defkind=sk=None
        if n==0:
            defkind=self.byte();check(defkind<5,('instance kind',defkind))
            if defkind==4:sk=self.byte();check(sk<12,('shim',sk))
            did=self.defid()
            if defkind==3:self.u()
            if sk==1 and self.boolean():self.byte()
            if sk in(2,8,9,10,11):self.ty()
            if sk==3:self.defid();self.boolean()
            if sk==4:self.boolean()
            if sk==6:self.ty();self.ty()
            if sk==7 and self.boolean():self.ty()
            self.seq(self.arg)
        elif n in(1,2):did=self.defid()
        else:raise ValueError(('mono',n))
        inline=self.boolean();link=self.byte();vis=self.byte();w=self.u()
        check(link<10 and vis<3 and w<10000000,('item data',inline,link,vis,w))
        return (n,defkind,sk,did,inline,link,vis,w,start,self.p)
def read(raw,unit):
    d=Decoder(raw,unit['items_start']);rows=[]
    for k in range(unit['items']):
        off=d.p
        try:rows.append(d.item())
        except Exception as ex:raise ValueError((k,off,d.p,raw[off:off+60].hex(),ex))from ex
    check(d.p==unit['items_end'],('item slice',d.p,unit['items_end']));check(sum(x[7]for x in rows)==unit['size'],'cached MIR sum');return rows
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();tabs=json.loads((a.root/'partition-ordinary-exact.json').read_bytes())
    for st in('old','edit'):
        b=(a.root/f'partition-{st}-query-cache.bin').read_bytes()
        for name,v in tabs[st]['rows'].items():
            if not name.startswith(('35bor','cdh33','f4um5')):continue
            try:
                rows=read(b,v);print(st,name[:6],len(rows),collections.Counter((r[0],r[4],r[5])for r in rows))
            except ValueError as ex:print(st,name[:6],str(ex)[:430])
