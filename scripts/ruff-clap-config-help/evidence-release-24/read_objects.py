"""Read each of the four original signed ET_REL objects and qualify physical differences."""
import bisect
import collections
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path
import zipfile

def need(x,why):
    if not x:raise ValueError(why)
def h(data):
    return hashlib.sha256(data).hexdigest()
def cstr(raw,idx):
    end=raw.index(b'\0',idx)
    return raw[idx:end].decode('utf-8')
def members(z,phase):
    m=json.loads(z.read(phase+'/selected-ruff-members.json'))['members']
    return {x[2]:x[3:]for x in m}
class Elf:
 def __init__(self,data):
    need(data[:7]==b'\x7fELF\x02\x01\x01'and struct.unpack_from('<HH',data,16)==(1,62),'x86_64 GNU relocatable ELF')
    self.raw=data
    _,_,_,_,_,off,_,_,_,_,wid,num,strings=struct.unpack_from('<HHIQQQI6H',data,16)
    need(wid==64 and off+num*wid<=len(data) and 0<strings<num,'section header bounds')
    self.secs=[struct.unpack_from('<IIQQQQIIQQ',data,off+wid*i)for i in range(num)]
    for s in self.secs:need(s[1]==8 or s[4]+s[5]<=len(data),'section file bounds')
    def blob(s):return data[s[4]:s[4]+s[5]]if s[1]!=8 else b''
    self.blob=blob;st=blob(self.secs[strings]);self.names=[cstr(st,s[0])for s in self.secs]
    syms=[s for s in self.secs if s[1]==2];need(len(syms)==1 and syms[0][9]==24,'one symbol table')
    sym=syms[0];table=blob(self.secs[sym[6]]);ss=[]
    for i in range(sym[4],sym[4]+sym[5],24):
        n,kind,other,sec,val,width=struct.unpack_from('<IBBHQQ',data,i);ss.append((cstr(table,n),kind,other,sec,val,width))
    group={}
    for i,s in enumerate(self.secs):
        if s[1]!=17:continue
        sig=ss[s[7]][0];words=struct.unpack('<'+'I'*(s[5]//4),blob(s));need(words[0]==1 and sig,'COMDAT signature')
        for idx in [i,*words[1:]]:
            need(idx not in group and 0<idx<num,'one group per allocated section');group[idx]=sig
    self.keys=[(n,s[1],group.get(i,''))for i,(s,n)in enumerate(zip(self.secs,self.names))]
    def target(index):
        name,kind,other,sec,val,width=ss[index]
        where=self.keys[sec]if 0<sec<num else ('S',sec)
        return (name,kind,other,where,val,width)
    relocs=collections.defaultdict(list)
    for i,s in enumerate(self.secs):
        if s[1] not in (4,9):continue
        need(s[1]==4 and s[9]==24 and self.secs[s[6]]==sym,'bounded ELF64 RELA section')
        for off in range(s[4],s[4]+s[5],24):
            pos,info,add=struct.unpack_from('<QQq',data,off)
            relocs[s[7]].append((pos,info&0xffffffff,target(info>>32),add))
    self.functions={}
    for n,kind,o,sec,val,size in ss:
        if kind&15!=2 or not(0<sec<num)or not size:continue
        s=self.secs[sec];need(s[2]&4 and val+size<=s[5]and n,'defined machine function')
        rel=tuple(sorted((at-val,how,ref,add)for at,how,ref,add in relocs[sec]if val<=at<val+size))
        key=(n,kind,o);need(key not in self.functions,'ambiguous defined function')
        self.functions[key]=(blob(s)[val:val+size],rel)
    self.alloc={};self.literals={}
    for i,s in enumerate(self.secs):
        if not s[2]&2:continue
        k=self.keys[i];need(k not in self.alloc,'ambiguous allocated section')
        b=blob(s);self.alloc[k]=(s[2],s[5],s[8],h(b),tuple(sorted(relocs[i])))
        for literal in (b'--config "lint.line-length = 100"',b'--config "line-length = 100"'):
            if literal in b:self.literals[literal.decode()]=[k,b.index(literal)]
def compact(k):
    return [*k]
def main(file,expected,out):
    with file.open('rb')as f:need(hashlib.file_digest(f,'sha256').hexdigest()==expected,'original SHA')
    with zipfile.ZipFile(file)as z:
        metas={p:members(z,p)for p in ('old','edit','independent-clean-new')}
        ids=['26b50y1455r2nn7imncnrh1im','3xhp4sunmhbswr1ovpiqoyj96','3u3vz84botgcprgohgbxpi18d','c3vf9hzmvyyz4hr2bieid2ks6']
        result={}
        for cgu in ids:
            images={};contacts={}
            for p,q in metas.items():
                digest,length=q[cgu];need(0<length<10_000_000,'bound before decompression')
                b=subprocess.check_output(['zstd','-qdc'],input=z.read('four-native-bodies/'+digest+'.zst'))
                need(len(b)==length and h(b)==digest,'complete object bytes')
                if digest not in images:images[digest]=Elf(b)
                contacts[p]=digest
            need(contacts['edit']==contacts['independent-clean-new'],'independent clean object')
            a,b=(images[contacts[p]]for p in ('old','edit'))
            af,bf=a.functions,b.functions;keys=af.keys()&bf.keys();raw=[];rels=[]
            for k in sorted(keys):
                old,ro=af[k];new,rn=bf[k]
                if old!=new:
                    raw.append({'name':k[0],'before':len(old),'after':len(new),'different_positions':abs(len(old)-len(new))+sum(x!=y for x,y in zip(old,new))})
                if rn!=ro:rels.append({'name':k[0],'old_relocations':len(ro),'new_relocations':len(rn),'old_only':len(set(ro)-set(rn)),'new_only':len(set(rn)-set(ro))})
            U=a.alloc;V=b.alloc
            surface=collections.Counter();witness=[]
            for key in sorted(U.keys()|V.keys()):
                l,r=U.get(key),V.get(key)
                if l==r:continue
                if l is None or r is None:kind='new-only'if l is None else'old-only'
                elif l[:4]!=r[:4] and l[4]!=r[4]:kind='section and relocations'
                elif l[:4]!=r[:4]:kind='section bytes, size or flags'
                else:kind='resolved relocations'
                surface[kind]+=1;witness.append([key,kind])
            result[cgu]={'physical':contacts,'function_counts':[len(af),len(bf)],'total_named_old_function_bytes':sum(len(v[0])for v in af.values()),'born_or_removed':[[k[0]for k in sorted(af.keys()-bf.keys())],[k[0]for k in sorted(bf.keys()-af.keys())]],'machine_byte_changes':raw,'resolved_relocation_changes':rels,'allocated_section_counts':[len(U),len(V)],'allocated_delta':dict(surface),'allocated_witnesses':witness,'literal_locations':[a.literals,b.literals]}
        out.write_text(json.dumps({'archive_sha256':expected,'modules':result},sort_keys=True,indent=1)+'\n')
        for k,x in result.items():print(k,x['function_counts'],len(x['machine_byte_changes']),len(x['resolved_relocation_changes']),x['allocated_delta'])
if __name__=='__main__':main(Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3]))
