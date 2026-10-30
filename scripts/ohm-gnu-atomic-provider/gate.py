"""Train once per case, change owned non-Rust bytes, then isolate linking from rebundling."""
import json
import os
from pathlib import Path
import re
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from sdk import ROOT, SDK, load, save, sha, identity
from observe import OUT, OBJECTS, PREFIX, TARGET, AR, DRIVER, command, run, stored, visit

APP='''fn main() { println!("{}", qa_plain::value()); }
'''
LEAF='''#[inline(never)]
pub unsafe fn atomic_value(ptr: *const u64) -> u64 {
    let value: u64;
    unsafe {
        core::arch::asm!("ldar {value}, [{ptr}]",
            value = out(reg) value, ptr = in(reg) ptr, options(nostack, preserves_flags));
    }
    value
}
'''
PLAIN='''#[link(name = "qa_owned_atomic", kind = "static", modifiers = "MODE")]
unsafe extern "C" { static qa_owned_word: u64; }
#[inline(never)]
pub fn value() -> u64 {
    unsafe { qa_leaf::atomic_value(core::ptr::addr_of!(qa_owned_word)) }
}
'''
BUILD='''fn main() {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    println!("cargo:rerun-if-changed=build.rs");
    for name in ["early", "late"] {
        let dir = root.join(name);
        println!("cargo:rustc-link-search=native={}", dir.display());
        WATCH
    }
}
'''
PROBE='''#include <stdio.h>
extern const unsigned long long qa_owned_word;
int main(void) { printf("%llu\\n", qa_owned_word); return 0; }
'''
MUTATIONS=('replace-same-mtime','higher-priority','malformed','removed','malformed-higher')
def put(p,t):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(t)
def stat(p):
    if not p.exists():return None
    s=p.stat();return {'dev':s.st_dev,'ino':s.st_ino,'mtime_ns':s.st_mtime_ns,'size':s.st_size,'sha256':sha(p)}
def env_for(work):
    proxy=Path(shutil.which('rustup')).resolve(strict=True)
    shim=ROOT/'bin';shim.mkdir()
    for tool in ('rustup','cargo','rustc'):(shim/tool).symlink_to(proxy)
    rh=ROOT/'rustup';(rh/'toolchains').mkdir(parents=True);(rh/'toolchains/ohm').symlink_to(SDK,target_is_directory=True)
    home=ROOT/'home';home.mkdir()
    e={'HOME':str(home),'PATH':str(shim)+':/usr/local/bin:/usr/bin:/bin','RUSTUP_HOME':str(rh),
       'CARGO_HOME':str(work/'cargo-home'),'CARGO_TARGET_DIR':str(work/'target'),'CARGO_BUILD_BUILD_DIR':str(work/'shared'),
       'RUSTUP_AUTO_INSTALL':'0','CARGO_NET_OFFLINE':'true','LANG':'C','LC_ALL':'C','TERM':'dumb',
       'CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER':'/usr/bin/'+DRIVER}
    if 'LD_LIBRARY_PATH' in os.environ:
        # Deliberately start clean. The selected compiler has its own relative runtime paths.
        assert 'LD_LIBRARY_PATH' not in e
    for tool in ('rustc','cargo'):
        r=run(['rustup','which','--toolchain','ohm',tool],ROOT,e)
        assert r.returncode==0 and Path(r.stdout.decode().strip()).samefile(SDK/'bin'/tool)
    host=run(['cargo','+ohm','-Vv'],ROOT,e);cc=run(['rustc','+ohm','-vV'],ROOT,e)
    assert host.returncode==cc.returncode==0,(host.stderr,cc.stderr)
    native={'rustc':cc.stdout.decode(),'cargo':host.stdout.decode(),'executables':{},'env':e,'uname':os.uname()._asdict() if hasattr(os.uname(),'_asdict') else list(os.uname())}
    for n in (DRIVER,'aarch64-linux-gnu-ar','aarch64-linux-gnu-readelf','qemu-aarch64','strace','rustup'):
        p=Path(shutil.which(n,path=e['PATH'])).resolve(strict=True)
        native['executables'][n]={'path':str(p),'bytes':identity(p)}
    save(OUT/'tools.json',native)
    return e

