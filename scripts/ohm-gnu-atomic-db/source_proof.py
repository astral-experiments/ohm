"""Independently stream every source-built SDK component and both full external Ruff executables."""
import argparse
import contextlib
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from collect import BASE,GH,api,screen
from pairs import CARGO,DRIVERS,REG


@contextlib.contextmanager
def archive(artifact,run,head):
    assert not artifact['expired'] and (artifact['workflow_run']['id'],artifact['workflow_run']['head_sha'])==(run,head)
    with os.fdopen(os.memfd_create('atomic-source-readback'),'w+b') as raw:
        subprocess.run([GH,'api',BASE+'artifacts/'+str(artifact['id'])+'/zip'],stdout=raw,check=True)
        raw.seek(0);assert 'sha256:'+hashlib.file_digest(raw,'sha256').hexdigest()==artifact['digest']
        with zipfile.ZipFile(raw) as z:yield z


@contextlib.contextmanager
def decompressed(z,name,expected=None):
    with os.fdopen(os.memfd_create('atomic-source-component'),'w+b') as packed:
        with z.open(name) as f:shutil.copyfileobj(f,packed,2**20)
        packed.seek(0);compression=hashlib.file_digest(packed,'sha256').hexdigest()
        if expected is not None:assert compression==expected
        packed.seek(0)
        with subprocess.Popen(['zstd','-qdc'],stdin=packed,stdout=subprocess.PIPE) as p:
            yield p.stdout
            assert not any(p.stdout.read()) and p.wait()==0


def members(z,expected,run,head):
    assert set(z.namelist())=={'source.json','sdk.tar.zst'}
    proof=json.loads(z.read('source.json'))
    assert (proof['run'],proof['head'],proof['source'],proof['tree'],proof['members'])==(
        run,head,REG['source']['parent']['source'],REG['source']['parent']['tree'],119)
    assert z.getinfo('sdk.tar.zst').file_size==proof['bytes']
    result={}
    with decompressed(z,'sdk.tar.zst',proof['archive_sha256']) as stream:
        with tarfile.open(fileobj=stream,mode='r|') as tf:
            for member in tf:
                n=member.name
                assert n in expected and n not in result and member.isfile()
                with tf.extractfile(member) as f:result[n]=[hashlib.file_digest(f,'sha256').hexdigest(),member.size,member.mode]
    assert result==expected and len(result)==119
    return proof


def image(data):
    assert data[:7]==b'\x7fELF\x02\x01\x01' and struct.unpack_from('<H',data,18)[0]==183
    offset=struct.unpack_from('<Q',data,32)[0];size,n=struct.unpack_from('<HH',data,54)
    assert size==56 and n>0
    sha=lambda b:hashlib.sha256(b).hexdigest()
    segments=[]
    for i in range(n):
        kind,flags,start,vaddr,paddr,length,mem,align=struct.unpack_from('<IIQQQQQQ',data,offset+i*size)
        part=data[start:start+length];assert len(part)==length
        segments.append({'type':kind,'flags':flags,'vaddr':vaddr,'offset':start,'bytes':length,'memsz':mem,'sha256':sha(part)})
    return {'elf':sha(data),'bytes':len(data),'segments':segments}


