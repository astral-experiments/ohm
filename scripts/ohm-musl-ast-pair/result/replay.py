"""Reopen the retained native files, or reproduce their capture from the four official ZIPs."""
import argparse
import gzip
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import native

SOURCES={
    'ordinary-P':(41170783373,13030489513,'a8dbfc087ef6feb9946c40c18936efc887b1fde7c25c967f39505527877e8119'),
    'ordinary-C':(41170783373,13031366705,'93343357758f1b3947b2ce98f9556f2fd13c77945fb31f3f2b60b8c593865009'),
    'native-private':(41173218253,13032126797,'e377f30488a473c0568090db98637fc35b49b4ac3bc042d5af437d458d528e13'),
    'native-shared':(41173218253,13031467472,'49e5991a1c0e4e7e7fe48494b387ef3edb245cf364d3a5bbd4d51e1d014afd61'),
}
REPEATS=('unchanged','second-unchanged')
RIGHT='elif predicates 1, elif/else clauses 2\n'
OLD='elif predicates 2, elif/else clauses 0\n'
sha=native.sha

def json_bytes(doc):return (json.dumps(doc,sort_keys=True,separators=(',',':'))+'\n').encode()

def hold(images,name,b):
    assert re.fullmatch('[a-f0-9]{64}',name) and sha(b)==name
    assert images.setdefault(name,b)==b

def collect(root,b3):
    images={};evidence={'archives':SOURCES,'ordinary':{},'native':{},'depfiles':{},'verdicts':{},'hard_native':{}}
    for key,(run,_,digest) in SOURCES.items():
        p=root/str(run)/(key+'.zip')
        with p.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==digest
        with zipfile.ZipFile(p) as z:
            get=lambda n:json.loads(z.read(n));assert len(z.namelist())==len(set(z.namelist()))
            if key.startswith('native-'):
                r=native.check(z.read,z.namelist(),b3);assert r['visits']=={'mechanism':42,'signed':26,'strict':26}
                assert r['paired_cases']=={'mechanism':21,'signed':13,'strict':13} and r['redecoded_unique_depfiles']==29
                assert len(r['reexecuted_musl_images'])==7 and set(r['prior_v2_before_write'])=={'signed','strict'}
                evidence['native'][key]=r;evidence['verdicts'].update(r['reexecuted_musl_images'])
                for n in z.namelist():
                    if '/cas/' not in n:continue
                    name=Path(n).name;raw=z.read(n)
                    if name.endswith('.elf.gz'):hold(images,name.removesuffix('.elf.gz'),gzip.decompress(raw))
                    else:
                        hold(images,name,raw)
                        if raw.startswith(b'\x01\0\0\0\xff'):
                            d=native.encoded(raw,b3);kind=['encoded',d['LNK1'],d['markers']]
                        else:kind=['raw',None,[s[:-1] for s in raw.decode().splitlines() if s.endswith(':') and s[:-1] in native.MARKS]]
                        assert evidence['depfiles'].setdefault(name,kind)==kind
                continue
            role=key[-1];ordinary=evidence['ordinary'][role]={};origin=get('ordinary/terminal.json');assert origin['role']==role
            for n in z.namelist():
                if n.startswith('images/') and n.endswith('.zst'):
                    hold(images,Path(n).stem,subprocess.run(['zstd','-q','-dc'],input=z.read(n),check=True,capture_output=True).stdout)
            hard={}
            for case,j in get('native/terminal.json').items():
                a,n=j['warm'],j['empty'];v=j['expected'];assert j['valid'] and a['status']==n['status']==(101 if v is None else 0)
                if v is None:assert 'elf' not in a and 'elf' not in n;hard[case]=[101,None,None]
                else:
                    assert a['stdout']==n['stdout']==v and a['elf']==n['elf'];hard[case]=[0,a['elf']['sha256'],v]
            evidence['hard_native'][role]=hard
            for mode in ('build','test'):
                j=get(mode+'/terminal.json');assert j['full_byte_gate_passed'] and all(j['same_entire_elf'].values())
                assert j['independent_edit_behavior']==(mode=='build')
                visits={}
                for phase,v in j['visits'].items():
                    out=j['outputs'].get(phase);visits[phase]={'emitted':v['emitted'],'typed':v['typed'],'fresh':v['typed_fresh'], 'linkers':[x[0] for x in v['link_tools']],'blocks':v['disk']['allocated_bytes_once'],'image':out['client']['sha256'] if out else None,'observed':out['stdout'] if out else None}
                ordinary[mode]={'cmd':j['cmd'],'visits':visits}
            normal={}
            for phase,r in origin['all'].items():
                assert r['cmd']==ordinary['build']['cmd'];o=r.get('observed');normal[phase]=[r['exit'],o['client']['sha256'] if o else None,o['stdout'] if o else None,r['capacity']['all']['allocated_bytes_once']]
            messages=[json.loads(line) for line in gzip.decompress(z.read('ordinary/invalid/stdout.jsonl.gz')).splitlines()]
            assert messages[-1]=={'reason':'build-finished','success':False} and any(m['message'].get('code') and m['message']['code']['code']=='E0425' for m in messages if m['reason']=='compiler-message')
            ordinary['plain']=normal
    return evidence,images

