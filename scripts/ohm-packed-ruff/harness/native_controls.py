"""Prove native input changes, malformed native inputs and type-reader rejection."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def run(argv,cwd,env,destination, expected):
    begin=time.monotonic_ns()
    p=subprocess.run(list(map(str,argv)),cwd=cwd,env=env,capture_output=True)
    destination.with_suffix(".stdout").write_bytes(p.stdout)
    destination.with_suffix(".stderr").write_bytes(p.stderr)
    wanted = p.returncode!=0 if expected=="nonzero" else p.returncode==expected
    if not wanted:
        raise RuntimeError(f"{destination.name} expected {expected}, received {p.returncode}: {p.stderr[-650:]!r}")
    return p


def native_controls(root, receipt, env):
    receipt.mkdir()
    src=root/"control-src";src.mkdir()
    fixture=src/"native-archive";fixture.mkdir()
    (src/"src").mkdir()
    (src/"Cargo.toml").write_text('[package]\nname="ohm_lean_native_guard"\nversion="0.0.0"\nedition="2024"\n[workspace]\n')
    (src/"Cargo.lock").write_text('version = 4\n\n[[package]]\nname = "ohm_lean_native_guard"\nversion = "0.0.0"\n')
    (src/"build.rs").write_text('''fn main() {
        let here = std::env::var("CARGO_MANIFEST_DIR").unwrap();
        println!("cargo::rerun-if-changed=native-archive/libguard.a");
        println!("cargo::rustc-link-search=native={here}/native-archive");
        println!("cargo::rustc-link-lib=static=guard");
    }''')
    (src/"src/main.rs").write_text('unsafe extern "C" {fn observed()->i32;} fn main(){println!("{}",unsafe{observed()});}\n')
    ar=fixture/"libguard.a"
    def provider(value):
        (fixture/"provider.c").write_text(f"int observed(void){{return {value};}}\n")
        subprocess.run(["cc","-c","provider.c","-o","provider.o"],cwd=fixture,check=True)
        if ar.exists():ar.unlink()
        subprocess.run(["ar","crs",ar,"provider.o"],cwd=fixture,check=True)
    cmd=["cargo","+ohm","build","--locked","--offline","-j4","--message-format=json"]
    verdicts={}
    for name,datum in [("first",17),("change",29),("truncated",None),("repair",29),("clean",29)]:
        if datum is None:ar.write_bytes(b"!<arch>\nBROKEN\n")
        else:provider(datum)
        if name=="clean":
            target=root/"fresh-control-t";build=root/"fresh-control-b"
            target.mkdir();build.mkdir()
            env=env|{"CARGO_TARGET_DIR":str(target),"CARGO_BUILD_BUILD_DIR":str(build)}
        before=hashlib.sha256(ar.read_bytes()).hexdigest()
        result=run(cmd,src,env,receipt/name,101 if datum is None else 0)
        messages=[json.loads(line) for line in result.stdout.splitlines()]
        assert messages[-1]=={"reason":"build-finished","success":datum is not None}
        if datum is None:
            assert b"link" in result.stderr.lower() or b"link" in result.stdout.lower()
            verdicts[name]={"archive":before,"error":True};continue
        binary,=[Path(m["executable"]) for m in messages if m.get("executable")]
        execution=run([binary],src,env,receipt/(name+"-run"),0)
        assert execution.stdout.decode().strip()==str(datum)
        verdicts[name]={"archive":before,"result":datum,"executable_sha256":hashlib.sha256(binary.read_bytes()).hexdigest()}
    # Recreate the independent clean root at the same paths in the real parser oracle.
    assert verdicts["first"]["archive"]!=verdicts["change"]["archive"] and verdicts["repair"]["result"]==verdicts["clean"]["result"]
    assert verdicts["repair"]["executable_sha256"] == verdicts["change"]["executable_sha256"] == verdicts["clean"]["executable_sha256"]
    assert verdicts["first"]["executable_sha256"] != verdicts["clean"]["executable_sha256"]
    for value in (64,56):
        reader=src/"reader.rs";reader.write_text(f"const _: [(); {value}] = [(); std::mem::size_of::<[u64;8]>()];\n")
        r=run(["rustc","+ohm","--crate-type=lib","--emit=metadata","--error-format=json",reader,"-o",src/"reader.rmeta"],src,env,receipt/f"reader-{value}",0 if value==64 else 1)
        if value==56:assert any(m.get("code") and m["code"]["code"]=="E0308" for m in map(json.loads,r.stderr.splitlines()))
    (receipt/"verified.json").write_text(json.dumps(verdicts,indent=2,sort_keys=True)+"\n")
    return verdicts


def reader_controls(root, receipt, env, oracle_source):
    """Run the actual pilot reader and archive projection on two synthetic Rust layouts."""
    import outputs
    receipt.mkdir()
    coords=root/"toy-layout";coords.mkdir()
    copy=coords/"harness";copy.mkdir();(copy/"consumer.rs").write_bytes(oracle_source.read_bytes())
    pkg=coords/"src-tree";pkg.mkdir()
    (pkg/"Cargo.toml").write_text('[workspace]\nresolver="2"\nmembers=["ast","parser"]\n')
    a=pkg/"ast";(a/"src").mkdir(parents=True)
    (a/"Cargo.toml").write_text('[package]\nname="ruff_python_ast"\nversion="0.0.0"\nedition="2024"\n')
    p=pkg/"parser";(p/"src").mkdir(parents=True)
    (p/"Cargo.toml").write_text('[package]\nname="ruff_python_parser"\nversion="0.0.0"\nedition="2024"\n[dependencies]\nruff_python_ast={path="../ast"}\n')
    (p/"src/lib.rs").write_text('''pub struct Mod { pub body: Vec<()> }
pub struct Parsed(Mod);
impl Parsed { pub fn has_valid_syntax(&self)->bool { true } pub fn syntax(&self)->&Mod { &self.0 } }
pub fn parse_module(s: &str)->Result<Parsed,()> { if s.trim_end().ends_with('[') {Err(())} else {Ok(Parsed(Mod{body:vec![()]}))} }
''')
    env=env|{"CARGO_TARGET_DIR":str(coords/"target"),"CARGO_BUILD_BUILD_DIR":str(coords/"build")}
    verdicts={}
    for name,size in (("A",64),("B",56)):
        (a/"src/lib.rs").write_text(f"pub struct Expr(pub [u8; {size}]);\n")
        d=receipt/name;d.mkdir()
        cmd=["cargo","+ohm","build","--offline","-j4","--message-format=json","-p","ruff_python_parser"]
        cargo=run(cmd,pkg,env,d/"cargo",0)
        msgs=list(map(json.loads,cargo.stdout.splitlines()))
        assert msgs[-1]=={"reason":"build-finished","success":True}
        one=outputs.outputs(msgs,d,coords,coords,env,pkg,name,run)
        assert one['typed_size']==size and outputs.compare(one,one)=={}
        verdicts[name]={k:v for k,v in one.items() if k!="archives"}
        if name=="B":
            wrong=receipt/"incorrect-oracle";wrong.mkdir()
            try:outputs.outputs(msgs,wrong,coords,coords,env,pkg,"A",run)
            except AssertionError:pass
            else:raise AssertionError("accepted stale expected layout A on B")
    (receipt/"verified.json").write_text(json.dumps(verdicts,sort_keys=True,indent=2)+"\n")
