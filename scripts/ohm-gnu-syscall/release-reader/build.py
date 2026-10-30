"""Build the merged reader with the signed Linux release and verify both source parents."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1] / "ohm-aarch64-versioned"), str(HERE.parents[1] / "ohm-apple-zmij")]
from receipt_cargo import materialize as classic
from transport import apply

ROOT = Path(os.environ.get("QA_ROOT", "/unused-reader-integration"))
LOG = ROOT / "receipts"
SOURCE = ROOT / "cargo-src"
HOST = "x86_64-unknown-linux-gnu"
BASE = "ohm-1.99.0-20-" + HOST
REGISTERED = json.loads((HERE / "source.json").read_bytes())
SIGNED = "abf43741c6c75f7fd4a3bcbf1db0cfc29824a07727bde4a3974b3ea44b379c1a"
SDK = ROOT / "rustup/toolchains/ohm"


def h(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def record(name, cmd, cwd, env, expected=0):
    out = LOG / name
    out.mkdir(parents=True)
    process = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True)
    for stream in ("stdout", "stderr"):
        (out / (stream + ".gz")).write_bytes(gzip.compress(getattr(process, stream), mtime=0))
    (out / "command.json").write_text(json.dumps({"argv": list(map(str, cmd)), "returncode": process.returncode}))
    if expected is not None and process.returncode != expected:
        sys.stderr.buffer.write(process.stderr[-8000:])
        raise RuntimeError((name, process.returncode, expected))
    return process


def materialize(source):
    classic(source)
    entry = apply("cargo", source)
    assert entry["source"] == REGISTERED["released"]["base"]
    def git(*args, data=None):
        return subprocess.check_output(["git", *args], cwd=source, input=data)
    for name in ("released", "integrated"):
        meta = REGISTERED[name]
        assert git("rev-parse", "HEAD").decode().strip() == meta["base"]
        commit = (HERE / (name + ".commit")).read_bytes()
        patch = gzip.decompress((HERE / (name + ".patch.gz")).read_bytes())
        assert hashlib.sha256(patch).hexdigest() == meta["diff_sha256"]
        assert commit.splitlines()[:len(meta["parents"]) + 1] == [
            ("tree " + meta["tree"]).encode(), *(("parent " + p).encode() for p in meta["parents"])
        ]
        assert git("hash-object", "-t", "commit", "-w", "--stdin", data=commit).decode().strip() == meta["commit"]
        if name == "released":
            with (source / ".git/shallow").open("a") as shallow:
                shallow.write(meta["commit"] + "\n")
        git("apply", "--index", "--binary", "-", data=patch)
        assert git("write-tree").decode().strip() == meta["tree"]
        git("update-ref", "HEAD", meta["commit"], meta["base"])
        assert not git("status", "--porcelain")
    assert git("show", "-s", "--format=%P", "HEAD").decode().split() == REGISTERED["integrated"]["parents"]
    git("fsck", "--strict", "--full", "--no-progress")
    assert len(git("ls-tree", "-r", "HEAD").splitlines()) == 3114


def env_for(name):
    return dict(os.environ, RUSTUP_HOME=str(ROOT / "rustup"), RUSTUP_AUTO_INSTALL="0",
                CARGO_HOME=str(ROOT / "registry"), CARGO_TARGET_DIR=str(ROOT / name / "target"),
                CARGO_BUILD_BUILD_DIR=str(ROOT / name / "shared"), CARGO_NET_OFFLINE="true",
                CARGO_TERM_COLOR="never", LC_ALL="C")


def install():
    inbox = ROOT / "inbox"
    archive = inbox / (BASE + ".tar.gz")
    assert archive.stat().st_size == 359585079 and h(archive) == "edb64a2ee39b2f2951614f98d53ec4e4197f55149ff794c911bd81bc7f870b15"
    side, prov = inbox / (archive.name + ".sha256"), inbox / (BASE + "-provenance.json")
    assert h(side) == "31164b6c91d93ee4662b50ae347b1165983fc92521cf6faeb4cd322de2f10ec0"
    assert h(prov) == "1bac589fa5a90d9d9ddcbbc1e847ff2bf8cb500aa58df02b0dd8c2933ceeb15a"
    assert side.read_text().split() == [h(archive), archive.name]
    subprocess.run(["tar", "-xzf", archive, "-C", inbox], check=True)
    subprocess.run([inbox / BASE / "install.sh", "--prefix=" + str(SDK), "--disable-ldconfig"], check=True)
    assert h(SDK / "bin/cargo") == SIGNED
    assert h(SDK / "bin/rustc") == "86d60426c7f3ebba0da187ca4f24339006aafbfb83a54eca94eadf507caea644"
    assert h(SDK / "lib/rustlib" / HOST / "bin/wild-ld/ld.bfd") == "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"


def build():
    install()
    materialize(SOURCE)
    env = env_for("construction")
    online = dict(env, CARGO_NET_OFFLINE="false")
    proxy = ["cargo", "+ohm", "-Zohm-defaults=no"]
    args = ["--release", "--locked", "--offline", "-p", "cargo", "--features", "ohm-defaults,all-static", "-j8"]
    record("builder", ["cargo", "+ohm", "-Vv"], SOURCE, env)
    record("compiler", ["rustc", "+ohm", "-vV"], SOURCE, env)
    record("fetch", [*proxy, "fetch", "--locked", "--target", HOST], SOURCE, online)
    trace = ROOT / "construction-traces"
    trace.mkdir()
    result = record("build", ["strace", "-ff", "-q", "-s", "262144", "-e", "trace=execve,execveat",
                              "-o", trace / "proc", *proxy, "build", *args, "--bin", "cargo", "--message-format=json"], SOURCE, env)
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert rows[-1] == {"reason": "build-finished", "success": True}
    products = [r for r in rows if r["reason"] == "compiler-artifact"]
    product, = [Path(r["executable"]) for r in products if r["target"]["name"] == "cargo" and r["target"]["kind"] == ["bin"]]
    assert product.samefile(ROOT / "construction/target/release/cargo")
    version = record("result-version", [product, "-Vv"], SOURCE, env).stdout
    assert REGISTERED["integrated"]["commit"].encode() in version
    paths = [line for p in trace.iterdir() for line in p.read_bytes().splitlines()
             if line.startswith(b'execve("' + os.fsencode(SDK / "bin/rustc") + b'",') and line.endswith(b" = 0")]
    assert any(b'"--crate-name", "cargo"' in line and b'"--crate-type", "bin"' in line for line in paths)
    (LOG / "root-cargo.bin-rustc.gz").write_bytes(gzip.compress(b"\n".join(line for line in paths if b'"--crate-name", "cargo"' in line), mtime=0))
    out = ROOT / "product"
    out.mkdir()
    subprocess.run(["zstd", "-q", "-3", "-o", out / "cargo.zst", product], check=True)
    manifest = {"git": REGISTERED["integrated"]["commit"], "tree": REGISTERED["integrated"]["tree"],
                "parents": REGISTERED["integrated"]["parents"], "sha256": h(product), "builder": SIGNED,
                "typed_units": len(products), "construction_rustcs": len(paths), "workflow": os.environ["GITHUB_SHA"]}
    (out / "product.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    print(manifest, flush=True)


def unit():
    argv = ["cargo", "+ohm", "-Zohm-defaults=no", "test", "--release", "--locked", "--offline", "-p", "cargo",
            "--lib", "--features", "ohm-defaults,all-static", "-j8", "compiler::fingerprint::dep_info::encoded_dep_info"]
    output = record("marker-tests", argv, SOURCE, env_for("construction")).stdout
    assert b"recheck_links_only_for_the_compiler_generated_marker ... ok" in output and b"; 0 failed;" in output
    print(output.decode()[-1000:])


if __name__ == "__main__":
    if sys.argv[1] == "source":
        materialize(Path(sys.argv[2]))
    elif sys.argv[1] == "build":
        build()
    else:
        assert sys.argv[1:] == ["unit"]
        unit()
