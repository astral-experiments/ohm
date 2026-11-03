"""Ordinary Cargo reproductions for the three released worktree and doctest regressions."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess as sp


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2)+"\n")


class Case:
    def __init__(self, root, sdk, name, base, logs):
        self.work=root/name
        (self.work/"src").mkdir(parents=True)
        (self.work/"Cargo.toml").write_text('[package]\nname="release_case"\nversion="0.0.1"\nedition="2024"\n[workspace]\n')
        self.lib=self.work/"src/lib.rs"
        self.lib.write_text("pub fn documented() {}\n")
        ru=self.work/"rustup/toolchains";ru.mkdir(parents=True);(ru/"ohm").symlink_to(sdk,target_is_directory=True)
        self.logs=logs/name;self.logs.mkdir()
        self.env=dict(base,RUSTUP_HOME=str(ru.parent),RUSTUP_TOOLCHAIN="ohm",CARGO_HOME=str(self.work/"cargo-home"),
                      CARGO_TARGET_DIR=str(self.work/"target"),CARGO_BUILD_BUILD_DIR=str(self.work/"build"),
                      CARGO_NET_OFFLINE="true",RUST_TEST_THREADS="1")
        assert "RUSTC_BOOTSTRAP" not in self.env
        for tool in ("rustc","cargo","rustdoc"):
            live=Path(sp.check_output(["rustup","which","--toolchain","ohm",tool],env=self.env,text=True).strip())
            assert live.samefile(sdk/"bin"/tool)
        self.rows=[]
    def call(self,name,status,needle=None,args=None,extra=None):
        argv=["cargo","+ohm",*(args if args is not None else ["test","--doc","--offline","-v"])]
        p=sp.run(argv,cwd=self.work,env=dict(self.env,**(extra or {})),capture_output=True,timeout=160)
        (self.logs/(name+".stdout")).write_bytes(p.stdout)
        (self.logs/(name+".stderr")).write_bytes(p.stderr)
        r=dict(name=name,status=p.returncode,argv=argv,source=sha(self.lib),
               out=hashlib.sha256(p.stdout).hexdigest(),err=hashlib.sha256(p.stderr).hexdigest())
        self.rows.append(r);save(self.logs/"commands.json",self.rows)
        assert p.returncode==status,(name,p.returncode,p.stdout[-600:],p.stderr[-600:])
        if needle:assert needle in p.stdout+p.stderr,(name,needle,p.stdout[-500:],p.stderr[-500:])
        return p


def gates(case, broken):
    docs=case.work/"example.md"
    case.lib.write_text('''#[macro_export]
macro_rules! bench_hint {
    ($value:expr) => {{ extern crate test as benchmark; benchmark::black_box($value) }};
}
#[doc=include_str!("../example.md")]
pub fn documented() {}
''')
    for kind,snippet in [("bench","#[bench]\nfn candidate() {}\nassert_eq!(2+2,4);"),("macro","release_case::bench_hint!(3);")]:
        docs.write_text("```\n"+snippet+"\n```\n")
        for phase in ("first","repeat"):
            case.call(kind+"-"+phase,0 if broken else 101,b"1 passed;" if broken else b"E0658")
        case.call(kind+"-rustdoc",101,b"E0658",["-Zohm-cached-doctests=no","test","--doc","--offline"])
    return docs


def repair(case, docs):
    docs.write_text("```\nassert_eq!(2+2,4);\n```\n")
    for name in ("repair","repaired-repeat"):case.call(name,0,b"1 passed;")


def overlap(case, broken):
    case.lib.write_text('''/// ```
/// release_case::wait_for_the_second_build();
/// ```
pub fn alpha() {}
pub fn wait_for_the_second_build() {
    let root=std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    std::fs::write(root.join("ready"), "ready").unwrap();
    let start=std::time::Instant::now();
    while !root.join("resume").is_file() {
        assert!(start.elapsed().as_secs()<90, "second Cargo did not finish");
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
}
#[doc=include_str!("../zulu.md")]
pub fn zulu() {}
''')
    doc=case.work/"zulu.md"
    doc.write_text('```\nstd::fs::write("ran-example", "old").unwrap();\npanic!("original example");\n```\n')
    argv=["cargo","+ohm","test","--doc","--offline","-v"]
    logfile=case.logs/"overlapping.stdout";errfile=case.logs/"overlapping.stderr"
    import time
    with logfile.open("wb")as out,errfile.open("wb")as err:
        child=sp.Popen(argv,cwd=case.work,env=case.env,stdout=out,stderr=err)
        try:
            deadline=time.monotonic()+90
            while not (case.work/"ready").exists():
                assert child.poll() is None and time.monotonic()<deadline
                time.sleep(0.02)
            doc.write_text('```\nstd::fs::write("ran-example", "new").unwrap();\n```\n')
            case.call("second-build-list",0,b"zulu",["test","--doc","--offline","-v","--","--list"])
            assert child.poll() is None
            (case.work/"resume").touch()
            status=child.wait(timeout=55)
        finally:
            if child.poll() is None:
                child.terminate();child.wait(timeout=5)
    case.rows.append(dict(name="original-during-rebuild",status=status,argv=argv,out=sha(logfile),err=sha(errfile)))
    save(case.logs/"commands.json",case.rows)
    assert b"--test-run-directory" not in errfile.read_bytes()
    marker=case.work/"ran-example"
    assert status==(0 if broken else 101) and marker.read_bytes()==(b"new" if broken else b"old"),(status,logfile.read_bytes()[-1000:],errfile.read_bytes()[-600:])
    (case.logs/"example-that-ran").write_bytes(marker.read_bytes())
    case.call("new-examples",0,b"2 passed;")
    assert marker.read_bytes()==b"new"


def git_identity(case, broken):
    private=dict(case.env,GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_NOSYSTEM="1")
    def git(path,*args):
        return sp.check_output(["git","-C",path,*args],env=private,text=True,stderr=sp.PIPE).strip()
    donor,other,child=(case.work/v for v in ("donor","other","child"))
    for repo in (donor,other):
        (repo/"src").mkdir(parents=True)
        (repo/"Cargo.toml").write_text('[package]\nname="'+repo.name+'"\nversion="0.1.0"\nedition="2024"\n[workspace]\n')
        (repo/"src/lib.rs").write_text("pub fn "+repo.name+"() {}\n")
        git(repo,"init","--quiet");git(repo,"add",".")
        git(repo,"-c","user.name=Fixture","-c","user.email=fixture@example.invalid","-c","commit.gpgsign=false","commit","-qm",repo.name)
    od=other/".git"
    extra=dict(GIT_DIR=str(od),GIT_WORK_TREE=str(other),GIT_COMMON_DIR=str(od),GIT_INDEX_FILE=str(od/"index"),
               GIT_OBJECT_DIRECTORY=str(od/"objects"),GIT_ALTERNATE_OBJECT_DIRECTORIES=str(od/"objects"))
    case.call("selected-manifest",0,args=["worktree","add","--detach","--manifest-path",str(donor/"Cargo.toml"),str(child),"HEAD"],extra=extra)
    commits={p.name:git(p,"rev-parse","HEAD")for p in (donor,other,child)}
    assert commits["donor"]!=commits["other"] and commits["child"]==commits["other" if broken else "donor"]
    assert (str(child) in git(other,"worktree","list","--porcelain"))==broken
    save(case.logs/"git-heads.json",commits)


def archive(case):
    libdir=case.work/"native";libdir.mkdir()
    case.lib.write_text('''/// ```
/// #[link(name = "answer", kind = "static")]
/// unsafe extern "C" { fn answer() -> i32; }
/// assert_eq!(unsafe { answer() }, 2);
/// ```
pub fn documented() {}
''')
    (case.work/"build.rs").write_text('fn main() {println!("cargo::rustc-link-search=native={}/native",env!("CARGO_MANIFEST_DIR")); println!("cargo::rerun-if-changed=build.rs");}\n')
    def change(value):
        (libdir/"answer.c").write_text(f"int answer(void) {{ return {value}; }}\n")
        sp.run(["cc","-c","answer.c","-o","answer.o"],cwd=libdir,check=True)
        sp.run(["ar","rcs","libanswer.a","answer.o"],cwd=libdir,check=True)
    change(2);case.call("native-seed",0,b"1 passed;")
    original=sha(libdir/"libanswer.a");change(3);assert sha(libdir/"libanswer.a")!=original
    case.call("native-replaced",101,b"FAILED")
    change(2);case.call("native-repaired",0,b"1 passed;")


def run(root,normal,fixed,env,logs):
    base={k:env[k] for k in ("PATH","HOME","USER","TMPDIR","LANG","DEVELOPER_DIR","SDKROOT")if k in env}
    for role,sdk in (("signed",normal),("integrated",fixed)):
        broken=role=="signed"
        c=Case(root,sdk,"docs-"+role,base,logs);docs=gates(c,broken);repair(c,docs)
        overlap(Case(root,sdk,"overlap-"+role,base,logs),broken)
        git_identity(Case(root,sdk,"worktree-"+role,base,logs),broken)
    archive(Case(root,fixed,"native-integrated",base,logs))
    mixed=root/"unchanged-rust-upgrade";shutil.copytree(normal,mixed,symlinks=True,copy_function=os.link)
    caller=Case(root,mixed,"cargo-only-upgrade",base,logs)
    docs=gates(caller,True)
    before={str(p.relative_to(mixed)):[p.stat().st_dev,p.stat().st_ino,sha(p)]for p in (mixed/"bin/rustc",mixed/"bin/rustdoc",*list((mixed/"lib").glob("librustc_driver-*")))}
    staged=mixed/"bin/replacement-cargo";os.link(fixed/"bin/cargo",staged);staged.replace(mixed/"bin/cargo")
    assert all([ (mixed/p).stat().st_dev, (mixed/p).stat().st_ino, sha(mixed/p)]==v for p,v in before.items())
    for phase in ("first","repeat"):caller.call("unchanged-after-upgrade-"+phase,101,b"E0658")
    repair(caller,docs);save(caller.logs/"untouched-rust.json",before)
