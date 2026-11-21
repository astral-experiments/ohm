"""Exercise fixes through their normal Cargo entry points."""
import json
from pathlib import Path
import shutil
import subprocess

fixtures = json.loads((Path(__file__).parent / "regressions.json").read_text())


def manifest(pkg):
    return f'[package]\nname="{pkg}"\nversion="0.1.0"\nedition="2024"\n'


def package(lib, client):
    return {"Cargo.toml": manifest("client") + '[dependencies]\ndep={path="dep"}\n',
            "dep/Cargo.toml": manifest("dep"), "dep/src/lib.rs":lib, "src/main.rs":client}


def verify(root, log, cargo, settings):
    log.mkdir()
    base = root / "probes"
    base.mkdir()
    result = {}
    edition = None
    counter = 0

    def write(name, text):
        path = cwd / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(text)
        return path

    def init(n, files):
        nonlocal env, cwd, edition
        cwd = base / str(n)
        cwd.mkdir()
        env = settings | {"CARGO_HOME":str(cwd / "cargo"), "CARGO_TARGET_DIR":str(cwd / "target")}
        edition = str(n)
        if n in (474,487,495,497):
            env["RUSTC_BOOTSTRAP"] = "1"
        for name, text in files.items():
            write(name, text)

    def run(args, code=0, contains=None, value=None):
        nonlocal counter
        p = subprocess.run([cargo, *args.split()], cwd=cwd, env=env, capture_output=True, text=True)
        counter += 1
        (log / f"{edition}-{counter}.txt").write_text(str(p.returncode) + "\n" + p.stdout + p.stderr)
        found = p.returncode == code
        if contains:
            found &= contains in p.stdout + p.stderr
        if value is not None:
            found &= p.stdout.strip() == str(value)
        result[edition] = result.get(edition, True) and found
        return p

    env, cwd = {}, None
    for n, cmd, rc, text, value in [
            (457,"check -p client",101,"gated behind",None),
            (474,"check -p client",0,None,None),
            (476,"run -p client",0,None,1),
            (480,"check -p client",101,"E0603",None),
            (572,"test --doc",101,"assertion",None)]:
        init(n,fixtures[str(n)])
        for _ in range(2):run(cmd,rc,text,value)
    lib = """
mod inner {
    pub trait Ext { fn len(&self) -> usize { 13 } }
    impl Ext for Box<str> {}
}
mod m { pub(crate) use super::inner::Ext; }
use m::*;
pub use inner::*;
"""
    init(483,package(lib, 'use dep::*; fn main(){let x:Box<str>="ok".into();println!("{}",x.len());}'))
    run("run",value=13)
    init(486,package("", '#[macro_use] extern crate dep;\nfn main() { println!("{}",line!()); }'))
    for alias, expected in [("first",43),("other",17)]:
        write("dep/src/lib.rs", "macro_rules! first { () => { 43 }; }\nmacro_rules! other { () => { 17 }; }\nuse "+alias+" as line;\n")
        run("run",value=expected)
    files = package("#![feature(extern_item_impls)] #[eii(provide)] pub fn val() -> u8 { 7 }",
                    "#![feature(extern_item_impls)] #[dep::provide] fn answer() -> u8 { 43 }")
    files["src/lib.rs"] = files.pop("src/main.rs")
    init(487,files)
    run("check")
    init(495,fixtures["495"])
    run("check")
    init(497,fixtures["497"])
    run("check",101,"inline")
    init(499,fixtures["499"])
    run("check")
    write("src/lib.rs",fixtures["499"]["src/lib.rs"]+"\npub fn another() {}\n")
    run("check")
    run("build")
    init(569,{
        "Cargo.toml":manifest("foo")+'[dependencies]\noptional={version="0.1",optional=true}\n',
        "src/lib.rs":"",
        ".cargo/config.toml":'[source.crates-io]\nreplace-with="vendor"\n[source.vendor]\ndirectory="vendor"\n',
        "vendor/optional/Cargo.toml":manifest("optional"),
        "vendor/optional/src/lib.rs":"",
        "vendor/optional/.cargo-checksum.json":'{"files":{},"package":null}'
    })
    run("generate-lockfile --offline")
    run("check --locked --offline")
    shutil.rmtree(cwd / "vendor/optional")
    run("check --locked --offline",101,"no matching package")
    dep = base / "git-dep"
    init(573,{"Cargo.toml":manifest("foo")+'[dependencies]\ndep={git="'+dep.as_uri()+'"}\n',
              "src/lib.rs":"pub use dep::read;"})
    write("../git-dep/Cargo.toml",manifest("dep"))
    original = "pub fn read()->u8{43}"
    write("../git-dep/src/lib.rs",original)
    for args in (["init","-q"],["add","."],["-c","user.name=Fixture","-c","user.email=fixture@example.org","commit","-qm","Source"]):
        subprocess.run(["git","-C",dep,*args],check=True)
    run("fetch")
    checkout, = (cwd/"cargo/git/checkouts").glob("*/*/.git")
    (checkout/"config").write_text("[core]\nrepositoryformatversion = 1\n[extensions]\nfuture = true\n")
    code = checkout.parent / "src/lib.rs"
    code.write_text("pub fn read()->u8{5}")
    run("vendor --locked --offline")
    result[edition] &= (code.read_text()==original and (cwd/"vendor/dep/src/lib.rs").read_text()==original)
    init(580, {"Cargo.toml":manifest("foo"),"src/main.rs":'fn main(){println!("chosen");}'})
    for arg in ("-o chosen","--emit=link=chosen"):
        run("rustc -- "+arg)
        exe = cwd / "chosen"
        result[edition] &= exe.exists() and subprocess.check_output([exe]).strip()==b"chosen" and not (cwd/"chosen.rlink").exists()
        exe.unlink(missing_ok=True)
    init(94,fixtures["94"])
    path = cwd / "settings.toml"
    path.symlink_to("/dev/null")
    args = "fmt --check -- --config-path settings.toml"
    run(args)
    path.unlink()
    p=run(args,1)
    result[edition] &= "settings.toml" in p.stdout+p.stderr
    shutil.rmtree(base)
    print(json.dumps(result),flush=True)
    return result
