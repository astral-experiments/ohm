"""Reopen the complete mismatching Ruff rlibs and compare every object, metadata and GNU ar table."""
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/'ohm-aarch64-linux')]
from collect import BASE,GH,api
import qualify


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_members(data):
    assert data.startswith(b'!<arch>\n')
    pos=8;table=b'';result={}
    while pos<len(data):
        hdr=data[pos:pos+60]
        assert len(hdr)==60 and hdr[58:]==b'`\n'
        size=int(hdr[48:58]);body=data[pos+60:pos+60+size];name=hdr[:16].rstrip()
        if name==b'//':table=body
        elif name.startswith(b'/') and name[1:].isdigit():
            offset=int(name[1:]);name=table[offset:table.index(b'/\n',offset)]
        elif name!=b'/':name=name.removesuffix(b'/')
        name=name.decode('ascii')
        assert name not in result and len(body)==size
        result[name]=body;pos+=60+size+size%2
    assert pos==len(data)
    return result


def differences(a,b):
    spans=[];changes=0;start=None
    for i,(x,y) in enumerate(zip(a,b)):
        if x!=y:
            changes+=1
            if start is None:start=i
        elif start is not None:
            spans.append((start,i));start=None
    if start is not None:spans.append((start,min(len(a),len(b))))
    if len(a)!=len(b):spans.append((min(len(a),len(b)),max(len(a),len(b))));changes+=abs(len(a)-len(b))
    return {'sizes':[len(a),len(b)],'digests':[sha(a),sha(b)],'changed_bytes':changes,
            'runs':len(spans),'span_lengths':dict(sorted(collections.Counter(y-x for x,y in spans).items()))}


def capture():
    evidence=HERE/'evidence';sources=json.loads((evidence/'sources.json').read_text())
    totals={};all_objects={}
    for role in 'PC':
        source=sources['build-'+role];id_=source['artifact'];origin=api('artifacts/'+str(id_))
        assert (origin['workflow_run']['id'],origin['workflow_run']['head_sha'])==(source['run'],source['head'])
        assert origin['digest']=='sha256:'+source['digest'] and not origin['expired']
        recorded=json.loads(gzip.decompress((evidence/('build-'+role+'.json.gz')).read_bytes()))['report']['snapshots']
        with os.fdopen(os.memfd_create('ruff-db-real-rlib'),'w+b') as archive:
            subprocess.run([GH,'api',BASE+f'artifacts/{id_}/zip'],stdout=archive,check=True)
            archive.seek(0);assert hashlib.file_digest(archive,'sha256').hexdigest()==source['digest']
            with zipfile.ZipFile(archive) as z:
                out={};extra={}
                for state in ('edit','first-repeat','second-repeat','repair','clean'):
                    path='observed-ruff-db/receipts/clean-comparison/'+state+'.zst'
                    packed=z.read(path)
                    data=subprocess.check_output(['zstd','-qdc'],input=packed)
                    complete=qualify.archive(data)
                    assert complete==recorded[state]['archive'] and complete['raw']==recorded[state]['sha256']
                    physical=read_members(data)
                    canonical={k:(sz,h) for k,name,sz,h in complete['objects']}
                    assert len(canonical)==216 and all(len(physical[n])==size and sha(physical[n])==h for _,n,size,h in complete['objects'])
                    assert all_objects.setdefault(state,canonical)==canonical
                    extra[state]={name:body for name,body in physical.items() if not name.endswith('.o')}
                    assert set(extra[state])=={'/','//','lib.rmeta','lib.rmeta-link'}
                    out[state]={'raw':sha(data),'bytes':len(data),'compressed_sha256':sha(packed),'members':len(physical),
                                'physical_object_hashes':sha(json.dumps(canonical,sort_keys=True).encode())}
                for state in ('edit','first-repeat','second-repeat','repair'):
                    assert all_objects[state]==all_objects['clean']
                    out[state]['non_object_vs_clean']={n:differences(data,extra['clean'][n]) for n,data in extra[state].items()}
                    normalize=lambda b:re.sub(rb'\.[0-9a-z]{7}(?=\.rcgu\.o)',b'.SESSION',b)
                    for n in ('//','lib.rmeta-link'):
                        out[state]['non_object_vs_clean'][n]['equal_after_removing_session_names']=normalize(extra[state][n])==normalize(extra['clean'][n])
                totals[role]={'archive':id_,'zip_sha256':source['digest'],'products':out}
    answer={'all_216_object_bodies_match_in_all_ten_archives':True,'roles':totals}
    saved=evidence/'library-archive-readback.json';text=json.dumps(answer,indent=2,sort_keys=True)+'\n'
    if saved.exists():assert saved.read_text()==text
    else:saved.write_text(text)
    print('Reopened and matched 216 objects in each of ten complete AArch64 rlibs.')


if __name__=='__main__':capture()
