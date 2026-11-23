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
root = Path(tempfile.mkdtemp(prefix="probes9-", dir=os.environ["RUNNER_TEMP"]))
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
def derive(t,trait=False):
    src="""#[derive(Default)] struct Writer;
impl Writer {
fn write() {}
}
#[derive(Clone, Debug)]
pub enum Ink<T> { None, Color(T) }
"""
    if trait:
        src=src.replace("impl Writer","trait Write { fn write(); } impl Write for Writer")
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

@case("rustc655")
def trait_derive(t):
    return derive(t,True)

def fails_fresh(t,command,code):
    # Start with the ordinary invocation to exercise reuse before the detailed diagnostic comparison.
    p=t.cargo(command,check=False)
    if not p.returncode:t.known_bug=True
    else:require(code in t.log,t.log)
    t.notes["initial_status"]=p.returncode
    fresh=t.compare_error(command,code,True)
    return code

@case("cargo644")
def both_paths(t):
    t.package("app","mod data; pub use data::value;")
    t.write("src/data.rs","pub fn value()->u8{1}")
    t.cargo("build --lib")
    t.write("src/data/mod.rs","")
    result=fails_fresh(t,"check --lib","E0761")
    t.write("src/lib.rs",'#[path="data.rs"] mod data; pub use data::value;')
    t.cargo("check --lib")
    return result

@case("cargo646")
def dependency_ambiguity(t):
    t.package("app","pub fn value()->u8 {1}")
    t.write("src/main.rs","mod data; fn main(){ app::value(); }")
    t.write("src/data.rs","")
    t.cargo("check")
    t.write("src/lib.rs",'pub fn value()->u8 { helper::item() }\n#[path="data/mod.rs"] mod helper;')
    t.write("src/data/mod.rs","pub(super) fn item()->u8{2}")
    return fails_fresh(t,"check","E0761")

@case("rustc653")
def diamond(t):
    src="pub use inner::Root;\nmod inner {\npub struct Root { pub a: &'static A0, pub b: &'static B0 }\n"
    for i in range(128):
        for name in "AB":
            src+=f"pub struct {name}{i} {{pub a: &'static A{i+1}, pub b: &'static B{i+1} }}\n"
    src+="pub struct A128 { pub value: u32 }\npub struct B128;\n}\n"
    t.package("app","pub fn f(x: dep::Root) -> u32 { x"+".a"*129+".value }\nfn main() {}\n",DEP,binary=True)
    t.package("dep",src)
    t.cargo("check")
    t.write("dep/src/lib.rs",src.replace("u32","u64"))
    result=fails_fresh(t,"check","E0308")
    t.write("dep/src/lib.rs",src)
    t.cargo("check")
    return result

@case("rustc647")
def focused(t):
    t.package("app","#[cfg(test)] mod tests { #[test]fn first(){} #[test]fn second(){} }")
    cmd="test -p app --lib tests::first -- --exact"
    t.cargo(cmd)
    require("1 passed" in t.log,t.log)
    env=dict(CARGO_UNSTABLE_OHM_FOCUSED_TESTS="true")
    p=t.cargo(cmd,env=env,check=False)
    if p.returncode:
        require("E0716" in t.log,t.log)
        t.known_bug=True
    else:require("tests::first ... ok" in t.log and "1 passed" in t.log and "0 filtered out" in t.log,t.log)
    t.write("Cargo.toml",(t.dir/"Cargo.toml").read_text().replace("2024","2021"))
    t.cargo(cmd,env=env)
    require("1 passed" in t.log,t.log)
    require("0 filtered out" in t.log,t.log)
    return "one selected"

def short(t,dep):
    t.package("app","fn unused() {"+(" dep::n(); " if dep else "")+"}",DEP if dep else "")
    if dep:t.package("dep","pub fn n() -> u8 { 1 }")
    t.cargo("check" if dep else "build --lib")
    if dep:t.write("dep/src/lib.rs","pub fn n() -> u8 { 2 }")
    cmd="check --lib --message-format=short"
    raw=t.cargo(cmd).stderr
    fresh=t.cargo(cmd,target="fresh").stderr
    line="src/lib.rs:1:4: warning: function `unused` is never used"
    require(line in fresh and "function `unused` is never used" in raw,(raw,fresh))
    t.known_bug=line not in raw
    return line

case("cargo650")(lambda t:short(t,False))
case("cargo658")(lambda t:short(t,True))

