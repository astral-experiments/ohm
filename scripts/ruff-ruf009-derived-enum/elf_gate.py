"""Compare two actual Ruff ELFs, allowing one authenticated native compiler directory."""
from collections import Counter
from pathlib import Path
import hashlib
import json
import mmap
import os
import re
import resource
import shutil
import struct
import subprocess
import tempfile


def need(cond, why):
    if not cond:raise ValueError(why)


def digest(buf):
    return hashlib.sha256(buf).hexdigest()


def file_digest(file):
    with file.open('rb')as src:return hashlib.file_digest(src,'sha256').hexdigest()


def image(mm):
    ident,_,machine,_,_,phoff,shoff,_,_,phsz,nph,shsz,nsh,strings=struct.unpack_from('<16sHHIQQQIHHHHHH',mm)
    need(ident[:6]==b'\x7fELF\x02\x01' and machine==62 and phsz==56 and shsz==64,'different ELF format')
    rows=[struct.unpack_from('<IIQQQQIIQQ',mm,shoff+i*shsz)for i in range(nsh)]
    names=rows[strings][4];sections={}
    for r in rows:
        pos=names+r[0];name=mm[pos:mm.find(b'\0',pos)].decode();need(name not in sections,'duplicate ELF section');sections[name]=r
    programs=[struct.unpack_from('<IIQQQQQQ',mm,phoff+i*phsz)for i in range(nph)]
    pos=sections['.note.gnu.build-id'][4];ns,ds,t=struct.unpack_from('<III',mm,pos)
    need((ns,ds,t)==(4,32,3) and mm[pos+12:pos+16]==b'GNU\0','unexpected GNU build ID')
    return sections,programs,pos+16


def canonical_strings(data,role_path):
    tag=b'COMPILER_DIRECTORY';need(tag not in data,'ambiguous path normalization')
    group=Counter(data.replace(role_path,tag).split(b'\0'))
    return group


def pointer_proof(old,new,str_a,str_b,path_a,path_b):
    count=0;diff_bytes=0;end=0
    for idx,(a,b) in enumerate(zip(old,new)):
        if a==b:continue
        diff_bytes+=1
        if idx<end:continue
        options=[]
        for start in range(max(end,idx-3),min(idx,len(old)-4)+1):
            oa=struct.unpack_from('<I',old,start)[0];ob=struct.unpack_from('<I',new,start)[0]
            if min(oa,ob)<1 or oa>=len(str_a) or ob>=len(str_b) or str_a[oa-1] or str_b[ob-1]:continue
            x=str_a[oa:str_a.index(b'\0',oa)];y=str_b[ob:str_b.index(b'\0',ob)]
            if x and x.replace(path_a,b'COMPILER_DIRECTORY')==y.replace(path_b,b'COMPILER_DIRECTORY'):
                options.append(start)
        need(len(options)==1,('unexplained or ambiguous debug-string offset',idx,options))
        end=options[0]+4;count+=1
    return {'different_bytes':diff_bytes,'authenticated_strp_words':count}


def decode(binary,comp_dir,section):
    tool=Path(shutil.which('llvm-dwarfdump-18')).resolve(strict=True)
    def cap():resource.setrlimit(resource.RLIMIT_AS,(1536<<20,1536<<20))
    cmd=[tool,'--debug-'+section,'--show-form',binary]
    out=hashlib.sha256();raw=hashlib.sha256();replaced=lines=size=0
    with tempfile.TemporaryFile()as err,subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=err,preexec_fn=cap)as child:
        try:
            for block in iter(lambda:child.stdout.readlines(1<<19),[]):
                data=b''.join(block);raw.update(data);size+=len(data)
                if not lines:
                    first,rest=data.split(b'\n',1)
                    need(first==os.fsencode(binary)+b':\tfile format elf64-x86-64','different decoder identity')
                    data=b'SUBJECT.ELF:\tfile format elf64-x86-64\n'+rest
                replaced+=data.count(comp_dir);out.update(data.replace(comp_dir,b'COMPILER_DIRECTORY'));lines+=len(block)
                need(size<4<<30,'oversize DWARF decoding')
            status=child.wait();err.seek(0);need(status==0 and not err.read(),('bad DWARF',section,status))
        finally:
            if child.poll()is None:child.kill();child.wait()
    return dict(tool=file_digest(tool),raw=raw.hexdigest(),canonical=out.hexdigest(),lines=lines,bytes=size,replacements=replaced)


