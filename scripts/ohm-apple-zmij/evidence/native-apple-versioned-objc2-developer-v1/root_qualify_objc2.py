"""Recover the actual Cargo builds, linker executions, binary identities and literal CLI behavior."""
import argparse,gzip,hashlib,json,re,struct,zipfile
from pathlib import Path
H=lambda b:hashlib.sha256(b).hexdigest()
def mch(b):
 assert b[:8]==bytes.fromhex('cffaedfe0c000001') and struct.unpack_from('<I',b,12)[0]==2
 n,clen=struct.unpack_from('<II',b,16);cur=32;end=32+clen;sections=[]
 for _ in range(n):
  tag,size=struct.unpack_from('<II',b,cur);assert size>=8 and cur+size<=end<=len(b)
  if tag==0x19:
   ns=struct.unpack_from('<I',b,cur+64)[0];assert 72+80*ns<=size
   for i in range(ns):
    p=cur+72+80*i
    if b[p:p+32].split(bytes(1),1)[0]==b'__text' and b[p+16:p+32].rstrip(bytes(1))==b'__TEXT':
     length,offset=struct.unpack_from('<QI',b,p+40);assert length>0 and offset+length<=len(b)
     sections.append([length,H(b[offset:offset+length])])
  cur+=size
 assert cur==end and len(sections)==1
 return sections[0]