def fixture(src,mode,watched,env):
    src.mkdir()
    put(src/'Cargo.toml','[workspace]\nmembers=["leaf","plain","app"]\nresolver="2"\n')
    for d,name,deps in [('leaf','qa_leaf',''),('plain','qa_plain','qa_leaf={path="../leaf"}\n'),('app','qa_app','qa_plain={path="../plain"}\n')]:
        put(src/d/'Cargo.toml',f'[package]\nname="{name}"\nversion="0.0.1"\nedition="2021"\n[dependencies]\n'+deps)
    put(src/'leaf/src/lib.rs',LEAF);put(src/'app/src/main.rs',APP)
    put(src/'plain/src/lib.rs',PLAIN.replace('MODE',mode))
    put(src/'plain/build.rs',BUILD.replace('WATCH',{
        'unwatched':'','both-directories':'println!("cargo:rerun-if-changed={}",dir.display());',
        'selected-file':'if name=="late" { println!("cargo:rerun-if-changed={}",dir.join("libqa_owned_atomic.a").display()); }',
        'all-files':'println!("cargo:rerun-if-changed={}",dir.join("libqa_owned_atomic.a").display());'
    }[watched]))
    for name in ('early','late'):(src/'plain'/name).mkdir()
    result=run(['cargo','+ohm','generate-lockfile','--offline'],src,env)
    assert result.returncode==0,(result.stderr,env)
    return {str(p.relative_to(src)):stored(p.read_bytes()) for p in src.rglob('*') if p.is_file()}
def make_inputs(src,case,env):
    d=case/'provision';d.mkdir();inputs={};objects={}
    for value in (17,29):
        put(d/'provider.c',f'const unsigned long long qa_owned_word = {value}ULL;\n')
        command([DRIVER,'-c','provider.c','-o','provider.o'],d,env,d/f'compile-{value}')
        ar=d/('archive-'+str(value)+'.a');command([AR,'rcsD',ar,'provider.o'],d,env,d/f'archive-{value}')
        inputs[value]=ar.read_bytes();objects[str(value)]=(d/'provider.o').read_bytes()
        assert len(objects[str(value)])>100
    assert len(inputs[17])==len(inputs[29]) and inputs[17]!=inputs[29]
    assert len(objects['17'])==len(objects['29']) and objects['17']!=objects['29']
    save(d/'products.json',{'archives':{n:stored(b) for n,b in inputs.items()},'objects':{n:stored(b) for n,b in objects.items()}})
    # Only content-addressed copies of the original setup bytes are authoritative.
    put(d/'probe.c',PROBE)
    return inputs,objects
def cprobe(case,env,src,name,wanted):
    d=case/'provision';dest=d/'independent-c'; binary=dest.with_suffix('.elf')
    r=run([DRIVER,'probe.c','-L'+str(src/'plain/early'),'-L'+str(src/'plain/late'),'-lqa_owned_atomic','-o',binary],d,env)
    answer=None
    if r.returncode==0:
        q=run(['qemu-aarch64','-L','/usr/aarch64-linux-gnu',binary],d,env)
        assert q.returncode==0 and q.stdout in (b'17\n',b'29\n');answer=int(q.stdout)
    save(case/('c-reference-'+name+'.json'),{'link_code':r.returncode,'link_stderr':stored(r.stderr),'answer':answer,
         'elf':stored(binary.read_bytes()) if answer else None})
    assert answer==wanted,(name,answer,wanted,r.stderr)
def fingerprint_evict(work,names,where):
    selected={}
    for name in names:
        paths=sorted({p for b in (work/'target',work/'shared') for p in b.rglob(name)
                      if p.is_file() and re.fullmatch(b'[0-9a-fA-F]{16}',p.read_bytes())})
        for f in paths:
            selected[str(f)]=stored(f.read_bytes());f.unlink()
    save(where,{'requested':names,'removed':selected})
    return selected
def expectation(result):return result['value']['value'] if result['cargo_exit']==0 else None
def source_dgs(src):
    return {str(p.relative_to(src)):sha(p) for p in sorted(src.rglob('*')) if p.is_file() and p.suffix in ('.toml','.rs','.lock')}