@case("cargo670")
def artifact(t):
    t.package("app","pub fn value()->dep::Value{dep::value()}",DEP)
    t.package("dep","pub struct Value; pub fn value()->Value{Value}\nfn unused(){}")
    t.write("dep/src/main.rs","fn main(){dep::value();}")
    t.write("reader.rs","pub fn read() -> dep::Value { app::value() }")
    def events(p,name):
        return [e for e in decoded(p.stdout) if e.get("target",{}).get("name")==name
                and e["target"]["kind"]==["lib"]]
    def metadata(items):
        return [Path(f) for e in items if e["reason"]=="compiler-artifact"
                for f in e["filenames"] if f.endswith(".rmeta")]
    for profile in ("--release",""):
        build=t.cargo(f"build -p dep --lib {profile} --message-format=json")
        native,=metadata(events(build,"dep"))
        rows=t.notes[profile or "debug"]=[]
        for selection in ("--workspace --lib","--workspace","--workspace","-p app"):
            p=t.cargo(f"check {selection} {profile} --message-format=json")
            app,=metadata(events(p,"app"))
            dep=events(p,"dep")
            warnings=[e for e in dep if e["reason"]=="compiler-message"]
            paths=metadata(dep)
            require(paths and warnings and warnings[0]["message"]["code"]["code"]=="dead_code",t.log)
            # A separate check can produce metadata incompatible with the native dep
            # referenced by app. Compile using ONLY paths in Cargo's JSON receipt.
            checks=[]
            for path in paths:
                consumer=rust(t,"reader.rs","--crate-type=lib","--edition=2024","--emit=metadata",
                              "--extern","app="+str(app),"--extern","dep="+str(path),
                              "-L","dependency="+str(path.parent),check=False)
                errors=re.findall(r"error\[(E[0-9]+)\]",consumer.stderr)
                if consumer.returncode:require("E0460" in errors or "E0308" in errors,t.log)
                checks.append(dict(native=(path==native),status=consumer.returncode,codes=errors))
            rows.append(dict(selection=selection,warnings=len(warnings),consumers=checks))
            require(any(c["status"]==0 for c in checks),rows)
            if paths!=[native] or len(dep)!=2 or len(warnings)!=1 or checks[0]["status"]:
                t.known_bug=True
    return "each consumer can read its one reported dependency"

@case("cargo668")
def debugger(t):
    t.package("app",'fn main(){println!("ok");}',binary=True)
    for fmt,forced in [("full",False),("line-tables-only",False),("full",True)]:
        args="-Zohm-worktree-seeds=yes " if forced else ""
        t.cargo(args+"build -v",env={"CARGO_PROFILE_DEV_DEBUG":fmt},target=fmt+str(forced))
        require("--crate-name app" in t.log,t.log)
        remap="-Zremap-cwd-prefix" in t.log
        t.notes[fmt+str(forced)]=remap
        if fmt=="full" and not forced:t.known_bug=remap
        else:require(remap,t.log)
    return "line tables and forced retain seeds"

@case("rustc654")
def disabled_bodies(t):
    t.write("lib.rs","pub mod cached;")
    body="#[cfg(test)] fn helper() { missing_helper(); }\n" +\
        "#[cfg(test)] #[test] fn example(){ missing_test(); #[cfg(any())] let _ = 0" + ".method()"*512 + "; }"
    t.write("cached.rs",body)
    def check(key="warm",*opt):
        return rust(t,"lib.rs","--edition=2024","--crate-type=rlib","--emit=metadata","-Zohm-shared-stages",
                    "-Zincremental-verify-ich","-Cincremental="+key,*opt,check=False,
                    env={"RUSTC_LOG":"ohm_module_syntax=info"})
    require(check().returncode==0,t.log)
    p=check()
    t.notes["reused"]="reused parsed module" in p.stderr
    require(p.returncode==0 and (not candidate(t) or t.notes["reused"]),t.log)
    for key in ("warm","fresh"):
        p=check(key,"--test")
        require(p.returncode and all(("cannot find function `"+x+"`") in p.stderr for x in ("missing_helper","missing_test")),t.log)
    t.write("cached.rs",body.replace("missing_test();","let = 0;"))
    require(check().returncode and "expected pattern" in t.log,t.log)
    t.write("cached.rs","// "+"x"*1024+"\n#[cfg(test)] #[test] fn f() { #[allow(custom::lint)] let _ = 0; }")
    t.write("lib.rs","#![feature(register_tool)]\n#![register_tool(custom)]\npub mod cached;")
    require(check().returncode==0,t.log)
    t.write("lib.rs","#![feature(register_tool)]\npub mod cached;")
    require(check().returncode and "E0710" in t.log,t.log)
    return "cfg switch and pre-expansion errors"

