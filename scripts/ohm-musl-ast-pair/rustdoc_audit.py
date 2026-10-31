"""Check the two independently built rustdocs and exercise both with each enrolled driver."""
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess

P_DOC='db2c67930584f89f1fa456065151b814f5988a785cd09deff3643e8783738c23'
C_DOC='85ed5fc3001d3ab2ad692dea4f0e145f550cbff9b90b1abf8dc9b5b6b72d8469'
FILE='compiler/rustc_interface/src/passes.rs'
VIRTUAL_SOURCE='''/// A native documentation and type-check witness.
///
/// ```
/// assert!(cfg!(all(target_arch = "x86_64", target_env = "musl")));
/// assert_eq!(Some(41_u32).map(|v| v + 1), Some(42));
/// ```
pub fn round_trip(v: u32) -> u32 { v + 1 }
#[cfg(all(target_env = "musl", target_arch = "x86_64"))]
/// Present only with this actual musl target.
pub struct MuslOnly;
'''

def sha(data):return hashlib.sha256(data).hexdigest()

def unpack(data):
    assert data[:7]==b'\x7fELF\x02\x01\x01' and struct.unpack_from('<H',data,18)[0]==62
    shoff=struct.unpack_from('<Q',data,40)[0];size,count,idx=struct.unpack_from('<HHH',data,58)
    headers=[struct.unpack_from('<IIQQQQIIQQ',data,shoff+i*size) for i in range(count)]
    assert size==64 and count>20
    def section(head):return data[head[4]:head[4]+head[5]] if head[1]!=8 else b''
    names=section(headers[idx]); table={}
    for hdr in headers[1:]:
        label=names[hdr[0]:names.index(0,hdr[0])].decode();assert label not in table
        table[label]=(hdr,section(hdr))
    return table

def audit(old,new,source_line):
    assert (sha(old),sha(new),len(old),len(new))==(P_DOC,C_DOC,14705112,14705416)
    a,b=unpack(old),unpack(new);assert a.keys()==b.keys()
    changed={n for n in a if a[n][1]!=b[n][1]};assert changed=={'.note.gnu.build-id','.data.rel.ro','.symtab','.strtab'},changed
    for n in a:
        p,c=a[n][0],b[n][0]
        if p[2]&2:assert p==c,n
    for buf in (old,new):assert struct.unpack_from('<HH',buf,54)==struct.unpack_from('<HH',old,54)
    ph=struct.unpack_from('<Q',old,32)[0];assert struct.unpack_from('<Q',new,32)[0]==ph
    length=struct.unpack_from('<H',old,54)[0]*struct.unpack_from('<H',old,56)[0];assert old[ph:ph+length]==new[ph:ph+length]
    note='.note.gnu.build-id';assert a[note][1][:16]==b[note][1][:16]==struct.pack('<III',4,20,3)+b'GNU\0' and len(a[note][1])==len(b[note][1])==36
    norm=lambda n:re.sub(rb'\.llvm\.\d+$',b'.llvm.<local>',n)
    def syms(t):
        st=t['.strtab'][1];out=Counter();names=set()
        for i,info,other,shndx,val,sz in struct.iter_unpack('<IBBHQQ',t['.symtab'][1]):
            name=st[i:st.index(0,i)];names.add(name);out[(norm(name),info,other,shndx,val,sz)]+=1
        return out,names
    sa,na=syms(a);sb,nb=syms(b);assert sa==sb and len(na-nb)==len(nb-na)==374
    assert all(re.search(rb'\.llvm\.\d+$',n) for n in (na-nb)|(nb-na))
    assert Counter(map(norm,a['.strtab'][1].split(b'\0')))==Counter(map(norm,b['.strtab'][1].split(b'\0')))
    section='.data.rel.ro';pa,cb=a[section][1],b[section][1];assert len(pa)==len(cb)
    off=[i for i,(x,y) in enumerate(zip(pa,cb)) if x!=y];assert off==[85648,85672],off
    rows=[]
    for t,role,lines in ((a,'P',[1093,1094]),(b,'C',[1098,1099])):
        reloc={at:(info,add) for at,info,add in struct.iter_unpack('<QQq',t['.rela.dyn'][1])}
        for pos,ln,cl in zip(off,lines,(62,13)):
            addr=t[section][0][3]+pos-16;info,add=reloc[addr];assert info==8
            slen=struct.unpack_from('<Q',t[section][1],pos-8)[0];ro=t['.rodata'];index=add-ro[0][3]
            assert ro[1][index:index+slen]==FILE.encode() and struct.unpack_from('<II',t[section][1],pos)==(ln,cl)
            rows.append([role,hex(addr),hex(add),FILE,ln,cl,source_line(role,ln)])
    assert [r[-1] for r in rows[:2]]==[r[-1] for r in rows[2:]]==['let feed = tcx.create_crate_num(stable_crate_id).unwrap();','assert_eq!(feed.key(), LOCAL_CRATE);']
    return {'independent_rustdocs':[P_DOC,C_DOC],'different_sections':sorted(changed),'all_section_hashes':{n:[sha(a[n][1]),sha(b[n][1])] for n in a},
            'differing_loaded_data_offsets':off,'actual_R_X86_64_RELATIVE_and_locations':rows,'normalized_static_symbols':sum(sa.values()),'changed_private_llvm_names':374,
            'program_headers_identical':True,'identical_dynamic_symbols_import_names_and_relocations':True,'operational_rustdoc_sha256':P_DOC}

