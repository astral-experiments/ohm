"""Check the two original Cargo phase inventories, raw ELF files and dep-info."""
import argparse
import ctypes
import hashlib
import json
import re
import subprocess
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--packet',required=True,type=Path)
p.add_argument('--llvm',required=True,type=Path,help='signed Rust LLVM exposing llvm_blake3_hasher_*')
p.add_argument('--output',required=True,type=Path)
args=p.parse_args()
sha=lambda b:hashlib.sha256(b).hexdigest()
blob={};manifest=None
z=subprocess.Popen(['zstd','-q','-dc',args.packet],stdout=subprocess.PIPE)
with tarfile.open(fileobj=z.stdout,mode='r|') as t:
    for entry in t:
        assert entry.isfile() and 0<=entry.size<=16*2**20
        b=t.extractfile(entry).read()
        if entry.name=='manifest.json':
            assert manifest is None
            manifest=json.loads(b)
        else:
            key=sha(b)
            assert entry.name=='blobs/'+key and key not in blob
            blob[key]=b
assert z.wait()==0
assert {'41593423160','41597635908'}==set(manifest)
origins={'41593423160':(13211506211,'d7153c048a0d42aea3ef43b461b66bcc1ca7c491cffeb95c393ca893e5311b5f'),
         '41597635908':(13212967273,'232eef164c9273cf8e475c69d253f74c80d8fd3912e898060ab71168d60bbace')}
lib=ctypes.CDLL(str(args.llvm.resolve()))
def blake(data):
    state=ctypes.create_string_buffer(8192);out=ctypes.create_string_buffer(32)
    lib.llvm_blake3_hasher_init(state);lib.llvm_blake3_hasher_update(state,data,ctypes.c_size_t(len(data)))
    lib.llvm_blake3_hasher_finalize(state,out,ctypes.c_size_t(32))
    return out.raw.hex()
assert blake(b'')=='af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262'
def fnv(data):
    h=14695981039346656037
    for byte in data:h=(h^byte)*1099511628211 & ((1<<64)-1)
    return h
