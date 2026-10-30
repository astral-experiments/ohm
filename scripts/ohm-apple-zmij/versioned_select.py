"""Select a physical Cargo at one stable executable path without modifying either Rust installation."""
from pathlib import Path
import json
import os
from study import CARGO_SOURCE, need, physical, run, sha, save

CLASSIC = "735e1528ed741015c57676dccf05dbdc0ff7bed1"
AWARE = "9a102b4519b40f9034aa40533d92c83583dcb289"
CARGOS = {"signed": (CARGO_SOURCE,"signed/bin/cargo"), "classic": (CLASSIC,"cargo-293"), "aware": (AWARE,"cargo-aware")}
def current(root):
    selection=json.loads((root/"receipts/versioned-current.json").read_bytes())
    rev,subject=CARGOS[selection["name"]]
    expected=root/subject; dest=root/"native/bin/cargo"
    need(selection["source"]==rev and dest.samefile(expected) and selection["binary"]==physical(dest),"wrong deployed Cargo")
    return selection
def choose(root, name):
    rev,subject=CARGOS[name]; expected=root/subject; dst=root/"native/bin/cargo"
    if name=="signed":
        need(sha(expected)==json.loads((root/"receipts/release.json").read_bytes())["cargo"]["sha256"], "unauthenticated signed Cargo")
    else:
        record=json.loads((root/("receipts/cargo293/product.json" if name=="classic" else "receipts/cargo-aware/product.json")).read_bytes())
        need(record["source"]["commit"]==rev and record["binary"]==physical(expected),"unauthenticated source build")
    if not dst.samefile(expected):
        tmp=dst.with_name("cargo-versioned.next");need(not tmp.exists(), "abandoned selection")
        os.link(expected,tmp);os.replace(tmp,dst)
    version=run([dst,"-Vv"]).decode()
    need("commit-hash: "+rev in version and dst.samefile(expected),"incorrect version after switch")
    selection={"name":name,"source":rev,"binary":physical(dst),"version":version}
    path=root/"receipts/versioned-current.json";tmp=path.with_suffix(".next");save(tmp,selection);os.replace(tmp,path)
    return current(root)
