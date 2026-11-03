"""Install the compiler, Cargo, bundled tools and standard libraries in a private SDK."""
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import shutil
import subprocess
import tarfile

h=Path(__file__).resolve().parent
inputs=json.loads((h/"intake.json").read_bytes())
archive,=[h/"packed"/k for k in inputs["files"] if k.endswith(".tar.gz")]
provenance,=[h/"packed"/k for k in inputs["files"] if k.endswith("provenance.json")]
def sha(f):
    with f.open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()
for f in (archive,provenance):
    assert f.with_name(f.name+".sha256").read_text().split()==[sha(f),f.name]
    assert sha(f)==inputs["files"][f.name]["sha256"]
assert sha(archive)=="ecde6809d7f1fc1966798198479867c4a49bdf7a51f3873336d23a40fabce453"
prov=json.loads(provenance.read_bytes())
assert prov["coordinator"]["revision"]==inputs["head"] and prov["toolchain"]=="ohm-1.99.0-24"
sdk=h/"sdk"
sdk.mkdir(exist_ok=True)
components={"cargo":{"bin"},"rust-std-x86_64-unknown-linux-gnu":{"lib"},"rustc":{"bin","lib","libexec"}}
manifest={}
with tarfile.open(archive,mode="r|gz") as tar:
    for m in tar:
        path=PurePosixPath(m.name)
        assert path.parts[0]=="rust-1.99.0-dev-x86_64-unknown-linux-gnu" and ".." not in path.parts
        if len(path.parts)<4 or path.parts[2] not in components.get(path.parts[1],()):continue
        if m.isdir():continue
        assert m.isfile()
        key=Path(*path.parts[2:])
        assert str(key) not in manifest
        out=sdk/key
        out.parent.mkdir(parents=True,exist_ok=True)
        src=tar.extractfile(m)
        digest=hashlib.sha256()
        if out.exists():
            while chunk:=src.read(1<<20):digest.update(chunk)
            assert out.stat().st_size==m.size and sha(out)==digest.hexdigest()
        else:
            with out.open("xb") as dst:
                while chunk:=src.read(1<<20):
                    dst.write(chunk);digest.update(chunk)
            assert out.stat().st_size==m.size
            out.chmod(m.mode & 0o777)
        manifest[str(key)]={"source":m.name,"sha256":digest.hexdigest(),"bytes":m.size}
assert all(k in manifest for k in ("bin/cargo","bin/rustc","bin/rustdoc"))
ru=h/"rustup"
tools=ru/"toolchains"
tools.mkdir(parents=True,exist_ok=True)
if not (tools/"ohm").exists():(tools/"ohm").symlink_to(sdk,target_is_directory=True)
assert (tools/"ohm").resolve()==sdk
env={k:os.environ[k] for k in ("PATH","HOME","USER")}
env["RUSTUP_HOME"]=str(ru)
versions={tool:subprocess.check_output([tool,"+ohm","-vV"],env=env,text=True) for tool in ("cargo","rustc","rustdoc")}
assert prov["sources"]["rust"]["revision"] in versions["rustc"] and prov["sources"]["cargo"]["revision"] in versions["cargo"]
assert prov["bundled_tools"]["wild"]=={"version":"0.11.0","sha256":"25012a78de164686f552b7703b5d0223adab4829c79cd1fb351108221d61c7d8"}
# The manifest pins the upstream compressed distribution. Verify the actual deployed ELF
# against the independently authenticated previous release, which pins that same archive.
wild="lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
assert manifest[wild]["sha256"]=="0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
assert "0.11.0" in subprocess.check_output([sdk/wild,"--version"],env=env,text=True)
(h/"compiler.json").write_text(json.dumps({"members":manifest,"versions":versions,"wild":wild,"tar_sha256":sha(archive)},indent=2)+"\n")
print(len(manifest),versions["rustc"].splitlines()[0],versions["cargo"].splitlines()[0],wild)
