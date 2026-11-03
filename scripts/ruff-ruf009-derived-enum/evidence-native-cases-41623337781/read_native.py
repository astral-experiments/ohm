"""Reopen unscored ELF bodies plus native input and compiler observations from a hosted acquisition."""
import ast
from collections import Counter
import gzip
import hashlib
import json
import mmap
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile


def digest(path):
    with path.open('rb') as src:
        return hashlib.file_digest(src,'sha256').hexdigest()


def elf(path):
    with path.open('rb') as fp,mmap.mmap(fp.fileno(),0,access=mmap.ACCESS_READ) as data:
        eh=struct.unpack_from('<16sHHIQQQIHHHHHH',data)
        assert eh[0][:6]==b'\x7fELF\x02\x01' and eh[2]==62 and eh[9]==56 and eh[11]==64
        sh=[struct.unpack_from('<IIQQQQIIQQ',data,eh[6]+i*64)for i in range(eh[12])]
        ns=sh[eh[13]][4]
        sections={data[ns+v[0]:data.find(b'\0',ns+v[0])].decode(): {'sha256':hashlib.sha256(memoryview(data)[v[4]:v[4]+v[5]]).hexdigest()if v[1]!=8 else None,'header':list(v)}for v in sh}
        note=sections['.note.gnu.build-id']['header']
        n,d,t=struct.unpack_from('<III',data,note[4]);assert n==4 and t==3 and data[note[4]+12:note[4]+16]==b'GNU\0'
        off=note[4]+16;loads=[]
        for i in range(eh[10]):
            ph=struct.unpack_from('<IIQQQQQQ',data,eh[5]+i*56)
            if ph[0]!=1:continue
            start,size=ph[2],ph[5];end=start+size;raw=hashlib.sha256(memoryview(data)[start:end]).hexdigest();normalized=raw
            if start<=off and off+d<=end:
                key=hashlib.sha256(memoryview(data)[start:off]);key.update(bytes(d));key.update(memoryview(data)[off+d:end]);normalized=key.hexdigest()
            loads.append({'program':list(ph),'sha256':raw,'without_build_id':normalized})
        return {'size':len(data),'sections':sections,'loads':loads,'build_id':data[off:off+d].hex()}


def compare(a,b):
    names=sorted(a['sections'].keys()|b['sections'].keys());fields=['name','type','flags','addr','offset','size','link','info','addralign','entsize']
    mismatch={};payload=[]
    for k in names:
        x=a['sections'].get(k);y=b['sections'].get(k)
        if x is None or y is None:mismatch[k]={'absent':'reference'if x is None else 'comparison'};continue
        changed={f:[u,v]for f,u,v in zip(fields,x['header'],y['header'])if u!=v}
        if x['sha256']!=y['sha256']:changed['sha256']=[x['sha256'],y['sha256']];payload.append(k)
        if changed:mismatch[k]=changed
    return {'size':[a['size'],b['size']],'changed_payloads':payload,'changed_headers_and_bodies':mismatch,'loadable_except_id_equal':[x['without_build_id']for x in a['loads']]==[x['without_build_id']for x in b['loads']]}


def products(z,name):
    return {(row[0],row[1],tuple(row[2]),p.rsplit('/',1)[1]):(sha,size) for row in json.loads(gzip.decompress(z.read(name)))for p,sha,size in row[-1]}


