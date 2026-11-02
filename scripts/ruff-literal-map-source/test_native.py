"""Exercise native archive comparison on the registered real source scout."""
from contextlib import ExitStack
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import native_payload as n

def main(path):
    with path.open("rb") as f:
        assert hashlib.file_digest(f,"sha256").hexdigest()=="80b89441167c1f779dd9450e09268e04ba563cd3221200157f331a2d78cb4e67"
    with tempfile.TemporaryDirectory() as td,zipfile.ZipFile(path) as z:
        base=Path(td);os.environ.setdefault("RUNNER_TEMP",td);os.environ.setdefault("GITHUB_WORKSPACE",td)
        from ordinary_read import reassemble
        from ordinary import opportunity,OWNERS
        store=base/"compressed";store.mkdir();raw=base/"raw";raw.mkdir();parsed={}
        def blob(key):
            file=raw/key
            if not file.exists():
                with file.open("xb") as f:subprocess.run(["zstd","-dq","-c",store/(key+".zst")],check=True,stdout=f)
                assert hashlib.sha256(file.read_bytes()).hexdigest()==key
            return file
        for label in ("old","edit","clean"):
            library=base/(label+".rlib");library.write_bytes(gzip.decompress(z.read(label+"/libruff_python_literal.rlib.gz")))
            arch,recipe=n.manifest(library,store);parsed[label]=arch
            restored=base/"reassembled.rlib";reassemble(restored,recipe,blob);assert restored.read_bytes()==library.read_bytes()
            assert set(subprocess.check_output(["ar","t",library],text=True).splitlines())==set(arch["metadata"])|set(arch["objects"])
            for name,(digest,count) in arch["objects"].items():
                data=subprocess.check_output(["ar","p",library,name])
                assert len(data)==count and hashlib.sha256(data).hexdigest()==digest
        assert len(n.stable(parsed["clean"]))==22 and n.stable(parsed["edit"])==n.stable(parsed["clean"])!=n.stable(parsed["old"])
        assert not parsed["edit"]["objects"].keys()&parsed["clean"]["objects"].keys()
        new=base/"session-new";old=base/"session-old";new.mkdir();old.mkdir()
        for name,(key,_) in n.stable(parsed["clean"]).items():shutil.copyfile(blob(key),old/name)
        with ExitStack() as stack:
            files=n.old_files(stack,old);chosen=sorted(files)[0]
            for k in files:
                if k==chosen:shutil.copyfile(old/k,new/k)
                else:os.link(old/k,new/k)
            rows=n.observe_objects(new,files,parsed["clean"])
            assert sum(v["retained"] for v in rows.values())==len(rows)-1 and not rows[chosen]["retained"]
            with (new/chosen).open("r+b") as f:
                f.seek(-1,2);v=f.read(1);f.seek(-1,2);f.write(bytes([v[0]^1]))
            try:n.observe_objects(new,files,parsed["clean"])
            except ValueError as err:assert "does not match all archived" in str(err)
            else:raise AssertionError("corrupt full object accepted")
        def example(kept):
            records={str(i):dict(after=[1,i+1,size],after_sha256="same",retained=i in kept)
                     for i,size in enumerate((9,1,90))}
            return {"ledgers":{owner:{"objects":records} for owner in OWNERS}}
        assert not opportunity(example(set()),example({0}))["meaningful"]
        assert opportunity(example(set()),example({0,1}))["meaningful"]
        assert not opportunity(example({2}),example({0,1}))["meaningful"]
    print("Three signed rlibs exactly reassembled, 66 GNU ar payloads independently reopened, changed-byte negative rejected.")

if __name__=="__main__":main(Path(sys.argv[1]))
