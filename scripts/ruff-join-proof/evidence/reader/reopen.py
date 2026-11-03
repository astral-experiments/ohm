"""Reopen original raw checks and execute the retained, independently built fixtures (Linux x86_64)."""
import argparse,hashlib,io,json,os,platform,subprocess,tarfile,tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
def digest(b):return hashlib.sha256(b).hexdigest()
def unpack(p):
    expected=json.loads((p.parent/'registration.json').read_bytes())
    assert digest(p.read_bytes())==expected['zstd_sha256'] and p.stat().st_size==expected['bytes']
    data=subprocess.check_output(['zstd','-dc',p]);assert digest(data)==expected['tar_sha256']
    bodies={}
    with tarfile.open(fileobj=io.BytesIO(data))as f:
        for m in f:
            assert m.isfile()and m.name.rsplit('/',1)[-1]==m.name and m.name not in bodies
            b=f.extractfile(m).read();assert digest(b)==m.name;bodies[m.name]=b
    return expected,bodies
def decode(b):
    d=io.BytesIO(b)
    def read(n):v=d.read(n);assert len(v)==n;return v
    def number(n):return int.from_bytes(read(n),'little')
    def string():return read(number(4)).decode()
    assert read(5)==bytes.fromhex('01000000ff');v=number(1);n=number(4);rows=[]
    for _ in range(n):
        ty=number(1);path=string();flag=number(1);assert ty in(0,1)and flag in(0,1)
        rows.append([ty,path,[number(8),string()]if flag else None])
    assert number(4)==0 and d.read()==b''
    return [v,rows]
def verify(blake3,packet=HERE):
    reg,raw=unpack(packet/'originals.tar.zst');idx=reg['index'];rows={}
    for value,claim in [('11ff865d',reg['old_payload_blake3']),('1dff865d',reg['new_payload_blake3'])]:
        actual=subprocess.check_output([blake3],input=bytes.fromhex(value)).split()[0].decode()
        assert actual==claim
    for case,labels in idx.items():
        rows[case]={}
        for label,sha in labels['phases'].items():
            row=json.loads(raw[sha]);assert row['phase']==label
            out=[json.loads(x) for x in raw[row['stdout']].splitlines()];log=raw[row['stderr']];trace=raw[row['exec']].decode()
            errors=[x['message']['code']['code']for x in out if x.get('reason')=='compiler-message' and x['message'].get('code')]
            success=out[-1]=={'reason':'build-finished','success':True};assert row['rc']==(0 if success else 101) and errors==([]if success else['E0308'])and errors==row['errors']
            actual=sum('"--crate-name", "consumed_input"'in l and '/bin/rustc",'in l and ' = 0'in l for l in trace.splitlines())
            assert actual==row['physical_rustc'] and row['min_avail']>=8*2**30
            fresh=[x['fresh']for x in out if x.get('reason')=='compiler-artifact'and x['target']['name']=='consumed-input'];assert fresh==row['fresh']==([]if not success else[actual==0])
            if errors: assert all(s.isascii()for s in errors)
            rows[case][label]=row
        if 'saved' in labels:
            m=json.loads(raw[labels['saved']]);vv,files=decode(raw[m['fp']]);assert [vv,files]==m['encoded']
            sums=[(v[0],v[1])if v else None for _,n,v in files if n.endswith('payload.bin')]
            lines=[l for l in raw[m['raw']].decode().splitlines()if l.startswith('# checksum:')and l.endswith('payload.bin')]
            assert lines==m['raw_rows']
            if case=='upgrade':
                assert vv==4 and sums==[(4,'blake3='+reg['new_payload_blake3'])]
            elif case=='fixed-c1':
                assert vv==5 and set(sums)=={(4,'blake3='+k)for k in(reg['old_payload_blake3'],reg['new_payload_blake3'])}
            else: assert vv==5 and sums and set(sums)=={None} and lines==[]
            if case!='fixed-c2':
                assert [x.split(' file_len:')[0]for x in lines]==['# checksum:blake3='+k for k in(reg['old_payload_blake3'],reg['new_payload_blake3'])]
                assert [x.split(' ')[-1]for x in lines]==['src/payload.bin','src/./payload.bin']
    assert set(rows)=={'upgrade','fixed-c1','fixed-c2','positive-c1','positive-c2'}
    oldu,newu=rows['upgrade']['poison-unchanged'],rows['upgrade']['first-after-upgrade']
    assert oldu['cargo']==reg['prior_cargo'] and newu['cargo']==reg['reader_cargo']
    assert (oldu['rc'],oldu['physical_rustc'],newu['rc'],newu['physical_rustc'])==(0,0,101,1) and oldu['mtime_ns']==newu['mtime_ns']
    for case in ('upgrade','fixed-c1','fixed-c2'):
        x=rows[case];assert x['during-save']['before']=='11ff865d' and x['during-save']['after']=='1dff865d'
        if case!='upgrade': assert x['first-unchanged']['rc']==x['independent-empty']['rc']==101 and x['first-unchanged']['mtime_ns']==x['during-save']['mtime_ns']
        a,b=x['native-repair'],x['native-empty'];assert a['elf_sha']==b['elf_sha'] and a['verdict']==b['verdict']=='29 29'
        with tempfile.TemporaryDirectory()as t:
            elf=Path(t)/'native';elf.write_bytes(raw[a['elf_sha']]);elf.chmod(0o700)
            assert subprocess.check_output([elf],text=True)=='29 29\n'
        assert x['repair-settled']['physical_rustc']==0
    for role in ('positive-c1','positive-c2'):
        assert rows[role]['ordinary']['physical_rustc']==1 and rows[role]['ordinary-unchanged']['physical_rustc']==0
    allrows=[x for s in rows.values()for x in s.values()]
    counts={'commands':len(allrows),'physical_consumer_rustcs':sum(x['physical_rustc']for x in allrows),'cases':{k:len(v)for k,v in rows.items()},'actual_ELF_pairs_reopened':3,'v4_poisoned_upgrade':'E0308 on first check'}
    assert counts['commands']==26 and counts['physical_consumer_rustcs']==20
    print(json.dumps(counts,sort_keys=True))
if __name__=='__main__':
    assert platform.system()=='Linux'and platform.machine()=='x86_64'
    parser=argparse.ArgumentParser();parser.add_argument('--b3sum',default='b3sum')
    parser.add_argument('--packet',type=Path,default=HERE)
    args=parser.parse_args();verify(args.b3sum,args.packet)
