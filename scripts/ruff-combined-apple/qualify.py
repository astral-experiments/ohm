"""Nonpublishing macOS qualification of the exact Cargo and Rust checksum heads."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess as sp
import sys
import tarfile

host = "aarch64-apple-darwin"
root = Path(os.environ["RUNNER_TEMP"]) / "combined"
workspace = Path(os.environ["GITHUB_WORKSPACE"])
normal = root / "reopened/normal"
fixed = root / "reopened/defer"
ru = root / "rustup"
logs = root / "logs"
logs.mkdir(exist_ok=True)
assert platform.system() == "Darwin" and platform.machine() == "arm64"
assert os.environ["GITHUB_RUN_ATTEMPT"] == "1"
src = workspace / "rust"
cargo = workspace / "cargo-src"
sys.path.insert(0, str(workspace / "fixtures/scripts/ruff-matched-stage"))
import smoke

def git_sha(path, expr):
    return sp.check_output(["git", "-C", path, "rev-parse", expr], text=True).strip()

def check_sources():
    for repo, ref, tree in ((src, "d46c44b58d91b9d7b4b0d2fc4850c31ad5cbc8f2", "d9d8d190d49a742d7b990d46420bace16f9fd2db"), (cargo, "4a6de7858c60e579fc30e01f5b60ddcaa84c2e30", "1a128e47d068ee91f33ba94e416ee0c0e014de5a"), (workspace/"fixtures", "5b47d5755bd515e61a98b9f85eca3af0aaf7c137", "d22f09981bdd81fc892fd47d894233639d0f3dab")):
        assert git_sha(repo, "HEAD") == ref and git_sha(repo, "HEAD^{tree}") == tree
        sp.run(["git", "-C", repo, "diff", "--exit-code", "HEAD", "--"], check=True)

def clean_env():
    keys = ("PATH", "HOME", "USER", "LANG", "TMPDIR", "DEVELOPER_DIR", "SDKROOT")
    return {k: os.environ[k] for k in keys if k in os.environ}

def install():
    check_sources()
    archive = root / "ohm-1.99.0-23-aarch64-apple-darwin.tar.gz"
    assert archive.stat().st_size == 295155861 and smoke.sha(archive) == "371e7cb6ca778e44b599ee4fbb83c7ca85f6306353825bce1d40f7d692f03a53"
    pack = root/"dist"; pack.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(pack, filter="data")
    dist = pack / ("rust-1.99.0-dev-"+host)
    sp.run([dist/"install.sh", "--prefix="+str(normal), "--disable-ldconfig", "--components=cargo,rustc,rust-std-"+host], check=True)
    smoke.save(logs/"signed.json", {"release":smoke.sha(archive), "tools": tools(normal)})

def tools(sdk):
    driver, = (sdk/"lib").glob("librustc_driver-*.dylib")
    paths = [sdk/"bin"/n for n in ("rustc","cargo","rustdoc")]+[driver]
    return {str(p.relative_to(sdk)): smoke.sha(p) for p in paths}

def build():
    check_sources()
    env = clean_env()
    bindir = root/"bootstrap-alias"/"toolchains"
    bindir.mkdir(parents=True)
    (bindir/"ohm").symlink_to(normal, target_is_directory=True)
    ce = dict(env, RUSTUP_HOME=str(bindir.parent), RUSTUP_TOOLCHAIN="ohm", CARGO_HOME=str(root/"builder-cargo-home"), CARGO_TARGET_DIR=str(root/"cargo-target"), CARGO_BUILD_BUILD_DIR=str(root/"cargo-build"), CARGO_PROFILE_DEV_DEBUG="0", CARGO_PROFILE_DEV_INCREMENTAL="false", CARGO_NET_GIT_FETCH_WITH_CLI="true")
    sp.run(["cargo","+ohm","-Zohm-defaults=no","build","--locked","-p","cargo","--bin","cargo","--features","ohm-defaults","-j6"], env=ce, cwd=cargo, check=True)
    candidate = root/"cargo-target/debug/cargo"
    assert candidate.is_file()
    output = root/"rust-build"
    args = [sys.executable,"x.py","--ci","false","--build-dir",str(output),"--set","build.submodules=false","--set","rust.debug-assertions=false","--set","rust.lto=off","--set","llvm.download-ci-llvm=true","--set","rust.download-rustc=false","build","--stage","1","-j6","compiler/rustc","library","src/tools/rustdoc"]
    sp.run(args, env=env, cwd=src, check=True)
    check_sources()
    shutil.copytree(output/host/"stage1", fixed, symlinks=False)
    dest = fixed/"bin/cargo"
    if dest.exists(): dest.unlink()
    shutil.copy2(candidate, dest)
    pieces = tools(fixed)
    assert pieces["bin/cargo"] == smoke.sha(candidate) and pieces["bin/cargo"] != smoke.sha(normal/"bin/cargo")
    assert next(v for k,v in pieces.items() if "rustc_driver" in k) not in tools(normal).values()
    smoke.save(logs/"candidate.json", {"rust":git_sha(src,"HEAD"),"cargo":git_sha(cargo,"HEAD"),"tools":pieces,"rust_command":args})

def prerequisite(role, sdk, base):
    project = root/("prerequisite-"+role)
    (project/"src").mkdir(parents=True)
    (project/"dep/src").mkdir(parents=True)
    (project/"Cargo.toml").write_text('[package]\nname="observer"\nversion="0.1.0"\nedition="2024"\n[dependencies]\nproducer={path="dep"}\n[workspace]\n')
    (project/"dep/Cargo.toml").write_text('[package]\nname="producer"\nversion="0.1.0"\nedition="2024"\n')
    producer = project/"dep/src/lib.rs"
    original = "#![allow(dead_code)]\npub const VALUE:u8=1; fn private()->u8 {10}\n"
    producer.write_text(original)
    main = project/"src/lib.rs"
    main.write_text("pub use producer::VALUE;\n")
    home = project/"cargo-home"
    alias = Path(base["RUSTUP_HOME"])/"toolchains/ohm"
    if alias.is_symlink(): alias.unlink()
    alias.symlink_to(sdk, target_is_directory=True)
    def check(label, expected, split=False):
        artifacts = home/"registry/generated-artifacts"/("clean" if split else "warm")
        env = dict(base, CARGO_NET_OFFLINE="true", CARGO_HOME=str(home), CARGO_TARGET_DIR=str(artifacts/"target"), CARGO_BUILD_BUILD_DIR=str(artifacts/"build"))
        p = sp.run(["cargo","+ohm","check","--offline","--message-format=json"],cwd=project,env=env,capture_output=True,timeout=120)
        dst = logs/("prerequisite-"+role+"-"+label)
        dst.with_suffix(".jsonl").write_bytes(p.stdout)
        dst.with_suffix(".stderr").write_bytes(p.stderr)
        rows = [json.loads(r) for r in p.stdout.splitlines()]
        codes=[r["message"]["code"]["code"] for r in rows if r["reason"]=="compiler-message" and r["message"].get("code")]
        assert p.returncode==expected and rows[-1]=={"reason":"build-finished","success":expected==0} and ("E0308"in codes)==(expected==101), (role,label,p.returncode,codes,p.stderr[-1200:])
        return rows
    initial = check("seed",0)
    prod, = [a for a in initial if a["reason"]=="compiler-artifact" and a["target"]["name"]=="producer"]
    rmeta, = [Path(f) for f in prod["filenames"] if f.endswith(".rmeta")]
    assert rmeta.is_relative_to(home/"registry/generated-artifacts")
    old = rmeta.read_bytes()
    (main.parent/"previous.rmeta").write_bytes(old)
    main.write_text("pub use producer::VALUE;\nconst PREVIOUS:&[u8]=include_bytes!(\"previous.rmeta\");\nconst CURRENT:&[u8]=include_bytes!("+json.dumps(str(rmeta))+");\n"+"""
