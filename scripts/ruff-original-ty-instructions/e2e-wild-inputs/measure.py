"""Capture exactly one normal Wild exec, then challenge the recorded current Ruff e2e link."""
import gzip,hashlib,json,os,re,shutil,stat,subprocess as sp,sys
from pathlib import Path
H=Path(__file__).resolve().parent;sys.path.insert(0,str(H.parent))
import workspace29697 as b
sys.path.insert(0,str(H))
import build_source
w=b.w;P=b.PROOF;priv=w.root/'e2e-native-role'
OLD='f203086dc58594dc33899d25dcbdcd5ec86d04e3dfb493efe7c7a59f6abd97e2'
NEW='86b94323a752a316a501f542a846408648ca8b74c56bc60298690b671b7b0563'
LIST='76d24b892727ff181fdf019636ef5e928d741eb8df4f58f06dcc626d0bf67c52'
WILD='0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'
E2E='e2e-f5c6198f896cf7b0'
FROZEN_LINK={'run':41627259427,'epoch':337,'zip':'9c5a3ac75da6e79b13042be19228a37418f46fc356cc40e5f77cddd2147ecf57','abs_files':396}
def snapshot(p):return {'sha256':w.hf(p),'bytes':p.stat().st_size}
def prep():
    priv.mkdir()
    for name in ('whole_count','exec_count'):
        src=H.parent/(name+'.c')
        flags=[]
        if name=='exec_count':
            s=src.read_text();a='static void record_image(struct task *task, const char *trigger) {'
            end='require(n==0 && total && close(fd)==0 && fclose(f)==0,"argv completed");'
            assert s.count(a)==s.count(end)==1
            s=s.replace(a,'#include <dirent.h>\n'+(H/'capture.inc').read_text()+'\n'+a).replace(end,end+'\n    capture_link(task->tid,executable,trigger,name);')
            src=w.root/'exec_count.c';src.write_text(s);flags=['-DQA_CAPTURE="'+str(priv)+'"']
        sp.run(['cc','-Wall','-Wextra','-Werror','-O2',*flags,src,'-o',w.root/name],check=True)
def check_role(out,inv,expected):
    assert Path(inv['binary']).name==E2E and w.root/inv['binary']==out and len(inv['executables'])==102
    assert w.hf(out)==expected
    assert inv['executables'][inv['binary']]['elf']['sha256']==expected

