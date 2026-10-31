"""Exercise ordinary Cargo builds across a private exported constructor edit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def source(symbol, value, invalid):
    if invalid:
        return 'pub const BAD_BUILD: u8 = "must be rejected";\n'
    return f'''extern "C" fn install() {{
    super::VALUE.store({value}, core::sync::atomic::Ordering::SeqCst);
}}
#[used]
#[unsafe(export_name = "ohm_retained_hook_{symbol}")]
#[cfg_attr(target_vendor = "apple", unsafe(link_section = "__DATA,__mod_init_func,mod_init_funcs"))]
#[cfg_attr(not(target_vendor = "apple"), unsafe(link_section = ".init_array"))]
static REGISTER: extern "C" fn() = install;
'''


def cargo_lane(work, receipts, rustup, shims, mode, role, revision, cargo_sha):
    root = work / "project"
    for part in ("dep/src", "app/src", "app/tests"):
        (root / part).mkdir(parents=True, exist_ok=True)
    receipts.mkdir(parents=True)
    (root / "Cargo.toml").write_text('[workspace]\nmembers=["dep","app"]\nresolver="3"\n')
    for package in ("dep", "app"):
        extra = '[dependencies]\ndep={path="../dep"}\n' if package == "app" else ""
        (root / package / "Cargo.toml").write_text(f'[package]\nname="{package}"\nversion="0.0.0"\nedition="2024"\n' + extra)
    (root / "Cargo.lock").write_text('version = 4\n\n[[package]]\nname="dep"\nversion="0.0.0"\n\n[[package]]\nname="app"\nversion="0.0.0"\ndependencies=["dep"]\n')
    (root / "dep/src/lib.rs").write_text("use core::sync::atomic::{AtomicU8,Ordering};\nstatic VALUE: AtomicU8 = AtomicU8::new(3);\npub fn value() -> u8 { VALUE.load(Ordering::SeqCst) }\nmod hidden;\n")
    binding = 'let v=dep::value(); println!("actual native = {v}"); assert_eq!(v,std::env::var("WANT").unwrap().parse::<u8>().unwrap());'
    (root / "app/src/main.rs").write_text("fn main() { " + binding + " }\n")
    (root / "app/tests/control.rs").write_text("#[test] fn root_value() { " + binding + " }\n")
    argv = ["cargo", "+ohm", "build", "--bin", "app"] if mode == "build" else ["cargo", "+ohm", "test", "--test", "control", "--no-run"]
    argv += ["-p", "app", "--locked", "--offline", "--message-format=json"]
    env = {k:os.environ[k] for k in ("USER","LANG","LC_ALL","SDKROOT","DEVELOPER_DIR","MACOSX_DEPLOYMENT_TARGET","TMPDIR") if k in os.environ}
    env.update(PATH=str(shims) + os.pathsep + os.environ["PATH"], HOME=str(work/"home"), CARGO_HOME=str(work/"cargo-home"), RUSTUP_HOME=str(rustup),
               RUSTUP_AUTO_INSTALL="0", CARGO_NET_OFFLINE="true", CARGO_TERM_COLOR="never", RUST_BACKTRACE="0")
    for name in ("HOME","CARGO_HOME"):
        Path(env[name]).mkdir()

    def capture(cmd, dst, expected=None, **extra):
        p = subprocess.run(cmd, env=env | extra, cwd=root, capture_output=True, timeout=180)
        (dst.parent / (dst.name + ".stdout")).write_bytes(p.stdout)
        (dst.parent / (dst.name + ".stderr")).write_bytes(p.stderr)
        if expected is not None:
            assert p.returncode == expected, (cmd, p.returncode, p.stderr[-1200:])
        return p

    sdk = rustup / "toolchains/ohm"
    cargo = sdk / "bin/cargo"
    driver, = (sdk/"lib").glob("librustc_driver-*." + ("dylib" if platform.system()=="Darwin" else "so"))
    assert digest(cargo) == cargo_sha
    versions = {t:capture([t,"+ohm","-vV"], receipts/t, 0).stdout.decode() for t in ("cargo","rustc","rustdoc")}
    for tool, rev in (("cargo","4591cf45cc10abb19d2456c40b99606e08167f29"),("rustc",revision),("rustdoc",revision)):
        assert "commit-hash: " + rev + "\n" in versions[tool], (tool, versions[tool])
    save(receipts/"identity.json", {"versions":versions,"cargo":digest(cargo),"driver":digest(driver),"rustc":digest(sdk/"bin/rustc"),"argv":argv,"role":role})
    results = {}
    selected = root/"dep/src/hidden.rs"
    for phase, symbol, value, lane in [
        ("cold-A","aaaa",17,"warm"),("repeat-A","aaaa",17,"warm"),
        ("edit-B","bbbb",83,"warm"),("repeat-B","bbbb",83,"warm"),
        ("type-error","bbbb",83,"warm"),("repair-B","bbbb",83,"warm"),("restore-A","aaaa",17,"warm"),
        ("empty-B","bbbb",83,"empty"),("empty-B-repeat","bbbb",83,"empty")]:
        data = source(symbol,value,phase=="type-error")
        if not selected.exists() or selected.read_text() != data:
            selected.write_text(data)
        env.update(CARGO_TARGET_DIR=str(work/lane/"target"), CARGO_BUILD_BUILD_DIR=str(work/lane/"build"))
        out = receipts/phase
        out.mkdir()
        (out/"source.rs").write_text(data)
        res = capture(argv, out/"cargo")
        messages = [json.loads(line) for line in res.stdout.splitlines()]
        assert [m["success"] for m in messages if m["reason"]=="build-finished"] == [res.returncode==0]
        diag = res.stderr.decode() + "\n".join((m["message"]["rendered"] or "") for m in messages if m["reason"]=="compiler-message")
        ices = list(root.glob("rustc-ice-*.txt"))
        for ice in ices:
            ice.rename(out/ice.name)
        row = {"exit":res.returncode, "source":digest(selected), "ice":bool(ices) or "internal compiler error" in diag,
               "unstable_export": "unstable fingerprints" in diag and "codegen_fn_attrs" in diag}
        if phase=="type-error":
            assert res.returncode and not row["ice"] and any(m.get("message",{}).get("code",{}) and m["message"]["code"]["code"]=="E0308" for m in messages)
        elif res.returncode:
            assert role=="parent" and lane=="warm" and phase not in ("cold-A","repeat-A") and row["unstable_export"], (phase, diag[-2000:])
        else:
            assert not row["ice"]
            product, = [Path(m["executable"]) for m in messages if m["reason"]=="compiler-artifact" and m.get("executable") and m["target"]["name"]==("app" if mode=="build" else "control")]
            shutil.copy2(product, out/"product")
            row["product"] = digest(product)
            syms = capture(["nm","-a",str(product)],out/"nm",0)
            row["markers"] = sorted({word.removeprefix("_") for word in re.findall(r"\b_?ohm_retained_hook_[a-z]+\b",syms.stdout.decode())})
            args = [str(product)]
            if mode=="test":
                lines = capture(args+["--list"],out/"inventory",0).stdout.splitlines()
                assert lines == [b"root_value: test",b"",b"1 test, 0 benchmarks"], lines
                args += ["--exact","root_value","--nocapture"]
            p = capture(args,out/"positive",WANT=str(value))
            actual, = re.findall(rb"actual native = (\d+)",p.stdout)
            actual = int(actual)
            assert (p.returncode==0)==(value==actual)
            assert actual==value or role=="parent" and phase in ("edit-B","repeat-B","repair-B","restore-A") and actual in (3,17,83)
            anti = 17 if actual!=17 else 83
            q = capture(args,out/"negative",WANT=str(anti))
            assert q.returncode and f"actual native = {actual}".encode() in q.stdout
            row["actual"]=actual
        results[phase]=row
        save(receipts/"results.json",results)
        print(role,mode,phase,row,flush=True)
    for s in ("A","B"):
        left = results["repeat-A" if s=="A" else "empty-B"]
        right = results["cold-A" if s=="A" else "empty-B-repeat"]
        assert left["product"]==right["product"]
    if role=="candidate":
        assert all(results[p]["actual"]==83 for p in ("edit-B","repeat-B","repair-B","empty-B","empty-B-repeat"))
        assert all(results[p]["markers"]==results["empty-B"]["markers"] for p in ("edit-B","repeat-B","repair-B"))
        assert results["restore-A"]["actual"]==17 and results["restore-A"]["markers"]==results["cold-A"]["markers"]


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("work","receipts","rustup","shims"):
        p.add_argument(name,type=Path)
    p.add_argument("mode",choices=("build","test"))
    p.add_argument("role",choices=("parent","candidate"))
    p.add_argument("revision")
    p.add_argument("cargo_sha")
    a=p.parse_args()
    cargo_lane(a.work.resolve(),a.receipts.resolve(),a.rustup.resolve(),a.shims.resolve(),a.mode,a.role,a.revision,a.cargo_sha)
