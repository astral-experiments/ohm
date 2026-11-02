"""Conservative old-only ELF64/LLVM DWARF4 line-table patch for a whole-line insertion.
All unsupported forms, unsupported location-bearing DIEs, opaque source/column edits, layout
changes and noncanonical old line programs refuse the member. This is not a reuse admission.
"""
from collections import Counter
from pathlib import PurePosixPath
import hashlib,struct
from old_inputs import PR,check,sha

def leb(b,p,signed=False):
 value=0
 for shift in range(0,70,7):
  check(p<len(b),'truncated LEB');x=b[p];p+=1;value|=(x&127)<<shift
  if x<128:
   if signed and x&64:value-=1<<(shift+7)
   return value,p
 raise ValueError('oversized LEB')
def enc(v,signed=False):
 check(signed or v>=0,'negative unsigned LEB');out=bytearray()
 while True:
  x=v&127;v>>=7
  if (v==0 and (not signed or x&64==0))or(signed and v==-1 and x&64):out.append(x);return bytes(out)
  out.append(x|128)
def u16(b,p):return struct.unpack_from('<H',b,p)[0]
def u32(b,p):return struct.unpack_from('<I',b,p)[0]
def cstr(b,p):
 e=b.index(0,p);return b[p:e].decode('utf8'),e+1

class Image:
 def __init__(self,old):
  self.raw=old;h=struct.unpack_from('<16sHHIQQQIHHHHHH',old);check(h[0][:7]==b'\x7fELF\x02\x01\x01'and h[1:3]==(1,62)and h[11]==64,'expected x86_64 ET_REL');self.rows=[struct.unpack_from('<IIQQQQIIQQ',old,h[6]+i*64)for i in range(h[-2])];tab=self.section(h[-1]);self.names=[cstr(tab,r[0])[0]for r in self.rows];self.n={}
  for i,name in enumerate(self.names):
   if name.startswith(('.debug_','.rela.debug_')):
    check(name not in self.n,'duplicate DWARF section');self.n[name]=i
  check(not any('loclist'in k or k in {'.debug_loc','.debug_types','.debug_macro','.debug_macinfo'}for k in self.n),'variable, type-unit or macro location section unsupported');check({'.debug_line','.debug_info','.debug_abbrev'}<=self.n.keys(),'missing required debug vector')
 def section(self,i):
  r=self.rows[i];check(r[4]+r[5]<=len(self.raw),'section interval');return bytes(self.raw[r[4]:r[4]+r[5]])
 def contents(self,k):return self.section(self.n[k])
 def relocs(self,k):
  tag='.rela'+k
  if tag not in self.n:return {}
  i=self.n[tag];r=self.rows[i];check(r[1]==4 and r[7]==self.n[k]and r[9]==24,'bad relocation header');tab=self.section(r[6]);out={}
  for off,info,add in struct.iter_unpack('<QQq',self.section(i)):
   sym=info>>32;_name,_type,_other,sec,val,_size=struct.unpack_from('<IBBHQQ',tab,sym*24);check(0<sec<len(self.names)and off not in out,'bad debug relocation');out[off]=(info&0xffffffff,self.names[sec],val+add)
  return out
 def replace(self,updated):
  out=bytearray(self.raw)
  for k,data in updated.items():
   row=self.rows[self.n[k]];check(len(data)==row[5],'updated section changes ELF extent');out[row[4]:row[4]+row[5]]=data
  return bytes(out)

class SourceMap:
 def __init__(self,path,mapping,old,new):
  check(path==PR and isinstance(mapping,dict)and len(mapping)==len(old),'incomplete or unidentified source map');last=0
  for i,line in enumerate(old,1):
   j=mapping.get(i);check(isinstance(j,int)and last<j<=len(new)and line==new[j-1],'mapped complete source/column bytes differ');last=j
  self.path=path;self.map=mapping;self.old=old;self.new=new
 def location(self,filename,line,column):
  check(isinstance(line,int)and 0<=line<2**32 and isinstance(column,int)and 0<=column<2**32,'unsupported source position');
  if filename!=self.path:
   check(not filename.endswith('/'+self.path),'unbound absolute alias of changed source');return line
  if line==0:return 0
  j=self.map.get(line);check(j is not None and self.old[line-1]==self.new[j-1],'no exact mapped source/column bytes');return j

