"""One native Ruff macro codegen counterfactual on signed Ohm. See MACRO-HOST.md."""
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

def child_exec(path):
    def need(ok,why):
        if not ok:raise ValueError(why)
    doc=json.loads(path.read_bytes()); env=doc['env']; spec=env.get('CARGO_MAKEFLAGS','')
    matches=re.findall(r'--jobserver-(?:auth|fds)=(\d+),(\d+)',spec)
    if spec:
        need(matches and len(set(matches))==1 and 'fifo:' not in spec,'unsupported recorded jobserver mode')
        a,b=map(int,matches[0]);need(2<a<1024 and 2<b<1024 and a!=b,'unusual jobserver descriptor');rd,wr=os.pipe();import fcntl
        safe=max(a,b,wr,rd)+1;r=fcntl.fcntl(rd,fcntl.F_DUPFD_CLOEXEC,safe);v=fcntl.fcntl(wr,fcntl.F_DUPFD_CLOEXEC,safe);os.close(rd);os.close(wr);os.write(v,b'+'*7);os.dup2(r,a,inheritable=True);os.dup2(v,b,inheritable=True);os.close(r);os.close(v)
    os.chdir(doc['cwd']);os.execve(doc['argv'][0],doc['argv'],env)


# The replay trampoline runs in the actual stripped Cargo environment. Do not
# import GitHub runner helpers before exec, even to obtain a temporary path.
if __name__=='__main__' and len(sys.argv)==3 and sys.argv[1]=='exec':
    child_exec(Path(sys.argv[2]));raise RuntimeError('exec unexpectedly returned')

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import worker as w
ROOT,OUT,SDK,STATE,SRC=w.ROOT,w.OUT,w.SDK,w.STATE,w.SRC
need,sha,save=w.need,w.sha,w.save
PRIVATE=ROOT/'macro-private'
BODIES=ROOT/'native-alternatives'
KNOWN=('P','C')


class Images(dict):
    def __init__(self):
        super().__init__();self.executed=set()


def roles(epochs, *, roster_only=False):
    data=Images(); costs={}; bad=[]; cfg=[x.split()for x in (epochs/'epochs.tsv').read_text().splitlines()]
    for row in cfg:
        if row[0]=='I':
            i=int(row[1]);e=(epochs/f'{i:05}.nul').read_bytes().split(b'\0');need(e[-1]==b'','complete process args');data[i]=(int(e[0]),os.fsdecode(e[3]),[os.fsdecode(k)for k in e[4:-1]])
            if row[5]=='exec':data.executed.add(i)
        elif row[0]=='C':
            need(len(row)==7,'wrong counter layout');i=int(row[1]);value,enabled,running=map(int,row[4:]);need(i in data,'unknown image interval');costs[i]=costs.get(i,0)+value
            if enabled!=running or (value and not enabled):bad.append([int(v)for v in row[1:]])
    if roster_only:
        save(epochs/'roster-only.json',dict(priced=False,invalid_intervals=bad));return data,{}
    need(not bad,'hardware intervals had incomplete scheduling');return data,costs


def rustc_call(data,owner):
    terms=[(key,pid,argv)for key,(pid,exe,argv)in data.items() if key in data.executed and exe==str(SDK/'bin/rustc') and '--crate-name'in argv and argv[argv.index('--crate-name')+1]==owner]
    item,=terms;return item