def clean_visit(work,src,env,out,objects):
    parked=work/'allocated-before-clean';parked.mkdir()
    for nm in ('target','shared'):
        (work/nm).rename(parked/nm)
    try:return visit(src,work,env,out,objects)
    finally:
        for nm in ('target','shared'):
            p=work/nm
            if p.exists():shutil.rmtree(p)
            (parked/nm).rename(p)
        parked.rmdir()
def baseline_check(cold,role,mode,late,env):
    assert expectation(cold)==17 and cold['cross_linker_pids']
    assert {'qa_plain','qa_leaf','qa_app'} <= {c for _,k,c in cold['rustc'] if k=='full'}
    leaf_deps=[j for p,j in cold['depfiles'].items() if Path(p).name.startswith('qa_leaf')];assert leaf_deps
    markers={j['kind'] for j in leaf_deps}
    if role=='strict-C':assert 'v2' in markers,markers
    elif role in ('signed-on','strict-P'):assert 'hard' in markers,markers
    else:assert markers<={None},markers
    dis=run(['/usr/bin/aarch64-linux-gnu-objdump','-d',cold['libs']['qa_leaf']['path']],ROOT,env)
    assert dis.returncode==0 and re.search(rb'\bldar\s+x[0-9]+,\s*\[x[0-9]+\]',dis.stdout),dis.stderr
    bundle=cold['libs']['qa_plain']
    matches={n for m in bundle['members'] for n in m['matches_provider_object']}
    assert matches==({'17'} if mode=='+bundle' else set()),(mode,matches)
    external=[line for m in bundle['relocations'] for line in m['relocations']]
    assert any('R_AARCH64_' in x for x in external),external
    hits=[e for e in cold['native']['opened'] if any(str(late) in l and l.startswith('open') and re.search(r'= [0-9]+$',l) for l in e['calls'])]
    assert hits,(mode,'baseline lacked original provider open')
    assert any(e['owner'] and e['owner'][1:]==(['full','qa_plain'] if mode=='+bundle' else ['linker',None]) for e in hits),(mode,hits)
    return {'leaf_markers':sorted(x for x in markers if x),'bundle_original_objects':sorted(matches),'selected_provider_opens':hits,'rooted_relocations':external,'original_leaf_disassembly':stored(dis.stdout)}