class Lines:
 def __init__(self,b):
  self.b=b;check(len(b)>=16 and u32(b,0)+4==len(b)and u16(b,4)==4,'expected one DWARF32 v4 line table');self.start=u32(b,6)+10;self.min,self.maxops,self.stmt,self.base,self.span,self.opbase=struct.unpack_from('<BBBbBB',b,10);check((self.min,self.maxops,self.stmt,self.opbase)==(1,1,1,13)and -128<=self.base<0 and self.span>0,'unsupported line settings');p=16;check(list(b[p:p+12])==[0,1,1,1,1,0,0,0,1,0,0,1],'unknown standard opcode flags');p+=12;dirs=[''];self.files=[''];self.times=[]
  while b[p]:s,p=cstr(b,p);dirs.append(s)
  p+=1
  while b[p]:
   name,p=cstr(b,p);di,p=leb(b,p);tm,p=leb(b,p);size,p=leb(b,p);check(di<len(dirs)and name not in ('.','..'),'invalid source path');full=str(PurePosixPath(dirs[di])/name);self.files.append(full);self.times.append((tm,size));
   if full==PR:check(tm==size==0,'changed source has timestamp or size in line header')
  check(p+1==self.start,'unconsumed line prologue')
 def file(self,i):check(0<i<len(self.files),'unknown DWARF source file index');return self.files[i]
 def encode(self,ld,ad,end=False):
  # Pinned LLVM MCDwarfLineAddr::encode, with this source cohort's min instruction width of 1.
  b=self.base;r=self.span;base=self.opbase;limit=(255-base)//r;out=bytearray();check(ad>=0,'negative address delta')
  if end:
   if ad==limit:out.append(8)
   elif ad:out.extend(b'\x02'+enc(ad))
   return bytes(out)+b'\0\1\1'
  temp=ld-b;need_copy=False
  if temp<0 or temp>=r or temp+base>255:
   out.extend(b'\x03'+enc(ld,True));ld=0;temp=-b;need_copy=True
  if ld==ad==0:return bytes(out)+b'\1'
  temp+=base
  if ad<256+limit:
   op=temp+ad*r
   if op<=255:return bytes(out)+bytes([op])
   op=temp+(ad-limit)*r
   if 0<=op<=255:return bytes(out)+bytes([8,op])
  out.extend(b'\x02'+enc(ad));out.append(1 if need_copy else temp);return bytes(out)
 def rewrite(self,source,relocs):
  b=self.b;p=self.start;out=bytearray(b[:p]);start=p;oldline=newline=1;file=1;column=0;addr=ld=0;counts=Counter();seen=set();maxaddr=(255-self.opbase)//self.span;digest=hashlib.sha256();last_ended=True
  def passthrough(a,end):
   nonlocal start
   check(start==a,'interleaved source state inside LLVM row encoding');out.extend(b[a:end]);start=end
  while p<len(b):
   a=p;op=b[p];p+=1;ended=False;row=False
   if op==0:
    length,p=leb(b,p);end=p+length;check(length>0 and end<=len(b),'bad extended line opcode');kind=b[p];p+=1
    if kind==1:check(length==1,'malformed end_sequence');ended=True;row=True
    elif kind==2:
     check(length==9 and p in relocs and p-a+len(out)==p,'set_address relocation would move');typ,sym,add=relocs[p];check(typ==1 and sym.startswith('.text')and add==0,'unbound set_address');seen.add(p);passthrough(a,end);last_ended=False
    elif kind==4:
     _,stop=leb(b,p);check(stop==end,'malformed discriminator');passthrough(a,end)
    else:raise ValueError(f'unsupported extended line opcode {kind}')
    p=end
   elif op==1:row=True
   elif op==2:v,p=leb(b,p);addr+=v
   elif op==3:v,p=leb(b,p,True);ld+=v
   elif op==8:addr+=maxaddr
   elif op in (4,5,12):
    v,p=leb(b,p)
    if op==4:self.file(v);file=v
    if op==5:column=v
    passthrough(a,p)
   elif op in (6,7,10,11):passthrough(a,p)
   elif op==9:raise ValueError('unsupported fixed PC advance')
   elif op>=self.opbase:
    code=op-self.opbase;addr+=code//self.span;ld+=self.base+code%self.span;row=True
   else:raise ValueError(f'unsupported line opcode {op}')
   if row:
    check(self.encode(ld,addr,ended)==b[start:p],f'old line program is not canonical LLVM at {start}');oldline+=ld;new=source.location(self.file(file),oldline,column);check(not ended or (ld==0 and new==newline),'end row needs independent location rewrite');out.extend(self.encode(new-newline,addr,ended));counts['rows']+=1;counts['end_rows']+=ended;counts['mapped_rows']+=(new!=oldline);counts['target_rows']+=(self.file(file)==PR);digest.update(struct.pack('<IIII?',file,oldline,new,column,ended));newline=new;addr=ld=0;start=p
    if ended:oldline=newline=1;file=1;column=0;last_ended=True
  check(start==len(b)and last_ended and seen==set(relocs),'incomplete DWARF sequences or extra relocations');check(len(out)==len(b),'line-program length changes');return bytes(out),dict(counts),digest.hexdigest()

