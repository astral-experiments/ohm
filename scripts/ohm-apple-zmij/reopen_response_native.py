"""Reopen the complete Xcode calibration product, actual response fd events and code signature."""
import gzip,hashlib,json,struct
from pathlib import Path
import sys
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from response_custody import resolved
from study import digest,need
from test_held_response import negatives

def signature(data):
    need(data[:8]==bytes.fromhex('cffaedfe0c000001') and struct.unpack_from('<I',data,12)[0]==2,'not an arm64 Mach-O program')
    n,size=struct.unpack_from('<II',data,16);pos=32;found=[]
    for i in range(n):
        cmd,count=struct.unpack_from('<II',data,pos);need(8<=count<=32+size-pos,'invalid Mach-O load command')
        if cmd==0x1d:found.append(struct.unpack_from('<II',data,pos+8))
        pos+=count
    need(pos==32+size and len(found)==1,'missing original Xcode signature')
    (offset,total),=found;need(offset+total==len(data),'unexpected signature extent')
    magic,length,entries,slot,rel=struct.unpack_from('>5I',data,offset);need((magic,entries,slot,rel)==(0xfade0cc0,1,0,20) and length<=total and not any(data[offset+length:]),'unsupported Mach-O signature')
    at=offset+rel;cd,ns,version,flags,hash_at,name,special,pages,limit=struct.unpack_from('>9I',data,at)
    need((cd,version,flags,special,limit)==(0xfade0c02,0x20400,0x20002,0,offset) and ns==length-rel and
         struct.unpack_from('4B',data,at+36)==(32,2,0,12) and hash_at+pages*32==ns and pages==(offset+4095)//4096,'unexpected direct/long Apple CodeDirectory')
    for i in range(pages):
        lo=i*4096;actual=hashlib.sha256(data[lo:min(lo+4096,offset)]).digest()
        need(data[at+hash_at+i*32:at+hash_at+(i+1)*32]==actual,'invalid physical signed page')
    return pages

def check(read):
    q=json.loads(read('terminal.json'));fixture=json.loads(read('fixture.json'))
    obj=gzip.decompress(read(fixture['object_sha256']+'.o.gz'));need(digest(obj)==fixture['object_sha256'] and obj[:8]==bytes.fromhex('cffaedfe0c000001') and struct.unpack_from('<I',obj,12)[0]==1,'wrong original ARM64 object')
    cases={};bodies=set();nonces=set()
    for role,rec in sorted(q.items()):
        body=gzip.decompress(read(rec['whole_macho']+'.macho.gz'));need(digest(body)==rec['whole_macho'] and len(body)==rec['bytes'] and rec['source_object']==fixture['object_sha256'],'wrong captured native program')
        pages=signature(body);bodies.add(rec['whole_macho'])
        need(gzip.decompress(read(role+'-program.out.gz'))==rec['stdout'].encode()==b'29\n' and not gzip.decompress(read(role+'-program.err.gz')) and rec['program_exit']==0,'native direct/response program verdict differs')
        original=json.loads(gzip.decompress(read(role+'-exec.json.gz'))); expanded=list(resolved(original))
        ld,=[e for e in original if e['pid']==rec['signed_linker_pid'] and Path(e['path']).name in ('ld','ld64','ld-classic','ld-prime')]
        matched,=[e for e in expanded if e['pid']==ld['pid'] and e['seq']==ld['seq']]
        need(ld['argv']==rec['exact_raw_args'] and [v for k,v in zip(matched['argv'],matched['argv'][1:]) if k=='-o']==[rec['real_output']] and fixture['object'] in matched['argv'],'physical output or direct object changed')
        p=ld.get('xcode_response');need(bool(p)==(role!='direct'),'wrong enrolled direct/indirect native linker')
        result={'code_pages':pages,'real_ld_pid':ld['pid'],'kernel_events':len(original),'returned_image':digest(body)}
        if p:
            reject=negatives(original);need(reject==rec['real_adversarial_refusals']==16 and p['sha256']==rec['sha256'] and ld['ppid']==rec['actual_parent'] and p['identity'][:2]==rec['held_inode'],'changed physical input or negative controls')
            c=p['held_custody'];nonces.add(p['path']);result.update(physical_response_bytes=len(__import__('base64').b64decode(p['bytes'])),
                physical_events=[next(iter(e['event'])) for e in c['events']],immutable_fd=c['fd']['final_before']==c['fd']['final_after'],refusals=reject)
        cases[role]=result
    need(set(cases)=={'direct','response-1','response-2'} and len(bodies)==1 and len(nonces)==2,'missing identical native calibration outcomes')
    return {'actual':cases,'unchanged_source_object':fixture['object_sha256'],'complete_unique_programs':len(bodies)}
if __name__=='__main__':
    p=Path(sys.argv[1])
    if p.is_dir():out=check(lambda n:(p/n).read_bytes())
    else:
        with ZipFile(p) as z:
            top,=[n.rsplit('/',1)[0] for n in z.namelist() if n.endswith('receipts/terminal.json')]
            out=check(lambda n:z.read(top+'/'+n))
    print(json.dumps(out,sort_keys=True),flush=True)
