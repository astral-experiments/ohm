"""Compare released and candidate Ohm SDKs on local, offline regression fixtures."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import traceback

pair, control, candidate, output = sys.argv[1:]
out = Path(output).resolve()
out.mkdir(exist_ok=True, parents=True)
kits = {"control": Path(control).resolve(), "candidate": Path(candidate).resolve()}
root = Path(tempfile.mkdtemp(prefix="probes8-", dir=os.environ["RUNNER_TEMP"]))
roles = list(kits) if int(pair) % 2 else list(reversed(kits))
registry = {}

def case(label):
    def register(fn):
        registry[label] = fn
        return fn
    return register


def require(value, evidence):
    if not value:
        raise AssertionError(str(evidence)[-3000:])


def decoded(s):
    return [json.loads(ln) for ln in s.splitlines() if ln.startswith('{"')]


class Trial:
    def __init__(self, role, name):
        self.role = role
        self.kit = kits[role]
        self.dir = root / role / name
        self.dir.mkdir(parents=True)
        self.logs = out / "probes" / name / role
        self.logs.mkdir(parents=True, exist_ok=True)
        self.serial = 0
        self.notes = {}
        self.known_bug = False
        self.env = {
            "HOME": str(Path.home()), "LANG": "C.UTF-8",
            "PATH": str(self.kit / "bin") + os.pathsep + os.environ["PATH"],
            "CARGO_HOME": str(self.dir / "cargo-home"),
            "CARGO_TERM_COLOR": "never", "CARGO_NET_OFFLINE": "true",
            "CARGO_BUILD_JOBS": "4", "CARGO_TARGET_DIR": str(self.dir / "target"),
        }
        for key in ("USER", "SDKROOT", "DEVELOPER_DIR"):
            if key in os.environ: self.env[key] = os.environ[key]

    def write(self, name, content):
        path = self.dir / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(content, encoding="utf-8")

    def package(self, name, source, extra="", binary=False):
        folder = "" if name == "app" else name + "/"
        self.write(folder+"Cargo.toml", f"[package]\nname='{name}'\nversion='0.1.0'\nedition='2024'\n"
                   + ("[workspace]\n" if not folder else "") + extra + "\n")
        self.write(folder+("src/main.rs" if binary else "src/lib.rs"), source)

    def run(self, *args, check=True, env=None, target="target"):
        local = dict(self.env, CARGO_TARGET_DIR=str(self.dir / target))
        local.update(env or {})
        p = subprocess.run(args, cwd=self.dir, text=True, env=local, capture_output=True, timeout=180)
        self.serial += 1
        self.log = p.stdout + p.stderr
        (self.logs / f"{self.serial:02}.txt").write_text(
            f"{args} {target} {env or {}} ({p.returncode})\n" + self.log)
        require(p.returncode >= 0 and "internal compiler error" not in self.log, self.log)
        if check: require(p.returncode == 0, self.log)
        return p

    def cargo(self, args, **kw):
        return self.run(self.kit/"bin/cargo", *args.split(), **kw)

    def diagnostics(self, args="check", **kw):
        p = self.cargo(args+" --message-format=json", check=False, **kw)
        ms = [item["message"] for item in decoded(p.stdout)
              if item.get("reason") == "compiler-message" and item["message"]["level"] in ("warning","error")]
        # Compare the public message, spans, suggestions and children, independent of Cargo progress.
        norm = json.dumps(ms, sort_keys=True, ensure_ascii=False).replace(str(self.dir), "PROJECT").replace(str(self.kit), "KIT")
        return p.returncode, json.loads(norm)

    def compare_error(self, args, code, may_miss=False, **kw):
        warm = self.diagnostics(args, **kw)
        fresh = self.diagnostics(args, target="fresh", **kw)
        require(fresh[0] and any(m["level"]=="error" and code in str(m) for m in fresh[1]), self.log)
        if may_miss and warm[0] == 0 and all(m["level"]!="error" for m in warm[1]):
            self.known_bug = True
        else:
            require(warm == fresh, (warm,fresh))
        self.notes["warm_status"] = warm[0]
        return fresh

    def doc_edit(self, error, env=None):
        def result(target):
            p = self.cargo("test --doc",check=False,target=target,env=env)
            if p.returncode:
                require(error in self.log,self.log)
                return error
            require("1 passed" in p.stdout,self.log)
            return "accepted"
        warm,fresh = result("target"),result("fresh")
        require(fresh == error, self.log)
        self.notes["warm"] = warm
        self.known_bug = warm == "accepted"
        return fresh


DEP = "[dependencies]\ndep.path='dep'"

@case("cargo615")
def proc_macro_doc(t):
    t.package("app",'#[cfg(doctest)] #[doc = dep::example!()] pub fn sample() {}', '[dev-dependencies]\ndep.path="dep"')
    t.package("dep","pub use probe::example;", '[dependencies]\nprobe.path="../probe"')
    t.package("probe",r'''use proc_macro::{Literal, TokenStream, TokenTree};
        #[proc_macro] pub fn example(_: TokenStream) -> TokenStream {
            let value = std::env::var("EXAMPLE_VALUE").unwrap();
            let source = format!("```\nassert_eq!(1, {value});\n```");
            TokenTree::Literal(Literal::string(&source)).into()
        }''', "[lib]\nproc-macro=true")
    t.cargo("test --doc",env={"EXAMPLE_VALUE":"1"})
    result = t.doc_edit("assertion",{"EXAMPLE_VALUE":"2"})
    t.cargo("test --doc",env={"EXAMPLE_VALUE":"1"})
    return result


@case("cargo620")
def macro_artifact(t):
    t.package("app","const _: () = assert!(dep::value!() == 1);",DEP)
    t.package("dep","pub use probe::value;", '[dependencies]\nprobe.path="../probe"')
    t.package("probe",'''use proc_macro::TokenStream;
        #[proc_macro] pub fn value(_: TokenStream) -> TokenStream {
            std::fs::read_to_string(concat!(env!("OUT_DIR"),"/value")).unwrap().parse().unwrap()
        }''',"[lib]\nproc-macro=true")
    t.write("probe/build.rs",'''fn main() {
        println!("cargo::rerun-if-changed=value");
        let path = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
        std::fs::copy("value",path.join("value")).unwrap();
    }''')
    t.write("probe/value","1")
    t.cargo("check")
    t.write("probe/value","2")
    return t.compare_error("check","E0080",True)


@case("cargo625")
def include_archive(t):
    t.package("app","#[test] fn check() {}", "[dev-dependencies]\nhelper.path='helper'")
    t.package("helper",'pub const MESSAGE: &str = "HELLO1HELLO";')
    seed = decoded(t.cargo("test --lib --no-run --message-format=json").stdout)
    path, = [f for item in seed if item.get("target",{}).get("name")=="helper"
             for f in item.get("filenames",[]) if f.endswith(".rlib")]
    (t.dir/"src/current.bin").symlink_to(path)
    t.write("helper/src/lib.rs",'pub const MESSAGE: &str = "HELLO2HELLO";')
    t.write("src/lib.rs",'''#[test] fn check() {
        let archive = include_bytes!("current.bin");
        assert!(archive.windows(11).any(|bytes| bytes == b"HELLO2HELLO"), "stale archive");
    }''')
    warm = t.cargo("test --lib check",check=False)
    if warm.returncode:
        require("stale archive" in t.log and "1 failed" in t.log,t.log)
        t.known_bug = True
    else:
        require("1 passed" in t.log,t.log)
    t.cargo("build -p helper")
    require(b"HELLO2HELLO" in Path(path).read_bytes(),path)
    t.cargo("test --lib check",target="fresh")
    require("1 passed" in t.log,t.log)
    return "HELLO2HELLO"

def candidate(t):
    return t.role=="candidate" and not pilot

def rust(t,*args,**kw):
    return t.run(t.kit/"bin/rustc",*args,**kw)

@case("cargo642")
def trust(t):
    proc_macro_doc(t)
    trust={"CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST":"all"}
    def docs(expect,mode,flags=""):
        p=t.cargo("test --doc -v "+flags,env=mode|{"EXAMPLE_VALUE":str(expect)},check=False)
        require((p.returncode==0 and "1 passed" in p.stdout) if expect==1
                else (p.returncode and "assertion" in t.log), t.log)
        return "--test-run-directory" in t.log
    docs(1,trust)
    reuse=not docs(1,trust)
    t.notes["trusted_reuse"]=reuse
    require(not candidate(t) or reuse,t.log)
    require(docs(2,trust,"-Zohm-proc-macro-trust=audited"),t.log)
    require(docs(2,{}),t.log)
    docs(1,trust)
    path=t.dir/"Cargo.toml"
    t.write("Cargo.toml",path.read_text().replace("[workspace]","[workspace]\nexclude=['probe']"))
    require(docs(1,trust),t.log)
    require(docs(2,trust),t.log)
    return "audited and excluded rerun"

@case("cargo628")
def relocate(t):
    t.package("app",'''/// ```
/// assert_eq!(env!("CARGO_MANIFEST_DIR"),std::env::var("CARGO_MANIFEST_DIR").unwrap());
/// ```
pub fn example() {}''')
    before=t.dir/"before"
    before.mkdir()
    for x in ("Cargo.toml","src"):(t.dir/x).rename(before/x)
    t.cargo("test --doc --manifest-path before/Cargo.toml")
    before.rename(t.dir/"after")
    p=t.cargo("test --doc --manifest-path after/Cargo.toml",check=False)
    if p.returncode:
        require("assertion" in t.log,t.log)
        t.known_bug=True
    t.cargo("test --doc --manifest-path after/Cargo.toml",target="fresh")
    return "1 passed" in t.log

@case("cargo637")
def nested(t):
    t.package("app","#[test] fn example() {}", "[dev-dependencies]\nhelper.path='helper'")
    t.package("helper","pub fn value() {}")
    t.write("probe.rs","fn main() { helper::added(); }")
    t.cargo("test --lib")
    helper, = (t.dir/"target").rglob("libhelper-*.rmeta")
    env=dict(HELPER_RMETA=str(helper))
    t.write("helper/src/lib.rs","pub fn added() {}")
    t.write("src/lib.rs",'''#[test]
fn example(){
    assert!(std::process::Command::new("rustc")
        .args(["probe.rs","--emit=metadata","--extern",concat!("helper=", env!("HELPER_RMETA"))])
        .status().unwrap().success());
}''')
    p=t.cargo("test --lib",env=env,check=False)
    if p.returncode:
        require("E0425" in t.log,t.log)
        t.known_bug=True
    t.cargo("test --lib",env=env|{"CARGO_UNSTABLE_OHM_DEFER_DEV_DEPS":"false"})
    return "1 passed" in t.log

@case("rustc622")
def cycle(t):
    bad="<&'static Cycle as std::ops::Deref>::Target"
    for label,src in [("valid","pub struct Value(u32);"),("struct",f"pub struct Cycle({bad});"),
                      ("enum",f"pub enum Cycle {{ C({bad}) }}")]:
        t.write("dep.rs",src)
        results=[]
        for cap in ("allow","warn"):
            p=rust(t,"dep.rs","--emit=metadata","--crate-type=lib","--cap-lints="+cap,check=False)
            if label=="valid":require(not p.returncode,t.log)
            elif not p.returncode and cap=="allow":t.known_bug=True
            else:require(p.returncode and re.search("E0391|E0072",p.stderr),t.log)
            results.append(p.returncode)
        t.notes[label]=results
    return "recursive shape rejected"

MATCHES = r'''
#![feature(allow_internal_unstable)]
#![allow(internal_features)]

use std::io::ErrorKind;
use std::matches as accepts;

pub const DIRECT: bool = matches!(const { 2 }, 1 | 2);
pub const GUARDED: bool = accepts!(Some(2), Some(n) if n > BOUND,);
const _: () = assert!(DIRECT && GUARDED == EXPECTED);

// The caller does not enable the lint feature. The wrapper can still set its level.
#[allow_internal_unstable(non_exhaustive_omitted_patterns_lint)]
macro_rules! wrap {
    ($expr:expr) => {
        #[deny(non_exhaustive_omitted_patterns)]
        pub const FOUND: bool = $expr;
    };
}
wrap!(matches!(ErrorKind::NotFound, ErrorKind::NotFound));

macro_rules! matches {
    ($e:expr, $p:pat) => {
        false
    };
}
const _: () = assert!(FOUND && !matches!(0, 0));
'''

@case("rustc619")
def matches(t):
    def call(cache,*args,check=True):
        return rust(t,"dep.rs","--edition=2024","--emit=metadata","--crate-type=rlib",
                    "-Zincremental-verify-ich","-Cincremental="+cache,*args,check=check)
    for i,(prefix,bound,expected) in enumerate([("",1,"true"),("",2,"false"),("\n",1,"true")]):
        t.write("dep.rs",prefix+MATCHES.replace("BOUND",str(bound)).replace("EXPECTED",expected))
        call("warm")
        warm=(t.dir/"libdep.rmeta").read_bytes()
        call("fresh"+str(i),"-Zdeduplicate-diagnostics=no")
        require(warm==(t.dir/"libdep.rmeta").read_bytes(),i)
    t.write("dep.rs","pub const BAD: bool = matches!(0, 0 | if 1);")
    p=call("warm",check=False)
    require(p.returncode and "a trailing `|` is not allowed" in p.stderr and "expected pattern" in p.stderr,t.log)
    return "declarative matches"

def public(t,source,hint=True,cache="warm",native=False):
    t.write("dep.rs",source)
    p=rust(t,"dep.rs","--crate-type=rlib","--emit=metadata"+(",link" if native else ""),
           "-Zpublic-api-hash","-Zincremental-verify-ich","-Cincremental="+cache,
           "--error-format=json","--json=artifacts",*(["-Zohm-terminal-check-hash"] if hint else []))
    return next(r["public_api_hash"]["value"] for r in decoded(p.stderr)
                if r.get("$message_type")=="artifact" and r.get("emit")=="metadata")

def moved(t,src,edit):
    initial=public(t,src)
    meta=t.dir/"libdep.rmeta"
    disk=meta.read_bytes()
    shifted=public(t,edit)
    t.notes["stable_terminal_key"]=initial==shifted
    require(initial==shifted or not candidate(t),t.notes)
    warm=meta.read_bytes()
    require(warm!=disk,t.log)
    require(shifted==public(t,edit,cache="fresh") and warm==meta.read_bytes(),t.log)
    require(public(t,src,False)!=public(t,edit,False),t.log)
    return initial

@case("rustc630")
def derive(t):
    src="""#[derive(Default)] struct Writer;
