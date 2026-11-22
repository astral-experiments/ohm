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
root = Path(tempfile.mkdtemp(prefix="probes7-", dir=os.environ["RUNNER_TEMP"]))
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

@case("rustc581")
def character_columns(t):
    source = "/*abc*/pub const fn f()->u32 { std::panic::Location::caller().column() }\n"
    t.package("app", "const _: () = assert!((const { dep::f() }) == 32);\nfn main() {}", DEP, True)
    t.package("dep", source)
    t.cargo("check --release")
    t.write("dep/src/lib.rs", source.replace("abc","汉"))
    return t.compare_error("check --release","E0080",True)


@case("rustc584")
def dependency_snippet(t):
    source = "pub fn f<'a, 'b: 'a, 'c>(_: &'a str, _: &'b str, _: &'c str) {} // OLD\n"
    t.package("app", """fn main() { dep::f::<'static, 'static>("", "", ""); }""", DEP, True)
    t.package("dep", source)
    old = t.diagnostics("check --release")
    require(old[0]==0 and "OLD" in str(old), t.log)
    t.write("dep/src/lib.rs",source.replace("OLD","NEW"))
    warm,fresh = t.diagnostics("check --release"), t.diagnostics("check --release",target="fresh")
    require(fresh[0]==0 and "NEW" in str(fresh) and "OLD" not in str(fresh), t.log)
    require(warm in (old, fresh), warm)
    t.known_bug = warm == old
    return fresh


@case("cargo613")
def external_doctest(t):
    t.package("app",'#[cfg(doctest)] extern crate examples;\n#[cfg(doctest)] #[doc = examples::example!()] pub fn example() {}')
    t.write("build.rs",'''fn main() {
        println!("cargo::rerun-if-changed=build.rs");
        println!("cargo::rustc-link-search={}/ext", env!("CARGO_MANIFEST_DIR"));
    }''')
    (t.dir/"ext").mkdir()
    def library(value):
        doc = json.dumps("```\nassert_eq!(1, %d);\n```" % value)
        t.write("examples.rs","#[macro_export] macro_rules! example { () => { "+doc+" } }")
        t.run(t.kit/"bin/rustc","--crate-type=rlib","examples.rs","--out-dir","ext")
    library(1)
    t.cargo("test --doc")
    library(2)
    result = t.doc_edit("assertion")
    library(1)
    t.cargo("test --doc")
    return result


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


@case("cargo623")
def competing_module(t):
    t.package("app","#[cfg(doctest)] mod extra;")
    t.write("src/extra.rs","//! ```\n//! assert!(true);\n//! ```\n")
    t.cargo("test --doc")
    t.cargo("test --doc")
    t.write("src/extra/mod.rs","")
    result = t.doc_edit("E0761")
    (t.dir/"src/extra/mod.rs").unlink()
    t.cargo("test --doc")
    return result


@case("cargo618")
def sibling_library(t):
    if sys.platform=="darwin":
        # The installed -6 rust-objcopy can't locate libLLVM in this local pilot.
        t.env["CARGO_PROFILE_RELEASE_STRIP"] = "none"
    t.package("app","extern crate generated; const _: () = assert!(generated::VALUE == 1);",DEP+"\npublisher.path='publisher'")
    t.package("dep","")
    t.package("publisher","")
    t.write("publisher/build.rs",'''fn main() {
        println!("cargo::rerun-if-env-changed=GENERATED_DIR");
        println!("cargo::rustc-link-search={}",std::env::var("GENERATED_DIR").unwrap());
    }''')
    t.write("dep/build.rs",'''fn main() {
        println!("cargo::rerun-if-changed=generated.rs");
        assert!(std::process::Command::new(std::env::var_os("RUSTC").unwrap())
            .args(["--crate-type=rlib","generated.rs","--out-dir"]).arg(std::env::var_os("OUT_DIR").unwrap())
            .status().unwrap().success());
    }''')
    t.write("dep/generated.rs","pub const VALUE: u32 = 1;")
    t.cargo("build --release -p dep")
    generated, = (t.dir/"target").rglob("libgenerated.rlib")
    t.env["GENERATED_DIR"] = str(generated.parent)
    t.cargo("build --release")
    t.write("dep/generated.rs","pub const VALUE: u32 = 2;")
    t.cargo("build --release -p dep")
    return t.compare_error("build --release","E0080",True)


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