FIXED={1:8,5:2,6:4,7:8,11:1,12:1,14:4,16:4,17:1,18:2,19:4,20:8,23:4,25:0,32:8}
FILE_LINE={'decl':(0x3a,0x3b,0x39),'call':(0x58,0x59,0x57)}
def abbrevs(b):
 p=0;answer={}
 while p<len(b):
  code,p=leb(b,p)
  if not code:check(p==len(b),'multiple abbreviation tables');break
  tag,p=leb(b,p);ch=b[p];p+=1;check(code not in answer and ch in(0,1),'invalid abbreviation');check(tag in (0x11,0x2e,0x1d,0x0b),'unsupported variable/type or other location-bearing DIE');attrs=[]
  while True:
   name,p=leb(b,p);form,p=leb(b,p)
   if not name:check(form==0,'bad abbrev terminator');break
   check(name not in (2,0x40),'variable/frame location expression unsupported');check(form in FIXED or form in (8,13,15,21),'unsupported attribute form');attrs.append((name,form))
  answer[code]=(tag,ch,attrs)
 return answer

def info(image,lines,source):
 b=image.contents('.debug_info');check(u32(b,0)+4==len(b)and u16(b,4)==4 and b[10]==8,'expected one x86_64 DWARF4 CU');rel=image.relocs('.debug_info');check(u32(b,6)==0 and rel.get(6)==(10,'.debug_abbrev',0),'unbound abbreviation origin');ab=abbrevs(image.contents('.debug_abbrev'));out=bytearray(b);p=11;depth=0;dies=Counter();changes=Counter();check_root=0;digest=hashlib.sha256()
 while p<len(b):
  code,p=leb(b,p)
  if code==0:check(depth>0,'unbalanced DIE end');depth-=1;continue
  check(code in ab,'unknown DIE');tag,ch,attrs=ab[code];dies[hex(tag)]+=1;have={}
  if tag==0x11:check_root+=1;check(depth==0 and check_root==1,'multiple CUs')
  for name,form in attrs:
   a=p
   if form in FIXED:v=int.from_bytes(b[p:p+FIXED[form]],'little');p+=FIXED[form]
   elif form==8:v,p=cstr(b,p)
   else:v,p=leb(b,p,form==13)
   check(p<=len(b)and name not in have,'truncated or duplicate attr');have[name]=(v,a,p,form)
  if tag==0x11:
   check(have[0x13][0]==0x1c,'not Rust DWARF');v,off,_,_=have[0x10];check(v==0 and rel.get(off)==(10,'.debug_line',0),'wrong CU line table')
  for label,(fa,la,ca)in FILE_LINE.items():
   if la not in have:continue
   check(fa in have,'unbound file/line pair');v,a,end,form=have[la];f=lines.file(have[fa][0]);col=have.get(ca,(0,))[0];new=source.location(f,v,col);check(form in(5,6,7,11,15)and a not in rel,'non-integral or relocated source line');digest.update(struct.pack('<IIII',have[fa][0],v,new,col));changes[label+'_attrs']+=1;changes[label+'_changed']+=new!=v
   if new!=v:
    z=enc(new)if form==15 else new.to_bytes(FIXED[form],'little');check(len(z)==end-a,'source-line form width changed');out[a:end]=z
  depth+=ch
 check(depth==0 and check_root==1,'incomplete Rust CU');return bytes(out),dict(changes),dict(dies),digest.hexdigest()

def reconstruct(old,source):
 e=Image(old);l=Lines(e.contents('.debug_line'));n,ls,ld=l.rewrite(source,e.relocs('.debug_line'));i,ds,tags,dd=info(e,l,source);result=e.replace({'.debug_line':n,'.debug_info':i});return result,dict(line=ls,die=ds,tags=tags,line_rows_sha=ld,die_locations_sha=dd,old_elf_sha=sha(old),predicted_elf_sha=sha(result),predicted_debug_line=sha(n),predicted_debug_info=sha(i),changed_bytes=sum(a!=b for a,b in zip(old,result,strict=True)))
