"""Check actual Cargo/strace, physical rmeta payloads, and the binary fingerprint records. No build."""
import argparse,gzip,hashlib,json,os,re,struct,subprocess
from pathlib import Path

def read(p):return json.loads(p.read_bytes())
def h(blob):return hashlib.sha256(blob).hexdigest()
def decode_fingerprint(b, epoch):
    assert epoch in (4,5) and b[:6]==bytes.fromhex('01000000ff')+bytes([epoch]);off=6
    def take(n):
        nonlocal off
        data=b[off:off+n];assert len(data)==n;off+=n;return data
    def u(n):return int.from_bytes(take(n),'little')
    items={}
    for _ in range(u(4)):
        kind=u(1);path=take(u(4)).decode();checked=u(1);assert kind in (0,1) and checked==1
        length=u(8);checksum=take(u(4)).decode();assert re.fullmatch('blake3=[0-9a-f]{64}',checksum)
        assert path not in items;items[path]={'bytes':length,'blake3':checksum[7:]}
    assert u(4)==0 and off==len(b);return items

def fnv(b):
    x=14695981039346656037
    for c in b:x=((x^c)*1099511628211)%(1<<64)
    return x
def all_records(root, b3, mode):
    plan=read(root/'registration.json')
    epoch={'f7cfe387ec3bd7e2e367d80596f379349faa23530194bf7cd7ba80a33adc6dee':4, '0617e34321cf33fcce38904d066f0d4981b79f752896d37b97d1aed1fbddc48f':5, '1d4c93cd725a06b9a31704dc05a67a5d418c4cf97a3d3680ce8fb522ccee404f':4}[plan['actual_native_cargo']]
    n=0;kcount=0;out={};source={}
    for role in plan['roles']:
        out[role]={};source[role]={}
        for history in plan['histories']:
            source[role][history]={}; d=root/'out'/role/history;first=None;actual=None;old=None;old_file=None
            client=(d/'registered-app.rs').read_bytes()
            for stage in plan['phases']:
                s=d/stage;rows=[json.loads(x)for x in (s/'stdout').read_bytes().splitlines()];ex=0 if rows[-1]=={'reason':'build-finished','success':True} else 101
                if ex:assert rows[-1]=={'reason':'build-finished','success':False}
                checked=read(s/'result.json');assert checked['exit']==ex
                e=[r['message'] for r in rows if r.get('reason')=='compiler-message' and r['message']['level']=='error']
                if ex:
                    assert len(e)==1 and e[0]['code']['code']=='E0308'
                    span,=[v for v in e[0]['spans'] if v['is_primary']]
                    assert span['file_name']=='app/src/main.rs'and'byte_hash(ACTUAL_INPUT)'in span['text'][0]['text']
                else:assert not e
                a,=[r for r in rows if r.get('reason')=='compiler-artifact' and r['target']['name']=='dep']
                f,=[z for z in a['filenames']if z.endswith('.rmeta')];assert f==checked['meta']['path']
                assert bool(plan['registry_outputs'])==str(f).startswith(str(root/'cargo-home/registry/private-capability')+'/')
                inventory=read(s/'files.json');data={}
                for name,row in inventory.items():
                    p=root/'out/blobs'/row['sha256'];v=p.read_bytes()
                    assert h(v)==row['sha256'] and len(v)==row['bytes']
                    data[name]=v
                native_bytes,=[v for name,v in data.items()if name.endswith('/'+Path(f).name)]
                physical=h(native_bytes);observed=fnv(native_bytes)
                b3got=subprocess.run([b3,'--no-names'],input=native_bytes,stdout=subprocess.PIPE,check=True).stdout.decode().strip()
                assert (checked['meta']['sha256'],checked['blake3'],checked['fnv'])==(physical,b3got,observed)
                rt=(s/'root-output.txt').read_text()
                private=re.search(r'^private hash ([0-9a-f]{32}) stable_crate_id',rt,re.M)[1];pub=re.search(r'^public_hash ([0-9a-f]{32})$',rt,re.M)[1]
                assert (private,pub)==(checked['private'],checked['public'])
                assert native_bytes.count(bytes.fromhex(private)[::-1]+bytes.fromhex(pub)[::-1])==1
                kernel=[];probes=0
                if history=='kernel':
                    decoder=json.JSONDecoder()
                    attached={r['pid']:r for r in read(s/'kernel.json')}
                    for x in s.glob('trace.*.gz'):
                        event=gzip.decompress(x.read_bytes()).decode();maps=re.findall(r'^mmap\(.*PROT_EXEC.*<([^>]*?/librustc_driver-[^<>]*?\.so)>.* = 0x[\da-f]+$',event,re.M)
                        for line in event.splitlines():
                            if (line.startswith('execve(') and line.endswith(' = 0') and json.dumps(plan["option"]) in line and '"--print=sysroot"' in line):
                                image, at=decoder.raw_decode(line[7:]);argv,_=decoder.raw_decode(line[7+at:].lstrip(', '))
                                if image.endswith('/bin/rustc'):
                                    assert maps and argv[1:]==[plan["option"],'--print=sysroot']
                                    probes+=1
                            if not line.startswith('execve(')or not line.endswith(' = 0')or'"--crate-name"'not in line or '"--emit=dep-info,metadata"'not in line:continue
                            image,i=decoder.raw_decode(line[7:]);argv,_=decoder.raw_decode(line[7+i:].lstrip(', '))
                            if image.endswith('/proxies/rustc'):continue
                            assert maps and image.endswith('/bin/rustc')
                            pid=int(x.name.split('.')[1]);sealed=attached.pop(pid)
                            assert sealed['argv']==argv and sealed['driver']==plan['driver'][role] and sealed['mappings'] and all(m in event for m in sealed['mappings'])
                            crate=argv[argv.index('--crate-name')+1];assert crate in ('dep','app')
                            assert (plan["option"]in argv)==(mode=='aware'and role=='C'and crate=='dep')
                            if crate=='app':assert '--extern'in argv and 'dep='+f in argv
                            kernel.append(crate)
                    assert not attached and sorted(kernel)==checked['kernel'];kcount+=len(kernel)
                    assert probes==int(mode=='aware'),(role,stage,probes)
                if stage=='discover':
                    old={'length':len(native_bytes),'fnv':observed,'blake3':b3got,'sha256':physical,'public':pub,'path':f}
                    assert f.encode() in client and str(observed).encode()+b'u64' in client
                else:assert f==old['path']
                saved=None
                if stage in ('old-literal','old-unchanged','first-edited','next-unchanged'):
                    text,=[v for name,v in data.items()if name.endswith('.d')and '/app/'in name];assert f.encode() in text
                    name,=[name for name in data if name.endswith('/fingerprint/dep-bin-app')];raw=data[name]
                    saved=decode_fingerprint(raw,epoch)[f];assert saved=={'bytes':old['length'],'blake3':old['blake3']}
                    if stage=='old-literal':old_file=inventory[name]
                    if stage=='first-edited' and role=='C' and ex==0:
                        assert saved['blake3']!=b3got and saved['bytes']!=len(native_bytes)
                        assert inventory[name]==old_file
                if stage in ('first-edited','next-unchanged','independent-empty-edited'):
                    assert observed!=old['fnv'] and b3got!=old['blake3'] and physical!=old['sha256']
                    assert (pub==old['public'])==(role=='C' and mode=='aware')
                    if stage=='first-edited':first=ex;actual=physical
                    else:assert ex==101 and physical==actual
                else:assert ex==0 and physical==old['sha256']
                source[role][history][stage]={'exit':ex,'rmeta':physical,'public':pub,'bytes':len(native_bytes),'blake3':b3got,'fnv1a64':observed,'physical_rustcs':sorted(kernel)if history=='kernel'else None,'physical_capability_probes':probes if history=='kernel'else None,'cargo_nonfresh':sorted(r['target']['name']for r in rows if r.get('reason')=='compiler-artifact' and not r['fresh']),'saved_rmeta_blake3':saved['blake3']if saved else None}
                n+=1
            assert first==101
        for st in plan['phases']:
            u=source[role]['ordinary'][st];t=source[role]['kernel'][st]
            assert {k:v for k,v in u.items()if k not in ('physical_rustcs','physical_capability_probes')}=={k:v for k,v in t.items()if k not in ('physical_rustcs','physical_capability_probes')}
        r=source[role]['kernel'];expected=['app','dep']
        assert r['first-edited']['physical_rustcs']==expected and r['old-unchanged']['physical_rustcs']==[] and r['next-unchanged']['physical_rustcs']==['app'] and r['independent-empty-edited']['physical_rustcs']==['app','dep']and r['repaired-unchanged']['physical_rustcs']==[]
        out[role]=r
    return {'report':'First-check source-matched derived-enum / literal metadata dependency','outcome':mode,'commands':n,'binary_fingerprint_epoch':epoch,'kernel_typed_rustcs':kcount,'terminal_sha256':h((root/'out/terminal.json').read_bytes()),'registration_sha256':h((root/'registration.json').read_bytes()),'roles':out}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--b3sum',required=True);ap.add_argument('--expect',choices=('legacy','aware'),required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    result=all_records(a.root,a.b3sum,a.expect);a.output.write_text(json.dumps(result,sort_keys=True,indent=1)+'\n')
    print(result['outcome'],result['commands'],result['kernel_typed_rustcs'],h(a.output.read_bytes()))