# Run the ordinary Clippy traversal before --fix. A cached ordering of
# overlapping suggestions can roll back the edit or silently change the result.
FIXES = {
    "clippy92": (
        "pub fn f(a: bool) -> bool { (matches!(if a { false } else { true }, true)) == false }\n",
        "for a in [true,false] { assert_eq!(app::f(a),a); }"),
    "clippy95": (
        "#![warn(clippy::equatable_if_let)]\npub fn f(p: bool) -> bool { if let true = p == false { false } else { true } }\n",
        "for a in [true,false] { assert_eq!(app::f(a),a); }"),
    "clippy98": (
        'pub fn f(s: String) -> bool { !matches!(s.to_string() != "".to_owned(), true) }\n',
        'for s in ["","a","汉"] { assert_eq!(app::f(s.to_owned()),s.is_empty()); }'),
    "clippy100": (
        "pub fn f(a: bool, b: bool) -> bool { Some(a & b).unwrap() == false }\n",
        "for a in [true,false] { for b in [true,false] { assert_eq!(app::f(a,b),!(a & b)); } }"),
}


def clippy_fix(t, name):
    source,check = FIXES[name]
    t.package("app",source)
    t.write("tests/cases.rs","#[test] fn values() {"+check+"}")
    t.cargo("clippy --lib")
    def order(**kw):
        msgs = t.diagnostics("clippy --lib",**kw)
        require(not msgs[0], msgs)
        return [m["code"]["code"] for m in msgs[1] if m["code"] and m["code"]["code"].startswith("clippy::")]
    actual_order = order()
    t.cargo("clippy --lib")
    warm = t.cargo("clippy --lib --fix --allow-no-vcs",check=False)
    fixed = (t.dir/"src/lib.rs").read_text()
    require(warm.returncode == 0 or (fixed==source and "fix" in t.log),t.log)
    values = t.cargo("test --test cases",check=False)
    if values.returncode:
        require(name=="clippy100" and "!a & b" in fixed and "1 failed" in t.log,t.log)
    else:
        require("1 passed" in t.log, t.log)

    # Nonincremental Clippy always uses its whole-crate traversal.
    t.write("src/lib.rs",source)
    clean = dict(env={"CARGO_INCREMENTAL":"0"},target="fresh")
    expected_order = order(**clean)
    t.cargo("clippy --lib --fix --allow-no-vcs",**clean)
    expected = (t.dir/"src/lib.rs").read_text()
    require(expected != source and len(expected_order) >= 2, (expected,expected_order))
    t.cargo("test --test cases",**clean)
    require("1 passed" in t.log,t.log)
    require(sorted(actual_order)==sorted(expected_order),(actual_order,expected_order))
    t.notes.update(fixed=fixed,order=actual_order,values_ok=not values.returncode)
    t.known_bug = fixed!=expected or actual_order!=expected_order or bool(warm.returncode or values.returncode)
    return dict(source=expected, order=expected_order)


for name in FIXES:
    case(name)(lambda t, label=name: clippy_fix(t,label))


@case("clippy96")
def unit_arg(t):
    t.package("app","#![warn(clippy::unit_arg)]\npub mod first;\n")
    source = "fn consume(_: ()) {}\nfn mark() {}\npub fn run() { consume(mark(/*hide*/)); }\n"
    # JSON deliberately selects the whole-crate traversal on -7.
    def lint(target):
        t.cargo("clippy --lib",target=target)
        return ("clippy::unit_arg" in t.log or "#unit_arg" in t.log)
    observations=[]
    for n,comment in enumerate(["/*hide*/","        ","/*hide*/"]):
        t.write("src/first.rs",source.replace("/*hide*/",comment))
        warm,fresh = lint("target"),lint("fresh"+str(n))
        require(fresh == (n==1),t.log)
        observations.append(warm)
    require(observations in ([False,False,False],[False,True,False]),observations)
    t.known_bug = not observations[1]
    t.notes["warm"] = observations
    return [False,True,False]


