"""Full cross-option ELF readback and field-wise dissection of the separately refused seed."""
import argparse,hashlib,importlib.util,json,mmap,os,shutil,struct,subprocess,tempfile,zipfile
from pathlib import Path

def source(path):
    s=importlib.util.spec_from_file_location('registered_elf_gate',path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def strings_and_consumers(data,g):
    sections,_,bid=g.image(data);body=lambda n: data[sections[n][4]:sections[n][4]+sections[n][5]]
    b=body('.strtab');symbols=body('.symtab');names={}
    for i,rec in enumerate(struct.iter_unpack('<IBBHQQ',symbols)):
        start=rec[0];end=b.index(b'\0',start);names.setdefault(start,[]).append((i,*rec[1:]))
    assert len(symbols)%24==0 and len(b)>0 and b[-1]==0
    return sections,b,bid,names

def strtab(a,b,g):
    with a.open('rb')as fa,b.open('rb')as fb,mmap.mmap(fa.fileno(),0,access=mmap.ACCESS_READ)as x,mmap.mmap(fb.fileno(),0,access=mmap.ACCESS_READ)as y:
        S,X,I,ref=strings_and_consumers(x,g);T,Y,J,refs=strings_and_consumers(y,g)
        assert len(x)==len(y) and S==T and I==J and ref==refs and len(X)==len(Y)
        jobs=[];diffs=0;start=0
        for old,new in zip(X.split(b'\0'),Y.split(b'\0'),strict=True):
            assert len(old)==len(new)
            if old!=new:
                offsets=[i for i,(u,v)in enumerate(zip(old,new))if u!=v];diffs+=len(offsets)
                suffixes=[[key-start,val] for key,val in ref.items() if start<=key<=start+len(old)]
                jobs.append({'start':start,'previous':old.decode(),'current':new.decode(),'affected_bytes':[start+i for i in offsets],'symbols':suffixes})
            start+=len(old)+1
        off=S['.strtab'][4];length=S['.strtab'][5];spans=[(off,off+length),(I,I+32)];cursor=0;h=hashlib.sha256()
        for lo,hi in sorted(spans)+[(len(x),len(x))]:
            assert memoryview(x)[cursor:lo]==memoryview(y)[cursor:lo]
            h.update(memoryview(x)[cursor:lo]);cursor=hi
        return {'length':len(x),'changed_strings':jobs,'changed_symbol_table_bytes':diffs,'unchanged_outside_strtab_and_id':h.hexdigest(),'build_ids':[g.wild_note(obj,I) for obj in (x,y)]}

def main():
    p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('digest');p.add_argument('elf_gate',type=Path);p.add_argument('output',type=Path);p.add_argument('--objects',type=Path);a=p.parse_args();g=source(a.elf_gate.resolve())
    with a.archive.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==a.digest
    r={'sha':a.digest,'native_owners':{},'seed_vs_cold':{},'cold_cross_role':{}}
    with tempfile.TemporaryDirectory()as d,zipfile.ZipFile(a.archive)as z:
        d=a.objects if a.objects is not None else Path(d);records={}
        for role in ('P','C'):
            for name in ('seed-buggy','fully-empty-buggy','fully-empty-fixed'):
                rec=json.loads(z.read(role+'/'+name+'/snapshot.json'));digest=rec['sha256'];records[role,name]=rec
                dest=d/digest
                if not dest.exists():
                    assert a.objects is None
                    compressed=d/(digest+'.zst')
                    with z.open('members/'+digest+'.elf.zst')as src,compressed.open('xb')as out:shutil.copyfileobj(src,out)
                    with dest.open('xb')as out:subprocess.run(['zstd','-qdc',compressed],stdout=out,check=True)
                    with dest.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==digest
            get=lambda n:d/records[role,n]['sha256'];r['seed_vs_cold'][role]=strtab(get('seed-buggy'),get('fully-empty-buggy'),g)
        # Save the completed seed-oracle separately before the external DWARF decode.
        a.output.with_suffix('.strtab.json').write_text(json.dumps(r['seed_vs_cold'],sort_keys=True,indent=2)+'\n')
        for n in ('fully-empty-buggy','fully-empty-fixed'):
            P,C=[records[role,n]for role in ('P','C')]
            previous=Path.cwd()
            try:
                os.chdir(d)
                r['cold_cross_role'][n]=g.compare(Path(P['sha256']),Path(C['sha256']),P['native_out_dir'],C['native_out_dir'])
            finally:
                os.chdir(previous)
            a.output.with_suffix('.'+n+'.json').write_text(json.dumps(r['cold_cross_role'][n],sort_keys=True,indent=2)+'\n')
    a.output.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n')

if __name__=='__main__':main()
