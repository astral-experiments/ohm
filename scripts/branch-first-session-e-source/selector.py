"""Type-check the actual rustc_interface selector against both session layouts."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import argparse
import shutil
import tempfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("repository", type=Path)
parser.add_argument("sdk", type=Path)
parser.add_argument("receipts", type=Path)
args=parser.parse_args()
ROOT=args.repository.resolve()
SDK=args.sdk.resolve()
args.receipts.mkdir()
K = "0afbeff303d3658bff52582d8f1a996d59e6c8ce"
E = "c9a6a212d38d778ed0e9d2c7057a9dedb179fff2"
S = "compiler/rustc_session/src/session.rs"
Q = "compiler/rustc_interface/src/queries.rs"

def show(rev, path):
    return subprocess.check_output(["git", "-C", ROOT, "show", f"{rev}:{path}"], text=True)

def decl(s, start):
    a = s.index(start)
    return s[a:s.index("\n}\n", a) + 3]

def block(s):
    a = s.index("let temporary_modules =")
    return s[a:s.index("rustc_incremental::finalize_session_directory(", a)]

def sha(b):
    return hashlib.sha256(b).hexdigest()

with tempfile.TemporaryDirectory(prefix="ohm-switch-selector-") as t:
    tmp = Path(t)
    home = tmp / "rustup"
    (home / "toolchains").mkdir(parents=True)
    (home / "toolchains/ohm").symlink_to(SDK, target_is_directory=True)
    env = dict(os.environ, RUSTUP_HOME=str(home))
    rustc = [shutil.which("rustc"), "+ohm"]
    selected=subprocess.check_output(["rustup","which","--toolchain","ohm","rustc"],env=env,text=True).strip()
    assert Path(selected).samefile(SDK/"bin/rustc"), "different actual compiler"
    def run(cmd):
        return subprocess.run(cmd, cwd=tmp, env=env, capture_output=True, text=True)
    vv = run(rustc + ["-vV"])
    assert vv.returncode == 0 and "release:" in vv.stdout, vv
    results = {"compiler": vv.stdout, "sdk_executable_sha256": sha((SDK / "bin/rustc").read_bytes()), "cases": {}}
    bodies = {"K": block(show(K, Q)), "E": block(show(E, Q))}
    # The failed E job has exactly the K selector with E's new record. The original
    # failed source and its selected body are also hash-bound in the signed control.
    assert sha(bodies["K"].encode()) == "9a9f53fe233bc930b59e9f037657c4fd3f9a0a5f065485597f258b496c2cee65"
    assert sha(bodies["E"].encode()) == "984498d47c6c38948f9eb436edc82d046baad3f3360d9b5ccfa944f3b33d52c0"
    for role, layout, body in [("K","K","K"), ("stale","E","K"), ("E","E","E"), ("both_variants","E","E")]:
        ds = show(K if layout == "K" else E, S)
        rec = decl(ds, "pub struct IncrCompSession {")
        enum = "" if layout == "K" else decl(ds,"pub enum BranchCachePacking {")
        lib = "use std::path::PathBuf; pub mod flock {pub type Lock=std::fs::File;}\n" + enum + rec
        (tmp / "session.rs").write_text(lib)
        rc = run(rustc + ["--crate-name", "rustc_session", "--crate-type", "rlib", "--edition", "2024", "session.rs"])
        assert rc.returncode == 0, rc.stderr
        field = ("branch_cache_source: (role == 3).then(|| \"old\".into())," if layout == "K" else
                 "branch_cache_packing: match role {2=>Some(BranchCachePacking::FirstCheckout),3=>Some(BranchCachePacking::SwitchedFrom(\"old\".into())),_=>None},")
        actual = bodies[body]
        if role == "both_variants":
            original = "matches!(s.branch_cache_packing, Some(BranchCachePacking::SwitchedFrom(_)))"
            assert actual.count(original) == 1
            actual = actual.replace(original, "s.branch_cache_packing.is_some()")
        source = """
use rustc_session::*;
enum OutputType { Object }
#[derive(PartialEq,Eq,Clone,Copy)] enum SplitDebuginfo { Packed, Unpacked }
struct Cg {save_temps: bool} struct Unstable {no_link:bool,emit_rlink:bool}
struct Outputs(bool,bool);
impl Outputs { fn should_link(&self)->bool{self.0} fn contains_key(&self,_:&OutputType)->bool{self.1} }
struct Opts {cg:Cg,unstable_opts:Unstable,output_types:Outputs}
struct Session {opts:Opts,split:SplitDebuginfo}
impl Session {fn split_debuginfo(&self)->SplitDebuginfo{self.split}}
struct Compiled { modules:[u8;2] }
fn main(){
for role in 0..4 { for bits in 0u32..64 {
 let flag=|n| bits & (1u32<<n) != 0u32;
 let sess=Session {opts:Opts{cg:Cg{save_temps:flag(0)},unstable_opts:Unstable{no_link:flag(1),emit_rlink:flag(2)},output_types:Outputs(flag(3),flag(4))},split:if flag(5){SplitDebuginfo::Unpacked}else{SplitDebuginfo::Packed}};
 let incr_comp_session = (role!=0).then(|| IncrCompSession {session_directory:"dest".into(),FIELD _lock_file:std::fs::File::open("/dev/null").unwrap()});
 let compiled_modules=Compiled{modules:[17,29]};
 BODY
 if let Some(s) = incr_comp_session { assert_eq!(s.session_directory,std::path::Path::new("dest")); drop(s._lock_file); }
 println!("{role} {bits} {}",temporary_modules.len());
}}}
""".replace("FIELD", field).replace("BODY",actual)
        (tmp / "caller.rs").write_text(source)
        cc = run(rustc + ["--edition","2024","--extern","rustc_session=librustc_session.rlib","caller.rs","-o","caller"])
        entry = {"session_layout_sha256":sha(lib.encode()), "literal_selector_sha256":sha(actual.encode()), "typecheck":cc.returncode}
        (args.receipts/(role+"-compiler.stderr")).write_text(cc.stderr)
        if role == "stale":
            assert cc.returncode == 1 and "error[E0609]" in cc.stderr and "no field `branch_cache_source`" in cc.stderr, cc.stderr
            entry["diagnostic"] = cc.stderr
        else:
            assert cc.returncode == 0, cc.stderr
            exe = run([tmp / "caller"]); assert exe.returncode == 0, exe.stderr
            (args.receipts/(role+"-run.stdout")).write_text(exe.stdout)
            rows = [tuple(map(int, line.split())) for line in exe.stdout.splitlines()]
            assert len(set((r,b) for r,b,_ in rows)) == len(rows) == 256
            positive = [(r,b,n) for r,b,n in rows if n]
            assert positive == ([(2,8,2),(3,8,2)] if role == "both_variants" else [(3,8,2)]), positive
            entry.update(rows=len(rows), selected=positive, stdout_sha256=sha(exe.stdout.encode()))
        results["cases"][role] = entry
    assert results["cases"]["K"]["stdout_sha256"] == results["cases"]["E"]["stdout_sha256"]
    results["source"] = E
    driver, = (SDK/"lib").glob("librustc_driver-*.so")
    with driver.open("rb") as f:
        results["driver_sha256"] = hashlib.file_digest(f,"sha256").hexdigest()
    out=args.receipts/"result.json"
    out.write_text(json.dumps(results,indent=2,sort_keys=True)+"\n")
    verify_native=Path(__file__).with_name("selector_record.py")
    subprocess.run([shutil.which("python3"),"-IB",verify_native,args.receipts],check=True)