def cold_record():
    source=(w.KITS/'exec_count.c').read_text();hook=(HERE/'macro_capture.c.inc').read_text();marker='static void record_image(struct task *task, const char *trigger) {';after='require(n==0 && total && close(fd)==0 && fclose(f)==0,"argv completed");';need(source.count(marker)==source.count(after)==1,'observer source');source=source.replace(marker,hook+'\n'+marker).replace(after,after+'\n    capture_compiler(task->tid, executable, id, trigger);');PRIVATE.mkdir(mode=0o700);c=PRIVATE/'recorder.c';c.write_text(source);exe=PRIVATE/'recorder';subprocess.run(['/usr/bin/cc','-Wall','-Wextra','-Werror','-O2','-DOHM_SIGNED_RUSTC='+json.dumps(str(SDK/'bin/rustc')),'-DOHM_PRIVATE_ROOT='+json.dumps(str(PRIVATE)),c,'-o',exe],check=True)
    epochs=OUT/'prepare-epochs';epochs.mkdir();out=OUT/'prepare-old';w.run([exe,epochs,*w.CMD],w.environment(),out,timeout=2100);inv,meta,dirs=w.cargo_result(out);normal=w.native(out,w.OLD,meta,dirs,w.environment());rs,cs=roles(epochs,roster_only=True);rec={}
    for owner in ('ruff_macros','ruff_linter'):
        key,pid,argv=rustc_call(rs,owner);f=PRIVATE/owner;need(int((f/'record').read_text())==key,'selected physical image wrong');raw=(f/'environment').read_bytes().split(b'\0');need(raw.pop()==b''and len(raw)<180,'private environment');env=dict(os.fsdecode(a).split('=',1)for a in raw);need(len(env)==len(raw) and not any(k in env for k in ('GH_TOKEN','GITHUB_TOKEN','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','RUSTFLAGS','LD_PRELOAD')),'unexpected compiler environment');cwd=(f/'cwd').read_text();need(Path(cwd).is_dir() and Path(cwd).is_relative_to(SRC),'compiler working directory');need(argv[0].endswith('rustc'),'compiler argv0');argv[0]=str(SDK/'bin/rustc');rec[owner]=dict(argv=argv,env=env,cwd=cwd);save(OUT/(owner+'-original.json'),dict(argv=argv,cwd=cwd,image=key,pid=pid,environment_keys=sorted(env),environment_hash=hashlib.sha256((f/'environment').read_bytes()).hexdigest(),retired_user=cs.get(key)))
    for name in ('syn','quote','proc_macro2'):
        rows=[dict(id=i,argv=a) for i,(_,e,a)in rs.items() if i in rs.executed and e==str(SDK/'bin/rustc') and '--crate-name'in a and a[a.index('--crate-name')+1]==name];need(rows,'missing cold dependency rustc');save(OUT/(name+'-original.json'),rows)
    macro,=[r for r in inv if r[1]=='ruff_macros'and r[2]==['proc-macro']];profile=json.loads(macro[4]);need(profile['opt_level']=='0'and profile['debug_assertions']and profile['overflow_checks']and profile['debuginfo']==0,'native crate profile not O0 with both checks');extern,=[a for a in rec['ruff_linter']['argv']if a.startswith('ruff_macros=')];file=Path(extern.split('=',1)[1]);need(file.is_absolute()and file.resolve().is_relative_to(STATE)and file.name==macro[5][0] and file.is_file() and not file.is_symlink(),'actual declared macro object');return rec,file,normal


def adjusted(args,output,incremental):
    args=args.copy();i=args.index('--out-dir');args[i+1]=str(output);hits=[i for i,x in enumerate(args)if x.startswith('incremental=')];need(len(hits)==1 and args[hits[0]-1]=='-C','selected macro incremental mode');args[hits[0]]='incremental='+str(incremental)
    return args


def invoke(record,argv,label,observer=None):
    cmd=PRIVATE/'command.json';save(cmd,dict(cwd=record['cwd'],env=record['env'],argv=argv));driver=[sys.executable,'-IB',__file__,'exec',str(cmd)];dest=OUT/label
    if observer:
        e=OUT/(label+'-epochs');e.mkdir();driver=[observer,e,*driver]
    w.run(driver,w.environment(),dest,timeout=1200);return dest