def wild_note(mm,offset):
    tool=Path(shutil.which('b3sum')).resolve(strict=True)
    with subprocess.Popen([tool,'--no-names','-'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)as child:
        child.stdin.write(memoryview(mm)[:offset-16]);child.stdin.write(bytes(48));child.stdin.write(memoryview(mm)[offset+32:])
        child.stdin.close();result=child.stdout.read().decode().strip()
        need(child.wait()==0 and result==mm[offset:offset+32].hex(),'wrong stock Wild build ID')
    return result

def compare(path1,path2,dir1,dir2):
    a,b=Path(path1),Path(path2);pa,pb=map(os.fsencode,(dir1,dir2));prior=[file_digest(a),file_digest(b)]
    if prior[0]==prior[1]:
        with a.open('rb')as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)as m:
            _,_,offset=image(m);value=wild_note(m,offset)
        return {'full_raw_sha256':prior,'identical':True,'build_ids':[value,value]}
    selected=re.compile(rb'^(.*?/build/registries/)v2-([0-9a-f]{16})(/tikv-jemalloc-sys/[0-9a-f]{16}/out/build)$')
    ma,mb=selected.fullmatch(pa),selected.fullmatch(pb);need(ma and mb and ma[1]==mb[1] and ma[3]==mb[3] and ma[2]!=mb[2],'unexpected Cargo native-directory distinction')
    with a.open('rb')as fa,b.open('rb')as fb,mmap.mmap(fa.fileno(),0,access=mmap.ACCESS_READ)as x,mmap.mmap(fb.fileno(),0,access=mmap.ACCESS_READ)as y:
        s,ph,g=image(x);ss,pp,gg=image(y);need(s==ss and ph==pp and g==gg and len(x)==len(y),'changed ELF headers/layout')
        names=('.debug_info','.debug_macro','.debug_str')
        ranges=[(g,g+32)]+[(s[n][4],s[n][4]+s[n][5])for n in names]
        for n in names:need(s[n][2]&6==0,'allowed debug range overlaps alloc/exec section')
        start=0;h=hashlib.sha256()
        for low,high in sorted([*ranges,(len(x),len(x))]):
            need(start<=low,'overlap');h.update(memoryview(x)[start:low]);need(memoryview(x)[start:low]==memoryview(y)[start:low],'changed ELF bytes outside allowed ranges');start=high
        loads=[]
        for kind,flags,offset,_,_,size,_,_ in ph:
            if kind!=1:continue
            xa=hashlib.sha256();xb=hashlib.sha256()
            for buf,dest in [(x,xa),(y,xb)]:
                stop=offset+size
                if offset<=g<stop:
                    need(flags&1==0 and g+32<=stop,'GNU ID in executable bytes');dest.update(memoryview(buf)[offset:g]);dest.update(bytes(32));dest.update(memoryview(buf)[g+32:stop])
                else:dest.update(memoryview(buf)[offset:stop])
            need(xa.digest()==xb.digest(),'different loadable bytes');loads.append([offset,size,flags,xa.hexdigest()])
        def section(mm,k):start,size=s[k][4:6];return mm[start:start+size]
        sa=section(x,'.debug_str');sb=section(y,'.debug_str')
        need(sa.count(pa)==sb.count(pb)==1 and sb.count(pa)==sa.count(pb)==0 and canonical_strings(sa,pa)==canonical_strings(sb,pb),'different debug string multiset')
        pointers={k:pointer_proof(section(x,k),section(y,k),sa,sb,pa,pb)for k in names[:2]}
        ids=[wild_note(buf,g) for buf in (x,y)]
    dec={}
    for name in ('info','macro'):
        dec[name]=[decode(a,pa,name),decode(b,pb,name)]
        n1,n2=dec[name];need(n1['canonical']==n2['canonical'] and n1['lines']==n2['lines'],'unexplained DWARF '+name)
    return dict(full_raw_sha256=prior,identical=False,dirs=[dir1,dir2],build_ids=ids,load_segments=loads,outside=h.hexdigest(),debug_string_offsets=pointers,dwarf=dec)