out={};scope={};elf={}
for run,j in manifest.items():
    src=j['source'];assert (src['id'],src['digest'][7:])==origins[run]
    files=j['members'];assert set(files.values())<=blob.keys()
    def read(path):return blob[files[path]]
    def js(path):return json.loads(read(path))
    commands=owners=0;cases={};native=set()
    def phase(prefix,proof):
        global commands,owners
        path=prefix+'/'
        assert js(path+'proof.json')==proof
        events=js(path+'exec-index.json')
        captured={}
        for name in files:
            if not name.startswith(path+'exec.'):continue
            for l in read(name).decode().splitlines():
                m=re.search(r'^execve\("[^"]*/rustc",.*?"--crate-name", "(selected_producer|selected_client)",',l)
                if m and l.endswith(' = 0'):captured.setdefault(m[1],[]).append(name.rsplit('/',1)[1])
        assert captured==events['rustcs']==proof['rustc_execs']
        owners+=sum(map(len,captured.values()));commands+=1
        assert events['exit']==proof['exit'] and events['minimum_available']>=8*2**30
        messages=[json.loads(l)for l in read(path+'stdout').decode().splitlines()if l.startswith('{')]
        codes=[x['message']['code']['code'] for x in messages if x['reason']=='compiler-message' and x['message']['level']=='error' and x['message'].get('code')]
        assert codes==proof['errors']
        artifact,=[x for x in messages if x['reason']=='compiler-artifact' and x['target']['name']=='selected_producer']
        assert any(f==proof['metadata_path'] or (f.endswith('.rlib') and str(Path(f).with_suffix('.rmeta'))==proof['metadata_path']) for f in artifact['filenames'])
        data=read(path+'actual.rmeta'); assert sha(data)==proof['rmeta'] and fnv(data)==proof['fnv'] and len(data)==proof['bytes']
        literal=read(path+'literal-input.rmeta') if path+'literal-input.rmeta' in files else data
        assert sha(literal)==proof.get('explicit_sha',proof['rmeta']) and fnv(literal)==proof.get('explicit_fnv',proof['fnv'])
        hdr=read(path+'root.txt').decode()
        assert re.search(r'private hash (\w{32}) stable_crate_id',hdr)[1]==proof['private']
        assert re.search(r'public_hash (\w{32})',hdr)[1]==proof['public']
        records=set()
        for name in files:
            if not name.startswith(path+'raw-') or not name.endswith('.d'):continue
            dep=read(name).decode()
            for digest,length,field in re.findall(r'^# checksum:blake3=(\w{64}) file_len:(\d+) (.+)$',dep,re.M):
                if field.endswith('/selected.rmeta') or field==proof['metadata_path']:
                    records.add((digest,int(length)))
        if proof.get('elf'):
            key=proof['elf'];body=read('bodies/'+key);assert sha(body)==key
            if key not in elf:
                with tempfile.TemporaryDirectory()as tmp:
                    exe=Path(tmp)/'probe';exe.write_bytes(body);exe.chmod(0o700)
                    elf[key]=int(subprocess.check_output([exe],env={'PATH':'/usr/bin:/bin'},cwd=tmp,timeout=5))
            assert elf[key]==proof['native'];native.add(key)
            assert elf[key]==(0 if prefix.endswith('/discover') else fnv(literal))
        return {'exit':proof['exit'],'diagnostics':codes,'rustcs':sorted(captured),'rmeta':sha(data),'literal':sha(literal),'blake':blake(literal),'bytes':len(literal),'records':sorted(records),'mtime_ns':proof.get('metadata_mtime_ns'),'public':proof['public'],'private':proof['private']}
    for arm,edits in js('completed.json').items():
        for edit,modes in edits.items():
            for mode,rec in modes.items():
                prefix='/'.join((arm,edit,mode))
                rs={k:phase(prefix+'/'+k,r) for k,r in rec.items()}
                old,changed,nxt,clean=[rs[k] for k in ('old','edit','next-unchanged','independent-clean')]
                assert old['rmeta']!=changed['rmeta']==clean['rmeta'] and rs['repair']['rmeta']==old['rmeta']
                if arm in ('shipped','fixed'):assert old['public']==changed['public']
                if edit=='macro_bytes':assert old['private']==changed['private']
                if edit=='private-same-mtime':assert rec['old']['source_mtime_ns']==rec['edit']['source_mtime_ns']
                if arm in ('shipped','fixed'):assert old['records']==[(old['blake'],old['bytes'])]
                if mode=='check':
                    assert nxt['diagnostics']==clean['diagnostics']==['E0308'] and rs['repair']['exit']==0
                    if arm=='shipped':
                        assert changed['exit']==0 and changed['rustcs']==['selected_producer'] and changed['records']==old['records']
                    else:assert changed['diagnostics']==['E0308'] and changed['rustcs']==['selected_client','selected_producer']
                else:assert rec['edit']['elf']==rec['independent-clean']['elf']
                cases[prefix]=rs
    if 'no-checksum-results.json' in files:
        assert js('no-checksum-failures.json')=={}
        for arm,rec in js('no-checksum-results.json').items():
            rs={k:phase('no-checksums/'+arm+'/'+k,r)for k,r in rec.items()}
            old,v,nxt,clean=(rs[k]for k in('old','edit','next-unchanged','independent-clean'))
            assert old['rmeta']!=v['rmeta']==nxt['rmeta']
            if not arm.startswith('upstream'):assert old['public']==v['public']
            assert clean['diagnostics']==['E0308'] and clean['rustcs']==['selected_client','selected_producer']
            if arm.startswith('fixed'):assert old['records']==[(old['blake'],old['bytes'])]
            else:assert old['records']==[]
            if arm.startswith('stock')or arm=='upgrade':
                assert v['exit']==nxt['exit']==0 and 'selected_client'not in v['rustcs'] and nxt['rustcs']==[]
                assert old['mtime_ns']==v['mtime_ns']
            else:
                assert v['diagnostics']==nxt['diagnostics']==['E0308'] and 'selected_client' in v['rustcs']
            if arm.endswith('-split'):
                assert rs['producer-only']['rustcs']==['selected_producer']and 'selected_producer'not in v['rustcs']
            if arm.endswith('registry-build'):assert '/registry/private-artifacts/'in rec['edit']['metadata_path']
            if arm=='upgrade':
                fixed=rs['fixed-first-unchanged']
                assert fixed['diagnostics']==['E0308'] and 'selected_client'in fixed['rustcs']
                assert fixed['literal']==v['literal']==clean['literal']
                assert [(rec['edit'][x],rec['next-unchanged'][x],rec['fixed-first-unchanged'][x],rec['independent-clean'][x]) for x in ('explicit_target','lexical_include','source_sha','client_source_sha')]==[(rec['edit'][x],)*4 for x in ('explicit_target','lexical_include','source_sha','client_source_sha')]
            else:assert rs['repair']['exit']==0 and v['rmeta']==clean['rmeta']
            cases['no-checksums/'+arm]=rs
        suites=[]
        for k in ('0','1','2'):
            assert js('cargo-tests-'+k+'.json')['rc']==0
            suites.append(int(re.search(rb'test result: ok\. (\d+) passed; 0 failed',read('cargo-tests-'+k+'.stdout'))[1]))
        assert suites==[15,1,1]
    out[run]={'asset':src['id'],'commands':commands,'typed_rustcs':owners,'unique_native_bodies_run':len(native),'histories':len(cases),'cases':cases}
    scope[run]=[commands,owners,len(native),len(cases)]
args.output.write_text(json.dumps({'physical':out,'native_bodies':elf},indent=2,sort_keys=True)+'\n')
print(json.dumps(scope),sha(args.output.read_bytes()))