def llvm_attributes(files):
    lib=SDK/'lib/libLLVM.so.23.1-rust-1.99.0-beta';need(lib.is_file(),'signed LLVM 23');llvm=ctypes.CDLL(str(lib));P,U,B,S=ctypes.c_void_p,ctypes.c_uint,ctypes.c_char_p,ctypes.c_size_t
    def fn(n,r,*a):f=getattr(llvm,n);f.restype=r;f.argtypes=list(a);return f
    ctxnew=fn('LLVMContextCreate',P);dispose=fn('LLVMContextDispose',None,P);buffer=fn('LLVMCreateMemoryBufferWithMemoryRangeCopy',P,B,S,B);dropbuf=fn('LLVMDisposeMemoryBuffer',None,P);parse=fn('LLVMParseBitcodeInContext2',ctypes.c_int,P,P,ctypes.POINTER(P));dropmod=fn('LLVMDisposeModule',None,P);first=fn('LLVMGetFirstFunction',P,P);advance=fn('LLVMGetNextFunction',P,P);blocks=fn('LLVMCountBasicBlocks',U,P);kind=fn('LLVMGetEnumAttributeKindForName',U,B,S)(b'optnone',7);attr=fn('LLVMGetEnumAttributeAtIndex',P,P,U,U);need(kind>0,'unknown optnone');all_={}
    for file in sorted(files):
        raw=file.read_bytes();need(len(raw)<128<<20,'large diagnostic bitcode');ctx=ctxnew();buf=buffer(raw,len(raw),b'Ruff macro source');mod=P();need(parse(ctx,buf,ctypes.byref(mod))==0,'signed LLVM rejected actual rustc bitcode');f=first(mod);count=opt=0
        while f:
            if blocks(f):count+=1;opt+=bool(attr(f,2**32-1,kind))
            f=advance(f)
        all_[file.name]=[hashlib.sha256(raw).hexdigest(),len(raw),count,opt];dropmod(mod);dropbuf(buf);dispose(ctx)
    need(sum(v[2]for v in all_.values())>10,'empty emitted macro bitcode');return all_


def prepare_bodies(rec,original,observer):
    BODIES.mkdir();p=ROOT/'direct-producer';note={};base=rec['ruff_macros'];args=base['argv'];count,=re.findall(r'^(-?opt-level=\d+)$','\n'.join(args),re.M)or ['opt-level=0'];need(count=='opt-level=0'and not any('mir-opt-level='in a or 'llvm-args='in a for a in args),'nonordinary source settings');need(args[args.index('--crate-type')+1]=='proc-macro','wrong source');need(not any('debug-assertions=no'in s or 'overflow-checks=no'in s for s in args),'unexpected disabled checks')
    for role in KNOWN:
        p.mkdir();inc=p/'incremental';out=p/'products';out.mkdir();inc.mkdir();a=adjusted(args,out,inc)
        if role=='C':a+=['-C','opt-level=1','-C','debug-assertions=yes','-C','overflow-checks=yes']
        invoke(base,a,'producer-'+role,observer);dso=out/original.name;need(dso.is_file()and dso.stat().st_size>100000,'no selected native DSO');shutil.copy2(dso,BODIES/role);note[role]=dict(argv=a,native_sha256=sha(dso),size=dso.stat().st_size);shutil.rmtree(p)
    need(note['C']['native_sha256']!=sha(original),'O1 produced no native change');note['signed_cargo_original']=sha(original)
    # A true independent fresh replay at the original path may differ in link notes
    # or the incremental output directory. The normal P arm always uses the genuine donor.
    p.mkdir();out=p/'products';inc=p/'incremental';out.mkdir();inc.mkdir();a=adjusted(args,out,inc)+['-C','save-temps=yes'];invoke(base,a,'source-ir');units=list(out.glob('*.no-opt.bc'));need(units,'missing native preoptimization CGUs');note['native_preopt']=llvm_attributes(units);shutil.rmtree(p);save(OUT/'producer.json',note)
    # rustc's codegen option legitimately contributes to the recorded crate hash.
    # Cargo continues reading the original metadata, while the equal-ABI audit
    # object selects only this freshly compiled implementation for dlopen.
    for name,f in [('original',original),('P',BODIES/'P'),('C',BODIES/'C')]:
        packed=BODIES/(name+'.rustc');subprocess.run(['/usr/bin/objcopy','--dump-section','.rustc='+str(packed),str(f),str(BODIES/(name+'.throwaway'))],check=True);need(packed.stat().st_size>100,'no native rustc metadata section');note[name+'_metadata']=sha(packed)
        text=subprocess.check_output(['/usr/bin/nm','-D','--defined-only',str(f)],text=True);declarations=re.findall(r'(?m)^\w+ [B-DF-RTVW] (__rustc_proc_macro_decls_[0-9a-f]+__)$',text);need(len(declarations)==1,'missing unique procedural macro declaration symbol');note[name+'_declaration']=declarations[0]
    need(note['original_declaration']==note['P_declaration']==note['C_declaration'],'host native ABI or stable crate identity changed');save(OUT/'producer.json',note);return note

