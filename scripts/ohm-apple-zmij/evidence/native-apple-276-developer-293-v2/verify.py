"""Reopen the native corpus in memory. Requires Python 3.11 or newer and zstd."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import struct
import sys
import tarfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'readback'))
from ast_archive import examine
from counts import census
from returned import macho_text,suite_verdicts
import reopen_cgu
from study import digest,need
EXPECTED_ZIP='b8ae4985fd2a05c381505e616f4ce3b76d98556672b30f55ce3eb3e450756a87'

def source(path):return json.loads(path.read_bytes())

class Pack:
    def __init__(self):
        custody=source(HERE/'custody.json');stored=HERE/'native-outputs.tar.zst'
        with stored.open('rb') as f:need(hashlib.file_digest(f,'sha256').hexdigest()==custody['packet_sha256'] and stored.stat().st_size==custody['packet_bytes'],'packet digest or size changed')
        self.blobs={};manifest=None
        with subprocess.Popen(['zstd','-q','-dc',str(stored)],stdout=subprocess.PIPE) as p:
            with tarfile.open(fileobj=p.stdout,mode='r|') as t:
                for m in t:
                    need(m.isreg() and m.size<25*2**20,'foreign packed entry')
                    body=t.extractfile(m).read()
                    if m.name=='manifest.json':
                        need(manifest is None and digest(body)==custody['member_manifest_sha256'],'repeated or modified original-member inventory')
                        manifest=json.loads(body)
                    else:
                        need(m.name=='b/'+digest(body) and m.name[2:] not in self.blobs,'repeated or changed decoded original member')
                        self.blobs[m.name[2:]]=body
            need(p.wait()==0,'zstd failed')
        self.rows=manifest['rows'];need(manifest['raw_archive']['digest']=='sha256:'+EXPECTED_ZIP and manifest['raw_archive']['id']==12989739951,'wrong Actions original')
        need({v[0] for v in self.rows.values()}==set(self.blobs) and len(self.rows)==custody['selected_original_members'],'unowned or omitted raw member')
        need(sum(v[1] for v in self.rows.values())==custody['decoded_bytes'] and all(len(self.blobs[h])==size and len(raw)==64 and original>0
             for h,size,raw,original in self.rows.values() if size),'incorrect decoded-byte census')
    def namelist(self):return set(self.rows)
    def decoded(self,n):return self.blobs[self.rows[n][0]]
    def read(self,n):return gzip.compress(self.decoded(n),compresslevel=1,mtime=0) if n.endswith('.gz') else self.decoded(n)
    def json(self,n):return json.loads(self.decoded(n))

class Body:
    def __init__(self,data):self.data=data
    def read_bytes(self):return self.data

def verify_metadata_section(p,observations):
    from archive_differences import named_members
    def meta(key):
        raw=p.decoded('ast-rlib/'+key+'.rlib.gz')
        b,=[body for name,_,body,_ in named_members(raw) if name=='lib.rmeta']
        need(b[:8]==bytes.fromhex('cffaedfe0c000001') and struct.unpack_from('<I',b,12)[0]==1,'not an Apple ARM64 crate metadata object')
        pos=32;sections=[]
        for _ in range(struct.unpack_from('<I',b,16)[0]):
            cmd,size=struct.unpack_from('<II',b,pos)
            if cmd==25:
                for k in range(struct.unpack_from('<I',b,pos+64)[0]):
                    row=pos+72+80*k;sect,seg,_,length,offset=struct.unpack_from('<16s16sQQI',b,row)
                    sections.append((seg.rstrip(bytes([0])),sect.rstrip(bytes([0])),offset,length))
            pos+=size
        need(len(sections)==1 and sections[0][:2]==(b'__DWARF',b'.rmeta'),'unexpected native metadata sections')
        _,_,at,length=sections[0];need(0<at<at+length<=len(b),'corrupt Rust metadata section')
        return b[:at],b[at:at+length],b[at+length:]
    for ids,entry in observations['original_full_ar_member_changes'].items():
        left,right=map(meta,ids.split('/'))
        need(left[0]==right[0] and left[2]==right[2] and left[1]!=right[1] and len(left[1])==len(right[1]),'variation outside the opaque Rust metadata section')
        need(not entry['changed_native_members'] and not entry['changed_headers'] and not entry['changed_names'] and set(entry['changed_special_members'])=={'lib.rmeta'},'other original archive contents changed')

def validate(p):
    registration=p.json('ast-registration.json')
    need(registration['rust']=={'P':'2035696c5316079f5b2e4373aee834839aac97e9','C':'444c0273a2e2bc0b161e988d43c882349bc2d7a6'} and
         registration['cargo']=='735e1528ed741015c57676dccf05dbdc0ff7bed1','wrong Rust or Cargo')
    observations=census(p);need(observations==source(HERE/'observations.json'),'independent native counts, A/A references or raw member census disagree')
    verify_metadata_section(p,observations)
    pp=p.json('provider-matrix/terminal.json');need(pp['passed'] and pp['commands']==392 and not any(pp['wrong_or_image_mismatch'].values()),'wrong provider terminal')
    reopen_cgu.packed=lambda z,n:z.decoded(n)
    def complete(z,key):
        b=z.decoded('test-executables/'+key+'.macho.gz');need(digest(b)==key,'different whole native test executable');return b
    reopen_cgu.program=complete
    proofs={};archives={};valid={'build':0,'test':0};bad={'build':0,'test':0};retained_test=0
    for verb in ('build','test'):
        for idx in (1,2):
            for role in 'PC':
                parent=f'ast-{verb}-structural/pair-{idx:02}/{role}'
                visits=(('empty-old',['clean-old' if verb=='build' else 'clean']),('empty-new',['clean-new' if verb=='build' else 'clean']),
                        ('actual',['cold','edit','repeat-1','repeat-2','invalid','repair']))
                for group,phases in visits:
                    known={}
                    for phase in phases:
                        d=parent+'/'+group+'/'+phase
                        q=p.json(d+'/verified.json');native=p.json(d+'/exec.json.gz');cache=p.json(d+'/local-incremental.json');events=cache['emitters']
                        for e in events:
                            [ev]=[x for x in native if x['pid']==e['pid'] and x['path']==e['compiler']]
                            argv=ev['argv'];need(e['incremental'] and any(v=='incremental='+e['incremental'][0] or v=='-Cincremental='+e['incremental'][0] for v in argv),'ordinary incremental real rustc missing')
                            need(('--test'in argv)==(verb=='test') and argv[argv.index('--crate-name')+1]=='ruff_python_ast','wrong physical AST root')
                        stdout=p.decoded(d+'/stdout.gz');cargo=[json.loads(l) for l in stdout.splitlines()];ok=q['state']!='invalid'
                        need(cargo[-1]=={'reason':'build-finished','success':ok},'typed Cargo terminal')
                        if not ok:
                            need(any((m.get('message',{}).get('code') or {}).get('code')=='E0425' for m in cargo),'invalid source returned wrong diagnostic')
                            bad[verb]+=1;continue
                        valid[verb]+=1
                        owned=cache['cache']['files']
                        need(any(Path(f[0]).name=='work-products.bin' and f[3]>0 for f in owned) and any(Path(f[0]).name=='dep-graph.bin' and f[3]>0 for f in owned),'missing actual incremental generation')
                        if verb=='build':
                            ref=q['reader'];h=ref['archive_sha256'];disk=p.json(d+'/ast-archive-work-products.json');physical={Path(f[0]).stem:(f[3],f[5]) for f in owned if f[0].endswith('.o') and str(Path(f[0]).parent)==disk['session']}
                            raw=p.decoded('ast-rlib/'+h+'.rlib.gz')
                            if h not in archives:archives[h]=examine(raw)[1]
                            proof=archives[h];need(proof==disk['proof'] and digest(raw)==h and proof['objects'].keys()==physical.keys() and all(physical[k]==(o['size'],o['sha256']) for k,o in proof['objects'].items()),'Ruff rlib not backed by its exact native CGUs')
                            body=p.decoded('clean-readers/'+ref['sha256']+'.macho.gz')
                            need(macho_text(Body(body))=={'raw':ref['sha256'],'text':ref['macho_text']},'actual external library consumer differs')
                        else:
                            t=q['product'];raw=complete(p,t['raw'])
                            need(macho_text(Body(raw))=={'raw':t['raw'],'text':t['text']} and suite_verdicts(p.decoded(d+'/test-suite.gz'),t['tests'])==t['verdicts'] and len(t['tests'])==(54 if q['state']=='new' else 53),'actual full native test suite diverged')
                            if d+'/cgu-proof.json' in p.rows:
                                proof=p.json(d+'/cgu-proof.json');ap=reopen_cgu.verify(p,d);need(ap['raw']==t['raw'] and ap['scope']=='kernel-xcode-ld+rustc-recipe','foreign native Test execution')
                                owners=p.json(d+'/ast-test-object-owners.json')['root_object_to_cache']
                                for obj in proof['nonce_objects']:
                                    trace=owners[obj['cgu']];m=proof['physical'][obj['path']];need(trace[1:]==[m['bytes'],m['sha256']] and any(f[0]==trace[0] and [f[3],f[5]]==trace[1:] for f in owned),'actual compiler CGU and linked object mismatch')
                                proofs[d]=ap;known[t['raw']]=proof
                            else:
                                proof=known[t['raw']];prior=p.json(d+'/prior-test-link.json')
                                need(prior=={'raw':t['raw'],'observed_recipe':proof['recipe'],'observed_argv':proof['linker_argv']},'linkless return has no earlier physical linker in its own installation')
                                retained_test+=1
                            need(q['test_debug']=={key:proof[key] for key in ('output','modules','same_path_image')},'signed debug equivalence is not physically bound')
    need(valid=={'build':28,'test':28} and bad=={'build':4,'test':4} and len(proofs)==20 and len(archives)==10 and retained_test==8,'missing source states')
    print('Verified 64 actual Cargo invocations, 10 complete AST libraries, 20 physical signed test links, eight same-installation no-link returns, 28 complete suite executions, and four invalid-source outcomes per verb.')
    print('The original lib test/build admission gates remained closed. No time samples were acquired.')

if __name__=='__main__':validate(Pack())