@case("cargo616")
def warning_replay(t):
    source = '#[deprecated(note="use other")]\npub fn f() {}'
    call = "fn main() { dep::f(); }"
    t.package("app",call,DEP,True)
    t.package("dep",source)
    cmd = "check -v -p app"
    results = []
    for i,(consumer,declaration,note) in enumerate([
            (call,source,"use other"),
            (call,source.replace("pub fn","\npub fn"),"use other"),
            (call,source.replace("use other","use new"),"use new"),
            ("macro_rules! m { () => { dep::f() }; } fn main() { m!(); }",source,"use other"),
    ]):
        if i==3:t.write("src/main.rs",consumer)
        t.write("dep/src/lib.rs",declaration)
        warm = t.diagnostics(cmd)
        if i==1: t.notes["skipped_binary"] = "--crate-name app " not in t.log
        fresh = t.diagnostics(cmd,target="fresh"+str(i))
        require(warm==fresh and warm[0]==0 and note in str(warm), (i,warm,fresh))
        results.append(warm)
    return results


@case("rustc555")
def moving_docs(t):
    source = """#[derive(Clone)] pub struct Packet;
impl Packet {
/// Read a packet.
/// Use the default size.
pub fn read(&self) {}
pub fn write(&self) {}
}
#[derive(Clone, Debug)] pub struct Cursor;
"""
    call = "fn main() { dep::Packet.read(); }"
    t.package("app",call,DEP,True)
    t.package("dep",source)
    cmd = "check -v -p app"
    require(t.diagnostics(cmd)==(0,[]),t.log)
    t.write("dep/src/lib.rs",source.replace("/// Use","///\n/// Another line.\n/// Use"))
    require(t.diagnostics(cmd)==(0,[]), t.log)
    t.notes["skipped_binary"] = "--crate-name app " not in t.log
    t.write("src/main.rs",call.replace("read()", "read(1)"))
    result = t.compare_error(cmd,"E0061")
    require("lib.rs:7:" in str(result),result)
    return result


TRAITS = {
    "rustc594": (
        "pub trait Marker {}\npub struct Payload<T>(T);\npub fn f(_: Option<&Payload<[u8; 8]>>) {}",
        "Payload<T>", "Payload<T: Marker>", "E0277"),
    "rustc600": (
        """pub struct Tag;
        pub trait Project<'a> { type Output; }
        impl<'a> Project<'a> for Tag { type Output = &'a u8; }
        pub fn project<'a, 'b>(_: &'b <Tag as Project<'a>>::Output, x: &'a u8) -> &'b u8 { x }""",
        "Output = &'a u8", "Output = u8", "lifetime may not live long enough"),
    "rustc602": (
        """pub struct Contains<'a>(pub &'a u8);
        fn shorten<'x, 'y>(_: &'x Contains<'y>, x: &'y u8) -> &'x u8 { x }
        pub fn call<'a,'b>(w: &'a Contains<'static>, x: &'b u8) -> &'a u8 { shorten(w, &0) }""",
        "shorten(w, &0)", "shorten(w, x)", "lifetime may not live long enough"),
    "rustc610": (
        """pub struct Wrap<T: ?Sized>(T);
        pub fn tail(x: &Wrap<[u8; 4]>) -> &Wrap<[u8]> { x }
        pub fn bytes(v: &Vec<u8>) -> &[u8] { v }
        pub fn object<T: std::fmt::Debug>(v: &T) -> &dyn std::fmt::Debug { v }""",
        "object<T: std::fmt::Debug>", "object<T>", "E0277"),
    "rustc611": (
        """pub struct Tail<T: ?Sized>(T);
        pub enum Entry<'a,'b> { Pair(Box<Tail<(&'a str, &'b str)>>), Empty }
        pub fn first<'a,'b>(xs: &[Entry<'a,'b>]) -> &'a str {
            match &xs[0] { Entry::Pair(pair) => pair.0.0, Entry::Empty => "" }
        }""",
        "(&'a str, &'b str)", "(&'b str, &'a str)", "lifetime may not live long enough"),
}


