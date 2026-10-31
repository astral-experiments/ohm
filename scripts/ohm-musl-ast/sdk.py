"""Reproduce the enrolled compiler, add its own rustdoc and a source-built musl sysroot."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS / "ohm-gnu-atomic-db"))
import build_candidate as bc

rt = bc.rt
MUSL = "x86_64-unknown-linux-musl"
RUN = 41141810291
HEAD = "20cf3bd81dd7d30009ae75062eed9acf113f935a"
LLVM = "1b9c0d5ff9bbe7634aead059efe6b11a7eeba145"
API = "repos/astral-experiments/ohm/actions/"
SEAL = json.loads((SCRIPTS / "ohm-gnu-atomic-db/evidence/source-41141810291.json").read_text())
SRC = json.loads((SCRIPTS / "ohm-gnu-atomic-db/source/source.json").read_text())["roles"]["candidate"]
ORIGINAL = json.loads((SCRIPTS / "ohm-aarch64-portable-review/source/sdk-members.json").read_text())
DEST = Path(os.environ.get("RUNNER_TEMP", "/unused")) / "musl-ast"
LOG = DEST / "receipts"


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def rows(paths, root):
    return {str(p.relative_to(root)): [sha(p), p.stat().st_size, p.stat().st_mode & 0o777] for p in sorted(paths)}


def originals():
    api = lambda path: json.loads(subprocess.check_output(["gh", "api", API + path]))
    info = api(f"runs/{RUN}")
    assert (info["head_sha"], info["head_branch"], info["run_attempt"], info["event"], info["conclusion"]) == (
        HEAD, "charlie/qa-gnu-atomic-ruff-db", 1, "workflow_dispatch", "success")
    arts = api(f"runs/{RUN}/artifacts?per_page=100")["artifacts"]
    origin = {}
    for name, files, size in [
        ("gnu-atomic-registered-compiler", {"atomic-candidate.json", "driver.zst"}, 34684290),
        ("gnu-atomic-source-cargo", {"cargo.zst", "product.json"}, 16812895),
    ]:
        a, = [a for a in arts if a["name"] == name]
        assert [a["id"], a["digest"]] == SEAL["artifacts"][name]
        assert not a["expired"] and a["size_in_bytes"] == size
        assert (a["workflow_run"]["id"], a["workflow_run"]["head_sha"]) == (RUN, HEAD)
        fn = DEST / (name + ".zip")
        with fn.open("xb") as f:
            subprocess.run(["gh", "api", API + f'artifacts/{a["id"]}/zip'], stdout=f, check=True)
        assert fn.stat().st_size == size and "sha256:" + sha(fn) == a["digest"]
        with zipfile.ZipFile(fn) as z:
            assert sorted(z.namelist()) == sorted(files) and z.testzip() is None
            z.extractall(DEST / name)
        origin[name] = [a["id"], a["digest"], size]
    save(LOG / "originals.json", {"run": RUN, "head": HEAD, "attempt": 1, "artifacts": origin})


def install():
    product = DEST / "gnu-atomic-source-cargo"
    assert json.loads((product / "product.json").read_text())["source"]["commit"] == SEAL["cargo"]["git"]
    driver = DEST / "gnu-atomic-registered-compiler"
    assert json.loads((driver / "atomic-candidate.json").read_text()) == SEAL["candidate"]
    assert sha(driver / "driver.zst") == SEAL["candidate"]["compression"]
    src = rt.ROOT / "rust"
    stage = src / "build" / rt.HOST / "stage1"
    kit = rt.SDK
    srcgit = lambda expr: bc.git(src, "rev-parse", expr)
    assert srcgit("HEAD") == SRC["source"] and srcgit("HEAD:library") == SRC["product"]["library"]
    reference = ORIGINAL["common"] | {ORIGINAL["driver_path"]: SEAL["candidate"]["driver"]}
    assert len(reference) == 119 and (rt.load(rt.LOG / "C-sdk.json")["files"] | {n:reference[n] for n in rt.TOOLS}) == reference
    for path, (digest, size, mode) in reference.items():
        dest = kit / path
        if path in ("bin/cargo", ORIGINAL["driver_path"]):
            old = product / "cargo.zst" if path == "bin/cargo" else driver / "driver.zst"
            tmp = dest.with_suffix(".incoming")
            dest.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["zstd","-q","-d",old,"-o",tmp], check=True)
            assert sha(tmp) == digest and tmp.stat().st_size == size
            tmp.chmod(mode)
            tmp.replace(dest)
        elif not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.link((stage / path).resolve(strict=True), dest)
        assert rt.sha(dest) == digest and (dest.stat().st_size, dest.stat().st_mode & 0o777) == (size, mode), path
    assert rows([p for p in kit.rglob("*") if p.is_file()], kit) == reference
    assert sha(stage / ORIGINAL["driver_path"]) == reference[ORIGINAL["driver_path"]][0]
    save(LOG / "base-119.json", reference)
    assert not (kit / "bin/rustdoc").exists()
    bc.stage(["build","--stage","1","-j8","--host",rt.HOST,"--target",rt.HOST,"src/tools/rustdoc"], "matching-rustdoc")
    llvm = src / "src/llvm-project"
    assert srcgit("HEAD:src/llvm-project") == LLVM
    subprocess.run(["git","-C",llvm,"init","--quiet"], check=True)
    subprocess.run(["git","-C",llvm,"remote","add","origin","https://github.com/rust-lang/llvm-project.git"], check=True)
    subprocess.run(["git","-C",llvm,"config","remote.origin.promisor","true"],check=True)
    subprocess.run(["git","-C",llvm,"config","remote.origin.partialclonefilter","blob:none"],check=True)
    subprocess.run(["git","-C",llvm,"sparse-checkout","set","compiler-rt/lib/builtins","libunwind"],check=True)
    subprocess.run(["git","-C",llvm,"fetch","--depth=1","--filter=blob:none","--no-tags","origin",LLVM],check=True)
    subprocess.run(["git","-C",llvm,"checkout","--detach","-q","FETCH_HEAD"],check=True)
    assert bc.git(llvm,"rev-parse","HEAD") == LLVM and not bc.git(llvm,"status","--porcelain")
    # Use only the six C runtime members from the verified Rust 1.99 distribution.
    # The bootstrap below builds all Rust libraries, libunwind and the four compiler-rt startup objects.
    manifest = DEST/"channel-rust-1.99.0.toml"
    subprocess.run(["curl","-fsSL","--retry","3","https://static.rust-lang.org/dist/"+manifest.name,"-o",manifest],check=True)
    assert sha(manifest)=="ce6dddc886364f8d786514771212cebe9b731ba82d6b859951c6b0ccc516b6a2"
    release = tomllib.loads(manifest.read_text())["pkg"]["rust-std"]["target"][MUSL]
    archive = DEST/"musl-native.tar.xz"
    assert release["xz_hash"]=="b106b0aa4565cc3525fd3161c69203a9e39044e6e6b4d618f261c3eeda14ad50"
    subprocess.run(["curl","-fsSL","--retry","3",release["xz_url"],"-o",archive],check=True)
    assert sha(archive)==release["xz_hash"]
    crt = DEST/"rust-1.99-musl-native"
    crt.mkdir()
    names = ("libc.a","crt1.o","Scrt1.o","rcrt1.o","crti.o","crtn.o")
    with tarfile.open(archive,"r|xz") as tar:
        for member in tar:
            path=Path(member.name)
            if path.name in names and path.parts[-5:-1]==("rustlib", MUSL, "lib","self-contained"):
                assert member.isfile()
                with (crt/path.name).open("xb") as dst:
                    shutil.copyfileobj(tar.extractfile(member), dst)
    crt_rows = rows([crt/n for n in names], crt)
    save(LOG / "musl-system.json", {"native_crt":crt_rows,"llvm":LLVM,"upstream_crt_package":release,"manifest_sha256":sha(manifest),
        "packages":subprocess.check_output(["dpkg-query","-W","musl","musl-dev","musl-tools","gcc","g++","binutils"],text=True)})
    options = [f"target.{MUSL}.{k}={v}" for k,v in (
        ("musl-libdir", str(crt)), ("cc","/usr/bin/musl-gcc"), ("cxx","/usr/bin/musl-gcc"),
        ("ar","/usr/bin/ar"), ("linker","/usr/bin/musl-gcc"))]
    bc.stage([*[s for o in options for s in ("--set",o)], "build","--stage","1","-j8","--host",rt.HOST,"--target",MUSL,"library"], "matching-musl-std")
    for n in reference:
        if n not in rt.TOOLS:
            assert (stage/n).is_file() and sha(stage/n)==reference[n][0], n
    doc = stage / "bin/rustdoc"
    os.link(doc.resolve(strict=True), kit/"bin/rustdoc")
    lib = stage / "lib/rustlib" / MUSL / "lib"
    target = kit / lib.relative_to(stage)
    shutil.copytree(lib, target, copy_function=lambda a,b: os.link(Path(a).resolve(strict=True),b))
    roster = rows([p for p in target.rglob("*") if p.is_file()],kit)
    for name in ("core","alloc","std","test","panic_unwind","proc_macro","compiler_builtins"):
        assert len(list(target.glob(f"lib{name}-*.rlib"))) == 1, name
    for name in (*names, "crtbegin.o","crtbeginS.o","crtend.o","crtendS.o","libunwind.a"):
        f = target/"self-contained"/name
        assert f.is_file() and f.stat().st_size>0, name
        if name in names: assert sha(f)==crt_rows[name][0]
    actual = rows([p for p in kit.rglob("*") if p.is_file()],kit)
    assert actual == reference | roster | rows([kit/"bin/rustdoc"], kit)
    assert bc.git(src,"status","--porcelain","--untracked-files=no") == ""
    save(LOG / "sdk.json", {"source":SRC,"installed":actual,"musl":MUSL,"llvm":LLVM,
        "strict_cargo":SEAL["cargo"]["git"],"host_rustdoc_needed":subprocess.check_output(["readelf","-d",kit/"bin/rustdoc"],text=True)})


if __name__ == "__main__":
    if sys.argv[1:] == ["inputs"]:
        LOG.mkdir(parents=True)
        originals()
    else:
        assert sys.argv[1:] == ["build"]
        bc.build()
        install()
