"""Invoked only by bootstrap's existing wrapper hook. Trace the original compiler from its exec."""
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from read import digest, load, reduce, require, save
from origins import originals,verify

def option(args, key):
    found=[]
    for i, arg in enumerate(args):
        if arg == key:
            require(i+1<len(args), ("argument",key))
            found.append(args[i+1])
        elif arg.startswith(key+"="):
            found.append(arg.split("=",1)[1])
    return found

def observe(original):
    home=Path(os.environ["OHM_PHASE_OUT"])
    config=load(home/"start.json")
    args=original[1:]
    names=option(args,"--crate-name")
    if names != ["rustc_driver"] or "dylib" not in {ty for v in option(args,"--crate-type")for ty in v.split(",")}:
        require(not any(a.startswith("@")for a in args), "unresolved compiler response file on selected manifest")
        os.execv(original[0], original)
    require(Path(original[0]).resolve()==Path(config["rustc"]).resolve(), ("unexpected real compiler",original[0],config["rustc"]))
    manifest=Path(config["manifest"]).resolve(strict=True)
    require(Path(os.environ["CARGO_MANIFEST_DIR"]).resolve(strict=True)==manifest, "manifest")
    policy=Path(os.environ["OHM_RUSTC_DRIVER_LINK_DIR"])
    require(policy.is_absolute() and (policy/"driver").read_text()==str(manifest), "canonical marker")
    candidates=[a for a in args if a.endswith(".rs") and Path(a).resolve()==manifest/"src/lib.rs"]
    require(len(candidates)==1 and not any(a.startswith("@")for a in args), "canonical driver input/response")
    d=home/("visit-"+str(os.getpid()))
    d.mkdir(mode=0o700)
    request={"argv":original,"cwd":os.getcwd(),"manifest":str(manifest),"policy":str(policy),"wrapper_pid":os.getpid(),
             "rustc_sha256":hashlib.file_digest(open(original[0],"rb"),"sha256").hexdigest(),"strace":config["strace"]}
    save(d/"request.json",request)
    command=[config["strace"],"-ff","-qq","-v","-s","8192","-yy","--seccomp-bpf","-e","abbrev=execve,execveat",
             "-e","trace=execve,execveat,statx,newfstatat,stat,lstat,fstat,open,openat,openat2,creat,clone,clone3",
             "-o",str(d/"syscall"),"--",*original]
    body=subprocess.run(command,close_fds=False)
    files=[]
    for path in sorted(d.glob("syscall.*")):
        require(re.fullmatch(r"syscall\.[0-9]+", path.name),("unexpected raw file",path))
        with path.open("rb") as src,path.with_suffix(path.suffix+".gz").open("xb") as target:
            h=hashlib.sha256();n=0
            with gzip.GzipFile(fileobj=target,mode="wb",filename="",mtime=0,compresslevel=2) as packed:
                while block:=src.read(1<<20):
                    h.update(block);n+=len(block);packed.write(block)
        files.append({"file":path.name+".gz","bytes":n,"sha256":h.hexdigest()})
        path.unlink()
    save(d/"trace.json",{"exit":body.returncode,"request":digest((d/"request.json").read_bytes()),"files":files})
    if body.returncode!=0:
        return body.returncode
    try:
        result=reduce(d)
        archive_sources=originals(d,result,request)
        verify(d,result,archive_sources,request["cwd"])
        save(d/"archives.json",archive_sources)
        save(d/"observed.json",result)
    except Exception as e:
        save(d/"refused.json",{"reason":str(e)})
        print("pre-LTO membership observer refused: "+str(e)[:500],file=sys.stderr)
        # Preserve all original dist, link and native results; finish() will enforce this separate gate.
    return body.returncode

if __name__=="__main__":
    sys.exit(observe(sys.argv[1:]))