@case("rustc656")
def large_method(t):
    source="""#![deny(unfulfilled_lint_expectations)]
pub mod data { pub struct Token; pub fn token() -> Token { Token } }
pub struct Wrapper<T>(pub T);
pub trait Marker {}
#[allow(unused_comparisons)]
impl<T> Wrapper<T> {
    pub fn other() {}
    #[expect(non_local_definitions)]
    pub fn inspect<U: Copy>(&self, byte: u8, _: U) -> bool {
        impl Marker for String {}
        let _ = || {
            mod nested {
                pub fn bytes() -> impl Copy {
                    let bytes: [u8; 1] = [const { 0 }];
                    bytes
                }
            }
        };
        let _: i8 = -128;
        let _ = [VALUES];
        let _ = data::token();
        byte > 255
    }
}
""".replace("VALUES","0,"*160)
    def check(text,key="warm"):
        t.write("lib.rs",text)
        p=rust(t,"lib.rs","--edition=2024","--crate-type=lib","--emit=metadata","--error-format=json",
               "-Zincremental-verify-ich","-Cincremental="+key,check=False)
        return p.returncode,decoded(p.stderr)
    expected=source.replace("allow(unused_comparisons)","expect(unused_comparisons)")
    moved=expected.replace("other() {}","other() {\n    let _ = 1;\n    }")
    nested=moved.replace("let _ = ||","let _: i8 = 0; let _ = ||")
    for text in [source,expected,moved,nested]:
        require(check(text)[0]==0,t.log)
    errors=[]
    for a,b,error in [
        ("expect(unused_comparisons)","deny(unused_comparisons)","comparison is useless due to type limits"),
        ("pub struct Token","struct Token","type `Token` is private"),
        ("[u8; 1]","[bool; 1]","E0308")]:
        text=nested.replace(a,b)
        warm=check(text)
        fresh=check(text,"fresh"+str(len(errors)))
        require(warm[0] and error in str(warm) and warm==fresh,(warm,fresh))
        errors.append(error)
        require(check(nested)[0]==0,t.log)
    return errors

CLIPPY_PRIMARY="""#![deny(unused_parens)]
#![allow(clippy::all)]
#![warn(clippy::unnecessary_literal_unwrap)]
pub fn f(a:u8,b:u8,x:u8) -> u8 {
    Some(a ^ b).unwrap().wrapping_add(Some(x & b).unwrap())
}
#[test]
fn receiver_and_argument() {
    for a in [0u8,1,2,255] { for b in [0,1,2,255] { for x in [0,1,2,255] {
        assert_eq!(f(a,b,x),(a ^ b).wrapping_add(x & b));
    }}}
}
"""
CLIPPY_EDGE="""pub fn cond(a:bool) -> bool {
    struct Mask { bit:bool }
    if Some(Mask { bit:a }.bit).unwrap() {true} else {false}
}
pub fn scrut(a:bool) -> bool {
    struct Mask { bit:bool }
    match Some(Mask { bit:a }).unwrap() { m=>m.bit }
}
pub async fn read(a: bool) -> Result<(), ()> {
    struct Mask { bit: bool }
    impl Mask {
        async fn read(self) -> Result<bool, ()> { Ok(self.bit) }
    }
    if Some(Mask { bit: a }.read().await?).unwrap() {}
    Ok(())
}
#[test]
fn grammar() {
    for a in [false,true] {
        assert_eq!(cond(a),a);
        assert_eq!(scrut(a),a);
    }
}
"""

def autofix(t,edge,fixit):
    t.env["CARGO_BUILD_JOBS"]="1"
    src=CLIPPY_PRIMARY + (CLIPPY_EDGE if edge else "")
    t.package("app",src)
    t.cargo("test --lib")
    cmd="fixit --clippy --Zdangerous-parallel-fixes --allow-no-vcs --all-targets" if fixit else "clippy --fix --lib --allow-no-vcs"
    fix=t.cargo(cmd,check=False)
    notes=t.log
    fixed=(t.dir/"src/lib.rs").read_text()
    (t.logs/"fixed.rs").write_text(fixed)
    p=t.cargo("check",check=False)
    left=fixed.count(".unwrap()")
    t.notes.update(fix_status=fix.returncode,check_status=p.returncode,remaining_unwraps=left)
    if p.returncode or fix.returncode or left:
        require(re.search("struct literals are not allowed|unused_parens|unnecessary parentheses|reverting.*original",notes+t.log),notes+t.log)
        t.known_bug=True
    else:
        t.cargo("test --lib")
        require(("2 passed" if edge else "1 passed") in t.log,t.log)
    return "all unwraps removed, values unchanged"