def main(archive, expected, objects=None):
    assert digest(archive)==expected
    with zipfile.ZipFile(archive)as z,tempfile.TemporaryDirectory()as t:
        folder=Path(t);obj=lambda n:json.loads(z.read(n));worker=obj('worker.json');stages={};bodies={};phases={};kernel={};relations={};deprows={}
        assert worker['phase']=='native-gate' and worker['block']==0 and worker['order']=='CP'
        for n in z.namelist():
            if not n.endswith('/snapshot.json') or n.split('/')[0]not in ('P','C'):continue
            r,phase,_=n.split('/');record=obj(n);h=record['sha256'];state=record['state'];key=f'{r}/{phase}';delta=[]
            for name,(old,new)in {'attr-field':(1,0),'attr-attributes':(0,1),'both-clean':(0,0),'both-warn':(1,1)}.items():
                row=obj(key+'/runtime-'+name+'.json');expected_code=old if state=='buggy'else new
                assert row['elf']==h and not row['stderr'] and row['code']==expected_code
                assert [m['code']for m in json.loads(row['stdout'])]==['RUF009']*expected_code;delta.append(row['code'])
            if h not in bodies:
                if objects is None:
                    save=folder/(h+'.zst')
                    with z.open('members/'+h+'.elf.zst') as src,save.open('xb') as dest:shutil.copyfileobj(src,dest)
                    output=folder/h
                    with output.open('xb') as dest:subprocess.run(['zstd','-qc','-d',save],stdout=dest,check=True)
                else:
                    output=objects/h
                assert digest(output)==h and output.stat().st_size==record['bytes'];bodies[h]=elf(output)
            ck=obj(key+'/native-sections.json');assert ck['elf']==h and ck['sections']==bodies[h]['sections'] and ck['build_id']==bodies[h]['build_id']
            stages[key]=h;phases[key]={'state':state,'true_empty':record['true_empty'],'external_nonfresh':record['external_nonfresh'],'exits':delta}
            pn=key+'/native-inputs/';deprows[key]={}
            for dep in ('portable_atomic','salsa'):
                raw=z.read(pn+dep+'/rustc.d');trans=z.read(pn+dep+'/cargo.bin')
                deprows[key][dep]=[len(raw),hashlib.sha256(raw).hexdigest(),len(trans),hashlib.sha256(trans).hexdigest(),raw.count(b'/dev/null/ohm-untracked-relink-inputs')]
            rawkey=key+'-kernel/kernel.json'
            if rawkey in z.namelist():
                k=obj(rawkey);roster=[]
                for process in k['rustcs']:
                    log=gzip.decompress(z.read(key+'-kernel/trace.'+str(process['pid'])+'.gz')).decode()
                    assert all(v in log for v in process['maps'])and any('PROT_EXEC'in v for v in process['maps'])
                    assert process['driver']==obj(r+'/sdk.json')['driver']
                    assert process['crate']==process['argv'][process['argv'].index('--crate-name')+1]
                    hits=[]
                    for line in log.splitlines():
                        if not line.startswith('execve("')or not line.endswith(') = 0'):continue
                        path,arg=line[8:].split('", [',1);args,_=json.JSONDecoder().raw_decode('['+arg)
                        if path==process['exe']and args==process['argv']:hits.append(args)
                    assert len(hits)==1;roster.append(process['crate'])
                kernel[key]=roster
        for key,h in stages.items():
            r,stage=key.split('/');reference=f"{r}/fully-empty-"+phases[key]['state']
            if reference not in stages:continue
            h2=stages[reference]
            if h==h2:continue
            A=products(z,key+'/artifacts.json.gz');B=products(z,reference+'/artifacts.json.gz')
            changed=[k for k in A.keys()|B.keys()if A.get(k)!=B.get(k)]
            relations[key+' vs '+reference]={'elf':compare(bodies[h],bodies[h2]),'different_artifact_count':len(changed),'artifact_roster':[[list(k[:2]),list(k[2]),k[3],A.get(k),B.get(k)]for k in sorted(changed)]}
        for state in ('buggy','fixed'):
            names=[r+'/fully-empty-'+state for r in ('P','C')]
            if all(v in stages for v in names)and stages[names[0]]!=stages[names[1]]:relations[' cross '.join(names)]={'elf':compare(*(bodies[stages[v]]for v in names))}
        summary=obj('native-verdict.json')if 'native-verdict.json'in z.namelist()else {}
        invalid={}
        for r in ('P','C'):
            key=r+'/invalid/stdout'
            if key not in z.namelist():continue
            msgs=[json.loads(l)for l in z.read(key).splitlines()];err=[x['message']for x in msgs if x['reason']=='compiler-message'and x['message']['level']=='error']
            assert len(err)==1 and err[0]['code']['code']=='E0308'and any(s['is_primary']and 'OHM_INVALID_CHECK_SENTINEL'in str(s['text'])for s in err[0]['spans'])
            invalid[r]=err[0]['code']['code']
        return dict(archive_sha256=expected,worker=worker,native_stages=stages,typed=phases,native_distinct=len(bodies),sections=bodies,raw_owners=kernel,dep_info=deprows,comparisons=relations,invalid=invalid,declared=summary.get('pass'),acquisition_errors=summary.get('errors',[]),refusals=summary.get('refusals',[]))


if __name__=='__main__':
    result=main(Path(sys.argv[1]),sys.argv[2]);Path(sys.argv[3]).write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print({k:len(result[k])for k in ('native_stages','sections','raw_owners','comparisons','invalid')},result['declared'])
