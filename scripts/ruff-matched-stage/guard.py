"""Run the original two-crate Cargo check against an authenticated Ohm toolchain and reopen its rmeta."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
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
def phase(label,mode,src,success=True,clean=False):
    guard()
    interface_path=w/'dep/src/lib.rs'; hidden_path=w/'dep/src/hidden.rs'
    def replace(p,value):
        if not p.exists() or p.read_text()!=value: p.write_text(value)
    replace(interface_path,mode);replace(hidden_path,src)
    target=str(out/('clean' if clean else 'ordinary'))
    env.update(CARGO_BUILD_BUILD_DIR=target+'-build',CARGO_TARGET_DIR=target+'-target')
    cmd=['cargo','+ohm','check','-p','app','--locked','--offline','-j1','--message-format=json']
    run=invoke(cmd); d=out/label;d.mkdir();(d/'stdout').write_bytes(run.stdout);(d/'stderr').write_bytes(run.stderr)
    rows=[json.loads(s)for s in run.stdout.splitlines()]
    assert rows[-1]=={'reason':'build-finished','success':success},(run.returncode,run.stderr)
    assert run.returncode==(0 if success else 101)
    artifacts=[r for r in rows if r['reason']=='compiler-artifact']
    dirty=[r['target']['name'] for r in artifacts if not r['fresh']]
    provider,=[r for r in artifacts if r['target']['name']=='dep']
    meta,=[Path(s) for s in provider['filenames'] if s.endswith('.rmeta')]
    status=invoke(['rustc','+ohm',str(meta),'-Zls=public_hash']);status.check_returncode()
    fingerprint=status.stdout.decode().strip()
    assert re.fullmatch(r'[a-f0-9]{16,64}',fingerprint.split()[-1]),fingerprint
    errors=[r['message']for r in rows if r['reason']=='compiler-message' and r['message']['level']=='error']
    if not success:
        assert len(errors)==1 and errors[0]['code']['code']=='E0277' and 'Send' in errors[0]['rendered']
        assert any(r['package_id'].endswith('/app#0.0.0') or 'app' in r['package_id'] for r in rows if r['reason']=='compiler-message' and r['message']['level']=='error')
    result={'argv':cmd,'returncode':run.returncode,'dirty':dirty,'provider_public':fingerprint,
            'provider_rmeta':sha(meta),'sources':{'lib.rs':sha(interface_path),'hidden.rs':sha(hidden_path)},
            'errors':[m['code']['code']for m in errors]}
    (d/'readback.json').write_text(json.dumps(result,indent=2)+'\n')
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
assert edit['dirty']==(['dep'] if allow else ['dep','app'])
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
fact={'role':a.role,'rustc':invoke(['rustc','+ohm','-vV']).stdout.decode(),'driver':str(driver),'driver_sha256':a.compiler_sha,'phases':book}
(out/'accepted.json').write_text(json.dumps(fact,indent=2)+'\n')
print(json.dumps({k:(v['dirty'],v['errors'],v['provider_public'])for k,v in book.items()},indent=2))
