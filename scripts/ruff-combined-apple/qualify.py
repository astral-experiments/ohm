"""Nonpublishing native qualification of the exact release Cargo and Rust source pins."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess as sp
import sys
import tarfile

host = os.environ["OHM_TARGET"]
root = Path(os.environ["RUNNER_TEMP"]) / "combined"
workspace = Path(os.environ["GITHUB_WORKSPACE"])
normal = root / "reopened/normal"
fixed = root / "reopened/defer"
ru = root / "rustup"
logs = root / "logs"
logs.mkdir(exist_ok=True)
assert (host,platform.system(),platform.machine()) in [("aarch64-apple-darwin","Darwin","arm64"),("x86_64-unknown-linux-gnu","Linux","x86_64")]
assert os.environ["GITHUB_RUN_ATTEMPT"] == "1"
src = workspace / "source/rust"
cargo = workspace / "cargo-src"
sys.path.insert(0, str(workspace / "fixtures/scripts/ruff-matched-stage"))
import smoke
sys.path.insert(0, str(Path(__file__).resolve().parent))
import matched_paths
import macho
import release_cases

def git_sha(path, expr):
    return sp.check_output(["git", "-C", path, "rev-parse", expr], text=True).strip()

def check_cargo_files():
    import stat
    items=sp.check_output(["git","-C",cargo,"ls-tree","-rz","HEAD"]).split(b"\0")
    expected=set()
    for item in items:
        if not item:continue
        header,raw=item.split(b"\t",1);mode,kind,oid=header.split()
        rel=Path(os.fsdecode(raw));path=cargo/rel;expected.add(rel)
        info=path.lstat()
        if mode==b"120000":
            assert stat.S_ISLNK(info.st_mode);body=os.fsencode(os.readlink(path))
        else:
            assert kind==b"blob" and stat.S_ISREG(info.st_mode)
            assert mode==(b"100755" if info.st_mode&stat.S_IXUSR else b"100644")
            body=path.read_bytes()
        assert hashlib.sha1(b"blob "+str(len(body)).encode()+b"\0"+body).hexdigest()==oid.decode(),rel
    actual=set()
    for directory,dirs,files in os.walk(cargo):
        base=Path(directory)
        if base==cargo and ".git" in dirs:dirs.remove(".git")
        for name in dirs[:]:
            if (base/name).is_symlink():files.append(name);dirs.remove(name)
        actual.update((base/name).relative_to(cargo)for name in files)
    assert len(expected)>3000 and actual==expected,(actual-expected,expected-actual)

def check_sources():
    check_cargo_files()
    for repo, ref, tree in ((src, "364b82f01c52f77e870cdb1bb5b9f66e2fa89694", "531c5eefa10de5179d81207bdd50f4246dc725b9"), (cargo, "d5185be60b88e36ffb5e9daeb543b9f14d077a37", "4b9a4d7ca2e5abb29c307fa501ec6a437e30dea3"), (workspace/"fixtures", "5b47d5755bd515e61a98b9f85eca3af0aaf7c137", "d22f09981bdd81fc892fd47d894233639d0f3dab")):
        assert git_sha(repo, "HEAD") == ref and git_sha(repo, "HEAD^{tree}") == tree
        if repo!=src:
            sp.run(["git", "-C", repo, "diff", "--exit-code", "HEAD", "--"], check=True)
    import importlib.util
    spec=importlib.util.spec_from_file_location("verified_layout",workspace/"legacy/scripts/dep-graph-slots/layout.py")
    layout=importlib.util.module_from_spec(spec);spec.loader.exec_module(layout)
    pins=json.loads((workspace/"qa-code/scripts/ruff-matched-stage/canonical-pins/pins.json").read_bytes())
    replacements={"src/tools/"+k:(pins[k]["after"],pins[k]["tree"]) for k in ("clippy","rustfmt")}
    previous=json.loads((Path(os.environ["RUNNER_TEMP"])/"ohm-branch-object-qa/logs/source.json").read_bytes())
    try:
        checked=layout.checked(src,git_sha(src,"HEAD"),git_sha(src,"HEAD^{tree}"),replacements)
    except ValueError:
        names=sp.check_output(["git","-C",src,"ls-files","--others","-z","--",".",":(exclude)src/tools/clippy",":(exclude)src/tools/rustfmt"]).split(b"\0")
        (logs/"untracked.json").write_text(json.dumps([os.fsdecode(n) for n in names if n],indent=2))
        print("Untracked names:",[os.fsdecode(n)for n in names[:12]],flush=True)
        raise
    previous_links=dict(previous["layout"]["gitlinks"])
    links=dict(checked["gitlinks"])
    assert previous_links.pop("src/tools/cargo")["commit"]=="7024b0d2dc5f64bba72c0d6d28f537a5cd9707ed"
    mounted=links.pop("src/tools/cargo")
    assert mounted["populated"] and mounted["commit"]==git_sha(cargo,"HEAD") and mounted["tree"]==git_sha(cargo,"HEAD^{tree}")
    assert links==previous_links
    assert json.loads(json.dumps(checked["authorized_differences"]))==previous["layout"]["authorized_differences"]

def source():
    assert git_sha(src,"HEAD")=="d57fd1515986dccecdcece8da85e651bfb4b81f9"
    packet=Path(__file__).resolve().with_name("parent.bundle");assert smoke.sha(packet)=="00cf7f98b1f31f484580a86dca0ed2696ed9e4545025110bfc7c3ca4f5fccb9f"
    sp.run(["git","-C",src,"bundle","verify",packet],check=True)
    sp.run(["git","-C",src,"fetch","--no-tags","--no-recurse-submodules",packet,"refs/heads/charlie/record-included-bytes-at-read"],check=True)
    assert git_sha(src,"FETCH_HEAD")=="d46c44b58d91b9d7b4b0d2fc4850c31ad5cbc8f2"
    sp.run(["git","-C",src,"checkout","--quiet","--detach","--no-recurse-submodules",git_sha(src,"FETCH_HEAD")],check=True)
    cargo_packet=Path(__file__).resolve().with_name("integrated-cargo.bundle")
    assert git_sha(cargo,"HEAD")=="4a6de7858c60e579fc30e01f5b60ddcaa84c2e30" and smoke.sha(cargo_packet)=="aac42ae4a0b972050f8d8492e70c927487e3c89ae889890a319bae15281255f2"
    sp.run(["git","-C",cargo,"bundle","verify",cargo_packet],check=True)
    sp.run(["git","-C",cargo,"fetch","--no-tags",cargo_packet,"refs/heads/charlie/qa-rc23-combined-doctest-and-input-fixes"],check=True)
    assert git_sha(cargo,"FETCH_HEAD")=="d5185be60b88e36ffb5e9daeb543b9f14d077a37"
    sp.run(["git","-C",cargo,"checkout","--quiet","--detach","FETCH_HEAD"],check=True)
    assert [git_sha(cargo,r) for r in ("HEAD^1","HEAD^2")]==["4a6de7858c60e579fc30e01f5b60ddcaa84c2e30","aee854cc8cc48194c5cb4e240fd944e2fdd14bce"]
    pin=Path(__file__).resolve().with_name("qualified-rust-pin.bundle")
    assert smoke.sha(pin)=="7b13e8af3f6aa8caba3de87ab6b4e801c533b1d25d1f14e0b6ce325e5e2abf77" and git_sha(src,"HEAD")=="d46c44b58d91b9d7b4b0d2fc4850c31ad5cbc8f2"
    sp.run(["git","-C",src,"bundle","verify",pin],check=True)
    sp.run(["git","-C",src,"fetch","--no-tags","--no-recurse-submodules",pin,"refs/heads/charlie/qa-rc23-qualified-cargo-pin-20261103"],check=True)
    assert git_sha(src,"FETCH_HEAD")=="364b82f01c52f77e870cdb1bb5b9f66e2fa89694" and git_sha(src,"FETCH_HEAD^")==git_sha(src,"HEAD")
    assert sp.check_output(["git","-C",src,"diff","--name-only","HEAD","FETCH_HEAD","--"])==b"src/tools/cargo\n"
    sp.run(["git","-C",src,"checkout","--quiet","--no-recurse-submodules","--detach","FETCH_HEAD"],check=True)
    nested=src/"src/tools/cargo"
    if (nested/".git").exists():
        sp.run(["git","-C",nested,"fetch","--no-tags",cargo,git_sha(cargo,"HEAD")],check=True)
        sp.run(["git","-C",nested,"checkout","--quiet","--detach",git_sha(cargo,"HEAD")],check=True)
    else:
        assert not nested.exists() or not any(nested.iterdir())
        shutil.copytree(cargo,nested,symlinks=True,dirs_exist_ok=True)
    check_sources()
    coordinator=workspace/"signed-coordinator"
    manifest=json.loads((coordinator/"toolchains/1.99.0/23.json").read_bytes())
    manifest["sources"]["rust"]["revision"]=git_sha(src,"HEAD")
    manifest["sources"]["cargo"]["revision"]=git_sha(cargo,"HEAD")
    manifest["release"].update(ohm_revision=24,toolchain_name="ohm-1.99.0-24")
    canonical=root/"source-proof/toolchains"
    proof=canonical/"1.99.0/24.json"
    proof.parent.mkdir(parents=True)
    (canonical/"manifest.schema.json").write_bytes(sp.check_output(["git","-C",coordinator,"show","HEAD:toolchains/manifest.schema.json"]))
    smoke.save(proof,manifest)
    shutil.copyfile(proof,logs/"source-manifest-for-qa.json")
    verifier=coordinator/"scripts/verify-release-sources.sh"
    verified=sp.run(["bash",verifier,proof,src,nested,src/"src/tools/clippy",src/"src/tools/rustfmt"],stdout=sp.PIPE,stderr=sp.STDOUT)
    (logs/"release-source-verifier.stdout").write_bytes(verified.stdout)
    print(verified.stdout.decode(),flush=True)
    assert verified.returncode==0 and git_sha(src,"HEAD").encode() in verified.stdout and git_sha(cargo,"HEAD").encode() in verified.stdout
    smoke.save(logs/"sources.json",{"rust":git_sha(src,"HEAD"),"cargo":git_sha(cargo,"HEAD"),"packet":smoke.sha(packet)})

def clean_env():
    keys = ("PATH", "HOME", "USER", "LANG", "TMPDIR", "DEVELOPER_DIR", "SDKROOT")
    return {**{k: os.environ[k] for k in keys if k in os.environ}, "PYTHONDONTWRITEBYTECODE":"1"}

def install():
    check_sources()
    archive = root / ("ohm-1.99.0-23-"+host+".tar.gz")
    wanted={"aarch64-apple-darwin":(295155861,"371e7cb6ca778e44b599ee4fbb83c7ca85f6306353825bce1d40f7d692f03a53"),
            "x86_64-unknown-linux-gnu":(359921838,"fc85a2ca6d47711058cd89c790c8e57f1799472e38f0ee0a08b0a51d06c1ee7b")}
    assert (archive.stat().st_size,smoke.sha(archive))==wanted[host]
    pack = root/"dist"; pack.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(pack, filter="data")
    dist = pack / ("rust-1.99.0-dev-"+host)
    sp.run([dist/"install.sh", "--prefix="+str(normal), "--disable-ldconfig", "--components=cargo,rustc,rust-std-"+host], check=True)
    smoke.save(logs/"signed.json", {"release":smoke.sha(archive), "tools": tools(normal)})

def tools(sdk):
    driver, = (sdk/"lib").glob("librustc_driver-*.dylib" if host.startswith("aarch64") else "librustc_driver-*.so")
    paths = [sdk/"bin"/n for n in ("rustc","cargo","rustdoc")]+[driver]
    return {str(p.relative_to(sdk)): smoke.sha(p) for p in paths}

def build():
    check_sources()
    env = clean_env()
    bindir = root/"bootstrap-alias"/"toolchains"
    bindir.mkdir(parents=True)
    (bindir/"ohm").symlink_to(normal, target_is_directory=True)
    ce = dict(env, RUSTUP_HOME=str(bindir.parent), RUSTUP_TOOLCHAIN="ohm", CARGO_HOME=str(root/"builder-cargo-home"), CARGO_TARGET_DIR=str(root/"cargo-target"), CARGO_BUILD_BUILD_DIR=str(root/"cargo-build"), CARGO_PROFILE_RELEASE_LTO="thin", CARGO_PROFILE_RELEASE_INCREMENTAL="false", CARGO_PROFILE_RELEASE_DEBUG="0", CARGO_NET_GIT_FETCH_WITH_CLI="true")
    sp.run(["cargo","+ohm","-Zohm-defaults=no","build","--release","--locked","-p","cargo","--bin","cargo","--features","all-static,ohm-defaults","-j6"], env=ce, cwd=cargo, check=True)
    candidate = root/"cargo-target/release/cargo"
    assert candidate.is_file()
    output = root/"rust-build"
    args = [sys.executable,"-IB","x.py","--ci","false","--build-dir",str(output),"--set","build.submodules=false","--set","rust.debug-assertions=false","--set","rust.lto=off","--set","llvm.download-ci-llvm=true","--set","rust.download-rustc=false","build","--stage","1","-j6","compiler/rustc","library","src/tools/rustdoc"]
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
    comparisons = matched_paths.histories(root, normal, fixed, base)
    for role,sdk in (("signed",normal),("fixed",fixed)):
        prerequisite(role,sdk,base)
    assert before=={"P":tools(normal),"C":tools(fixed)}
    import gzip
    native=[]
    for group in comparisons:
        if group[0] is None:
            assert set(group)=={None}
            continue
        if host.startswith("x86_64"):
            assert len(set(group))==1
            native.append({"identical":group[0]})
        else:
            left,right=group[0],group[-2]
            assert group[-1]==left
            data=[gzip.decompress((logs/(key+".macho.gz")).read_bytes())for key in (left,right)]
            assert [hashlib.sha256(b).hexdigest()for b in data]==[left,right]
            native.append(macho.compare(*data))
    assert len(native)==8
    smoke.save(logs/"native-comparisons.json",native)
    release_cases.run(root,normal,fixed,base,logs)
    assert before=={"P":tools(normal),"C":tools(fixed)}
    smoke.save(logs/"accepted-combined.json", {"rust":git_sha(src,"HEAD"),"cargo":git_sha(cargo,"HEAD"),"summaries":smoke.sha(logs/"smoke.json"),"tools":before,"prerequisite_commands":14})

if __name__=="__main__":
    {"source":source,"install":install,"build":build,"exercise":exercise}[sys.argv[1]]()
