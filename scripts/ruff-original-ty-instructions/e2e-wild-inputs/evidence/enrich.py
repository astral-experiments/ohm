"""Verify complete independently clean ELF bodies, typed temp-object symbol and all Wild positives."""
import collections,gzip,hashlib,json,os,struct,sys,zipfile
from pathlib import Path
import zstandard
sys.path.insert(0,str(Path(__file__).resolve().parent))
from reopen import OLD,NEW,LIBS,sha,read,doc,digest
ROOT=Path(__file__).resolve().parent
def symtab(data):
    assert data[:7]==b'\x7fELF\x02\x01\x01'and struct.unpack_from('<HH',data,16)==(1,62)
    shoff,=struct.unpack_from('<Q',data,40);entsize,n,strings=struct.unpack_from('<HHH',data,58)
    assert entsize==64 and n>0 and strings<n
    sections=[struct.unpack_from('<IIQQQQIIQQ',data,shoff+entsize*i)for i in range(n)]
    def body(s):
        off,sz=s[4:6];assert off+sz<=len(data);return data[off:off+sz]
    def word(s,offset):return s[offset:s.index(b'\x00',offset)].decode()
    names=body(sections[strings]);sym,=[s for s in sections if s[1]==2]
    string=sections[sym[6]];assert string[1]==3 and word(names,string[0])=='.strtab'and sym[9]==24
    out=[]
    for idx,row in enumerate(struct.iter_unpack('<IBBHQQ',body(sym))):
        name,info,other,section,value,size=row;out.append({'i':idx,'name':word(body(string),name),'name_file_offset':string[4]+name,'bind':info>>4,'type':info&15,'visibility':other&3,'section':section,'value':value,'size':size})
    return out
def enrich(zpath,original):
    inp=ROOT/'verified.json';r=json.loads(inp.read_bytes());res={'qa':r['run'],'base_reader_sha256':digest(inp)}
    assert digest(zpath)=='f77b1c66e8f1b45a6cec697c95aeca74409bed9dc2801f217eacd2ac9310c344'
    assert digest(original)=='2ab6618f9f643f0c2ef9c192192c3b4955fe02f378432c8c28f01f8f8718f677'
    with zipfile.ZipFile(original)as old:
        states={}
        for k in old.namelist():
            if k.endswith('/inventory.json.gz'):
                t=doc(old,k);path=t['binary'];states[k]=t['executables'][path]['elf']['sha256']
        assert states['independent-NEW/inventory.json.gz']==NEW and states['ordinary-old/inventory.json.gz']==OLD
        bodies={}
        for sh in (NEW,OLD):
            key=sh+'.elf.zst';n=0;h=hashlib.sha256()
            with old.open(key)as f,zstandard.ZstdDecompressor().stream_reader(f)as dec:
                while b:=dec.read(2**20):n+=len(b);h.update(b)
            assert h.hexdigest()==sh;bodies[key]={'bytes':n,'sha256':sh}
        res['independent_41617756983']={'digest':digest(original),'states':states,'full_reopened_elfs':bodies}
    with zipfile.ZipFile(zpath)as z:
        basis=read(z,'native-capture/symbols.o');changed=read(z,'native-capture/four-byte-symbols.o')
        oldrows=symtab(basis);newrows=symtab(changed);assert len(oldrows)==len(newrows)
        (o,c),=[pair for pair in zip(oldrows,newrows)if pair[0]!=pair[1]]
        assert {**o,'name':'zzQA'}==c and o['name']=='main'and (o['bind'],o['type'],o['section'])==(1,0,0) and o['name_file_offset']==8731
        res['elf_symbol']={'stock':o,'four_byte':c,'symbols':len(oldrows),'source_digest':sha(basis),'mutated_digest':sha(changed)}
        q=r['kernel']['syscall-observer'];dep=read(z,'stock-depfile-trace/stock.d').decode();trace=read(z,'stock-depfile-trace/stdout').decode().splitlines()
        positives=dep.splitlines()[0].split(': ',1)[1].split();assert set(positives)==set(trace)and len(positives)==len(trace)==409
        pkeys=collections.defaultdict(list)
        for path in q['opened_paths']:pkeys[os.path.normpath(path)].append(path)
        opened=q['opened_realpaths'];maps=set(q['mmap_paths']);got={};roles=collections.Counter()
        for p in positives:
            paths=pkeys[os.path.normpath(p)];targets=sorted({x for v in paths for x in opened[v]});mm=sorted(set(targets)&maps)
            got[p]={'opened_as':paths,'mapped_as':mm};roles[bool(paths),bool(mm)]+=1
        assert roles=={(True,True):409},[(p,row)for p,row in got.items()if not row['mapped_as']][:5]
        direct={n for t in q['winners'].values()for n in [t['winner']]}
        explicit=set(doc(z,'native-capture/all-literal-inputs.json.gz'))
        added=[p for p in positives if os.path.normpath(p)not in {os.path.normpath(v)for v in explicit|direct}]
        nested=[e for e in q['nested_script_path_probes']if e['result'].startswith('-1')]
        assert len(nested)==8 and all(x['path']not in set(positives)|set(trace)for x in nested)
        res['stock_positives']={'stock_depfile_and_trace':len(positives),'opened_and_file_mapped':409,'actual_kernel_join':got,'positive_names_beyond_literal_or_seven_library_winners':added,'unreported_nested_misses':nested}
    out=ROOT/'all-inputs.json';out.write_text(json.dumps(res,sort_keys=True,indent=2)+'\n');print(digest(out))
if __name__=='__main__':enrich(Path(sys.argv[1]),Path(sys.argv[2]))
