"""Stream two original native editor ELFs; identify the actual linked upstream symbol contact."""
import argparse,collections,hashlib,json,os,re,shutil,string,struct,subprocess,tempfile,zipfile
from pathlib import Path
ap=argparse.ArgumentParser()
ap.add_argument("archive",type=Path);ap.add_argument("--output",type=Path,required=True)
args=ap.parse_args();ZIP=args.archive;ROOT=ZIP.parent
assert shutil.disk_usage(ROOT).free>15*2**30+64*2**20
REF={'OLD':'9b7274e140420d30b49f0b96aa7fb1bbb9b7d4c620d5dd0eb7283aceeacc25bf','NEW':'fe246dc2a7743ed716eb7a9f007da069cb02ec6176bdfb1e81779a30b6d7470f'}
def selected(z,sha,member):
 with tempfile.TemporaryFile(dir=ROOT)as compressed:
  with z.open(member)as source:shutil.copyfileobj(source,compressed,2**20)
  def traverse(callback):
   compressed.seek(0);offset=0
   with subprocess.Popen(['zstd','-qdc'],stdin=compressed,stdout=subprocess.PIPE)as proc:
    while b:=proc.stdout.read(2**20):callback(offset,b);offset+=len(b)
    assert proc.wait()==0 and 100*2**20<offset<350*2**20
  elf=struct.Struct('<16sHHIQQQIHHHHHH');sh=struct.Struct('<IIQQQQIIQQ');sym=struct.Struct('<IBBHQQ')
  spans=[];table=bytearray();h=hashlib.sha256()
  def sub(off,data,start,n):
   lo=max(off,start);hi=min(off+len(data),start+n)
   return data[lo-off:hi-off]if lo<hi else b''
  def first(off,data):
   h.update(data)
   if not off:
    e=elf.unpack_from(data);assert e[0][:7]==b'\x7fELF\x02\x01\x01' and e[2]==62 and e[11]==sh.size and 0<e[12]<1024
    spans.extend((e[6],e[11]*e[12]))
   table.extend(sub(off,data,*spans))
  traverse(first);assert h.hexdigest()==sha and len(table)==spans[1]
  sections=list(sh.iter_unpack(table));s,=[e for e in sections if e[1]==2];t=sections[s[6]];assert s[-1]==sym.size and t[1]==3 and s[5]<20*2**20 and t[5]<110*2**20
  names={};pos=0;carry=b''
  with tempfile.TemporaryFile(dir=ROOT)as entries:
   def second(off,b):
    nonlocal carry,pos
    entries.write(sub(off,b,s[4],s[5]));raw=sub(off,b,t[4],t[5])
    if raw:
     parts=(carry+raw).split(b'\x00');carry=parts.pop();assert len(carry)<512*1024
     for name in parts:
      if any(tok in name for tok in (b'spec_from_iter',b'spec_extend',b'scripts_to_synchronize')) and name.startswith(b'_R'):names[pos]=name.decode('ascii')
      pos+=len(name)+1
   traverse(second);assert pos==t[5] and not carry and entries.tell()==s[5]
   entries.seek(0);actual={}
   while block:=entries.read(sym.size*8192):
    for i,info,other,section,value,n in sym.iter_unpack(block):
     if i in names and info&15==2 and 0<section<len(sections) and n and value:
      nm=names[i];assert nm not in actual
      target=sections[section];assert target[1]==1 and target[2]&4 and target[3]<=value and value+n<=target[3]+target[5]
      actual[nm]={"size":n,"binding":info>>4,"visibility":other,"offset":target[4]+value-target[3],"address":value}
  hs={k:hashlib.sha256()for k in actual}
  def code(off,data):
   for k,v in actual.items():
    if v["offset"]<off+len(data) and v["offset"]+v["size"]>off:hs[k].update(sub(off,data,v["offset"],v["size"]))
  traverse(code)
  for k in actual:actual[k]["code_sha256"]=hs[k].hexdigest()
  return actual
with zipfile.ZipFile(ZIP)as z:
 if "terminal.json"in z.namelist():
  t=json.loads(z.read("terminal.json"));roles=t["roles"];a={r["old"]["sha256"]for r in roles};b={r["new"]["sha256"]for r in roles};assert len(roles)==4 and len(a)==len(b)==1
  REF={"OLD":a.pop(),"NEW":b.pop()};members={k:"native/"+h+".zst"for k,h in REF.items()}
 else:members={k:h+".elf.zst"for k,h in REF.items()}
 states={k:selected(z,h,members[k])for k,h in REF.items()}
allnames=sorted(set(states['OLD'])|set(states['NEW']));out=subprocess.run(['c++filt','-s','rust'],input=('\n'.join(allnames)+'\n').encode(),capture_output=True,check=True).stdout.decode().splitlines();assert len(allnames)==len(out)
added=[];removed=[];official={}
for raw,name in zip(allnames,out):
 if name==raw:raise ValueError('native demangler did not decode Rust v0')
 if raw not in states['OLD']:added.append(name)
 if raw not in states['NEW']:removed.append(name)
 if 'scripts_to_synchronize' in name or ('ruff_db' in name and 'File' in name and ('ty_project' in raw or 'ty_project' in name)):
  official[raw]={'demangled':name,'old':states['OLD'].get(raw),'new':states['NEW'].get(raw)}
pairs={}
for raw,w in official.items():
 name=w["demangled"]
 if not name.endswith("::from_iter") or bool(w["old"])==bool(w["new"]):continue
 suffix=raw[raw.rindex("9from_iter")+10:]
 if suffix.startswith("B"):
  assert suffix.endswith("_");value=0;alphabet=string.digits+string.ascii_lowercase+string.ascii_uppercase
  for c in suffix[1:-1]:value=value*62+alphabet.index(c)
  # v0 base-62 encodes 0 as "_", otherwise n-1; indices count after the two-byte _R prefix.
  start=(value+1 if suffix[1:-1] else 0)+2;root=re.match(r"C(?:s[0-9a-zA-Z]*_)?([0-9]+)(ty_project|ty_server)",raw[start:])
 else:root=re.fullmatch(r"C(?:s[0-9a-zA-Z]*_)?([0-9]+)(ty_project|ty_server)",suffix)
 assert root and int(root[1])==len(root[2]);side="OLD" if w["old"]else"NEW"
 assert root[2]==("ty_server"if side=="OLD"else"ty_project")
 bucket=pairs.setdefault(name,{});assert side not in bucket
 bucket[side]={"mangled":raw,"instantiating_crate":root[2],**(w["old"]or w["new"])}
assert len(pairs)==2 and all(set(v)=={"OLD","NEW"}for v in pairs.values())
assert len(added)==3 and len(removed)==2 and sorted(set(added)-set(removed))[0].endswith("::scripts_to_synchronize")
r={"original_elf_sha256":REF,"all_defined_target_family":{k:len(v)for k,v in states.items()},"added":added,"removed":removed,"target_qualified":official,"changed_instantiating_crates":pairs}
args.output.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n")
print("Linked source holds both old/new owner pairs.",[(k.split("::")[-2][:18],v["OLD"]["size"],v["NEW"]["size"])for k,v in pairs.items()])
