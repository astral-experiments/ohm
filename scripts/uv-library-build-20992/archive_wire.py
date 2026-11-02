"""Reconstruct the complete GNU rlib using only the rustc CGU filename salt in its two typed inventories."""
import re,struct,hashlib
def ident(b):return hashlib.sha256(b).hexdigest()
def ck(x,msg):
 if not x:raise ValueError(msg)
def uint(b,k):
 n=0;start=k
 for shift in range(0,70,7):
  ck(k<len(b),'truncated length');v=b[k];k+=1;n|=(v&127)<<shift
  if v<128:
   ck(k==start+1 or v>0,'noncanonical length');return n,k
 raise ValueError('length overflow')
def archive(z):
 ck(z.startswith(b'!<arch>\n'),'GNU ar magic');pos=8;members=[];table=None;ends=set()
 while pos<len(z):
  hdr=z[pos:pos+60];ck(len(hdr)==60 and hdr[-2:]==b'`\n','ar header');n=int(hdr[48:58]);end=pos+60+n;ck(end<=len(z)and n>=0,'ar member bounds')
  tag=hdr[:16].decode().strip();content=z[pos+60:end];beg=pos+60
  if tag=='//':ck(table is None,'one name table');table=(beg,content);name='//';nameoff=None
  elif re.fullmatch('/[0-9]+',tag):
   ck(table is not None,'name before table');o=int(tag[1:]);t=table[1];ck(0<=o<len(t)and(o==0 or t[o-2:o]==b'/\n'),'name boundary');e=t.index(b'/\n',o);name=t[o:e].decode('ascii');nameoff=table[0]+o;ends.add((o,e+2))
  else:name=tag if tag=='/'else tag.removesuffix('/');nameoff=None
  if n%2:ck(z[end:end+1]==b'\n','ar padding')
  members.append((name,beg,content,hdr,nameoff));pos=end+n%2
 ck(pos==len(z)and len(set(row[0]for row in members))==len(members),'archive identity/count')
 ck([m[0]for m in members[:2]]==['/','//']and table is not None,'GNU symbol and long tables')
 cursor=0
 for a,b in sorted(ends):ck(a==cursor,'long names fully referenced');cursor=b
 ck(table[1][cursor:]in(b'',b'\n'),'GNU name padding')
 symbols=members[0][2];n=struct.unpack_from('>I',symbols)[0];ck(0<n<=1<<20 and len(symbols)>=4+4*n,'symbol count');offsets=struct.unpack_from('>'+str(n)+'I',symbols,4);valid={m[1]-60 for m in members[2:]};ck(set(offsets)<=valid,'symbol member references')
 names=symbols[4+4*n:];ck(names.endswith(b'\0')and len([n for n in names.split(b'\0')if n])==n,'ar symbol names')
 return members
def linkpayload(z):
 ck(z[:7]==b'\x7fELF\x02\x01\x01','ELF64 little endian');typ,mach=struct.unpack_from('<HH',z,16);ck((typ,mach)==(1,62),'x86_64 relocatable');off=struct.unpack_from('<Q',z,40)[0];entnum,number,strnum=struct.unpack_from('<HHH',z,58);ck(entnum==64 and 0<strnum<number<=256 and off+number*64<=len(z),'ELF section table')
 tab=[struct.unpack_from('<IIQQQQIIQQ',z,off+n*64)for n in range(number)];st=tab[strnum];labels=z[st[4]:st[4]+st[5]];sel=[]
 for h in tab:
  k=h[0];ck(k<len(labels),'ELF section name');e=labels.index(0,k)
  if labels[k:e]==b'.rmeta-link':sel.append(h)
 ck(len(sel)==1 and sel[0][1]==1,'one rmeta-link section');h=sel[0];offset,size=h[4:6];ck(offset+size<=len(z),'rmeta-link bounds');payload=z[offset:offset+size];finish=b'rust-end-file';ck(payload.endswith(finish),'Rust metadata wire end');p=payload[:-len(finish)];n,k=uint(p,0);ck(0<n<=4096,'rust object count');refs=[]
 for _ in range(n):
  l,k=uint(p,k);a=k;k+=l;ck(0<l<512 and k<len(p)and p[k]==0xc1,'Rust string sentinel');refs.append((p[a:k].decode('ascii'),offset+a));k+=1
 n,k=uint(p,k);ck(n==0 and k==len(p),'this observed native-lib vector must be empty');return refs
