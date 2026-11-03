"""Byte and decoded-DWARF checks on the actual executables before admitting a paired count."""
from pathlib import Path
import collections,contextlib,hashlib,itertools,json,os,shutil,struct,subprocess as sp
tool='/usr/bin/llvm-dwarfdump-18'
def table(b):
    off=struct.unpack_from('<Q',b,40)[0];size,num,strings=struct.unpack_from('<3H',b,58)
    headers=[struct.unpack_from('<2I4Q2I2Q',b,off+i*size)for i in range(num)]
    names=b[headers[strings][4]:headers[strings][4]+headers[strings][5]]
    return {names[h[0]:names.index(0,h[0])].decode():(h[4],h[5],h[1]) for h in headers[1:]}
def section_parity(root,report,kind):
    files=[(root/(r+'-'+kind)).read_bytes()for r in 'PC'];tab=[table(f) for f in files]
    assert tab[0]==tab[1];changed=[]
    i=0
    for name,(o,n,t) in sorted(tab[0].items(),key=lambda item:item[1][0]):
        if t==8 or not n:continue
        assert i<=o and files[0][i:o]==files[1][i:o],('gap',i,o)
        if files[0][o:o+n]!=files[1][o:o+n]:changed.append(name)
        i=o+n
    assert files[0][i:]==files[1][i:]
    assert set(changed)<={'.note.gnu.build-id','.debug_info','.debug_str','.debug_macro'}
    o,n,_=tab[0]['.note.gnu.build-id']
    ids=[v[o+16:o+n].hex()for v in files]
    assert all(v[o:o+16]==struct.pack('<III',4,32,3)+b'GNU\0'for v in files)
    o,n,_=tab[0]['.debug_str'];co=[report['roles'][r]['cohort'].encode() for r in 'PC']
    for v,r,c in zip(files,'PC',co):
        path=report['roles'][r]['native_build'].encode()
        assert v.count(c)==1 and v[o:o+n].count(path+b'\0')==1 and c in path
    vals=[collections.Counter(v[o:o+n].replace(c,b'v2-' + b'0'*16).split(b'\0'))for v,c in zip(files,co)]
    distinct=[sum((vals[i]-vals[1-i]).values()) for i in range(2)]
    return {'entire_remainder_identical':True,'sections':changed,'string_inventory_differences':distinct,'note_ids':ids}
def dump(root,report,kind,what):
    sums=[];nlines=[];first=None
    with contextlib.ExitStack() as cs:
        for r in 'PC':
            f=root/(r+'-'+kind);err=cs.enter_context((root/(f.name+'-'+what+'.stderr')).open('wb'))
            proc=cs.enter_context(sp.Popen([tool,'--'+what,str(f)],stdout=sp.PIPE,stderr=err))
            sums.append((r,f,proc,hashlib.sha256(),0))
        count=0;different=0
        for pair in itertools.zip_longest(*(x[2].stdout for x in sums)):
            norm=[]
            for raw,(r,f,proc,h,n) in zip(pair,sums):
                assert raw is not None;co=report['roles'][r]['cohort'].encode()
                if count==0:
                    assert raw.startswith(str(f).encode()+b':');raw=raw.replace(str(f).encode(),b'<ELF>',1)
                norm.append(raw.replace(co,b'<TOOLCHAIN-DIRECTORY>'));h.update(norm[-1])
            if norm[0]!=norm[1]:
                if first is None:first=[x[:500].decode(errors='replace')for x in norm]
                different+=1
            count+=1
        for r,f,proc,h,_ in sums:
            assert proc.wait()==0 and (root/(f.name+'-'+what+'.stderr')).stat().st_size==0
    return {'lines':count,'different_lines':different,'first':first,'normalized_hashes':[x[3].hexdigest() for x in sums]}

def admit(proof,root,histories,pair,probe):
    root.mkdir()
    cache={}
    def save(name,j):
        (proof/name).write_text(json.dumps(j,indent=2,sort_keys=True)+'\n')
    for role in 'PC':
        hist=histories[role];hold=json.loads((proof/(role+'-holdouts.json')).read_bytes())
        assert hold['source']['failed']and hold['native']['failed']
        import re
        cohort,=re.findall(r'v2-[a-f0-9]{16}',hold['shadow_directory'])
        cache[role]={'cohort':cohort,'native_build':str(Path(hold['shadow_directory']).parent)}
        for kind in ('old','settled'):
            row=hist[kind]['binary'];assert row['sha256']==hist[kind]['elf']
            dest=root/(role+'-'+kind);src=proof/row['zstd']
            with dest.open('xb')as f:sp.run(['zstd','-dqc',src],stdout=f,check=True)
            with dest.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==row['sha256']
            assert dest.stat().st_size==row['bytes'];dest.chmod(0o755)
            assert probe(dest)==hist[kind]['probes']
        assert hist['census']['wild_execs']==1
    assert len(histories['P']['census']['typed_execs'])==18
    assert histories['C']['census']['typed_execs']==['ruff','ty_python_semantic']
    for field in ('rmeta','rlib'):
        keys={r['owners']['portable_atomic'][field]for h in histories.values()for r in h.values()}
        assert len(keys)==1,(field,keys)
    report={'roles':cache};audit={}
    for k in ('old','settled'):
        res=section_parity(root,report,k);assert res['string_inventory_differences']==[0,0]
        for what,minimum in [('debug-info',1_000_000),('debug-macro',10_000)]:
            res[what]=dump(root,report,k,what)
            assert res[what]['lines']>minimum and res[what]['different_lines']==0,res[what]
        audit[k]=res
    save('decoded-binaries.json',audit)
    rows={phase:[histories[r][phase]['instructions']for r in 'PC']for phase in ('edit','settled','sample-0','sample-1','sample-2')}
    assert all(2*rows[k][1]<=rows[k][0]for k in ('settled','sample-0','sample-1','sample-2')),rows
    save('accepted-pair.json',{'pair':pair,'counts':rows,'typed':{r:histories[r]['census']['typed_execs']for r in 'PC'},'wild':{r:histories[r]['census']['wild_execs']for r in 'PC'}})