def loader(original):
    actual=BODIES/'active'/original.name;actual.parent.mkdir();log=PRIVATE/'opened';audit=PRIVATE/'load.so';args=['/usr/bin/cc','-Wall','-Wextra','-Werror','-O2','-fPIC','-shared',*(name+json.dumps(str(path)) for name,path in[('-DOHM_SIGNED_RUSTC=',SDK/'bin/rustc'),('-DOHM_ORIGINAL_DSO=',original.resolve()),('-DOHM_LOADED_DSO=',actual),('-DOHM_OPEN_RECEIPT=',log)]),HERE/'macro_load.c','-o',audit];subprocess.run(args,check=True);save(OUT/'loader.json',dict(original=str(original),active=str(actual),audit=str(audit),source=sha(HERE/'macro_load.c'),audit_sha256=sha(audit)));return actual,log,audit


def visits(log,actual):
    st=actual.stat();visits=[]
    for row in log.read_text().splitlines():
        pid,dev,ino,size=map(int,row.split());need((dev,ino,size)==(st.st_dev,st.st_ino,st.st_size),'loader accepted a different physical image');visits.append(pid)
    need(visits,'no selected load');log.unlink();return visits


def expanded(rec,argv,label,log,active,audit):
    r=dict(rec);r['env']={**rec['env']};
    if audit:r['env']['LD_AUDIT']=str(audit)
    a=argv.copy();a[0]=str(SDK/'bin/rustc');dest=PRIVATE/'expanded';dest.mkdir();a[a.index('--out-dir')+1]=str(dest)
    for j,s in enumerate(a):
        if s.startswith('incremental='):a[j]='incremental='+str(dest/'incremental')
    a+=['-Zunpretty=expanded,hygiene'];d=invoke(r,a,label);printed=d/'stdout';size=printed.stat().st_size;need(100000<size<192<<20,'unusual printed expansion');h=sha(printed);prefix=printed.open('rb').read(4096);need(b'#!'in prefix or b'extern crate'in prefix,'unexpected expanded Rust');compressed=OUT/'expansions';compressed.mkdir(exist_ok=True);saved=compressed/(h+'.rs.zst');
    if not saved.exists():
        with saved.open('xb')as f:subprocess.run(['zstd','-q','-3','-c',printed],stdout=f,check=True)
    printed.unlink();shutil.rmtree(dest);loaded=visits(log,active) if audit else[];record=dict(sha256=h,bytes=size,stored=sha(saved),loaded=loaded);save(d/'expansion.json',record);return h


def stage(dir,label,env,rev,expected=0,observer=None):
    dest=dir/label;e=dir/(label+'-epochs');argv=w.CMD
    if observer:e.mkdir();argv=[observer,e,*argv]
    w.run(argv,env,dest,expected);r=w.cargo_result(dest,expected==0)
    if expected:return None
    inv,meta,dirs=r;record=w.native(dest,rev,meta,dirs,w.environment());conf=json.loads((dest/'cargo.json').read_bytes());return dict(inv=inv,metadata=conf['metadata'],record=record)


def clean_root(dir,env):
    before=[x for x in STATE.rglob('libruff_linter*.rmeta')if x.is_file()];need(before,'no previous root');out=dir/'clean-root';w.run(['cargo','+ohm','clean','-p','ruff_linter','--offline','--locked'],env,out);need(not any(x.exists()for x in before) and not any(p.name in ('dep-graph.bin','work-products.bin','query-cache.bin')and any(s.startswith('ruff_linter-')for s in p.parts)for p in STATE.rglob('*.bin')),'old root session or metadata remained')


