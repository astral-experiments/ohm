"""Compare the actual GNU linker and normal Cargo when a new transitive provider appears."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('root',type=Path)
parser.add_argument('--wild-dir',type=Path,required=True)
parser.add_argument('--cargo',action='store_true')
parser.add_argument('--toolchain',default='ohm')
args=parser.parse_args()
root=args.root.resolve()
root.mkdir(parents=True,exist_ok=False)
native=root/'native';native.mkdir()
out=root/'results';out.mkdir()
calls={}

def h(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def run(name,command,env=None,stdin=None,required=True):
    res=subprocess.run(command,cwd=root,env=env,input=stdin,capture_output=True)
    (out/(name+'.stdout')).write_bytes(res.stdout)
    (out/(name+'.stderr')).write_bytes(res.stderr)
    calls[name]={'argv':[str(s) for s in command],'status':res.returncode}
    if required and res.returncode:raise RuntimeError((name,res.stderr[-2800:]))
    return res

def put(path,text):path.write_text(text+'\n')

def obj(name,code):
    run('compile-'+name,['cc','-fPIC','-x','c','-c','-o',native/(name+'.o'),'-'],stdin=code.encode())

def archive(name,objname):
    run('pack-'+name,['ar','rcs',native/('lib'+name+'.a'),native/(objname+'.o')])

obj('answer','extern int ohm_provider(void); int answer(void){return ohm_provider();}')
obj('old','int ohm_provider(void){return 17;}')
obj('new','int ohm_provider(void){return 29;}')
obj('main','extern int answer(void); int main(void){return answer();}')
archive('answer','answer');archive('ohm_private','old');archive('ohm_alternate','new')
libgcc=Path(run('system-libgcc',['cc','-print-file-name=libgcc_s.so.1']).stdout.decode().strip()).resolve(strict=True)
put(native/'libgcc_s.so','GROUP ( '+str(libgcc)+' -lohm_private )')
provider=native/'libohm_private.so'
fallback=(native/'libohm_private.a')
original={str(p):h(p) for p in [native/'libanswer.a',native/'libgcc_s.so',fallback,native/'libohm_alternate.a',libgcc]}
wild=args.wild_dir.resolve()/'ld.bfd'
assert wild.is_file()

def switch(mode):
    if mode=='new':put(provider,'INPUT ( '+str(native/'libohm_alternate.a')+' )')
    elif mode=='bad':put(provider,'INPUT ( /missing-real-ohm-transitive-provider )')
    else:provider.unlink(missing_ok=True)
    assert original=={p:h(Path(p)) for p in original}

direct={}
for label,prefix in [('gnu',[]),('wild',['-B'+str(wild.parent),'-fuse-ld=bfd'])]:
    direct[label]={}
    for mode,expected in [('old',17),('new',29),('bad',None),('restored',17)]:
        switch(mode)
        name=label+'-'+mode
        exe=out/name;depfile=out/(name+'.d')
        proc=run(name,['cc',*prefix,'-o',exe,native/'main.o','-L'+str(native),'-Wl,-Bstatic','-lanswer',
            '-Wl,-Bdynamic','-lgcc_s','-Wl,--dependency-file='+str(depfile)],required=False)
        actual=run(name+'-native',[exe],required=False).returncode if proc.returncode==0 else None
        direct[label][mode]=dict(link=proc.returncode,exit=actual,depfile=depfile.read_text() if depfile.exists() else None)
        assert actual==expected,(label,mode,actual,proc.stderr[-900:])

result={'wild':{'path':str(wild),'sha256':h(wild)},'stable_files':original,'direct':direct,'cargo':{},'commands':calls}

def cargo_probe():
    (root/'src').mkdir();(root/'engine/src').mkdir(parents=True)
    put(root/'Cargo.toml','[package]\nname="reader"\nversion="0.0.0"\nedition="2021"\n[dependencies]\nengine={path="engine"}')
    put(root/'engine/Cargo.toml','[package]\nname="engine"\nversion="0.0.0"\nedition="2021"')
    put(root/'engine/src/lib.rs','pub fn register(v: i32) -> i32 { unsafe { core::arch::asm!("/* {0:e} */", in(reg) v, options(nostack, nomem, preserves_flags)); } v }')
    put(root/'src/main.rs','extern "C" { fn answer() -> i32; } fn main() { println!("{}",engine::register(unsafe { answer() })); }')
    put(root/'build.rs','fn main() { let dir=std::env::var("CARGO_MANIFEST_DIR").unwrap(); for f in ["libanswer.a","libohm_private.a","libohm_alternate.a","libgcc_s.so"] { println!("cargo::rerun-if-changed={dir}/native/{f}"); } println!("cargo::rustc-link-search=native={dir}/native"); println!("cargo::rustc-link-lib=static=answer"); }')
    driver=root/'count-cc'
    put(driver,'#!/bin/sh\nfor arg do if [ "$arg" = -o ]; then echo link >>"$OHM_TRANSITIVE_LINK_LOG"; break; fi; done\nexec cc "$@"');driver.chmod(0o755)
    log=root/'links';log.touch()
    env=os.environ|{'CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER':str(driver),'CARGO_INCREMENTAL':'1',
        'CARGO_PROFILE_DEV_DEBUG':'0','CARGO_NET_OFFLINE':'true','CARGO_HOME':str(root/'cargo-home'),
        'OHM_TRANSITIVE_LINK_LOG':str(log),'LC_ALL':'C','CARGO_TERM_COLOR':'never'}
    assert 'RUSTFLAGS' not in env and 'RUSTC_WRAPPER' not in env
    cargo=shutil.which('cargo');assert cargo
    tool='+'+args.toolchain
    for binary in ('cargo','rustc'):
        r=run('version-'+binary,[shutil.which(binary),tool,'-vV'],env);result[binary+'_version']=r.stdout.decode()
    for phase,mode,tag in [('seed','old','warm'),('unchanged','old','warm'),('new','new','warm'),('new-clean','new','new-clean'),
        ('bad','bad','warm'),('bad-clean','bad','bad-clean'),('restored','restored','warm'),('old-clean','restored','old-clean')]:
        switch(mode)
        dest=root/tag;target=dest/'target';build=dest/'build';log.write_text('')
        cmd_env=env|{'CARGO_TARGET_DIR':str(target),'CARGO_BUILD_BUILD_DIR':str(build)}
        res=run('cargo-'+phase,[cargo,tool,'build','--offline','--message-format=json'],cmd_env,required=False)
        row={'status':res.returncode,'links':len(log.read_text().splitlines())}
        if res.returncode==0:
            exe=target/'debug/reader';native_run=run('exec-'+phase,[exe]);row.update(value=int(native_run.stdout),elf=h(exe))
        closures={}
        for base in (target,build):
            for path in base.glob('**/declared-native/inputs.json'):
                content=path.read_bytes();closures[str(path)]=json.loads(content)
        row['closures']=closures;result['cargo'][phase]=row
    print([(k,v['status'],v.get('value'),v['links'],len(v['closures'])) for k,v in result['cargo'].items()],flush=True)

try:
    if args.cargo:cargo_probe()
finally:
    with (out/'evidence.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
print(out/'evidence.json',flush=True)