def compare(a,b,crate,required=None):
 A=archive(a);B=archive(b);ck(len(a)==len(b)and len(A)==len(B),'same archive length and number of members')
 pattern=re.compile(re.escape(crate)+r'\.([a-z0-9]{20,32})\.([a-z0-9]{7})\.rcgu\.o$');oldnew={};o_seen=set();n_seen=set();sites=[];maxrows=4096;elf=0;headers=[];link=None;syms=None
 for x,y in zip(A,B,strict=True):
  xn,off,data,header,st=x;yn,yo,newdata,newhdr,ys=y
  ck(off==yo and header==newhdr,'member order, offsets and complete headers');mx=pattern.fullmatch(xn);my=pattern.fullmatch(yn)
  if mx or my:
   ck(mx and my and mx[1]==my[1] and xn not in oldnew and yn not in oldnew.values(),'unchanged CGU identity and bijection');ck(data==newdata and data[:4]==b'\x7fELF','complete native object bytes');ck(st is not None and ys==st,'both physical GNU name-table slots')
   oldnew[xn]=yn;o_seen.add(mx[2]);n_seen.add(my[2]);sites.append((st+mx.start(2),mx[2],my[2]));elf+=1
  elif xn=='lib.rmeta-link':
   ck(yn==xn,'late metadata identity');link=(off,data,newdata)
  else:
   ck(xn==yn,'unclassified member changed name')
   if xn=='//':continue
   ck(data==newdata,'symbol table, metadata or unknown member mutated')
   if xn=='/':syms=ident(data)
   if xn=='lib.rmeta':ck(data.startswith(b'\x7fELF'),'metadata must be original physical ELF')
  headers.append(xn)
 ck(elf>0 and elf<=maxrows and len(o_seen)==len(n_seen)==1 and set(['lib.rmeta','lib.rmeta-link','/','//'])<=set(row[0]for row in A),'canonical single codegen invocation and metadata')
 if required is not None:ck(elf==required,'registered native-object count')
 ck(link is not None and syms is not None,'link records present');linkoff,data,newdata=link;refs=linkpayload(data);newrefs=linkpayload(newdata);ck(len(refs)==len(newrefs)==len(oldnew),'all object refs')
 ck(len(set(x for x,z in refs))==len(refs)and set(x for x,z in refs)==set(oldnew),'one-to-one original link inventory')
 ck(len(set(x for x,z in newrefs))==len(newrefs)and set(x for x,z in newrefs)==set(oldnew.values()),'one-to-one new link inventory')
 for (x,at),(y,bt) in zip(refs,newrefs,strict=True):
  mx=pattern.fullmatch(x);my=pattern.fullmatch(y);ck(at==bt and oldnew[x]==y,'typed link references retain corresponding position and native member')
  sites.append((linkoff+at+mx.start(2),mx[2],my[2]))
 z=bytearray(a);seen=set()
 for at,o,n in sites:
  ck(at not in seen and z[at:at+len(o)]==o.encode(),'typed original filename occurrence');seen.add(at);z[at:at+len(o)]=n.encode()
 ck(bytes(z)==b,'all bytes outside the validated filename fields must match')
 return dict(before=ident(a),after=ident(b),reconstructed=ident(z),bytes=len(a),object_files=elf,verified_name_fields=len(sites),rust_link_references=len(refs),ELF_metadata='complete and byte-identical',symbol_table_sha256=syms,old_salt=next(iter(o_seen)),new_salt=next(iter(n_seen)),native_lib_filenames=0)