def study():
    w.checked_head();w.source(w.NEW);_,observer=w.setup_perf();env=w.environment();w.fresh_state();w.checkout(w.OLD);rec,original,old=cold_record();ordinary_sha=sha(original);parts,times=w.make_snapshot();producer=prepare_bodies(rec,original,observer);active,log,audit=loader(original);allrows={};expansions={};edittimes={}
    for idx,role in enumerate(('plain','P','C','C','P')):
        w.restore_snapshot(parts,times);need(sha(original)==ordinary_sha,'Cargo donor DSO changed');selected=original if role!='C'else BODIES/'C';active.unlink(missing_ok=True);shutil.copy2(selected,active);need(sha(active)==sha(selected),'active image materialization');d=OUT/f'{idx}-{role}';d.mkdir();process_env=env if role=='plain'else{**env,'LD_AUDIT':str(audit)};log.unlink(missing_ok=True)
        prev=stage(d,'old-unchanged',process_env,w.OLD);need(all(x[-1]for x in prev['inv'])and prev['record']==old and not log.exists(),'old role must be fully fresh');w.checkout(w.NEW)
        if not edittimes:edittimes={f:(SRC/f).stat().st_mtime_ns for f in w.FILES}
        else:
            for f,t in edittimes.items():path=SRC/f;os.utime(path,ns=(path.stat().st_atime_ns,t))
        edit=stage(d,'edit',process_env,w.NEW,observer=observer);ds,counts=roles(d/'edit-epochs');image,pid,argv=rustc_call(ds,'ruff_linter');need([x[1]for x in edit['inv']if not x[-1]]==['ruff_linter'],'different edited compiler roster');need('ruff_macros='+str(original)in argv and sum('--emit=dep-info,metadata'==s for s in argv)==1,'real Rust library check or macro donor differs');opened=[] if role=='plain'else visits(log,active);need(opened==([]if role=='plain'else[pid]),'unexpected host DSO process');need(not log.exists(),'unobserved native load');repeat=stage(d,'new-unchanged',process_env,w.NEW);need(all(x[-1]for x in repeat['inv'])and repeat['record']==edit['record'] and not log.exists(),'incorrect unchanged result');
        if idx<3:
            expansions[role]=expanded(rec['ruff_linter'],argv,'expansion-'+role,log,active,None if role=='plain'else audit)
        if role in ('P','C')and idx<3:
            before=(SRC/w.SOURCE).read_bytes();(SRC/w.SOURCE).write_bytes(before+b'\nconst OHM_INVALID_CHECK_SENTINEL: u64 = "incorrect";\n');
            try:stage(d,'invalid',process_env,w.NEW,expected=101)
            finally:(SRC/w.SOURCE).write_bytes(before)
            visits(log,active);w.source(w.NEW);repair=stage(d,'repair',process_env,w.NEW);visits(log,active);need(repair['record']==edit['record'],'repair diverged');clean_root(d,process_env);pinned=stage(d,'empty-root',process_env,w.NEW);visits(log,active);need([r[1]for r in pinned['inv']if not r[-1]]==['ruff_linter'] and pinned['record']==edit['record']and pinned['metadata']==edit['metadata'],'dependency-pinned clean root differs')
        need(sha(original)==ordinary_sha,'input metadata carrier changed');allrows[str(idx)]=dict(role=role,selected=counts[image],all=sum(n for i,n in counts.items()if Path(ds[i][1]).name!=observer.name),active_hash=sha(active),loaded=opened,edit=edit,old=prev['record'],unchanged=repeat['record']);
    w.fresh_state();d=OUT/'complete-empty';d.mkdir();pure=stage(d,'new',env,w.NEW);keys=('messages','native_object','executable');need(all(pure['record'][k]==allrows['0']['edit']['record'][k] for k in keys),'new independent native mismatch');first=allrows['0']['edit'];need(all(v['edit']==first for v in allrows.values()) and len(set(expansions.values()))==1,'full Cargo or expansion interface differs across ordinary and optimized native checks');save(OUT/'macro-admitted.json',dict(rows=allrows,printed_expanded_hygiene=expansions,independent=pure['record'],producer=producer,unchanged_original=ordinary_sha,scope='Matched one-worker paired upper-bound ablation of only the compiled Ruff native macro unit. Cargo always reads the original metadata; the audit hook chooses only one DSO for dlopen.'));print('Accepted native implementation counterfactual and complete real edit controls.',flush=True)

if __name__=='__main__':
    study()
