"""Registered same-path Apple Cargo migrations covering the six previous failed warm cases."""
from pathlib import Path
import gzip,hashlib,json,os,shutil,stat,subprocess,sys
D=Path(__file__).resolve().parent;OLD=Path(sys.argv[2]).resolve();sys.path.insert(0,str(OLD/'scripts/ohm-apple-zmij'))
import provider_edges as edge, fixed_crc, release_legacy
from study import need,check_host,env_for,physical,save,sha
from execs import ExecTrace
from versioned import marker_rules
sys.path.insert(0,str(D))
from schedule import P,C,V,BAD,checks
def stamp(p):
    p=p.resolve(strict=True);s=p.stat();return {'path':str(p),'dev':s.st_dev,'ino':s.st_ino,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'sha256':sha(p)}
def detail(p):
    s=p.lstat()
    if stat.S_ISLNK(s.st_mode):return [s.st_dev,s.st_ino,s.st_mode,'symlink',os.readlink(p)]
    if stat.S_ISREG(s.st_mode):return [s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,sha(p)]
    assert stat.S_ISDIR(s.st_mode)
    return [s.st_dev,s.st_ino,s.st_mode]
def namespace(src,work):
    return {str(p.relative_to(root)):detail(p) for root in (src.parent,) for top in (src,work/'target',work/'shared') for p in (top,*sorted(top.rglob('*')))}
def compact_zip(p,vals):
    with p.open('xb') as f:f.write(gzip.compress(json.dumps(vals,sort_keys=True,separators=(',',':')).encode(),compresslevel=4,mtime=0))
def install(root,sdk,role):
    f=root/'products'/role;dest=sdk/'bin/cargo'
    if not dest.samefile(f):
        tmp=dest.with_name('cargo-qa-next');assert not tmp.exists();os.link(f,tmp);os.replace(tmp,dest)
    assert dest.samefile(f) and sha(dest)==sha(f)
    return stamp(dest)
def actual_archive_owner(src,placement,watched,barrier=None):
    trigger=BASE_FORM(src,placement,watched,barrier)
    assert placement=='library'
    (src/'barrier/src/lib.rs').write_text(barrier+'''
#[link(name="qa_owned_external", kind="static", modifiers="-bundle")]
unsafe extern "C" { fn qa_value() -> i32; }
#[inline(never)]
pub fn resolved() -> i32 { barrier(unsafe { qa_value() }) }
''')
    (src/'src/main.rs').write_text('fn main() { println!("{} {}", barrier::resolved(), trigger::value()); }\n')
    return trigger
