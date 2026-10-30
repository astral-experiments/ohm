"""Record Xcode's actual dependency-info stream when a native provider changes."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

LD_HASH="2b48a59af70235283aa94c43eb0dd2ef80182c106db43279db936cc87426b443"


def sha(path):
    with path.open("rb") as f:
        h=hashlib.sha256()
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
        return h.hexdigest()


def decode(data):
    rows=[]
    pos=0
    while pos<len(data):
        opcode=data[pos]
        end=data.index(0,pos+1)
        rows.append([opcode,os.fsdecode(data[pos+1:end])])
        pos=end+1
    return rows


def write(path,x):
    with path.open("x") as f:
        json.dump(x,f,indent=2);f.write("\n")


def cmd(argv,cwd=None):
    p=subprocess.run(list(map(str,argv)),cwd=cwd,capture_output=True)
    assert p.returncode==0,(argv,p.stderr)
    return p.stdout.rstrip().decode()


def main(dest):
    assert platform.system()=="Darwin" and platform.machine()=="arm64"
    dest.mkdir()
    clang,ar,ld=[Path(cmd(["xcrun","--find",v])).resolve(strict=True) for v in ("clang","ar","ld")]
    sdk=cmd(["xcrun","--sdk","macosx","--show-sdk-path"])
    sdk_version=cmd(["xcrun","--sdk","macosx","--show-sdk-version"])
    assert sha(ld)==LD_HASH
    write(dest/"tools.json",{"ld":[str(ld),sha(ld)],"clang":[str(clang),sha(clang)],"ar":[str(ar),sha(ar)],"sdk":[sdk,sdk_version]})
    os.environ["ZERO_AR_DATE"]="1"
    main_c=dest/"main.c";main_o=dest/"main.o"
    main_c.write_text("extern int ds_actual_provider(void);\nint main(void) { return ds_actual_provider(); }\n")
    cmd([clang,"-arch","arm64","-mmacosx-version-min=13.0","-c",main_c,"-o",main_o])
    for val in (17,29,41):
        build=dest/str(val);build.mkdir()
        (build/"provider.c").write_text("int ds_actual_provider(void) { return "+str(val)+"; }\n")
        cmd([clang,"-arch","arm64","-mmacosx-version-min=13.0","-c","provider.c","-o","provider.o"],build)
        cmd([ar,"rcs","libdsactual.a","provider.o"],build)
    early=dest/"early";late=dest/"late"
    for d in (early,late):d.mkdir()
    e,l=[p/"libdsactual.a" for p in (early,late)]
    shutil.copyfile(dest/"17"/l.name,l)
    rows={}
    for phase,want in (("lower",17),("unchanged",17),("higher",29),("backdated-replace",41),("malformed",None),("fallback",17),("missing",None),("repair",29)):
        if phase in ("higher","repair"):
            shutil.copyfile(dest/"29"/e.name,e)
        if phase=="backdated-replace":
            st=e.stat()
            assert sha(e)!=sha(dest/"41"/e.name)
            shutil.copyfile(dest/"41"/e.name,e)
            os.utime(e,ns=(st.st_atime_ns,st.st_mtime_ns))
            assert e.stat().st_size==st.st_size and e.stat().st_mtime_ns==st.st_mtime_ns
        if phase=="malformed":e.write_bytes(b"not a native archive\n")
        if phase=="fallback":e.unlink()
        if phase=="missing":l.unlink()
        out=dest/phase;out.mkdir()
        exe=out/"main";dep=out/"deps.bin"
        argv=[str(v) for v in (ld,"-arch","arm64","-platform_version","macos","13.0",sdk_version,
                                "-syslibroot",sdk,"-L"+str(early),"-L"+str(late),main_o,"-ldsactual","-lSystem",
                                "-dependency_info",dep,"-o",exe)]
        selected={str(p):[sha(p),p.stat().st_size,p.stat().st_mtime_ns] for p in (e,l) if p.exists()}
        proc=subprocess.run(argv,capture_output=True)
        (out/"link.stdout").write_bytes(proc.stdout);(out/"link.stderr").write_bytes(proc.stderr)
        if want is not None:
            assert proc.returncode==0 and exe.read_bytes()[:8]==bytes.fromhex("cffaedfe0c000001"),(phase,proc.stderr)
            run=subprocess.run([str(exe)],capture_output=True)
            assert run.returncode==want and not run.stdout and not run.stderr,(phase,run)
            assert dep.stat().st_size>0
        else:
            assert proc.returncode!=0 and proc.stderr,(phase,proc)
        allops=decode(dep.read_bytes()) if dep.exists() else []
        actual=[v for v in allops if v[1].startswith(str(early)+"/") or v[1].startswith(str(late)+"/")]
        v={"argv":argv,"inputs":selected,"rc":proc.returncode,"program_exit":want,"output_sha":sha(exe) if want is not None else None,
           "record_sha":sha(dep) if dep.exists() else None,"all_records":allops,"provider_records":actual}
        write(out/"result.json",v)
        rows[phase]={"rc":v["rc"],"program_exit":want,"provider_records":actual}
    write(dest/"complete.json",rows)
    for key,v in rows.items():print(key,v,flush=True)


if __name__=="__main__":
    main(Path(sys.argv[1]).resolve())
