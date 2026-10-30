"""Read the original scoped Mac kernel events separately from Cargo's reported freshness."""
from pathlib import Path
import gzip
import hashlib
import json
import re


def read(path):
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix==".gz" else raw)


def main():
    root=Path(__file__).resolve().parent
    meta=read(root/"study.json")
    assert meta["mode"]=="kernel-exec" and meta["positive_stock_linker"] and meta["signed_release"]
    for visit in ("repeat-1","repeat-2"):
        rows=read(root/(visit+"-exec.json.gz"))
        cargo_rustcs=[r for r in rows if r["path"]==meta["compiler"] and "--crate-name" in r["argv"]]
        assert len(cargo_rustcs)==1
        ev,=cargo_rustcs
        a=ev["argv"]
        assert ev["cdhash"]==meta["compiler_cdhash"] and 0<ev["pid"] and a[a.index("--crate-name")+1]=="zmij" and any(n.startswith("--emit=") for n in a)
        assert all(r["path"]!=meta["linker"] for r in rows)
        compiler_events=[r for r in rows if "--crate-name" in r["argv"]]
        assert all(Path(r["path"]).name in {"bash","rustup","rustc"} for r in compiler_events)
        data=gzip.decompress((root/(visit+"-cargo.jsonl.gz")).read_bytes()).splitlines()
        reports=[json.loads(l) for l in data]
        assert reports[-1]=={"reason":"build-finished","success":True}
        typed=[r for r in reports if r["reason"]=="compiler-artifact"]
        dirty=sorted(r["target"]["name"] for r in typed if not r["fresh"])
        assert len(typed)==39 and dirty==["compact_str","ruff_python_ast","zmij"]
        print(visit,"3 dirty Cargo units, 1 physical rustc (zmij), 0 native links")
    assert meta["signed_qualification"]["status"]=="passed" and meta["signed_qualification"]["scores"]==0
    assert meta["signed_qualification"]["causal_counts"]=={"untouched":[1,1,1],"omit-vector-comment":[1,0,0],"restored":[1,1,1]}


if __name__=="__main__":main()