const _: [();1] = [(); {
    let mut i = 0;
    while i < CURRENT.len() && i < PREVIOUS.len() && CURRENT[i] == PREVIOUS[i] { i += 1; }
    (i == CURRENT.len() && i == PREVIOUS.len()) as usize
}];
""")
    primed = check("prime",0)
    consumer, = [r for r in primed if r["reason"]=="compiler-artifact" and r["target"]["name"]=="observer"]
    consumer_meta, = [Path(f) for f in consumer["filenames"] if f.endswith(".rmeta")]
    consumer_sha = hashlib.sha256(consumer_meta.read_bytes()).hexdigest()
    producer.write_text(original.replace("{10}","{20}"))
    result = check("changed",101 if role=="fixed" else 0)
    assert rmeta.read_bytes()!=old
    if role=="signed": assert hashlib.sha256(consumer_meta.read_bytes()).hexdigest()==consumer_sha
    check("clean-refusal",101,True)
    producer.write_text(original)
    check("repair",0)
    assert rmeta.read_bytes()==old
    check("clean-repair",0,True)
    fresh=check("repaired-unchanged",0)
    assert [r["fresh"]for r in fresh if r["reason"]=="compiler-artifact" and r["target"]["name"]=="observer"]==[True]

def exercise():
    check_sources()
    before = {"P":tools(normal),"C":tools(fixed)}
    base = dict(clean_env(), RUSTUP_HOME=str(ru), CARGO_HOME=str(root/"unused-cargo-home"), RUSTUP_TOOLCHAIN="ohm")
    smoke.smoke(root, {"arms":{"normal":{"root":str(normal)}, "defer":{"root":str(fixed)}}}, base)
    for role,sdk in (("signed",normal),("fixed",fixed)):
        prerequisite(role,sdk,base)
    assert before=={"P":tools(normal),"C":tools(fixed)}
    smoke.save(logs/"accepted-combined.json", {"rust":git_sha(src,"HEAD"),"cargo":git_sha(cargo,"HEAD"),"summaries":smoke.sha(logs/"smoke.json"),"tools":before,"prerequisite_commands":14})

if __name__=="__main__":
    {"install":install,"build":build,"exercise":exercise}[sys.argv[1]]()
