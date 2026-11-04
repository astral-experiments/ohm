"""Check the cold and settled cost of changing the type table on Ruff's AST crate."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

def trial(source, kernel, cargo_home, root, proof, meter=None):
    root.mkdir(parents=True)
    proof.mkdir(parents=True)
    home = root / "cargo-home"
    shutil.copytree(cargo_home, home)
    env = {k:os.environ[k] for k in ("HOME","USER","LANG","PATH","TZ","TMPDIR") if k in os.environ}
    env.update(RUSTUP_HOME=str(kernel), CARGO_HOME=str(home), CARGO_BUILD_JOBS="2",
               CARGO_TARGET_DIR=str(root/"target"), CARGO_BUILD_BUILD_DIR=str(root/"shared"), CARGO_NET_OFFLINE="true")
    products = []
    for phase in ("cold","settled"):
        at = proof/phase
        at.mkdir()
        args = ["cargo","+ohm","check","-p","ruff_python_ast","--lib","--locked","--offline","--message-format=json"]
        if meter is not None:
            args = [meter,at/"hardware.json",shutil.which("cargo"),*args]
        with (at/"stdout.jsonl").open("wb") as out, (at/"stderr").open("wb") as err:
            subprocess.run(args,env=env,cwd=source,stdout=out,stderr=err,check=True)
        rows = [json.loads(s) for s in (at/"stdout.jsonl").read_bytes().splitlines()]
        assert rows[-1] == {"reason":"build-finished","success":True}
        artifacts = [r for r in rows if r["reason"]=="compiler-artifact"]
        selected, = [r for r in artifacts if r["target"]["name"]=="ruff_python_ast" and r["target"]["kind"]==["lib"]]
        meta, = [Path(f) for f in selected["filenames"] if f.endswith(".rmeta")]
        with meta.open("rb") as f:
            digest=hashlib.file_digest(f,"sha256").hexdigest()
        dirty=sorted(a["target"]["name"] for a in artifacts if not a["fresh"])
        assert (len(dirty)==len(artifacts) if phase=="cold" else not dirty)
        products.append(digest)
        result={"sha256":digest,"units":len(artifacts),"dirty":dirty}
        if meter is not None:
            hw=json.loads((at/"hardware.json").read_bytes())
            assert hw["status"]==0 and hw["instructions"]>0 and hw["enabled"]==hw["running"]>0
            result["instructions"]=hw["instructions"]
        (at/"result.json").write_text(json.dumps(result,sort_keys=True)+"\n")
    assert products[0]==products[1]

if __name__=="__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import price
    assert price.git("rev-parse","HEAD")==price.new and not price.git("status","--porcelain")
    for role in price.order:
        actual=price.work/("used-sdk-"+role)
        assert price.sha(next((actual/"lib").glob("librustc_driver-*.so")))==price.transport.KIT[role]["driver"]
        alias=price.work/"ast-rustup/toolchains/ohm"
        alias.parent.mkdir(parents=True,exist_ok=True)
        alias.symlink_to(actual,target_is_directory=True)
        src=price.gitroot
        at=price.work/"ast-control"
        trial(src,alias.parent.parent,price.work/"enrolled-cargo-home",at,price.proof/role/"ordinary-ast",price.work/"whole_count")
        at.rename(price.work/("ast-control-"+role))
        alias.unlink()