def trait_change(t,label):
    source,before,after,code = TRAITS[label]
    t.package("app",source)
    t.cargo("check")
    t.write("src/lib.rs",source.replace(before,after))
    fresh = t.compare_error("check",code)
    t.write("src/lib.rs",source)
    t.cargo("check")
    return fresh


for name in TRAITS:
    case(name)(lambda t,label=name: trait_change(t,label))


@case("rustc607")
def driver(t):
    if sys.platform != "linux":
        require(pilot,"Linux driver required")
        t.notes["skipped"] = "Non-Linux pilot"
        return None
    so, = (t.kit/"lib").glob("librustc_driver*.so")
    # Avoid putting a full driver symbol table or relocation listing in the artifact.
    def readelf(*args):
        return subprocess.check_output(["readelf","--wide",*args,str(so)],text=True)
    symbols = readelf("--dyn-syms")
    exported = [ln for ln in symbols.splitlines() if "PROTECTED" in ln and " UND " not in ln]
    t.notes["protected"] = len(exported)
    t.notes["protected_rust"] = sum(bool(re.search(r"\s_(?:R|ZN)",ln)) for ln in exported)
    relocations = readelf("--relocs")
    for rel in ("R_X86_64_GLOB_DAT","R_X86_64_64"):
        t.notes[rel] = relocations.count(rel)
    comment = readelf("--string-dump=.comment")
    t.notes["linker_id"] = [ln.strip() for ln in comment.splitlines() if "Linker:" in ln]
    lld = t.kit/"lib/rustlib/x86_64-unknown-linux-gnu/bin/rust-lld"
    info = t.run(lld,"-flavor","gnu","--version",env={"LD_LIBRARY_PATH":str(t.kit/"lib")})
    t.notes["bundled_lld"] = info.stdout.strip()
    require("LLD" in info.stdout,t.log)
    if t.role=="candidate" and not pilot:
        require(t.notes["protected_rust"] > 0, t.notes)
        require(not t.notes["linker_id"] or any("LLD" in ln for ln in t.notes["linker_id"]),t.notes)
    return "LLD"


@case("rustdoc_clippy")
def tools(t):
    t.package("app","/// Probe for the installed driver.\npub fn probe() -> u8 { return 42; }")
    t.cargo("doc --lib --no-deps")
    require("Probe for the installed driver." in (t.dir/"target/doc/app/fn.probe.html").read_text(),t.log)
    p = t.cargo("clippy --lib -- -D clippy::needless_return",check=False)
    require(p.returncode and "needless_return" in t.log,t.log)
    return "html and lint"


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def main():
    global pilot
    versions = {role:{bin:subprocess.check_output([kit/"bin"/bin,"-V"],text=True).strip()
                      for bin in ("rustc","cargo","rustdoc","clippy-driver")} for role,kit in kits.items()}
    pilot = versions["control"] == versions["candidate"] and "ohm-1.100.0-6)" in versions["control"]["rustc"]
    report = dict(pair=pair, pilot=pilot, versions=versions, cases={}, passed=False)
    def save():
        (out/"probes.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    save()
    require("ohm-1.100.0-6)" in versions["control"]["rustc"],versions)
    require(pilot or "ohm-1.100.0-7)" in versions["candidate"]["rustc"],versions)
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
        if name=="rustc607" and not pilot and result["passed"]:
            result["passed"] = b["observed"]["protected_rust"] > a["observed"]["protected_rust"]
        print(name,"PASS" if result["passed"] else "FAIL",
              "baseline bug" if a.get("known_bug") else "",b.get("observed",{}),flush=True)
        save()
    report["passed"] = len(report["cases"])==22 and all(v["passed"] for v in report["cases"].values())
    save()
    return 0 if report["passed"] else 1

if __name__ == "__main__":
    sys.exit(main())