def exercise(parent_sdk,rows,driver_name,fresh_driver,fresh_doc,work,raw,target,save):
    rustup=Path(shutil.which('rustup')).resolve(strict=True);work.mkdir();raw.mkdir()
    view=work/'rustup/toolchains/ohm';view.mkdir(parents=True);staged=work/'rustup';shims=work/'proxies';shims.mkdir()
    for n in rows:
        dst=view/n;dst.parent.mkdir(parents=True,exist_ok=True);os.link(parent_sdk/n,dst)
    for n in ('rustup','rustdoc','rustc','cargo'):(shims/n).symlink_to(rustup)
    (work/'home').mkdir();env={'PATH':str(shims)+':/usr/local/bin:/usr/bin:/bin','HOME':str(work/'home'),'RUSTUP_HOME':str(staged),'RUSTUP_AUTO_INSTALL':'0','LC_ALL':'C','TZ':'UTC'}
    code=work/'probe.rs';code.write_text(VIRTUAL_SOURCE);bad=work/'invalid.rs';bad.write_text('pub fn broken(_: OHM_MUSL_DOC_UNRESOLVED) {}\n')
    docdir=work/'out';ledger={};source_views={'P':(parent_sdk/driver_name,parent_sdk/'bin/rustdoc'),'C':(fresh_driver,fresh_doc)}
    for driver,doc in (('P','P'),('P','C'),('C','P'),('C','C')):
        tag=driver+'-'+doc;directory=raw/tag;directory.mkdir()
        for dest,source in [(view/driver_name,source_views[driver][0]),(view/'bin/rustdoc',source_views[doc][1])]:
            if not dest.samefile(source):
                pending=dest.with_suffix('.candidate');os.link(source,pending);pending.replace(dest)
            assert dest.samefile(source)
        assert sha((view/'bin/rustdoc').read_bytes())=={'P':P_DOC,'C':C_DOC}[doc]
        def invoke(label,args,rc=0):
            trace=work/'opens';cmd=['rustdoc','+ohm',*map(str,args)]
            run=subprocess.run(['strace','-f','-qq','-yy','-s','8192','-e','trace=execve,execveat,open,openat,openat2','-o',trace,*cmd],env=env,cwd=work,capture_output=True)
            for kind,data in [('stdout',run.stdout),('stderr',run.stderr),('kernel',trace.read_bytes())]:(directory/(label+'.'+kind+'.gz')).write_bytes(gzip.compress(data,mtime=0,compresslevel=2))
            assert run.returncode==rc,(tag,label,run.returncode,run.stderr[-750:]);events=trace.read_text(errors='replace');trace.unlink()
            selected=[Path(name) for name in re.findall(r' = \d+<([^>]+)>',events) if Path(name).name==Path(driver_name).name]
            assert any(p.exists() and p.samefile(source_views[driver][0]) for p in selected),(tag,label,selected)
            image=str(view/'bin/rustdoc');assert any(f'execve("{image}"' in line and re.search(r' = 0$',line) for line in events.splitlines()),(tag,label,image)
            return run
        version=invoke('version',['-vV']).stdout
        sysroot=subprocess.check_output(['rustc','+ohm','--print','sysroot'],env=env,cwd=work,text=True).strip()
        assert Path(sysroot).samefile(view)
        tool=subprocess.check_output(['rustup','which','--toolchain','ohm','rustdoc'],env=env,cwd=work,text=True).strip()
        assert Path(tool).samefile(source_views[doc][1])
        if docdir.exists():docdir.rename(work/('previous-output-'+tag))
        common=['--edition','2021','--target',target,'--crate-name','ohm_musl_docs']
        invoke('html',[*common,code,'--out-dir',docdir]);pages={}
        for f,needle in [('fn.round_trip.html',b'A native documentation and type-check witness.'),('struct.MuslOnly.html',b'Present only with this actual musl target.')]:
            b=(docdir/'ohm_musl_docs'/f).read_bytes();assert needle in b;pages[f]=sha(b)
        test=invoke('doctest',[*common,'--test',code]);assert b'1 passed; 0 failed' in test.stdout,test.stdout
        error=invoke('invalid',[*common,'--error-format=json',bad,'-o',work/'invalid-output'],1)
        import json
        diag=[json.loads(l) for l in error.stderr.splitlines() if l.startswith(b'{')];matches=[m for m in diag if (m.get('code') or {}).get('code')=='E0425' and 'OHM_MUSL_DOC_UNRESOLVED' in m['message']]
        assert len(matches)==1 and any(sp['is_primary'] and Path(sp['file_name']).samefile(bad) and sp['line_start']==1 for sp in matches[0]['spans'])
        ledger[tag]={'html':pages,'version':version.decode(),'error':matches[0]['message'],'diagnostic_code':'E0425','native_musl_doctests':1}
        save(directory/'result.json',ledger[tag]);assert ledger[tag]==ledger['P-P'],(tag,ledger)
    save(raw/'terminal.json',ledger)
