"""Concrete non-persistent per-work-product coordinate record. Sorted files, typed signatures and line arrays."""
import struct

def must(value, message):
 if not value:raise ValueError(message)
def var(v):
 must(0<=v<=0xffffffff,'out-of-range coordinate integer');out=bytearray()
 while v>=128:out.append((v&127)|128);v>>=7
 out.append(v);return bytes(out)
def read(b,p):
 start=p;v=0
 for k in range(5):
  must(p<len(b),'truncated coordinate varint');byte=b[p];p+=1;v|=(byte&127)<<(7*k)
  if byte<128:
   must(v<=0xffffffff and bytes(b[start:p])==var(v),'out-of-range or noncanonical coordinate varint');return v,p
 raise ValueError('oversized coordinate varint')
TYPES={'CSK_MD5':(1,16),'CSK_SHA1':(2,20),'CSK_SHA256':(3,32)};TAGS={v:k for k,(v,n) in TYPES.items()}
def pack(key,files,signals,flat=False):
 must(len(key)==64 and set(files)<=set(signals)and 0<len(signals)<=4096,'unexpected emission manifest');out=bytearray(b'ODL1'+bytes([int(flat)])+bytes.fromhex(key)+var(len(signals)));counts={'header':len(out),'file_identity':0,'line_counts':0,'line_payload':0};
 for name,signs in sorted(signals.items()):
  start=len(out);raw=name.encode('utf8');must(0<len(raw)<16384 and b'\0'not in raw and len(signs)==1,'missing or ambiguous DIFile identity');out+=var(len(raw))+raw;s=signs[0];
  if s is None:out.append(0)
  else:
   typ,h=s.split(':',1);mode,n=TYPES[typ];payload=bytes.fromhex(h);must(len(payload)==n and payload.hex()==h,'bad typed file checksum');out.extend(bytes([mode])+payload)
  counts['file_identity']+=len(out)-start;vals=files.get(name,[]);must(len(vals)<=1_000_000 and all(type(v)is int and 0<v<=0xffffffff for v in vals)and all(a<b for a,b in zip(vals,vals[1:])),'invalid line ordinal table');prefix=var(len(vals));out+=prefix;counts['line_counts']+=len(prefix);beg=len(out);last=0
  for v in vals:out+=struct.pack('<I',v)if flat else var(v-last);last=v
  counts['line_payload']+=len(out)-beg
 must(sum(counts.values())==len(out)and len(out)<=16<<20,'oversized coordinate envelope');return bytes(out),counts

def unpack(b):
 must(38<=len(b)<=16<<20 and b[:4]==b'ODL1'and b[4]in(0,1),'coordinate format mismatch');flat=b[4];key=b[5:37].hex();count,pos=read(b,37);must(0<count<=4096,'too many DI files');files={};signs={};prior=''
 for _ in range(count):
  length,pos=read(b,pos);must(0<length<16384 and pos+length<len(b),'bad path length');path=b[pos:pos+length].decode('utf8');pos+=length;must(path>prior and '\x00'not in path,'duplicate or unsorted logical file');prior=path;tag=b[pos];pos+=1;s=None
  if tag:
   must(tag in TAGS,'unsupported checksum');t=TAGS[tag];n=TYPES[t][1];must(pos+n<=len(b),'truncated checksum');s=t+':'+b[pos:pos+n].hex();pos+=n
  signs[path]=[s];n,pos=read(b,pos);must(n<=1_000_000,'too many source lines');lines=[];last=0
  for _ in range(n):
   if flat:must(pos+4<=len(b),'truncated flat coordinates');v=struct.unpack_from('<I',b,pos)[0];pos+=4
   else:x,pos=read(b,pos);v=last+x
   must(last<v<=0xffffffff,'nonpositive or overflowing delta');lines.append(v);last=v
  if lines:files[path]=lines
 must(pos==len(b),'excess coordinate bytes');return key,files,signs