def main(run,head,out):
    r=api('runs/'+str(run))
    assert (r['head_branch'],r['event'],r['head_sha'],r['status'],r['conclusion'])==('charlie/qa-gnu-atomic-ruff-db','workflow_dispatch',head,'completed','success')
    jobs=api('runs/'+str(run)+'/jobs?per_page=100')['jobs']
    assert {j['name'] for j in jobs if j['conclusion']!='skipped'}=={'compile','source-cargo','source-parent','source-qualification (P)','source-qualification (C)'}
    assert all(j['conclusion'] in ('success','skipped') for j in jobs)
    a=api('runs/'+str(run)+'/artifacts?per_page=100')['artifacts'];arts={x['name']:x for x in a}
    assert len(a)==8 and set(arts)=={'gnu-atomic-bootstrap-manifests','gnu-atomic-registered-compiler','gnu-atomic-source-cargo',
       'gnu-atomic-source-builder-records','gnu-atomic-source-parent-sdk','gnu-atomic-source-parent-records','gnu-atomic-source-library-P','gnu-atomic-source-library-C'}
    results={'run':run,'head':head,'artifacts':{n:[v['id'],v['digest']] for n,v in arts.items()},'roles':{}}
    sdk_path=HERE.parent/'ohm-aarch64-portable-review/source/sdk-members.json'
    base=json.loads(sdk_path.read_bytes() if sdk_path.exists() else subprocess.check_output(
        ['git','show','HEAD:scripts/ohm-aarch64-portable-review/source/sdk-members.json'],cwd=HERE))
    parent=base['common']|{base['driver_path']:[DRIVERS['P'],142753096,493]}
    child=base['common']|{base['driver_path']:[DRIVERS['C'],142781688,493]}
    with archive(arts['gnu-atomic-registered-compiler'],run,head) as z:
        product=json.loads(z.read('atomic-candidate.json'))
        assert product['source']==REG['source']['candidate']['source'] and product['tree']==REG['source']['candidate']['tree']
        assert product['parent_driver']==parent[base['driver_path']] and product['driver']==child[base['driver_path']]
        with decompressed(z,'driver.zst',product['compression']) as raw:
            assert hashlib.file_digest(raw,'sha256').hexdigest()==DRIVERS['C']
        results['candidate']=product
    with archive(arts['gnu-atomic-source-parent-sdk'],run,head) as z:results['parent_kit']=members(z,parent,run,head)
    with archive(arts['gnu-atomic-source-cargo'],run,head) as z:
        cargo=json.loads(z.read('product.json'))
        assert cargo['cargo_sha256']==CARGO and cargo['git']=='c18e91b514b2c4e4966c9ab03232c804af3e1b57'
        with decompressed(z,'cargo.zst') as raw:assert hashlib.file_digest(raw,'sha256').hexdigest()==CARGO
        results['cargo']=cargo
    for role in 'PC':
        name='gnu-atomic-source-library-'+role
        with archive(arts[name],run,head) as z:
            assert json.loads(z.read('atomic-subjects/P-sdk.json'))==parent and json.loads(z.read('atomic-subjects/C-sdk.json'))==child
            result=screen(z,'build',role);states=result['snapshots']
            recorded=json.loads(gzip.decompress((HERE/'evidence'/('build-'+role+'.json.gz')).read_bytes()))['report']['snapshots']
            enroll=json.loads(z.read('atomic-code-witness/source-consumers.json'))
            products={}
            for state,claim in enroll.items():
                assert states[state]['consumer']==recorded[state]['consumer']
                assert (claim['sha256'],claim['bytes'],claim['verdicts'])==(states[state]['consumer']['elf'],states[state]['consumer']['bytes'],states[state]['consumer']['verdicts'])
                if claim['sha256'] not in products:
                    with decompressed(z,'atomic-code-witness/'+claim['sha256']+'.zst',claim['compressed']) as raw:
                        body=raw.read(); info=image(body)
                    assert info['elf']==claim['sha256'] and info['bytes']==claim['bytes'];products[claim['sha256']]=info
            assert len(products)==2 and enroll['edit']==enroll['first-repeat']==enroll['repair']==enroll['clean']
            assert sum(j['type']==1 for j in products[enroll['clean']['sha256']]['segments'])>0
            results['roles'][role]={'full_member_count':len(parent),'physical_consumers':products,'outcomes':enroll,
                   'repeat':{k:states['first-repeat'][k] for k in ['units','full','link_only','links']}}
    assert results['roles']['P']['physical_consumers']==results['roles']['C']['physical_consumers']
    content=json.dumps(results,sort_keys=True,indent=2)+'\n'
    if out.exists():assert out.read_text()==content
    else:out.write_text(content)
    print('Verified every original SDK member, the strict Cargo and both role pairs of complete old/new GNU AArch64 executables.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('run',type=int);parser.add_argument('head');parser.add_argument('out',type=Path)
    cli=parser.parse_args();main(cli.run,cli.head,cli.out)
