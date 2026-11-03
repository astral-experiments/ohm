"""Exercise a genuine procedural derive with ordinary Cargo and inspect rustc's mono inventory."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

root=Path(sys.argv[1]).resolve();role=sys.argv[2];assert role in ('parent','candidate')
root.mkdir(parents=True);env={**os.environ,'CARGO_HOME':str(root/'cargo'),'CARGO_TARGET_DIR':str(root/'target'),'CARGO_BUILD_BUILD_DIR':str(root/'shared'),'CARGO_NET_OFFLINE':'true','CARGO_BUILD_JOBS':'1'}
for name in ('RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','RUSTC_WRAPPER','CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST','CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST'):assert not env.get(name),name
def put(name,data):
 p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data)
def run(name,argv,rc=0):
 t=subprocess.run(argv,cwd=root,env=env,capture_output=True);(root/(name+'.out')).write_bytes(t.stdout);(root/(name+'.err')).write_bytes(t.stderr)
 if t.returncode!=rc:raise RuntimeError((name,t.returncode,t.stderr[-3000:]))
 return (t.stdout+t.stderr).decode()
put('Cargo.toml','[workspace]\nresolver="2"\nmembers=["make","owner_case"]\n[profile.dev]\nopt-level=1\ncodegen-units=16\n')
put('make/Cargo.toml','[package]\nname="make"\nversion="0.1.0"\nedition="2021"\n[lib]\nproc-macro=true\n')
put('make/src/lib.rs','''
use proc_macro::{TokenStream, TokenTree};
#[proc_macro_derive(Methods)]
pub fn methods(input: TokenStream) -> TokenStream {
    let mut it = input.into_iter();
    assert!(it.any(|t| matches!(t, TokenTree::Ident(i) if i.to_string() == "struct")));
    let name = it.next().unwrap().to_string();
    format!(r#"#[automatically_derived] impl Score for {name} {{
        #[inline(never)] fn twice(&self,y:i64)->i64 {{ std::hint::black_box(self.0*y+{name}::DELTA) }}
        #[inline(never)] fn add(&self,y:i64)->i64 {{ std::hint::black_box(self.0+y+{name}::DELTA) }}
    }}"#).parse().unwrap()
}
''')
put('owner_case/Cargo.toml','[package]\nname="owner_case"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nmake={path="../make"}\n')
body='''
use make::Methods;
pub trait Score { fn twice(&self,y:i64)->i64; fn add(&self,y:i64)->i64; }
#[derive(Methods)] pub struct Alpha(i64);
#[derive(Methods)] pub struct Beta(i64);
#[derive(Methods)] pub struct Gamma(i64);
impl Alpha { const DELTA:i64=3; }
impl Beta { const DELTA:i64=7; }
impl Gamma { const DELTA:i64=11; }
fn main() {
    let v:i64=std::env::args().nth(1).unwrap().parse().unwrap();
    let value=Alpha(2).twice(v)+Alpha(2).add(v)+Beta(3).twice(v)+Beta(3).add(v)+Gamma(4).twice(v)+Gamma(4).add(v);
    println!("{value}");
}
'''
path='owner_case/src/main.rs';put(path,body)
base=['cargo','+ohm','build','-p','owner_case','--offline'];selected=['cargo','+ohm','rustc','-p','owner_case','--offline','--','-Zprint-mono-items=yes','-Zhuman-readable-cgu-names=yes']
def verdict(name,extra):
 exe=Path(env['CARGO_TARGET_DIR'])/'debug/owner_case';v=[run(name+'-'+str(x),[str(exe),str(x)]).strip() for x in (4,9)];assert v==[str(12*x+9+42+extra)for x in(4,9)],v;return {'values':v,'elf':hashlib.sha256(exe.read_bytes()).hexdigest()}
run('old',base);old=verdict('old-native',0)
rows=run('mono',selected).splitlines();pick={}
for ty in ('Alpha','Beta','Gamma'):
 seen={x.split(' @@ ',1)[1].split('[',1)[0].strip()for x in rows if x.startswith('MONO_ITEM fn ')and ('<'+ty+' as Score>')in x and re.search(r'::(add|twice) @@ ',x)};assert len(seen)==1,(ty,[x for x in rows if ty+' as' in x][:8]);pick[ty]=seen.pop()
assert (all('-ohm-derived-'in x for x in pick.values()) and len(set(pick.values()))==3)if role=='candidate'else(all('-ohm-derived-'not in x for x in pick.values())),pick
edit=body.replace('DELTA:i64=3','DELTA:i64=13');put(path,edit);run('edited',base);new=verdict('edited-native',20);assert old['elf']!=new['elf'];run('unchanged',base);put(path,edit+'\nconst BAD: u16 = "wrong";\n');assert 'E0308'in run('invalid',base,101);assert 'E0308'in run('invalid-again',base,101);put(path,edit);run('repair',base);assert verdict('repaired-native',20)==new
env.update(CARGO_TARGET_DIR=str(root/'empty-target'),CARGO_BUILD_BUILD_DIR=str(root/'empty-shared'));run('clean',base);fresh=verdict('clean-native',20);assert fresh['values']==new['values']
(root/'verdict.json').write_text(json.dumps({'role':role,'named_native_units':pick,'old':old,'edit':new,'clean':fresh,'raw_mono_sha256':hashlib.sha256((root/'mono.out').read_bytes()).hexdigest()},sort_keys=True,indent=2)+'\n')
