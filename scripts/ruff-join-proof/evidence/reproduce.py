"""Exercise a dependency's real .rmeta as a source input to a Cargo check."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--sdk', required=True, type=Path, help='extracted signed -23 Rust SDK')
parser.add_argument('--cargo', required=True, type=Path, help='actual Cargo binary to test')
parser.add_argument('--cargo-sha256', required=True)
parser.add_argument('--work', required=True, type=Path, help='new, empty workspace')
parser.add_argument('--expect', required=True, choices=['shipped', 'fixed', 'upstream'])
parser.add_argument('--split', action='store_true', help='run the producer separately before checking the client')
parser.add_argument('--mtime', action='store_true', help='ordinary explicit remap, disabling signed worktree checksum seeds')
parser.add_argument('--under-cargo-home', action='store_true', help='use actual generated artifact paths under CARGO_HOME/registry')
args = parser.parse_args()
def sha(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file,'sha256').hexdigest()
assert sha(args.cargo) == args.cargo_sha256
sdk = args.sdk.resolve(strict=True)
work = args.work.absolute()
work.mkdir(parents=True, exist_ok=False)
rustup = work/'rustup'
tool = rustup/'toolchains/ohm'
binary = tool/'bin'
binary.mkdir(parents=True)
for f in sdk.iterdir():
    if f.name != 'bin':
        (tool/f.name).symlink_to(f)
for f in (sdk/'bin').iterdir():
    (binary/f.name).symlink_to(args.cargo.resolve() if f.name == 'cargo' else f)
proxy = Path(shutil.which('rustup')).absolute().parent/'cargo'
env = {k:os.environ[k] for k in ('PATH','HOME','LANG','LD_LIBRARY_PATH') if k in os.environ}
home = work/'cargo-home'
base = home/'registry/private-output' if args.under_cargo_home else work
target, shared = base/'target', base/'shared'
env.update(CARGO_HOME=str(home), RUSTUP_HOME=str(rustup), RUSTUP_TOOLCHAIN='ohm',
           CARGO_TARGET_DIR=str(target), CARGO_BUILD_BUILD_DIR=str(shared))
if args.mtime:
    env['RUSTFLAGS'] = '--remap-path-prefix=/ohm-never-an-input=/also-not-an-input'
v = subprocess.check_output([str(proxy.with_name('rustc')),'+ohm','-vV'],env=env,text=True)
assert 'd57fd1515986dccecdcece8da85e651bfb4b81f9' in v, v
assert subprocess.check_output([proxy,'+ohm','-Vv'],env=env) == subprocess.check_output([args.cargo,'-Vv'],env=env)
source = work/'source'
for name in ('producer','client'):
    (source/name/'src').mkdir(parents=True)
    (source/name/'Cargo.toml').write_text(f'[package]\nname="{name}"\nversion="0.1.0"\nedition="2024"\n'+('[dependencies]\nproducer={path="../producer"}\n' if name=='client' else ''))
(source/'Cargo.toml').write_text('[workspace]\nmembers=["producer","client"]\nresolver="3"\n')
old = '#![allow(dead_code)]\npub const API:u8=1;fn private()->u8{10}\n'
producer = source/'producer/src/lib.rs'
client = source/'client/src/lib.rs'
producer.write_text(old)
client.write_text('pub use producer::API;\n')
rows = {}
def check(label, package='client'):
    cp = subprocess.run([proxy,'+ohm','check','--offline','-p',package,'--message-format=json'],
                        cwd=source,env=env,capture_output=True,timeout=45)
    (work/(label+'.stdout')).write_bytes(cp.stdout)
    (work/(label+'.stderr')).write_bytes(cp.stderr)
    js = [json.loads(l) for l in cp.stdout.splitlines()]
    artifacts = {r['target']['name']:r for r in js if r['reason']=='compiler-artifact'}
    file, = [Path(f) for f in artifacts['producer']['filenames'] if f.endswith('.rmeta')]
    codes = [r['message']['code']['code'] for r in js if r['reason']=='compiler-message' and r['message'].get('code') and r['message']['level']=='error']
    row = {'exit':cp.returncode,'diagnostics':codes,'file':str(file),'sha256':sha(file),
           'mtime_ns':file.stat().st_mtime_ns,'nonfresh':sorted(k for k,r in artifacts.items() if not r['fresh'])}
    rows[label] = row
    (work/'result.json').write_text(json.dumps(rows,indent=2)+'\n')
    return row
discovery = check('discover')
assert discovery['exit'] == 0
actual = Path(discovery['file'])
alias = source/'selected.rmeta'
alias.symlink_to(actual)
expected = actual.read_bytes()
h = 14695981039346656037
for b in expected:
    h = (h^b)*1099511628211 & ((1<<64)-1)
include = json.dumps(str(actual) if args.under_cargo_home else '../../selected.rmeta')
client.write_text(f'pub use producer::API;const B:&[u8]=include_bytes!({include});\n'
                  'const fn hash(b:&[u8])->u64{let mut h=14695981039346656037u64;let mut i=0;'
                  'while i<b.len(){h=(h^(b[i] as u64)).wrapping_mul(1099511628211);i+=1}h}\n'
                  f'const _: [();1]=[();(hash(B)=={h})as usize];\n')
a=check('old')
assert a['exit']==check('old-unchanged')['exit']==0
time.sleep(1.10)
producer.write_text(old.replace('10','20'))
if args.split:
    assert check('separate-producer','producer')['exit']==0
b=check('edit')
c=check('next-unchanged')
assert b['sha256']!=a['sha256'] and b['sha256']==c['sha256'] and alias.samefile(b['file'])
for path in (target,shared):
    if path.exists():
        path.rename(path.with_name(path.name+'-prior'))
fresh=check('empty')
assert fresh['diagnostics']==['E0308'] and fresh['sha256']==b['sha256'] and alias.samefile(fresh['file'])
if args.expect in ('upstream','fixed'):
    assert b['diagnostics']==c['diagnostics']==['E0308'] and b['exit']==c['exit']==101
else:
    assert b['exit']==0 and (c['exit']==0 if args.mtime else c['diagnostics']==['E0308'])
    if args.mtime:
        assert b['mtime_ns']==a['mtime_ns']
time.sleep(1.10)
producer.write_text(old)
assert check('repair')['exit']==0
print(json.dumps({k:[v['exit'],v['diagnostics'],v['sha256']]for k,v in rows.items()},indent=2))
