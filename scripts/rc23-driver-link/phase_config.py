"""Install the observer through Cargo's existing per-directory child environment."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib

import gate as g

sys.path.insert(0,str(Path(__file__).resolve().parent/"prelto"))
import phase
from read import stat_values, stream

KEYS=("RUSTC_WRAPPER_REAL","OHM_PHASE_OUT","OHM_PHASE_MANIFEST")

def calibration(out):
    start=g.read(out/"start.json")
    with tempfile.TemporaryDirectory(dir=out) as name:
        d=Path(name);a=d/"source.rlib";b=d/"physical.rlib";missing=d/"absent.rlib"
        a.write_bytes(b"source archive admission");os.link(a,b)
        script="import os,sys; os.stat(sys.argv[1]); os.stat(sys.argv[2]); assert not os.path.exists(sys.argv[3])"
        raw=d/"trace";cmd=[start["strace"],"-qq","-v","-yy","-f","--seccomp-bpf","-e","trace=statx,newfstatat,stat","-o",str(raw),"--",sys.executable,"-ISB","-c",script,str(a),str(b),str(missing)]
        result=subprocess.run(cmd,check=True,capture_output=True)
        data=raw.read_bytes();(out/"calibration.trace.gz").write_bytes(gzip.compress(data,mtime=0))
        # A single pid is selected; strace -f may print that pid before the syscall.
        rows=stream(b"\n".join(line.split(None,1)[1] if line.split(None,1)[0].isdigit() else line for line in data.splitlines()),name)
        seen={path:(rc,errno,stat_values(op,args) if rc==0 else None) for _,op,args,rc,errno,path in rows if path in (str(a),str(b),str(missing))}
        st=a.stat();assert seen[str(a)]==seen[str(b)] and seen[str(a)][0]==0
        value=seen[str(a)][2];assert (value["dev"],value["ino"],value["size"],value["type"])==(st.st_dev,st.st_ino,st.st_size,"S_IFREG")
        assert seen[str(missing)][:2]==(-1,"ENOENT")
    g.save(out/"calibration.json",{"argv":cmd,"strace_sha256":start["strace_sha256"],"stderr":result.stderr.decode(),"stat_results":seen,"raw_sha256":hashlib.sha256(data).hexdigest()})

def enter(w,out,manifest=None,rustc=None,env=None):
    source=w/"source";root=source/"rust";target=g.POLICY["target"]
    manifest=(root/"compiler/rustc_driver" if manifest is None else manifest).resolve(strict=True)
    rustc=root/"build"/target/"stage1/bin/rustc" if rustc is None else rustc
    before=dict(os.environ if env is None else env)
    prepared=phase.begin(out,before,manifest,rustc)
    assert {k for k in prepared if prepared[k]!=before.get(k)}==set(KEYS)
    calibration(out)
    directory=source/".cargo";new=not directory.exists()
    assert source==source.resolve(strict=True) and not directory.is_symlink()
    directory.mkdir(exist_ok=True);p=directory/"config.toml"
    assert not (directory/"config").exists() and not p.is_symlink()
    cfg={k:prepared[k] for k in KEYS}
    body=("[env]\n"+"".join(k+" = "+json.dumps(v)+"\n" for k,v in cfg.items())).encode()
    assert tomllib.loads(body.decode())=={"env":cfg} and not p.exists()
    with p.open("xb") as f:f.write(body)
    st=p.stat()
    record={"path":str(p),"created_parent":new,"dev":st.st_dev,"ino":st.st_ino,"sha256":g.sha(p),"contents":body.decode(),"cargo_child_environment":cfg,"original_opt_dist_allowlist_unchanged":True}
    g.save(out/"cargo-config.json",record)
    return record

def leave(record,out):
    p=Path(record["path"]);st=p.lstat()
    assert not p.is_symlink() and (st.st_dev,st.st_ino,g.sha(p))==(record["dev"],record["ino"],record["sha256"])
    p.unlink()
    if record["created_parent"] and not any(p.parent.iterdir()):p.parent.rmdir()
    g.save(out/"cargo-config-closed.json",{"config":record["sha256"],"absent":not p.exists()})