case("clippy104_argument")(lambda t:autofix(t,False,False))
case("clippy104_struct")(lambda t:autofix(t,True,False))
case("clippy104_fixit")(lambda t:autofix(t,True,True))

MINICORE=r'''#![feature(lang_items,no_core,abi_gpu_kernel,linkage)]
#![allow(internal_features)]
#![no_core]
#[lang = "pointee_sized"] pub trait PointeeSized {}
#[lang = "meta_sized"] pub trait MetaSized: PointeeSized {}
#[lang = "sized"] pub trait Sized: MetaSized {}
#[lang = "copy"] pub trait Copy {}
'''

@case("rustc649")
def kernels(t):
    t.write("gpu.rs",MINICORE+'''#[no_mangle] pub extern "gpu-kernel" fn first(_:i32) {}
#[no_mangle] pub extern "gpu-kernel" fn second(_:i32) {}
''')
    rust(t,"--crate-type=rlib","-Copt-level=2","--target=amdgcn-amd-amdhsa","-Ctarget-cpu=gfx900","--emit=asm","gpu.rs")
    asm=(t.dir/"gpu.s").read_text()
    (t.logs/"gpu.s").write_text(asm)
    kernels=sorted(re.findall(r"\.amdhsa_kernel\s+(first|second)",asm))
    require(kernels,asm)
    t.notes["kernels"]=kernels
    t.known_bug=kernels!=["first","second"]
    return ["first","second"]

@case("rustc651")
def weak(t):
    source=MINICORE+'''#[no_mangle] pub extern "C" fn regular(_: u32) -> u32 { 45 }
#[linkage = "weak"]
#[no_mangle] pub extern "C" fn fallback(_: u32) -> u32 { 45 }
'''
    for name in ("weak","linkonce"):
        extra='#[no_mangle] pub extern "C" fn getter() -> extern "C" fn(u32) -> u32 { fallback }'
        t.write("weak.rs",source.replace('linkage = "weak"',f'linkage = "{name}"')+(extra if name=="linkonce" else ""))
        rust(t,"--crate-type=rlib","-Copt-level=2","-Clto=thin","--target=aarch64-apple-darwin","--emit=asm","weak.rs")
        asm=(t.dir/"weak.s").read_text()
        (t.logs/(name+".s")).write_text(asm)
        require(re.search(r"\.globl\s+_regular",asm),asm)
        visible=bool(re.search(r"\.globl\s+_fallback",asm) and re.search(r"\.weak_definition\s+_fallback",asm))
        t.notes[name]=visible
        if not visible:t.known_bug=True
    return "both visible"

BASELINE_BUGS={"cargo644","cargo646","rustc653","rustc647","cargo650","cargo658","cargo670","cargo668",
                "clippy104_argument","clippy104_struct","clippy104_fixit","rustc649","rustc651"}

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def main():
    global pilot
    versions = {role:{bin:subprocess.check_output([kit/"bin"/bin,"-V"],text=True).strip()
                      for bin in ("rustc","cargo","rustdoc","clippy-driver")} for role,kit in kits.items()}
    pilot = versions["control"] == versions["candidate"] and "ohm-1.100.0-8)" in versions["control"]["rustc"]
    report = dict(pair=pair, pilot=pilot, versions=versions, cases={}, passed=False)
    def save():
        (out/"probes.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    save()
    require("ohm-1.100.0-8)" in versions["control"]["rustc"],versions)
    require(pilot or "ohm-1.100.0-9)" in versions["candidate"]["rustc"],versions)
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
        result["passed"] = ("oracle" in a and a["oracle"]==b.get("oracle")
                            and a["known_bug"]==(name in BASELINE_BUGS)
                            and b["known_bug"]==(pilot and name in BASELINE_BUGS))
        print(name,"PASS" if result["passed"] else "FAIL",
              "baseline bug" if a.get("known_bug") else "",b.get("observed",{}),flush=True)
        save()
    report["passed"] = len(report["cases"])==len(registry) and all(v["passed"] for v in report["cases"].values())
    save()
    return 0 if report["passed"] else 1

if __name__ == "__main__":
    sys.exit(main())

