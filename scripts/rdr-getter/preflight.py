"""Exercise the real topology observer and authenticated setup outside the Ruff histories."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import cell
import worker

def main(observer,calibrated,signed=None):
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp); folder=root/"raw";folder.mkdir()
        subprocess.run(["cc","-O2",observer/"scripts/gnu-example-ceiling/observer.c","-o",root/"tree"],check=True)
        run,roster=cell.tree_call(folder,["sh","-c","/usr/bin/true; /usr/bin/printf ok"],root,os.environ.copy(),root,root/"plain")
        assert run.stdout==b"ok" and roster["execs"]>=3 and roster["rustcs"]==roster["linkers"]==[]
        assert worker.adapter(calibrated,root).HERE==root/"workload"
        print("genuine fork/exec/wait preflight",roster,flush=True)
        if signed:
            for name,digest in (("ruff_db","77a4399eaabba2782dd2c1f1c534ff34cf514abc588119758d3efc19022ffeef"),
                                ("ruff_notebook","cabc428fbe5a6e7969b0ce12ad021d8d74c5f9e11a2849d528c0a10ef3d82fbf")):
                path=root/name;path.write_bytes(gzip.decompress((signed/"cas"/digest).read_bytes()))
                info=cell.metadata(root,name,path);assert info["cas"]==digest
                print(name,info["def_count"],info["stamp"],info["global"])
            for p in sorted((signed/"raw").iterdir()):
                streams=json.loads(gzip.decompress((p/"trace.json.gz").read_bytes()))
                docs=[ln for trace in streams.values() for ln in trace.splitlines() if ln.startswith("execve(") and '/rustdoc"' in ln.split(", [")[0]]
                assert not docs,(p.name,docs)
            print("signed original contains zero positive rustdoc EXEC records across eight visits")

if __name__=="__main__":
    main(*map(lambda p:Path(p).resolve(),sys.argv[1:]))
