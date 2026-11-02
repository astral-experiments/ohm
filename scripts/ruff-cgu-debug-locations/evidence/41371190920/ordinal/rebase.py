"""Subset of the frozen source-independent encoder used by its portable replay."""
import bisect
from pathlib import PurePosixPath
from old_inputs import check
from patch_dwarf import abbrevs, cstr, leb, FIXED

def logical_cwd(image):
 b=image.contents('.debug_info');ab=abbrevs(image.contents('.debug_abbrev'));code,p=leb(b,11);tag,_,attrs=ab[code];check(tag==0x11,'missing single CU');r=image.relocs('.debug_info');strings=image.contents('.debug_str');cwd=None
 for name,form in attrs:
  start=p
  if form in FIXED:v=int.from_bytes(b[p:p+FIXED[form]],'little');p+=FIXED[form]
  elif form==8:v,p=cstr(b,p)
  else:v,p=leb(b,p,form==13)
  if name==0x1b:
   if form==8:cwd=v
   else:
    check(form==14 and start in r,'unbound compilation directory');kind,where,off=r[start];check(kind==10 and where=='.debug_str'and v==0,'wrong compilation directory relocation');cwd=cstr(strings,off)[0]
 check(cwd and PurePosixPath(cwd).is_absolute()and '..'not in PurePosixPath(cwd).parts,'ambiguous native compilation directory');return cwd

class Coordinates:
 def __init__(self,cwd,old,new):
  self.cwd=cwd;self.old,self.new=old[1],new[1];self.olds,self.news=old[2],new[2];check(old[0]==new[0],'semantic codegen key changed');check(self.old.keys()==self.new.keys()and self.olds.keys()==self.news.keys(),'debug sources differ');self.changed={p for p in self.olds if self.old.get(p,[])!=self.new.get(p,[])or self.olds[p]!=self.news[p]};self.seen={};self.hits=set()
  for p in self.changed:check(len(self.old.get(p,[]))==len(self.new.get(p,[])) and self.olds[p]!=[None]and self.news[p]!=[None],'unverifiable changed source shape or checksum')
 def location(self,filename,line,column):
  check(type(line)is int and 0<=line<2**32 and type(column)is int and 0<=column<2**32,'bad old native coordinate');
  if not line:return 0
  path=str(PurePosixPath(self.cwd)/filename)
  if '..'in PurePosixPath(path).parts:
   check(path in self.old and path in self.new and self.old[path]==self.new[path]and self.olds[path]==self.news[path]and self.olds[path]!=[None],'unresolved or changed literal native path');
  self.seen.setdefault(path,set()).add(line)
  if path not in self.changed:
   check(path in self.olds and self.olds[path]==self.news[path],'unbound native file outside unchanged debug scope');return line
  before=self.old[path];i=bisect.bisect_left(before,line);check(i<len(before)and before[i]==line,'native location absent from prior module ordinal table');self.hits.add((path,line));return self.new[path][i]
