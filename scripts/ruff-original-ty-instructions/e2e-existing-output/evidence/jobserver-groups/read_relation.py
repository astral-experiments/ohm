"""Reconstruct the whole ELF header table from the independently recorded uncovered ranges."""
import base64
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import struct
import sys
import zipfile

def validated_container(x):
    size=x['size'];secs=x['sections'];ranges=[]
    missing=[]
    for left,n,b64 in x['complete_complement']:
        raw=base64.b64decode(b64,validate=True);assert len(raw)==n and 0<=left<size and n<=size-left
        missing.append((left,raw));ranges.append((left,left+n,'gap'))
    def part(off,n):
        matches=[data[off-start:off-start+n]for start,data in missing if start<=off and off+n<=start+len(data)];raw,=matches;return raw
    head=struct.unpack('<16sHHIQQQIHHHHHH',part(0,64));assert head[0][:6]==b'\x7fELF\x02\x01'and head[2]==62 and head[12]==len(secs)and head[11]==64
    for i,sec in enumerate(secs):
        assert sec['index']==i
        row=struct.unpack('<IIQQQQIIQQ',part(head[6]+64*i,64));assert list(row)==sec['header']
        if row[5] and row[1]!=8:
            assert 0<=row[4]<=size and row[5]<=size-row[4] and len(sec['sha256'])==64
            ranges.append((row[4],row[4]+row[5],sec['section']))
        else:assert 'sha256'not in sec
    at=0
    for l,r,_ in sorted(ranges):
        assert l==at and r>l;at=r
    assert at==size and sum(len(x)for _,x in missing)==x['complement_bytes']
    note,=[x for x in secs if x['section']=='.note.gnu.build-id']
    wire=struct.pack('<III',4,32,3)+b'GNU\0'+bytes.fromhex(x['buildid'])
    assert len(wire)==note['header'][5]==48 and hashlib.sha256(wire).hexdigest()==note['sha256'] and x['buildid']==x['zeroed_complete_buildid']
    return head,dict(missing)
def differences(a,b):
    x,ap=validated_container(a);y,bp=validated_container(b)
    header_fields=('sh_name','sh_type','sh_flags','sh_addr','sh_offset','sh_size','sh_link','sh_info','sh_addralign','sh_entsize')
    out={'full_equal':a['sha256']==b['sha256'],'whole': [a['sha256'],b['sha256']],'headers':[],'different_section_payloads':[],
         'old_native_bytes':a['size'],'new_native_bytes':b['size'],'section_count':[len(a['sections']),len(b['sections'])]}
    for left,right in zip(a['sections'],b['sections']):
        if left['index']!=right['index']or left['section']!=right['section']:out['different_section_payloads'].append([left['section'],right['section']]);continue
        name=left['section']
        if left.get('sha256')!=right.get('sha256'):out['different_section_payloads'].append(name)
        for i,(v,w)in enumerate(zip(left['header'],right['header'])):
            if v!=w:out['headers'].append([name,header_fields[i],v,w])
    if set(ap)==set(bp)and all(len(data)==len(bp[k])for k,data in ap.items()):
        out['outside_section_byte_changes']=[[k+i,v,w]for k,block in ap.items()for i,(v,w)in enumerate(zip(block,bp[k]))if v!=w]
    else:out['outside_section_byte_changes']=None
    if out['full_equal']:assert not out['headers']and not out['different_section_payloads']and out['outside_section_byte_changes']==[]
    return out

def read(p,artifact_sha,head,runid):
    with Path(p).open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==artifact_sha
    with zipfile.ZipFile(p)as z:
        assert z.testzip()is None and len(z.namelist())==len(set(z.namelist()))
        raw=lambda n:json.loads(gzip.decompress(z.read(n)))if n.endswith('.gz')else json.loads(z.read(n))
        reg=raw('registration.json');assert reg['head']==head and reg['run']==runid and reg['never_skip']
        assert not any(n.endswith(('.elf.zst','.elf','.so'))or'local-env-'in n for n in z.namelist())
        facts={};current=None
        for tag in ('old','edit','warm1','warm2','capability','corrupt','replace','earlier','four','native-repair','save-repair','final'):
            src=tag+'-source-container.json.gz'
            if src not in z.namelist():continue
            native=raw(src);validated_container(native);inv=raw(tag+'/inventory.json.gz')
            reported=inv['executables'][inv['binary']]['elf'];assert len(inv['executables'])==102 and reported['sha256']==native['sha256'] and reported['bytes']==native['size']
            assert [(s['section'],s['sha256'])for s in native['sections']if 'sha256'in s]==[(r[0],r[-1])for r in reported['sections']if r[-1] and r[1]!=8 and r[3]!=0]
            captures=[n for n in z.namelist()if n.startswith(tag+'-signed-')and n.rsplit('-',2)[-2].isdigit()];ranges=[raw(n)for n in sorted(captures)];receipt={}
            if len(ranges)>1:receipt['stock_repetitions']=differences(ranges[0],ranges[1])
            if ranges:receipt['signed_vs_source']=differences(ranges[-1],native)
            if tag=='edit':current=native
            if current is not None:receipt['vs_ordinary_edited']=differences(current,native)
            facts[tag]={'sha256':native['sha256'],**receipt}
        return {'exact_run':reg,'original_sha256':artifact_sha,'facts':facts,'has_complete_job_receipt':'complete.json'in z.namelist()}
if __name__=='__main__':print(json.dumps(read(*sys.argv[1:]),sort_keys=True,indent=2))