impl Writer {
fn write() {}
}
#[derive(Clone, Debug)]
pub enum Ink<T> { None, Color(T) }
"""
    edit=src.replace("write() {}",'write() {\nlet _ = "μ";\n}')
    initial=moved(t,src,edit)
    public(t,edit)
    t.write("reader.rs","fn main() { dep::Ink::<u32>::Color(); }")
    p=rust(t,"reader.rs","--emit=metadata","--extern=dep=libdep.rmeta",check=False)
    require(p.returncode and "dep.rs:8:25" in p.stderr,t.log)
    require(initial!=public(t,src.replace("Clone, Debug","Debug")),t.log)
    require(initial!=public(t,src.replace("}\n#[derive","}\n\n#[derive")),t.log)
    suffix="pub const LINE: u32 = line!();"
    require(public(t,src+suffix)!=public(t,edit+suffix),t.log)
    require(public(t,src,native=True)!=public(t,edit,native=True),t.log)
    return "dep.rs:8:25"

@case("rustc644")
def cfg(t):
    src="""#[cfg(any(all(), not(unix)))]
pub struct Pen { #[cfg(not(any()))] pub color: u32 }
impl Pen {
    #[cfg(any(all(), target_os = "linux"))]
    pub fn color(&self) -> u32 { self.color }
}
"""
    moved(t,src,"\n"+src)
    initial=public(t,src)
    for a,b in [(" = ","  ="),("linux","macos")]:
        require(initial!=public(t,src.replace(a,b)),t.log)
    generated="macro_rules! make { () => { #[cfg(all())] pub struct Pen; } } make!();"
    require(public(t,generated)!=public(t,"\n"+generated),t.log)
    return "cfg sensitive"
def deps(t,src,middle,main):
    t.package("app",main,"[dependencies]\nmiddle.path='middle'",binary=True)
    t.package("middle",middle,"[dependencies]\ndep.path='../dep'")
    t.package("dep",src)

def invalid(t,selection,code,fresh):
    cmd="check -v --bin "+selection
    p=t.cargo(cmd,check=False)
    require(p.returncode and code in t.log,t.log)
    warm=t.diagnostics(cmd)
    clean=t.diagnostics(cmd,target=fresh)
    require(warm==clean and code in str(clean),[warm,clean])
    return code

@case("transitive")
def foreign(t):
    src="pub struct Value; pub const SIZE: usize = 1; pub const OTHER: usize = 1;"
    deps(t,src,"pub use dep::{SIZE,Value};",'''trait Local { fn clone(&self); }
        impl Local for middle::Value { fn clone(&self) {} }
        fn main() { middle::Value.clone(); }''')
    t.write("src/bin/other.rs","fn main() { let _: [(); 1] = [(); middle::SIZE]; }")
    t.cargo("check -v --bins")
    src=src.replace("SIZE: usize = 1","SIZE: usize = 2")
    t.write("dep/src/lib.rs",src)
    app="check -v --bin app"
    t.cargo(app)
    require("--crate-name app " in t.log,t.log)
    t.write("dep/src/lib.rs",src.replace("OTHER: usize = 1","OTHER: usize = 2"))
    t.cargo(app)
    skip="-Zohm-transitive-check-hash" in t.log and "--crate-name app " not in t.log
    t.notes["skip"]=skip
    require(not candidate(t) or skip,t.log)
    t.cargo(app)
    require("--crate-name " not in t.log,t.log)
    t.write("dep/src/lib.rs",src)
    invalid(t,"other","E0308","fresh_other")
    t.cargo(app,env={"RUSTFLAGS":"--cfg extra"})
    require("--crate-name app " in t.log and "-Zohm-transitive-check-hash" not in t.log,t.log)
    t.cargo(app)
    t.write("dep/src/lib.rs",src+" impl Clone for Value { fn clone(&self)->Self { Value } }")
    return invalid(t,"app","E0034","fresh_app")

@case("macro_reexport")
def reexport(t):
    src='#[macro_export] macro_rules! fetch { () => { $crate::helper() } }\npub fn helper()->u32{0}'
    deps(t,src,"pub use dep::fetch;","fn main(){let _:u32 = middle::fetch!();}")
    t.cargo("check -v --bin app")
    t.write("dep/src/lib.rs",src.replace("u32","i32"))
    return invalid(t,"app","E0308","fresh")

@case("namespace_reexport")
def namespace(t):
    src="pub const SIZE: usize = 1;"
    deps(t,src,"pub use dep as api;","fn main(){let _: [();1] = [();middle::api::SIZE];}")
    t.cargo("check -v --bin app")
    t.write("dep/src/lib.rs",src.replace("1","2"))
    return invalid(t,"app","E0308","fresh")

@case("foreign_field")
def visibility(t):
    src="pub struct Value { pub field:u32 }"
    deps(t,src,"pub use dep::Value;","fn main(){let _ = middle::Value { field: 42u32 };}")
    t.cargo("check -v --bin app")
    t.write("dep/src/lib.rs",src.replace("u32","u64"))
    invalid(t,"app","E0308","fresh_type")
    t.write("dep/src/lib.rs",src)
    t.cargo("check -v --bin app")
    t.write("dep/src/lib.rs",src.replace("pub field","pub(crate) field"))
    return invalid(t,"app","E0451","fresh_vis")

def clippy(t,expr,oracle):
    t.env["CARGO_BUILD_JOBS"]="1"
    require("0.1.17" in t.run("cargo-fixit","fixit","--version").stdout,t.log)
    t.package("app","pub fn four(v: u8) { let _ = (v.clone(), v.clone(), v.clone(), v.clone()); }")
    src="""#![warn(clippy::equatable_if_let)]
fn check(a: bool, b: bool) -> bool {
    let _ = (a.clone(), a.clone(), b.clone(), b.clone());
    EXPR
}
#[test]
fn truth() {
    for (a, b) in [(false, true), (false,false), (true,false), (true,true)] {
        assert_eq!(check(a.clone(), b.clone()), ORACLE);
    }
}
""".replace("EXPR",expr).replace("ORACLE",oracle)
    t.write("tests/check.rs",src)
    t.cargo("test --test check")
    fix=t.cargo("fixit --clippy --Zdangerous-parallel-fixes --allow-no-vcs --all-targets",check=False)
    fixed=(t.dir/"tests/check.rs").read_text()
    (t.logs/"fixed.rs").write_text(fixed)
    if fix.returncode and expr=="!(Some(a | b).unwrap())":
        require("reverting" in t.log and fixed==src and "delimiter" in t.log,t.log)
        t.known_bug=True
        t.notes["reverted"]=True
        t.cargo("test --test check")
        return oracle
    require(fixed!=src and ".unwrap()" not in fixed, (fixed,t.log))
    t.notes["expression"]=fixed.splitlines()[3].strip()
    p=t.cargo("test --test check",check=False)
    if p.returncode:
        require("truth ... FAILED" in p.stdout,t.log)
        t.known_bug=True
    else:
        require(fix.returncode==0 and "1 passed" in p.stdout,t.log)
    return oracle

@case("clippy_chain")
def chain(t):
    return clippy(t,"if let false = Some(a | b).unwrap() { true } else { false }","!(a | b)")

@case("clippy_binary")
def binary(t):
    return clippy(t,"Some(a | b).unwrap() & !a","(a | b) & !a")

@case("clippy_parens")
def parens(t):
    return clippy(t,"!(Some(a | b).unwrap())","!(a | b)")

@case("rustc616")
def unsized(t):
    t.write("dep.rs","pub fn repeated(_a: str, _b: str) {}")
    p=rust(t,"dep.rs","--crate-type=lib","--emit=metadata","--error-format=json",check=False)
    require(p.returncode and "E0277" in t.log,t.log)
    suggestions=sorted({s["column_start"] for d in decoded(p.stderr) for c in d.get("children",[])
                        for s in c.get("spans",[]) if s.get("suggested_replacement")=="&"})
    t.notes["columns"]=suggestions
    require(suggestions in ([21],[21,30]),t.log)
    t.known_bug=len(suggestions)!=2
    return "both borrowed"

@case("rustc_paths")
def paths(t):
    src='include!(concat!(env!("CARGO_MANIFEST_DIR"), "/src/included.rs"));'
    t.package("app",src,"[dependencies]\nhelper.path='helper'",binary=True)
    t.package("helper",r'''extern crate proc_macro;
        #[proc_macro]
        pub fn path(name:proc_macro::TokenStream) -> proc_macro::TokenStream {
            format!("{:?}", name.into_iter().next().unwrap().span().file()).parse().unwrap()
        }''',"[lib]\nproc-macro=true")
    t.write("src/included.rs","""/// See [Missing].
pub struct Test;
fn main() {
    println!("{}", helper::path!(a));
    println!("{}", file!());
}
#[test]
#[should_panic]
fn does_not_panic() {}
""")
    path=str(t.dir/"src/included.rs")
    a,b=t.cargo("run -q").stdout.strip().splitlines()
    require(b==path,(a,b))
    t.notes["macro_filename"]=a==b
    p=t.cargo("test -q",check=False)
    require(p.returncode and "test did not panic as expected" in t.log,t.log)
    t.notes["libtest_filename"]=path+":9:4" in t.log
    t.cargo("doc -q --no-deps")
    require("unresolved link" in t.log,t.log)
    t.notes["rustdoc_filename"]=path+":1:10" in t.log
    t.known_bug=not all(t.notes.values())
    return "original checkout paths"

@case("rustc614")
def rows(t):
    src='''/// Repeated rows
#[rustfmt::skip]
pub const TABLE: &[(&[&str], &[&str])] = &[''' + '(&["key"], &["value"]), '*63 + '(&[], &["", LAST])];'
    t.package("app",'fn main(){ println!("{}", dep::TABLE[63].1[1]); }', DEP, binary=True)
    t.package("dep","")
    for arg in ["alpha","omega","αβγ"]:
        t.write("dep/src/lib.rs",src.replace("LAST",'"'+arg+'"'))
        require(t.cargo("run -q").stdout.strip()==arg,t.log)
    t.write("dep/src/lib.rs",src.replace("LAST","42u8"))
    return invalid(t,"app","E0308","fresh")

@case("cargo632")
def hardlink(t):
    t.package("app","#[test] fn example() {}", "[dev-dependencies]\nhelper.path='helper'")
    t.package("helper","pub fn value() -> u32 { 42 }")
    t.cargo("test --lib")
    artifact, = (t.dir/"target").rglob("helper-*.d")
    os.link(artifact,t.dir/"src/current.bin")
    (t.dir/"src/old.bin").write_bytes(artifact.read_bytes())
    t.write("helper/src/value.rs","pub fn value() -> u32 { 42 }")
    t.write("helper/src/lib.rs","mod value; pub use value::value;")
    t.write("src/lib.rs",'''#[test] fn example() {
        assert!(include_bytes!("old.bin")[..] != include_bytes!("current.bin")[..], "stale depfile");
    }''')
    p=t.cargo("test --lib",check=False)
    if p.returncode:
        require("stale depfile" in t.log,t.log)
        t.known_bug=True
    t.cargo("test --lib",env={"CARGO_UNSTABLE_OHM_DEFER_DEV_DEPS":"false"})
    return "depfile was rebuilt"

def mir(t,wrapped):
    env={}
    t.package("app","#[test] fn example() {}", "[dev-dependencies]\nhelper.path='helper'")
    t.package("helper","pub fn value()->u32{12345}")
    if wrapped:
        t.write("wrap",'''#!/bin/sh
case " $* " in
    *" --crate-name helper "*) exec "$@" --emit=mir=wrapped.mir ;;
    *) exec "$@" ;;
esac
''')
        wrapper=t.dir/"wrap"
        wrapper.chmod(0o700)
        env["RUSTC_WRAPPER"]=str(wrapper)
    else:
        t.write(".cargo/config.toml","[build]\nrustflags=['--emit=mir']\n")
    t.cargo("test --lib",env=env)
    path, = t.dir.rglob("wrapped.mir" if wrapped else "helper-*.mir")
    require("12345" in path.read_text(),path)
    t.write("helper/src/lib.rs","pub fn value()->u32{67890}")
    t.write("src/lib.rs","#[test] fn example() { assert_eq!(1,1); }")
    t.cargo("test --lib",env=env)
    t.known_bug="67890" not in path.read_text()
    t.cargo("test --lib",env=env|{"CARGO_UNSTABLE_OHM_DEFER_DEV_DEPS":"false"})
    require("67890" in path.read_text(),path)
    return "67890"

case("cargo633")(lambda t: mir(t,False))
case("cargo636")(lambda t: mir(t,True))

@case("rustc631")
def derive_helper(t):
    t.write("derive.rs",'''extern crate proc_macro;
use proc_macro::TokenStream;
#[proc_macro_derive(Describe, attributes(helper))]
pub fn describe(input: TokenStream) -> TokenStream {
    let example = input.to_string().contains("example");
    format!("impl crate::Marker for Rule {{}} pub const EXAMPLE: bool = {example};").parse().unwrap()
}''')
    rust(t,"derive.rs","--edition=2021","--crate-type=proc-macro")
    lib=next(t.dir.glob("libderive.*"))
    t.write("dep.rs",'''#![allow(dead_code)]
#[macro_export] macro_rules! exported { () => {} }
pub trait Marker {}
pub mod items;
''')
    items="""#[derive(Debug)] struct Earlier;
impl Earlier { fn method(&self) {} }
/// An example.
#[derive(derive::Describe)]
#[helper(first)]
struct Rule;
"""
    def check(src,cache="warm"):
        t.write("items.rs",src)
        rust(t,"dep.rs","--crate-type=rlib","--edition=2021","--extern=derive="+lib.name,
             "-Zpublic-api-hash","-Zincremental-verify-ich","-Cincremental="+cache,"--emit=metadata")
        return rust(t,"libdep.rmeta","-Zls=public_hash").stdout
    before=check(items)
    wider=items.replace("An example","An  example")
    changed=check(wider)
    t.notes["stable_helper_hash"]=before==changed
    require(before==changed or not candidate(t),t.notes)
    require(changed==check(wider,"fresh"),t.log)
    require(changed!=check(wider.replace("#[helper","  #[helper")),t.log)
    require(changed!=check(wider.replace("first","later")),t.log)
    require(before!=check(items.replace("example","account")),t.log)
    require(before==check(items),t.log)
    return "changed attribute and expansion"

@case("rustc636")
def glob(t):
    src="pub mod inner { pub const VALUE:u16 = 500; }"
    deps(t,src,"pub use dep::inner::*;","fn main(){ let _: u16 = middle::VALUE; }")
    t.cargo("check -v --bin app")
    t.write("dep/src/lib.rs",src.replace("u16","u32"))
    t.cargo("check -p dep")
    return invalid(t,"app","E0308","fresh")

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def main():
    global pilot
    versions = {role:{bin:subprocess.check_output([kit/"bin"/bin,"-V"],text=True).strip()
                      for bin in ("rustc","cargo","rustdoc","clippy-driver")} for role,kit in kits.items()}
    pilot = versions["control"] == versions["candidate"] and "ohm-1.100.0-7)" in versions["control"]["rustc"]
    report = dict(pair=pair, pilot=pilot, versions=versions, cases={}, passed=False)
    def save():
        (out/"probes.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    save()
    require("ohm-1.100.0-7)" in versions["control"]["rustc"],versions)
    require(pilot or "ohm-1.100.0-8)" in versions["candidate"]["rustc"],versions)
    for name,probe in registry.items():
        result = {}
        report["cases"][name] = result
        for role in roles:
            t = Trial(role,name)
            try:
                oracle = probe(t)
                result[role] = dict(known_bug=t.known_bug, observed=t.notes, oracle=fingerprint(oracle))
            except Exception:
                result[role] = dict(error=traceback.format_exc()[-4200:])
                print(name,role,result[role]["error"],flush=True)
        a,b = result["control"],result["candidate"]
        result["passed"] = "oracle" in a and a["oracle"]==b.get("oracle") and (pilot or not b["known_bug"])
        print(name,"PASS" if result["passed"] else "FAIL",
              "baseline bug" if a.get("known_bug") else "",b.get("observed",{}),flush=True)
        save()
    report["passed"] = len(report["cases"])==len(registry) and all(v["passed"] for v in report["cases"].values())
    save()
    return 0 if report["passed"] else 1

if __name__ == "__main__":
    sys.exit(main())

