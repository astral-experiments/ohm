"""Run the original two-crate Cargo check against an authenticated Ohm toolchain and reopen its rmeta."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import traceback
import subprocess
import time

arg = argparse.ArgumentParser()
arg.add_argument('--rustup-home', required=True, type=Path)
arg.add_argument('--out', required=True, type=Path)
arg.add_argument('--role', required=True, choices=['parent','candidate'])
arg.add_argument('--wait-for-reserve', action='store_true')
arg.add_argument('--compiler-sha', required=True, help='SHA-256 of librustc_driver (both SDKs may identify as the same Rust commit).')
a = arg.parse_args()
out=a.out.resolve()
out.mkdir(exist_ok=False,parents=True)
w=out/'workspace'
(w/'dep/src').mkdir(parents=True)
(w/'app/src').mkdir(parents=True)
(w/'Cargo.toml').write_text('[workspace]\nmembers = ["dep", "app"]\nresolver = "3"\n')
(w/'dep/Cargo.toml').write_text('[package]\nname="dep"\nversion="0.0.0"\nedition="2024"\n')
(w/'app/Cargo.toml').write_text('[package]\nname="app"\nversion="0.0.0"\nedition="2024"\n[dependencies]\ndep={path="../dep"}\n')
(w/'Cargo.lock').write_text('version = 4\n\n[[package]]\nname = "app"\nversion = "0.0.0"\ndependencies = ["dep"]\n\n[[package]]\nname = "dep"\nversion = "0.0.0"\n')
(w/'app/src/main.rs').write_text('fn needs_send<T: Send>(_: T) {}\nfn main() { needs_send(dep::observed!()); }\n')
hidden = '''pub(super) fn classify(value: u8) -> bool { value == 0 }
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Hidden { Value(u8) }
'''
moved = hidden.replace('value == 0 }\n','value == 1 }\n\n')
interface='''#![allow(dead_code)]
mod hidden;
pub fn visible() -> impl std::fmt::Debug { 7u8 }
#[macro_export]
macro_rules! observed { () => { $crate::visible() }; }
'''
generated=interface+'''macro_rules! produce { () => {
    #[macro_export] macro_rules! generated { () => { 7u8 }; }
} }
produce!();
'''
opaque=interface.replace('{ 7u8 }','{ hidden::Hidden::Value(Default::default()) }',1)
env={**os.environ,'RUSTUP_HOME':str(a.rustup_home.resolve()),'CARGO_HOME':str(out/'cargo-home')}
assert not any(env.get(k) for k in ('RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','RUSTC','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST','CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST'))
def invoke(argv,quiet=True):
    return subprocess.run(argv,cwd=w,env=env,capture_output=quiet)
def sha(p):
    with p.open('rb') as src: return hashlib.file_digest(src,'sha256').hexdigest()
rustc=Path(invoke(['rustup','which','--toolchain','ohm','rustc']).stdout.decode().strip()).resolve()
driver,=list((rustc.parent.parent/'lib').glob('librustc_driver-*.so'))
assert sha(driver)==a.compiler_sha
def guard():
    mem=int(re.search(r'^MemAvailable:\s*(\d+)',Path('/proc/meminfo').read_text(),re.M)[1])*1024
    while a.wait_for_reserve and mem < (8<<30)+(256<<20):
        time.sleep(10)
        mem=int(re.search(r'^MemAvailable:\s*(\d+)',Path('/proc/meminfo').read_text(),re.M)[1])*1024
    assert mem >= (8<<30)+(256<<20),f'host reserve: {mem} available; no compilation started'
    st=os.statvfs(out)
    assert st.f_bavail*st.f_frsize>=15<<30
def save(p, value):
    p.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


active_phase = out
def retain_failure(ty, value, tb):
    save(active_phase/'failure.json', {'type': ty.__name__, 'message': str(value),
                                      'traceback': traceback.format_exception(ty, value, tb)})
    sys.__excepthook__(ty, value, tb)
sys.excepthook = retain_failure


def stamp(path):
    st=path.stat()
    return {'path':str(path.resolve()), 'dev':st.st_dev, 'ino':st.st_ino, 'size':st.st_size,
            'mtime_ns':st.st_mtime_ns, 'ctime_ns':st.st_ctime_ns, 'nlink':st.st_nlink}


def output_snapshot(directory, paths):
    directory.mkdir()
    result={}
    for name, outputs in paths.items():
        result[name]={}
        for kind, path in outputs.items():
            if not path.exists():
                result[name][kind]={'path':str(path),'missing':True}
                continue
            first=stamp(path); data=path.read_bytes()
            assert first==stamp(path) and len(data)==first['size'], ('unstable output', path)
            (directory/(name+'.'+kind)).write_bytes(data)
            result[name][kind]={**first,'sha256':hashlib.sha256(data).hexdigest()}
    save(directory/'outputs.json',result)
    return result


def owners(directory):
    decoder=json.JSONDecoder()
    result={'rustc':dict(stamp(rustc),sha256=sha(rustc)), 'driver':dict(stamp(driver),sha256=sha(driver)),
            'compiles':[], 'other_rustc_execs':[], 'streams':{}}
    for raw in sorted(directory.glob('exec.*')):
        pid=int(raw.name.split('.')[-1])
        data=raw.read_bytes(); lines=data.decode().splitlines()
        result['streams'][str(pid)]=hashlib.sha256(data).hexdigest()
        for line in lines:
            if not line.startswith('execve(') or not line.endswith(' = 0'): continue
            image,n=decoder.raw_decode(line[len('execve('):])
            rest=line[len('execve(')+n:].lstrip(', ')
            argv,_=decoder.raw_decode(rest)
            if Path(image).name!='rustc' and '--crate-name' not in argv: continue
            actual=Path(image).samefile(rustc)
            entry={'pid':pid,'program':image,'argv':argv,'physical_rustc':actual}
            if not actual:
                assert Path(image).samefile(rustup_proxy), ('unknown rustc/proxy',entry)
            if not actual or '--crate-name' not in argv or any(v=='--print' or v.startswith('--print=') for v in argv):
                result['other_rustc_execs'].append(entry)
                continue
            crate=argv[argv.index('--crate-name')+1]
            assert crate in ('app','dep') and '--emit=dep-info,metadata' in argv, ('unexpected physical compiler',entry)
            assert argv[argv.index('--crate-type')+1]=={'app':'bin','dep':'lib'}[crate]
            maps=[ln for ln in lines if ln.startswith('mmap(') and 'PROT_EXEC' in ln and
                  '<'+str(driver.resolve())+'>' in ln and re.search(r' = 0x[0-9a-f]+$',ln)]
            assert maps, ('missing actual executable driver mapping',pid,crate)
            result['compiles'].append(dict(entry,crate=crate,executable_driver_maps=maps))
        (directory/(raw.name+'.gz')).write_bytes(gzip.compress(data,compresslevel=1,mtime=0))
        raw.unlink()
    return result


rustup_proxy=Path(invoke(['which','rustup']).stdout.decode().strip()).resolve(strict=True)
known_outputs={}
def phase(label,mode,src,success=True,clean=False,traced=False):
    global active_phase
    d=out/label;d.mkdir();active_phase=d
    guard()
    interface_path=w/'dep/src/lib.rs'; hidden_path=w/'dep/src/hidden.rs'
    def replace(p,value):
        if not p.exists() or p.read_text()!=value: p.write_text(value)
    replace(interface_path,mode);replace(hidden_path,src)
    target=str(out/('kernel' if traced else 'clean' if clean else 'ordinary'))
    env.update(CARGO_BUILD_BUILD_DIR=target+'-build',CARGO_TARGET_DIR=target+'-target')
    cmd=['cargo','+ohm','check','-p','app','--locked','--offline','-j1','--message-format=json']
    argv=cmd
    if traced:
        trace=d/'trace';trace.mkdir()
        argv=['/usr/bin/strace','-ff','-qq','-yy','-s','131072','-e','trace=execve,mmap','-o',str(trace/'exec'),*cmd]
    paths=known_outputs.setdefault(target,{})
    before=output_snapshot(d/'before',paths)
    save(d/'invocation.json',{'argv':argv,'cargo':cmd,'expected_success':success,'target':target+'-target',
                               'build':target+'-build','sources':{'lib.rs':sha(interface_path),'hidden.rs':sha(hidden_path)}})
    run=invoke(argv);(d/'stdout').write_bytes(run.stdout);(d/'stderr').write_bytes(run.stderr)
    save(d/'exit.json',{'returncode':run.returncode})
    rows=[json.loads(s)for s in run.stdout.splitlines()]
    assert rows[-1]=={'reason':'build-finished','success':success},(run.returncode,run.stderr)
    assert run.returncode==(0 if success else 101)
    artifacts=[r for r in rows if r['reason']=='compiler-artifact']
    dirty=[r['target']['name'] for r in artifacts if not r['fresh']]
    for artifact in artifacts:
        name=artifact['target']['name']
        assert name in ('app','dep')
        meta,=[Path(s) for s in artifact['filenames'] if s.endswith('.rmeta')]
        depinfo=meta.with_name(meta.name.removeprefix('lib')).with_suffix('.d')
        assert meta.is_file() and depinfo.is_file(), ('missing physical compiler output',meta,depinfo)
        paths[name]={'rmeta':meta,'d':depinfo}
    after=output_snapshot(d/'after',paths)
    kernel=None
    if traced:
        kernel=owners(trace)
        save(d/'kernel.json',kernel)
    meta=paths['dep']['rmeta']
    status=invoke(['rustc','+ohm',str(meta),'-Zls=public_hash']);status.check_returncode()
    fingerprint=status.stdout.decode().strip()
    assert re.fullmatch(r'[a-f0-9]{16,64}',fingerprint.split()[-1]),fingerprint
    errors=[r['message']for r in rows if r['reason']=='compiler-message' and r['message']['level']=='error']
    if not success:
        assert len(errors)==1 and errors[0]['code']['code']=='E0277' and 'Send' in errors[0]['rendered']
        assert any(r['package_id'].endswith('/app#0.0.0') or 'app' in r['package_id'] for r in rows if r['reason']=='compiler-message' and r['message']['level']=='error')
    result={'argv':cmd,'returncode':run.returncode,'dirty':dirty,'provider_public':fingerprint,
            'provider_rmeta':sha(meta),'sources':{'lib.rs':sha(interface_path),'hidden.rs':sha(hidden_path)},
            'before':before,'after':after,'kernel':None if kernel is None else sorted(v['crate'] for v in kernel['compiles']),
            'errors':[m['code']['code']for m in errors]}
    save(d/'readback.json',result)
    return result
book={}
def get(label,*args,**kw):
    book[label]=phase(label,*args,**kw);return book[label]
old=get('private-old',interface,hidden)
assert old['dirty']==['dep','app']
assert not get('private-old-unchanged',interface,hidden)['dirty']
edit=get('private-edit',interface,moved)
assert not get('private-edit-unchanged',interface,moved)['dirty']
repair=get('private-repair',interface,hidden)
assert repair['provider_public']==old['provider_public']
allow=a.role=='candidate'
assert (old['provider_public']==edit['provider_public'])==allow
gen=get('generated-old',generated,hidden)
gen_move=get('generated-edit',generated,moved)
assert gen['provider_public']!=gen_move['provider_public'] and gen_move['dirty']==['dep','app']
good=get('opaque-old',opaque,moved)
fail=get('opaque-raw-pointer',opaque,moved.replace('Value(u8)','Value(*const u8)'),False)
assert good['provider_public']!=fail['provider_public']
fix=get('opaque-repair',opaque,moved)
assert fix['provider_public']==good['provider_public'] and not get('opaque-repair-unchanged',opaque,moved)['dirty']
empty=get('empty-private-edit',interface,moved,clean=True)
assert empty['provider_public']==edit['provider_public']
kernel={}
for name,old_phase,body in [('old','private-old',hidden),('unchanged','private-old-unchanged',hidden),('edit','private-edit',moved)]:
    observed=phase('kernel-'+name,interface,body,traced=True)
    original=book[old_phase]
    assert all(observed[k]==original[k] for k in ('returncode','provider_public','errors','sources','dirty')), ('observer changed ordinary verdict, header or Cargo roster',name)
    kernel[name]=observed
assert set(kernel['old']['after'])==set(kernel['unchanged']['after'])==set(kernel['edit']['after'])=={'dep','app'}
assert kernel['old']['kernel']==['app','dep'] and kernel['unchanged']['kernel']==[], 'cold or unchanged physical compiler roster'
assert kernel['unchanged']['before']==kernel['old']['after'] and kernel['unchanged']['after']==kernel['edit']['before'], 'physical history changed between Cargo commands'
assert kernel['unchanged']['after']==kernel['unchanged']['before'], 'unchanged Cargo rewrote physical outputs'
assert kernel['edit']['kernel']==(['dep'] if allow else ['app','dep']), ('actual edited compiler roster',kernel['edit']['kernel'],edit['dirty'])
assert sorted(edit['dirty']) in ([['dep'],['app','dep']] if allow else [['app','dep']]), ('unexpected typed roster',edit['dirty'])
if allow:
    for kind in ('rmeta','d'):
        assert kernel['edit']['after']['app'][kind]['sha256']==kernel['edit']['before']['app'][kind]['sha256'], ('ungenerated consumer output content changed',kind)
fact={'role':a.role,'rustc':invoke(['rustc','+ohm','-vV']).stdout.decode(),'driver':str(driver),'driver_sha256':a.compiler_sha,'phases':book,'kernel':kernel}
(out/'accepted.json').write_text(json.dumps(fact,indent=2)+'\n')
print(json.dumps({k:(v['dirty'],v['errors'],v['provider_public'])for k,v in book.items()},indent=2))