BASE_FORM=edge.form
def run(root):
    root=root.resolve();assert OLD.is_dir() and subprocess.check_output(['git','-C',OLD,'rev-parse','HEAD']).decode().strip()=='14c9d13d68f3dd21c53f1ef6c3721de8363c0123'
    assert 'GH_TOKEN' not in os.environ and 'GITHUB_TOKEN' not in os.environ
    check_host(root,8);sdk=root/'native';signed=root/'sdk-21'
    subprocess.run(['/bin/cp','-cR',signed,sdk],check=True)
    data=root/'receipts';stored=root/'products';stored.mkdir();dst=sdk/'bin/cargo'
    os.link(dst,stored/'signed');os.link(root/'inbound/strict-cargo',stored/'strict')
    for p in ('provider-matrix','edge-images','edge-markers','switches'):(data/p).mkdir()
    driver,=(sdk/'lib').glob('librustc_driver*.dylib');ids={k:stamp(sdk/'bin'/k) for k in ('cargo','rustc')}
    ids['driver']=stamp(driver)
    proof=json.loads((data/'strict-build.json').read_bytes());dist=json.loads((data/'21/installed.json').read_bytes());env=env_for(root/'proof',sdk)
    assert ids['rustc']['sha256']==dist['bin/rustc'] and ids['driver']['sha256']==dist[str(driver.relative_to(sdk))]
    rust=subprocess.check_output(['rustc','+ohm','-vV'],env=env,text=True);assert 'c79998a5cd143c445a4b2528f20953b176a65c5d' in rust and 'ohm-1.99.0-21' in rust
    assert Path(subprocess.check_output(['rustc','+ohm','--print','sysroot'],env=env,text=True).strip()).samefile(sdk)
    assert not {'CI','TF_BUILD','RUSTFLAGS','RUSTC_WRAPPER','CARGO_INCREMENTAL'}&set(env)
    assert all(sha(p)==sha(signed/p.relative_to(sdk)) for p in (sdk/'lib/rustlib/aarch64-apple-darwin/lib').iterdir() if p.is_file())
    products={}
    for name,source in [('strict',C),('signed',P)]:
        installed=install(root,sdk,name);v=subprocess.check_output(['cargo','+ohm','-Vv'],env=env,text=True);assert 'commit-hash: '+source+'\n' in v
        products[name]={'version':v,'sha256':installed['sha256'],'source':source}
    assert products['strict']['sha256']==proof['compiled'] and products['signed']['sha256']==dist['bin/cargo']
    ld=Path(subprocess.check_output(['xcrun','--find','ld'],text=True).strip()).resolve();code=subprocess.run(['/usr/bin/codesign','-dv','--verbose=4',ld],capture_output=True,check=True)
    dot={'driver':physical(driver),'rustc':physical(sdk/'bin/rustc'),'rustc_version':rust,'ld':stamp(ld),'xcode_signing':code.stderr.decode(),'sources':products,'qa':os.environ['GITHUB_SHA']}
    save(data/'release.json',dot)
    cases=checks();save(data/'registration.json',{'schedule':cases,'legacy_barrier':release_legacy.BARRIER,'archive_owner':True,'command':['cargo','+ohm','build','--locked','--offline','-j4','--message-format=json'],'prior_source':'14c9d13d68f3dd21c53f1ef6c3721de8363c0123'})
    archives=edge.provider_factory(root,data/'provider-matrix');trace=ExecTrace();trace.ready()
    observed={}
    try:
        for kind,place,policy,seq in cases:
            install(root,sdk,'signed');it=iter(seq);prev=None;current='signed';case_name=kind+'-'+place+'-'+policy+'-default'
            def change(src,state,bodies):
                nonlocal current,prev
                name,target,rust=next(it);assert target==state
                next_role='signed' if name.startswith('signed-') else 'strict'
                if current!=next_role:
                    assert name.startswith('upgrade-') and prev is not None
                    work=root/'provider-build';old=namespace(src,work)
                    rep=json.loads((data/'provider-matrix'/case_name/prev/'warm/verified.json').read_bytes())
                    assert rep['status']==0 and Path(rep['returned']).is_file() and sha(Path(rep['returned']))==rep['image']['raw']
                    before=stamp(sdk/'bin/cargo');d_before=stamp(driver);after=install(root,sdk,next_role)
                    assert old==namespace(src,work) and before['sha256']!=after['sha256'] and d_before==stamp(driver)==ids['driver']
                    assert (src/('early/libqa_owned_external.a')).exists()==(state in ('higher','malformed'))
                    compact_zip(data/'switches'/(case_name+'.json.gz'),{'namespace':old,'source':str(src),'old':before,'new':after,
                               'driver':d_before,'previous':prev,'warm_product':rep['image']['raw'],'warm_return':rep['returned'],'old_value':rep['answer'],'next':name})
                current=next_role;prev=name
                return edge.configure(src,state,bodies)
            if kind=='archive-owner':edge.form=actual_archive_owner
            try:
                rows=edge.run_case(root,trace,'signed-v1',place,policy,True,archives,visits=seq,change=change,evidence=fixed_crc.evidence,
                                   label=kind,sdk_override=sdk,barrier=release_legacy.BARRIER)
            finally:edge.form=BASE_FORM
            observed[case_name]=rows
            print(case_name,[(n,r['warm'][:2],r['empty'][:2]) for n,r in rows.items()],flush=True)
    finally:trace.close()
    save(data/'observed-terminal.json',{'cases':list(observed),'warm':sum(len(a) for a in observed.values()),'commands':sum(len(a)*2 for a in observed.values())})
if __name__=='__main__':run(Path(sys.argv[1]))
