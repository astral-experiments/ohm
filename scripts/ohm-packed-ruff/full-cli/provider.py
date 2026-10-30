"""Use two real branches to exercise changed native bytes, damaged input and recovery."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/'harness')]
from native import run
from omission import publish,require,sha


def native_controls(arm,base_env,root,logs):
    work=root/('provider-'+arm);work.mkdir();out=logs/('provider-'+arm);out.mkdir();src=work/'source';src.mkdir();(src/'src').mkdir();lib=src/'private-native';lib.mkdir()
    env=base_env|{'CARGO_TARGET_DIR':str(work/'target'),'CARGO_BUILD_BUILD_DIR':str(work/'build'),'GIT_AUTHOR_NAME':'Ohm QA','GIT_AUTHOR_EMAIL':'qa@example.invalid','GIT_COMMITTER_NAME':'Ohm QA','GIT_COMMITTER_EMAIL':'qa@example.invalid'}
    def git(*args):return subprocess.check_output(['git','-c','commit.gpgsign=false','-C',src,*args],env=env,text=True).strip()
    git('init','-q','--template=','-b','historical-parent');(src/'Cargo.toml').write_text('[package]\nname="packed_native_check"\nversion="0.0.0"\nedition="2024"\n[workspace]\n')
    (src/'Cargo.lock').write_text('version = 4\n\n[[package]]\nname = "packed_native_check"\nversion = "0.0.0"\n');(src/'.gitignore').write_text('/private-native/\n')
    (src/'build.rs').write_text('fn main() { println!("cargo::rerun-if-changed=private-native/libguard.a");println!("cargo::rustc-link-search=native={}/private-native",std::env::var("CARGO_MANIFEST_DIR").unwrap());println!("cargo::rustc-link-lib=static=guard"); }\n')
    body='unsafe extern "C" { fn value() -> i32; }\n#[inline(never)] fn branch() -> u8 { std::hint::black_box(BRANCH) }\nfn main() { println!("{} {}", unsafe { value() }, branch()); }\n'
    source=src/'src/main.rs';source.write_text(body.replace('BRANCH','1'));git('add','.');git('commit','-qm','Native witness A');git('switch','-qc','historical-feature');source.write_text(body.replace('BRANCH','2'));git('add','src/main.rs');git('commit','-qm','Native witness B')
    archive=lib/'libguard.a';rows={}
    for label,branch,value in (('cold-A','historical-parent',17),('first-B','historical-feature',29),('returned-A','historical-parent',29),('invalid','historical-parent',None),('repair','historical-parent',29),('empty-repair','historical-parent',29)):
        where=out/label;where.mkdir();git('switch','-q',branch)
        if label=='empty-repair':
            for path in (work/'target',work/'build'):
                require(path.is_dir() and not path.is_symlink() and path.parent==work,'unowned native fixture target');shutil.rmtree(path)
        if value is None:archive.write_bytes(b'!<arch>\ntruncated actual native archive\n')
        else:
            (lib/'provider.c').write_text(f'int value(void){{return {value};}}\n');subprocess.run(['cc','-c','provider.c','-o','provider.o'],cwd=lib,check=True);archive.unlink(missing_ok=True);subprocess.run(['ar','crs','libguard.a','provider.o'],cwd=lib,check=True)
        rc=101 if value is None else 0;child=run(['cargo','+ohm','build','--offline','--locked','-j4','--message-format=json'],env,src,where/'cargo',rc);events=list(map(json.loads,child.stdout.splitlines()));require(events[-1]=={'reason':'build-finished','success':value is not None},'bad native Cargo verdict');row={'archive':sha(archive),'exit':rc}
        if value is None:require(b'link' in (child.stdout+child.stderr).lower(),'native archive did not reach linker')
        else:
            exe,=[Path(m['executable']) for m in events if m.get('executable')];actual=run([exe],env,src,where/'witness').stdout.decode().strip();require(actual==f"{value} {1 if branch=='historical-parent' else 2}",'stale branch or stale provider');row|={'output':actual,'binary':sha(exe)}
        rows[label]=row
    require(rows['returned-A']['binary']==rows['repair']['binary']==rows['empty-repair']['binary']!=rows['cold-A']['binary'],'native repair differs from independently empty output');publish(out/'result.json',rows)