def one_case(src,work,env,role,mode,mut,watched):
    namespace='bundled-'+watched
    case=OUT/namespace/mut;case.mkdir(parents=True)
    for existing in ('target','shared'):(work/existing).mkdir(exist_ok=True)
    srcs=fixture(src,mode,watched,env)
    save(case/'sources.json',srcs)
    inputs,objects=make_inputs(src,case,env)
    early=src/'plain/early'/PREFIX;late=src/'plain/late'/PREFIX
    late.write_bytes(inputs[17]);before=stat(late);initial_source=source_dgs(src)
    cprobe(case,env,src,'baseline',17)
    cold=visit(src,work,env,case/'00-empty-original',objects)
    baseline=baseline_check(cold,role,mode,late,env)
    save(case/'baseline.json',baseline)
    normal=visit(src,work,env,case/'01-settled-original',objects);assert expectation(normal)==17
    assert not early.exists()
    malformed=(b'NOT_A_VALID_GNU_LD_INPUT\n' * ((len(inputs[17])//25)+2))[:len(inputs[17])]
    if mut=='higher-priority':early.write_bytes(inputs[29]);wanted=29
    elif mut=='normal-replacement':
        late.write_bytes(inputs[29]);assert late.stat().st_mtime_ns>before['mtime_ns'];wanted=29
    elif mut=='replace-same-mtime':
        saved=late.stat()
        with late.open('r+b') as f:f.write(inputs[29]);f.flush();os.fsync(f.fileno())
        os.utime(late,ns=(saved.st_atime_ns,saved.st_mtime_ns))
        after=stat(late)
        assert all(after[k]==before[k] for k in ['dev','ino','mtime_ns','size']) and after['sha256']!=before['sha256'];wanted=29
    elif mut=='malformed':late.write_bytes(malformed);wanted=None
    elif mut=='removed':late.unlink();wanted=None
    elif mut=='malformed-higher':early.write_bytes(malformed);wanted=None
    else:raise RuntimeError(mut)
    save(case/'mutation.json',{'before':before,'after_late':stat(late),'after_early':stat(early),'expected':wanted,'watch':watched})
    assert source_dgs(src)==initial_source
    cprobe(case,env,src,'mutated',wanted)
    raw={}
    for name in ('02-ordinary','03-ordinary-repeat'):
        raw[name]=visit(src,work,env,case/name,objects)
        if expectation(raw[name])!=wanted:print('::warning::',role,namespace,mut,name,'warm:',expectation(raw[name]),'C reference:',wanted,flush=True)
    removed=fingerprint_evict(work,['bin-qa_app'],case/'force-root.json')
    # A previous failed command can already have removed the final fingerprint.
    if raw['03-ordinary-repeat']['cargo_exit']==0:assert removed,(namespace,mut,'unforced root',list(work.iterdir()))
    raw['04-forced-root']=visit(src,work,env,case/'04-forced-root',objects)
    if raw['04-forced-root']['cargo_exit']==0:assert raw['04-forced-root']['cross_linker_pids']
    removed=fingerprint_evict(work,['lib-qa_plain','bin-qa_app'],case/'force-producer.json')
    if raw['04-forced-root']['cargo_exit']==0:assert any(Path(p).name=='lib-qa_plain' for p in removed),(namespace,mut,'unforced producer')
    raw['05-forced-rebundle']=visit(src,work,env,case/'05-forced-rebundle',objects)
    assert any(x[1:] == ('full','qa_plain') for x in raw['05-forced-rebundle']['rustc'])
    raw['06-independent-empty']=clean_visit(work,src,env,case/'06-independent-empty',objects)
    assert expectation(raw['05-forced-rebundle'])==expectation(raw['06-independent-empty'])==wanted,(namespace,mut,'forced/empty provider mismatch')
    if early.exists():early.unlink()
    late.write_bytes(inputs[17])
    cprobe(case,env,src,'repair',17)
    repair=visit(src,work,env,case/'07-repair',objects)
    repaired_clean=clean_visit(work,src,env,case/'08-clean-repair',objects)
    assert expectation(repaired_clean)==17
    raw['07-repair']=repair;raw['08-clean-repair']=repaired_clean
    if expectation(repair)!=17:
        print('::warning::',role,namespace,mut,'ordinary repair',expectation(repair),'independent empty',17,flush=True)
    assert source_dgs(src)==initial_source
    summary={k:{'value':expectation(v),'exit':v['cargo_exit'],'elf':v['value'] and v['value']['sha256'],
                'rustc':v['rustc'],'cross_linker_pids':v['cross_linker_pids']} for k,v in raw.items()}
    save(case/'complete.json',{'mode':mode,'mutation':mut,'role':role,'expected':wanted,'original':17,'summaries':summary,'ordinary_repair':expectation(repair),'clean_repair':17})
    # The complete raw outputs, exact source, and each distinct physical ELF/rlib were retained above.
    assert src.parent==ROOT and work.parent==ROOT
    for p in [src,work/'target',work/'shared']:
        assert p.is_dir() and not p.is_symlink();shutil.rmtree(p)
    return {k:[v['exit'],v['value']] for k,v in summary.items()}
def main():
    role=sys.argv[1];assert role==load(OUT/'sdk.json')['role']
    work=ROOT/'work';work.mkdir();OBJECTS.mkdir()
    source=ROOT/'source';env=env_for(work)
    summary={}
    schedules={'unwatched':MUTATIONS,'both-directories':('higher-priority','normal-replacement','replace-same-mtime'),
               'selected-file':('higher-priority','normal-replacement','replace-same-mtime'),
               'all-files':('higher-priority',)}
    if role not in ('upstream','signed-off'):
        schedules={'unwatched':MUTATIONS,'both-directories':('higher-priority','replace-same-mtime'),
                   'selected-file':('normal-replacement',)}
    if role=='signed-on':schedules={'unwatched':MUTATIONS,'both-directories':('higher-priority',)}
    for watch,mutations in schedules.items():
        for mut in mutations:
            assert shutil.disk_usage(ROOT).free>8*2**30
            summary[('+bundle',watch,mut)]=one_case(source,work,env,role,'+bundle',mut,watch)
    save(OUT/'terminal.json',{'role':role,'cases':[{'identity':k,'result':v} for k,v in summary.items()]})
if __name__=='__main__':main()