def main():
    assert os.environ['REVIEWED_HEAD']==os.environ['GITHUB_SHA']and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert w.git('rev-parse','HEAD')==b.NEW and w.git('rev-parse','HEAD^')==b.OLD and w.hf(w.src/'sdk.json')==b.SPEC['sdk_manifest']
    assert shutil.disk_usage(w.root).free>45*2**30;w.guard();prep()
    b.write(P/'registration.json',dict(head=os.environ['GITHUB_SHA'],run=os.environ['GITHUB_RUN_ID'],boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),study=b.SPEC,wild=WILD,previous_link=FROZEN_LINK,reference=dict(run=41617756983,old=OLD,edited=NEW,independent_clean=NEW,test_inventory=LIST),limits='Actual physical selected path/search scope only. No production skip.'))
    env=w.install();actors=build_source.build(w,env,P);b.select(b.OLD);b.write(P/'locked-registry.json.gz',b.inputs(env))
    meta=json.loads(sp.check_output(['cargo','+ohm','metadata','--format-version=1','--locked','--offline','--no-deps'],cwd=w.work,env=env))
    graph=json.loads(sp.check_output([*b.CMD[:2],'-Zunstable-options',*b.CMD[2:-1],'--unit-graph'],cwd=w.work,env=env))
    assert len(meta['workspace_default_members'])==55 and len(graph['units'])==693
    for path in (w.target,w.shared):
        if path.exists():assert path.parent==w.root and path.is_dir()and not path.is_symlink();shutil.rmtree(path)
    old=b.inventory('ordinary-old',env,meta);out=w.root/old['binary'];check_role(out,old,OLD)
    prior=w.root/'prior-e2e';shutil.copy2(out,prior);assert b.verdict(prior,'old-verdict',env,0)==LIST
    b.select(b.NEW);assert b.verdict(prior,'old-on-new-verdict',env,101)==LIST
    edit=b.inventory('ordinary-edit',env,meta);check_role(out,edit,NEW);assert b.verdict(out,'edit-verdict',env,0)==LIST
    seen=b.inventory('current-observed',env,meta,'census');check_role(out,seen,NEW);assert b.verdict(out,'observed-verdict',env,0)==LIST
    # The exact original complete ELFs are already independently retained in 41617756983.
    for h in (NEW,OLD):
        duplicate=P/(h+'.elf.zst')
        if duplicate.exists():duplicate.unlink()
    argdata=(priv/'argv.nul').read_bytes();records=argdata.split(b'\0');assert records[-1]==b''
    argv=[os.fsdecode(x)for x in records[4:-1]];assert argv[argv.index('-o')+1]==str(out)
    native=Path(argv[0]);assert w.hf(native)==WILD and os.path.samefile(native,os.fsdecode(records[3]))
    sym,=[Path(v)for v in argv if v.endswith('/symbols.o')];raw=Path(next(x[2:]for x in argv if x.startswith('-L')))
    assert raw==sym.parent/'raw-dylibs'and sym.parent.parent==out.parent and not sym.parent.exists()
    cap=P/'native-capture';cap.mkdir()
    for name in ('symbols.o','argv.nul','cwd','fds','stat','raw-present'):shutil.copy2(priv/name,cap/name)
    captured=(priv/'symbols.o').read_bytes();fields=list(map(int,(priv/'stat').read_text().split()))
    assert len(captured)==fields[2]and (native.stat().st_dev,native.stat().st_ino)==tuple(fields[3:])
    env_expected=dict(item.split(b'=',1)for item in (priv/'env.nul').read_bytes().rstrip(b'\0').split(b'\0'))
    b.write(cap/'identity.json',dict(executable=snapshot(native),argv_sha256=b.sha(argdata),symbol=snapshot(cap/'symbols.o'),native_env_sha256=w.hf(priv/'env.nul'),native_env_names=sorted(os.fsdecode(x)for x in env_expected),output=str(out)))
    sym.parent.mkdir();sym.write_bytes(captured)
    original_dir=(priv/'raw-present').read_text().strip()=='1'
    if original_dir:raw.mkdir()
    paths=[Path(t)for t in argv if t.startswith('/')and t!=str(out)and Path(t).suffix in ('.o','.rlib','.rmeta','.a','.so')]
    assert len(paths)==396 and sym in paths
    original={str(p):snapshot(p)for p in set(paths)};b.write(cap/'all-literal-inputs.json.gz',original)
    def visit(tag,add=(),traced=False,expected=None,exit83=False,error=False,actor=None):
        dest=P/tag;dest.mkdir();w.guard()
        if out.exists():assert out.is_file()and out.is_relative_to(w.root);out.unlink()
        options=[s.replace('$DEP',str(dest/'stock.d'))for s in add]
        args=[*argv,*options];cmd=args;trace=w.root/(tag+'-syscalls')
        if traced:
            trace.mkdir();cmd=['/usr/bin/strace','-ff','-qq','-ttt','-s','2048','-yy','-e','trace=%file,mmap,munmap','-o',str(trace/'task'),*args]
        doc=dest/'plan.json';b.write(doc,{'command':cmd,'private':str(priv),**({'actor':str(actors/actor)}if actor else {})})
        assert not (actor and traced)
        with(dest/'stdout').open('wb')as so,(dest/'stderr').open('wb')as se:
            proc=sp.run(['/usr/bin/python3','-IB',H/'dispatch.py',doc],env=env,stdout=so,stderr=se,timeout=180)
        if traced:
            files=list(trace.glob('task.*'));assert files and sum(f.stat().st_size for f in files)<180*2**20
            sub=dest/'syscalls';sub.mkdir()
            for f in files:
                with f.open('rb')as s,gzip.open(sub/(f.name+'.gz'),'wb',compresslevel=3)as z:shutil.copyfileobj(s,z)
        stamp=snapshot(out)if out.is_file()else None
        b.write(dest/'link-result.json',dict(returncode=proc.returncode,elf=stamp,inputs={str(sym):w.hf(sym),str(raw/'libutil.a'):w.hf(raw/'libutil.a')if(raw/'libutil.a').is_file()else None}))
        if error:assert proc.returncode!=0;return None
        assert proc.returncode==0 and stamp and os.access(out,os.X_OK),(dest/'stderr').read_text()[-900:]
        if expected:assert stamp['sha256']==expected,(tag,stamp)
        if exit83:
            rv=sp.run([out,'--list'],cwd=w.work/'crates/ty_server',env=env,capture_output=True);(dest/'runtime-stdout').write_bytes(rv.stdout);(dest/'runtime-stderr').write_bytes(rv.stderr)
            b.write(dest/'runtime.json',{'returncode':rv.returncode});assert rv.returncode==83 and not rv.stdout
        else:assert b.verdict(out,tag+'-verdict',env,0)==LIST
        return stamp['sha256']
    visit('stock',expected=NEW)
    visit('syscall-observer',traced=True,expected=NEW)
    visit('src-stock',actor='stock',expected=NEW)
    visit('src-observer',actor='observer',expected=NEW)
    visit('stock-depfile-trace',['--trace','--dependency-file=$DEP'],expected=NEW)
    if not original_dir:raw.mkdir()
    provider=raw/'libutil.a';assert not provider.exists()
    asm=priv/'force.s';obj=priv/'force.o'
    asm.write_text('.text\n.globl zzQA\n.type zzQA,@function\nzzQA: ret\n.type qa_force_exit,@function\nqa_force_exit: mov $83,%edi\n mov $231,%eax\n syscall\n ud2\n.section .init_array,"aw",@init_array\n.p2align 3\n.quad qa_force_exit\n.section .note.GNU-stack,"",@progbits\n')
    sp.run(['/usr/bin/as','--64','-o',obj,asm],check=True);sp.run(['/usr/bin/ar','crD',provider,obj],check=True)
    for p in (asm,obj,provider):shutil.copy2(p,cap/p.name)
    shadow=visit('earlier-library',['--trace','--dependency-file=$DEP'],traced=True)
    visit('src-shadow',actor='observer',expected=shadow)
    assert captured.count(b'\0main\0')==1
    def inplace(data):
        s=sym.stat();sym.write_bytes(data);os.utime(sym,ns=(s.st_atime_ns,s.st_mtime_ns))
        now=sym.stat();assert (now.st_dev,now.st_ino,now.st_size,now.st_mtime_ns)==(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
    swapped=captured.replace(b'\0main\0',b'\0zzQA\0');assert sum(a!=b for a,b in zip(swapped,captured))==4
    inplace(swapped);shutil.copyfile(sym,cap/'four-byte-symbols.o')
    bad=visit('four-byte-symbol',['--trace','--dependency-file=$DEP'],traced=True,exit83=True);assert bad!=shadow
    visit('src-four-byte',actor='observer',expected=bad,exit83=True)
    inplace(captured);visit('symbol-repair',expected=shadow)
    provider.write_bytes(b'DELIBERATELY MALFORMED NATIVE PROVIDER\n');visit('malformed-shadow',traced=True,error=True)
    visit('src-malformed',actor='observer',error=True)
    provider.unlink()
    if not original_dir:raw.rmdir()
    visit('remove-shadow-repair',expected=NEW)
    visit('src-final-repair',actor='observer',expected=NEW)
    assert all(snapshot(Path(name))==v for name,v in original.items())and not w.git('status','--porcelain')
    assert sum(f.stat().st_size for f in P.rglob('*')if f.is_file())<180*2**20

if __name__=='__main__':main()
