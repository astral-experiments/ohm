"""Decode each physical ELF and verify its actual GNU build ID with portable BLAKE3."""
from pathlib import Path
import ctypes,hashlib,json,struct,subprocess,tarfile,tempfile
here=Path(__file__).resolve().parent
def sha(b):return hashlib.sha256(b).hexdigest()
def elf(body,blake):
    h=struct.unpack_from('<16sHHIQQQIHHHHHH',body);assert h[0][:6]==b'\x7fELF\x02\x01'and h[2]==62 and h[11]==64
    rows=[struct.unpack_from('<IIQQQQIIQQ',body,h[6]+64*i)for i in range(h[12])]
    t=rows[h[13]];names=body[t[4]:t[4]+t[5]];sections={names[r[0]:].split(b'\0',1)[0].decode():(i,r)for i,r in enumerate(rows)}
    assert len(sections)==h[12];note=sections['.note.gnu.build-id'][1];off=note[4];assert note[5]==48 and struct.unpack_from('<III',body,off)==(4,32,3)and body[off+12:off+16]==b'GNU\0'
    normalized=bytearray(body);normalized[off:off+48]=bytes(48);assert blake(normalized)==body[off+16:off+48]
    ro,r=sections['.rodata'];word=h[6]+64*ro+56;assert int.from_bytes(body[word:word+8],'little')==r[-1]
    loads=[]
    for i in range(h[10]):
        p=struct.unpack_from('<IIQQQQQQ',body,h[5]+h[9]*i)
        if p[0]==1:loads.append((p[2],p[5]))
    assert len(loads)==4
    return off+16,word,len(rows),loads
def pair(bodies,one,two,blake):
    x,y=bodies[one],bodies[two];no,wo,ns,loads=elf(x,blake);assert (no,wo,ns,loads)==elf(y,blake)
    assert len(x)==len(y)and x[wo:wo+8]==bytes(8)and y[wo:wo+8]==bytes([1])+bytes(7)
    assert all(not(o<=wo<o+size)for o,size in loads)
    changes=[i for i,(a,b)in enumerate(zip(x,y))if a!=b];assert set(changes)=={wo}|{i for i in range(no,no+32)if x[i]!=y[i]}
    transformed=bytearray(x);transformed[wo]=1;transformed[no-16:no+32]=bytes(48);digest=blake(transformed)
    transformed[no-16:no]=x[no-16:no];transformed[no:no+32]=digest;assert bytes(transformed)==y
    return dict(threads_one=one,threads_two=two,sections=ns,load_segments=loads,changed_bytes=len(changes),build_id_start=no,sh_entsize_byte=wo)
with tarfile.open(here/'originals.tar.gz','r:gz')as t:
    assert all(m.isfile()and not Path(m.name).is_absolute()and '..'not in Path(m.name).parts for m in t);data={m.name:t.extractfile(m).read()for m in t};assert len(data)==len(t.getmembers())
def j(n):return json.loads(data[n])
with tempfile.TemporaryDirectory()as tmp:
    td=Path(tmp);src=td/'blake3';src.mkdir()
    for n,v in data.items():
        if n.startswith('blake3/')and n.endswith(('.c','.h')):(td/n).write_bytes(v)
    so=td/'hash.so';subprocess.run(['cc','-O2','-fPIC','-shared','-DBLAKE3_NO_AVX512','-DBLAKE3_NO_AVX2','-DBLAKE3_NO_SSE41','-DBLAKE3_NO_SSE2','-DBLAKE3_USE_NEON=0',*(str(p)for p in sorted(src.glob('*.c'))),'-o',str(so)],check=True)
    lib=ctypes.CDLL(str(so))
    def blake(b):
        state=ctypes.create_string_buffer(4096);out=ctypes.create_string_buffer(32);lib.blake3_hasher_init(state)
        lib.blake3_hasher_update(state,(ctypes.c_ubyte*len(b)).from_buffer(b),ctypes.c_size_t(len(b)));lib.blake3_hasher_finalize(state,out,ctypes.c_size_t(32));return out.raw
    bodies={n.split('/')[1]:v for n,v in data.items()if n.startswith('native/')};assert len(bodies)==6 and all(sha(b)==n for n,b in bodies.items())
    histories={};original=j('original-hash-only.json');assert original['rows']['repaired']['elf']=='ef3666e9492eb061214900eee8b45a2d3e7c8756ff9f75e0102f889b6fa42c01'
    for d in ('j1','j2'):
        hist={n.split('/')[1]:j(n)for n in data if n.startswith(d+'/')and n.endswith('/result.json')};assert len(hist)==9
        for name,v in hist.items():
            msgs=[json.loads(l)for l in data[d+'/'+name+'/stdout'].splitlines()if l.startswith(b'{')];assert msgs[-1]['reason']=='build-finished' and msgs[-1]['success']==(v['status']==0)
            if name.startswith('invalid'):
                assert v['status']==101 and 'E0308'in v['errors']and any(m['reason']=='compiler-message'and(m['message'].get('code')or{}).get('code')=='E0308'and any(s['is_primary']and s['file_name'].endswith('/insta-1.48.0/src/settings.rs')for s in m['message']['spans'])for m in msgs)
            else:assert v['status']==0 and v['native']==('snapsh0ts'if name=='edit'else'snapshots')
            assert v['elf']in bodies and v['cmd'][:6]==['cargo','+ohm','build','--locked','--offline','-'+d]
            assert v['src'][:4]==original['same_stat']
        assert len({v['elf']for n,v in hist.items()if n not in ('edit','invalid','invalid-again')})==1
        assert hist['edit']['elf']!=hist['cold-old']['elf'];histories[d]=hist
    assert histories['j1']['cold-old']['elf']==original['rows']['repaired']['elf']and histories['j2']['cold-old']['elf']==original['rows']['old']['elf']
    result={n:pair(bodies,histories['j1'][n]['elf'],histories['j2'][n]['elf'],blake)for n in ('cold-old','edit')}
    fg=j('fixed/result.json');assert sha(data['fixed/operands.json'])==fg['inputs']and sha(data['fixed/run-with'])==fg['run_with']
    assert len(fg['rows'])==11 and all(r['status']==0 and r['native']=='snapshots'for r in fg['rows'])
    one,={r['elf']for r in fg['rows']if r['threads']==1};two,={r['elf']for r in fg['rows']if r['threads']>1}
    result['fixed-ld-argv']=pair(bodies,one,two,blake);print(json.dumps(result,indent=2,sort_keys=True))
