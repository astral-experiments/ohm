"""Independent physical admission before Cargo builds the repository's real run-make driver."""
from pathlib import Path
import ctypes,hashlib,json,os,shutil,struct,subprocess
H=lambda b:hashlib.sha256(b).hexdigest();HOST='x86_64-unknown-linux-gnu';libc=ctypes.CDLL(None,use_errno=True)

def probe(src,sdk,case,out):
    case.mkdir();out.mkdir();(case/'out').mkdir();[shutil.copyfile(src/f,case/f)for f in('lib.rs','main.rs')];old=(case/'lib.rs').read_text();moved=old.replace('    input.wrapping_add','\n    input.wrapping_add');semantic=moved.replace('17','line!()');shifted=semantic.replace('    input.wrapping_add','\n    input.wrapping_add');line=next(i for i,s in enumerate(moved.splitlines(),1)if 'wrapping_add(17)'in s);env=dict(os.environ,LD_LIBRARY_PATH=str(sdk/'lib'),LC_ALL='C');rust=str(sdk/'bin/rustc');base=[rust,'-L',str(case),'lib.rs','--crate-name','placement','--crate-type','rlib','--emit=dep-info,metadata,link','-Copt-level=1','-Clto=off','-Cdebug-assertions=on','-Cdebuginfo=line-tables-only','-Cembed-bitcode=no','-Zohm-shared-stages','-Cincremental=incremental','--out-dir','out','--target='+HOST];prog=[rust,'-L',str(case),'main.rs','--extern','placement=out/libplacement.rlib','-o','caller','--target='+HOST];log={}
    def save(): (out/'native.json').write_text(json.dumps({'source':src.name,'compile':base,'link':prog,'phases':log},indent=1,sort_keys=True)+'\n')
    def body(b):
        h=H(b);p=out/'bodies'/h;p.parent.mkdir(exist_ok=True);p.write_bytes(b);return h
    def go(phase,text,expected=None):
        (case/'lib.rs').write_text(text);fd=libc.inotify_init1(os.O_NONBLOCK|os.O_CLOEXEC);assert fd>=0
        try:
            assert libc.inotify_add_watch(fd,os.fsencode(case/'out'),0x100)>=0
            p=subprocess.run(base,cwd=case,env=env,capture_output=True,timeout=30);events=[]
            while True:
                try:b=os.read(fd,64<<10)
                except BlockingIOError:break
                at=0
                while at<len(b):
                    wd,mask,cookie,length=struct.unpack_from('=iIII',b,at);name=b[at+16:at+16+length].rstrip(b'\0');assert not mask&0x4000;events.append((mask,name.decode()));at+=16+length
                assert at==len(b)
        finally:os.close(fd)
        indices=[{'name':v.name,'bytes':v.stat().st_size,'sha256':body(v.read_bytes())}for v in (case/'incremental').rglob('work-products.bin')if v.stat().st_size<1<<20];r={'compile':p.returncode,'stderr':p.stderr.decode(),'placements':[n for mask,n in events if mask&0x40000000 and n.startswith('ohm-placement-')],'events':events,'indices':indices,'source':H(text.encode())};log[phase]=r;save()
        if expected is None:assert p.returncode and b'E0308'in p.stderr;return
        assert p.returncode==0,p.stderr.decode();archive=case/'out/libplacement.rlib';names=[n for n in subprocess.check_output(['ar','t',archive],text=True).splitlines()if n.endswith('.o')];assert len(names)==1;obj=subprocess.check_output(['ar','p',archive,names[0]]);assert obj.startswith(b'\x7fELF')and len(obj)<1<<20;r['object']=body(obj);r['rlib']=body(archive.read_bytes());r['member']=names[0];subprocess.run(prog,cwd=case,env=env,check=True,capture_output=True,timeout=30);elf=case/'caller';r['executable']=H(elf.read_bytes());r['printed']=subprocess.check_output([elf],cwd=case,env=env,text=True).strip();save();assert r['printed']==str(expected)
    go('old',old,37);go('moved',moved,37);(case/'incremental').rename(case/'old-incremental');go('fresh-moved',moved,37);go('invalid',moved.replace('17','"wrong"'));go('repaired-line',semantic,20+line);go('moved-line',shifted,21+line)
    return {'has_positive':bool(log['moved']['placements']),'source_changed_object':log['old']['object']!=log['moved']['object'],'moved_object_matches_clean':log['moved']['object']==log['fresh-moved']['object'],'moved_elf_matches_clean':log['moved']['executable']==log['fresh-moved']['executable'],'observable_move_declined':not log['moved-line']['placements'],'genuine_outcomes':[log[x]['printed']for x in('old','moved','fresh-moved','repaired-line','moved-line')],'invalid_e0308':'E0308'in log['invalid']['stderr']}
