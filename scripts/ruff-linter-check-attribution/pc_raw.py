"""Read fixed-period kernel samples independently of perf's scripting and symbol resolution."""
from bisect import bisect_right
from collections import Counter,defaultdict
from pathlib import Path
import csv,gzip,hashlib,io,json,mmap,re,statistics,struct,subprocess,sys,tarfile,zipfile

def check(x,t):
 if not x:raise ValueError(t)
def raw_records(buf):
 head=struct.unpack_from('<9Q',buf);magic,hsize,asize,ao,alen,do,dlen,_,_=head;check(magic==int.from_bytes(b'PERFILE2','little') and hsize>=72 and alen==asize and ao>=hsize and do+dlen<=len(buf),'wrong original perf archive');typ,inner,config,period,bits,read_format,flags=struct.unpack_from('<IIQQQQQ',buf,ao);check(typ==0 and config==1 and inner>=64 and flags&32 and not flags&16 and bits&7==7 and bits&32,'not the actual hardware user instruction/fp event');i=do;out=Counter();records=Counter();chain_depth=Counter();modes=Counter();skid=set()
 while i<do+dlen:
  k,mode,length=struct.unpack_from('<IHH',buf,i);check(length>=8 and i+length<=do+dlen,'malformed kernel event');records[k]+=1
  if k==9:
   check(mode&7 in (1,2),'unknown execution-mode attribution on user-mode event');modes[mode&7]+=1;pos=i+8
   def value():
    nonlocal pos
    v=struct.unpack_from('<Q',buf,pos)[0];pos+=8;return v
   if bits&(1<<16):value()
   ip=value();pair=value();pid,tid=pair&0xffffffff,pair>>32;at=value()
   for flag in (8,64,512,128):
    if bits&flag:value()
   weight=value()if bits&256 else period;check(weight==period and not bits&16,'unexpected sample read format');depth=value();check(depth<=64 and pos+depth*8<=i+length,'bad callchain');chain_depth[depth]+=1;out[(pid,tid,at,weight,ip)]+=1
   if mode&7!=2:skid.add((pid,tid,at,weight,ip))
  i+=length
 check(i==do+dlen,'trailing kernel data');return period,out,dict(records),dict(chain_depth),dict(modes),skid

def symbol_rows(compressed):
 frames={};rows=[]
 with gzip.GzipFile(fileobj=compressed)as gz:
  for line in gz:
   v=json.loads(line)
   if v[0]=='f':_,n,dso,sym=v;check(n not in frames,'multiple symbol table definitions');frames[n]=(dso,sym)
   else:
    _,event,pid,tid,at,period,leaf,stack=v;check(event=='instructions:u' and all(x[0]in frames for x in [leaf,*stack]),'unknown sampled source name');rows.append(((pid,tid,at,period,leaf[1]),leaf,stack))
 return frames,rows
