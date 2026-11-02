"""Exercise the actual rmeta version rule on kept input files and both real sysroots."""
from pathlib import Path
import hashlib
import json
import subprocess

def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()

def save(path,obj):
    with path.open("x") as f:
        json.dump(obj,f,indent=2,sort_keys=True);f.write("\n")

def invoke(sdk,root,name,arguments):
    args=[str(sdk/"bin/rustc"),"--sysroot",str(sdk),"--edition=2024",*arguments]
    result=subprocess.run(args,cwd=root,env={"PATH":"/usr/bin:/bin","LC_ALL":"C"},capture_output=True,timeout=60)
    assert not result.stdout,(name,result.stdout)
    stdout=root/(name+".stdout");stderr=root/(name+".stderr")
    stdout.write_bytes(result.stdout);stderr.write_bytes(result.stderr)
    errors=[json.loads(line)for line in result.stderr.splitlines()]
    return {"argv":args,"status":result.returncode,"stdout":sha(stdout),"stderr":sha(stderr),
            "codes":[row["code"]["code"]for row in errors if row.get("code")]},errors

def metadata(sdks,out,*,expected):
    from origin.enrollment import SOURCES
    from origin.ordinary_rmeta import metadata as check_originals
    assert list(sdks)==list(expected)==SOURCES
    assert list(expected.values())==[(43319,43319),(43323,43319)]
    roles={commit: {"physical_sdk":str(sdk),"source":{"commit":commit},"rmeta_epoch":expected[commit][1]} for commit,sdk in sdks.items()}
    return check_originals(roles,out)

def header(path):
    # The banner's byte length is at most 255; inspect the original prefix, not each 50+ MB crate.
    with path.open("rb") as f:
        data=f.read(320)
    assert data[:8]==b"rust\x00\x00\x00\x0a"
    pos=16;size=0
    for k in range(3):
        b=data[pos];pos+=1;size|=(b&127)<<(k*7)
        if b<128:break
    assert 5<size<255 and data[pos+size]==193
    return data[pos:pos+size].decode()

def common_sysroot(sdks,out):
    out.mkdir();(out/"stdlib.rs").write_text("#![no_std]\nextern crate core as enrolled_core; pub const ANSWER: enrolled_core::primitive::usize = 43;\n")
    results={}
    for rev,sdk in sdks.items():
        root=sdk/"lib/rustlib/x86_64-unknown-linux-gnu/lib";row={}
        for file in sorted(root.glob("*.rmeta")):
            assert file.is_file() and file.resolve()==file
            row[file.name]={"sha256":sha(file),"version":header(file)}
        core,=root.glob("libcore-*.rmeta")
        outmeta=out/(rev+".rmeta");cmd,diags=invoke(sdk,out,rev,["stdlib.rs","--crate-name","origin_stdlib","--crate-type","lib","--emit=metadata",
                "--extern","core="+str(core),"--error-format=json","-o",str(outmeta)])
        assert cmd["status"]==0 and not diags and header(outmeta).endswith("(Ohm metadata 43319)") and rev[:9] in header(outmeta)
        results[rev]={"sysroot_members":row,"genuine_core":core.name,"compile":cmd,"product_sha256":sha(outmeta),
                      "unstamped_members":[name for name, v in row.items() if "(Ohm metadata " not in v["version"]]}
    save(out/"passed.json",{"by_real_compiler":results,"scope":"Actual installed target files and own native core type checks. Non-empty DefIndex directories in profiling are a separate Rust representation. No shared unversioned sysroot is inferred."})