def check(evidence,images,b3):
    assert evidence['archives']=={k:list(v) for k,v in SOURCES.items()} and len(evidence['verdicts'])==7 and len(evidence['depfiles'])==60
    for name,want in evidence['verdicts'].items():native.run_image(images[name],want)
    for name,(kind,link,marks) in evidence['depfiles'].items():
        b=images[name]
        if kind=='encoded':
            d=native.encoded(b,b3);assert (d['LNK1'],d['markers'])==(link,marks)
        else:assert kind=='raw' and link is None and [s[:-1] for s in b.decode().splitlines() if s.endswith(':') and s[:-1] in native.MARKS]==marks
    for n in evidence['native'].values():
        assert n['visits']=={'mechanism':42,'signed':26,'strict':26} and sum(n['paired_cases'].values())==47
        for v in n['prior_v2_before_write'].values():
            name=v['previous_bytes'];assert name in images and evidence['depfiles'][name][1]==native.MARK and v['true_linker'][::2]==['/usr/bin/ld',1]
    with tempfile.TemporaryDirectory() as td:
        def program(tag,args):
            p=Path(td)/tag
            if not p.exists():p.write_bytes(images[tag]);p.chmod(0o700)
            r=subprocess.run([p,*args],cwd=td,env={},check=True,capture_output=True,timeout=25);assert not r.stderr;return r.stdout.decode()
        executed=set()
        for role,ordinary in evidence['ordinary'].items():
            for mode in ('build','test'):
                s=ordinary[mode]['visits'];assert set(s)=={'old','edited','unchanged','second-unchanged','invalid','repair','empty'}
                assert s['invalid']['image'] is None and all(s[n]['image']==s['empty']['image'] for n in ['edited',*REPEATS,'repair'])
                for n in REPEATS:
                    full=[item[0] for item in s[n]['emitted'] if not item[3]];only=[item[0] for item in s[n]['emitted'] if item[3]]
                    assert (sorted(full),only)==((['compact_str','ruff_python_ast','zmij'],[]) if role=='P' else ([], [] if mode=='build' else ['ruff_python_ast']))
                    assert not s[n]['linkers'] if mode=='build' else s[n]['linkers'][-1]=='/usr/bin/ld'
                for n,m in s.items():
                    tag=m['image']
                    if not tag or tag in executed:continue
                    if mode=='build':assert program(tag,[])==m['observed']==(OLD if n=='old' else RIGHT)
                    else:
                        lines=program(tag,['--list']).splitlines();tests=sorted(l.removesuffix(': test') for l in lines if l.endswith(': test'))
                        assert len(tests)==54 and tests==sorted(m['observed'])
                    executed.add(tag)
            p=ordinary['plain']; assert p['invalid'][:3]==[101,None,None] and p['old'][2]==OLD
            assert p['empty'][0]==0 and p['empty'][2]==RIGHT and all(p[n][:3]==p['empty'][:3] for n in ('edit','repeat','repair'))
        assert len(executed)==3 and evidence['hard_native']['P']==evidence['hard_native']['C']
        hard=set()
        for status,tag,want in evidence['hard_native']['C'].values():
            if tag:
                assert status==0 and program(tag,[]).strip()==want;hard.add(tag)
            else:assert status==101
        assert len(hard)==4 and set(images)==executed|hard|set(evidence['verdicts'])|set(evidence['depfiles'])
    print('188 native visits, 94 warm/empty pairs, seven executed guard images, 60 stored file names, four hard-native programs, three Ruff ELFs, 54 named tests')

def pack(evidence,images):
    f=io.BytesIO()
    with tarfile.open(fileobj=f,mode='w',format=tarfile.USTAR_FORMAT) as t:
        for name,b in [('result.json',json_bytes(evidence)),*sorted(images.items())]:
            i=tarfile.TarInfo(name);i.size=len(b);t.addfile(i,io.BytesIO(b))
    return lzma.compress(f.getvalue(),preset=5)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archives',type=Path);p.add_argument('--b3sum',default=shutil.which('b3sum'));a=p.parse_args();assert a.b3sum,'install b3sum or pass --b3sum /path/to/b3sum'
    stored=HERE/'proof.tar.xz';b=stored.read_bytes();assert sha(b)==(HERE/'SHA256SUMS').read_text().split()[0]
    with tarfile.open(fileobj=io.BytesIO(b),mode='r:xz') as t:
        evidence=json.loads(t.extractfile('result.json').read());images={}
        for m in t.getmembers():
            if m.name!='result.json':hold(images,m.name,t.extractfile(m).read())
    check(evidence,images,a.b3sum)
    if a.archives:
        reconstructed,files=collect(a.archives,a.b3sum);assert json_bytes(reconstructed)==json_bytes(evidence) and files==images
        print('reconstructed the retained evidence from four complete original Actions ZIPs')
if __name__=='__main__':main()
