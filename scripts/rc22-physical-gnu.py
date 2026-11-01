"""Test explicit Rust archive search paths against the candidate's actual GNU linker."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

root = Path(os.environ["RUNNER_TEMP"])/"rc22-gnu-archive-resolution"
root.mkdir()
reports = root/"reports"
reports.mkdir()
def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
dist, = Path("release").resolve().glob("*.tar.gz")
assert sha(dist) == "0b424df45b3bb9ccea5d1eda44f2481cb17a44f31ec6290e82d3db073489fe8a"
with tarfile.open(dist) as tf:
    tf.extractall(root/"extract", filter="data")
install = root/"extract/rust-1.99.0-dev-x86_64-unknown-linux-gnu/install.sh"
sdk = root/"sdk"
with (reports/"install.log").open("xb") as log:
    subprocess.run(["sh",str(install),"--prefix="+str(sdk),"--disable-ldconfig"], cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
driver = sdk/"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld"
wild = driver/"ld.bfd"
version = subprocess.check_output([wild,"--version"],text=True).strip()
assert "0.11.0" in version, version
rustc = sdk/"bin/rustc"
rust_version = subprocess.check_output([rustc,"-vV"], text=True)
(reports/"tools.json").write_text(json.dumps({"archive":sha(dist),"wild":version,"wild_sha256":sha(wild),"rustc":rust_version},indent=2)+"\n")
directories = [root/n for n in ("early", "declared", "extra")]
for d in directories: d.mkdir()
program=root/"program"
main=root/"main.rs"
main.write_text('extern "C" { fn answer() -> i32; fn extra() -> i32; }\nfn main() { println!("{}", unsafe {answer()+extra()}); }\n')
def archive(d, name, value):
    obj=root/"value.o"
    subprocess.run(["cc","-c","-x","c","-o",obj,"-"],input=f"int {name}(void) {{ return {value}; }}\n".encode(),check=True)
    stage=root/f"{name}-{value}.a"
    subprocess.run(["ar","rcs",stage,obj],check=True)
    dest=d/("lib"+name+".a")
    dest.write_bytes(stage.read_bytes())
    return dest
def candidates():
    return {str(d/("lib"+n+".a")):sha(d/("lib"+n+".a")) if (d/("lib"+n+".a")).is_file() else None
            for d in directories for n in ("answer","extra")}
previous=None
rows=[]
def build(case, expected, should_link):
    global previous
    witnesses=candidates()
    linked=previous != (witnesses, sha(program) if program.is_file() else None)
    assert linked == should_link,case
    row={"case":case,"explicit_candidates":witnesses,"linked":linked}
    if linked:
        previous=None
        dep=reports/(case+".deps")
        argv=[str(rustc),str(main),"--emit=link","-o",str(program)]
        argv.extend("-Lnative="+str(d) for d in directories)
        argv.extend(["-lstatic=answer","-lstatic=extra","-C","link-arg=-fuse-ld=bfd","-C","link-arg=-B"+str(driver),
                     "-C","link-arg=-Wl,--dependency-file="+str(dep),"--print=link-args="+str(reports/(case+".args"))])
        if case=="cold":
            argv=["strace","-f","-e","trace=execve","-s","512","-o",str(reports/"cold.native"),*argv]
        p=subprocess.run(argv,cwd=root,capture_output=True)
        (reports/(case+".stderr")).write_bytes(p.stderr)
        (reports/(case+".stdout")).write_bytes(p.stdout)
        row["status"]=p.returncode
        if expected is None:
            assert p.returncode!=0 and b"extra" in p.stderr,case
        else:
            assert p.returncode==0,(case,p.stderr[-1200:])
            if case=="cold":
                assert any('execve("'+str(wild)+'"' in l and l.endswith("= 0") for l in (reports/"cold.native").read_text().splitlines())
            record=dep.read_text().splitlines()[0]
            assert record.startswith(str(program)+": "),record
            positive=set(record.split(": ",1)[1].split())
            def selected(name): return next(str(d/("lib"+name+".a")) for d in directories if witnesses[str(d/("lib"+name+".a"))])
            assert {selected("answer"),selected("extra")} <= positive,(case,positive)
            row["positive_user_inputs"]=sorted(positive & set(witnesses))
            assert all(path not in positive for path, digest in witnesses.items() if digest is None)
            assert candidates()==witnesses
            previous=(witnesses,sha(program))
    if expected is not None:
        value=int(subprocess.check_output([program],cwd=root))
        assert value==expected,(case,value,expected)
        row["value"]=value
    rows.append(row)
    (reports/"result.json").write_text(json.dumps(rows,indent=2)+"\n")
one=archive(directories[1],"answer",17)
two=archive(directories[2],"extra",3)
build("cold",20,True)
build("unchanged",20,False)
st=two.stat()
archive(directories[2],"extra",7)
os.utime(two,ns=(st.st_atime_ns,st.st_mtime_ns))
assert (two.stat().st_ino,two.stat().st_size,two.stat().st_mtime_ns)==(st.st_ino,st.st_size,st.st_mtime_ns)
build("same-stat-secondary",24,True)
archive(directories[0],"answer",41)
build("new-earlier-library",48,True)
build("unchanged-again",48,False)
two.write_bytes(b"not a native archive")
build("malformed",None,True)
two.rename(root/"retained-malformed.a")
build("missing",None,True)
archive(directories[2],"extra",11)
build("repaired",52,True)
