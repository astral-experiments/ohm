"""Check the native stdout of each case against the complete four-state by 64-mask truth table."""

import gzip
import hashlib
import json
from pathlib import Path
import sys

CORRECT = "97f8e25752996204740fc434544a7d8d3ca35ddb477f451b14973860faabce7f"
BOTH = "d0f6181019512b457daaf179c5d6268a342286744cf61cf3f057b3f6e617b200"
SELECTORS = {
    "K": "9a9f53fe233bc930b59e9f037657c4fd3f9a0a5f065485597f258b496c2cee65",
    "E": "984498d47c6c38948f9eb436edc82d046baad3f3360d9b5ccfa944f3b33d52c0",
    "both_variants": "3f787c5b6265b44e88a561c40cc3ed63635ca0debb5667e3851f8753bc10e0c0",
}


def require(ok, why):
    if not ok:
        raise ValueError(why)


def signed():
    p=Path(__file__).resolve().parent/"inputs/signed-selector.json.gz"
    raw=p.read_bytes()
    require(hashlib.sha256(raw).hexdigest()=="1a21b7b61aaf109f4e21a7fb46a01c33db4cc8ac49c02608b2362f8741588579",
            "different signed actual native positive/negative fixture")
    rows=json.loads(gzip.decompress(raw))
    for name in SELECTORS:
        require(rows[name]["compile"]==[0,"",""] and rows[name]["execute"][0]==0
                and hashlib.sha256(rows[name]["execute"][1].encode()).hexdigest()==(BOTH if name=="both_variants" else CORRECT)
                and rows[name]["execute"][2]=="", ("unqualified signed selector",name))
    require(rows["stale"]["compile"][0]==1 and "error[E0609]" in rows["stale"]["compile"][2]
            and "no field `branch_cache_source`" in rows["stale"]["compile"][2], "wrong original error")
    return rows


def verify(read):
    reference=signed()
    result=json.loads(read("result.json"))
    require(result["source"]=="c9a6a212d38d778ed0e9d2c7057a9dedb179fff2","different E")
    for role in ("K","E","both_variants"):
        raw=read(role+"-run.stdout")
        expected=bytes("".join(f"{state} {flags} {2 if flags==8 and (state==3 or (role=='both_variants' and state==2)) else 0}\n"
                               for state in range(4) for flags in range(64)),"ascii")
        row=result["cases"][role]
        require(raw==reference[role]["execute"][1].encode(), "actual native differs from independent signed compiler")
        require(row["typecheck"]==0 and raw==expected and
                hashlib.sha256(raw).hexdigest()==row["stdout_sha256"]==(BOTH if role=="both_variants" else CORRECT)
                and row["literal_selector_sha256"]==SELECTORS[role], ("incorrect active native predicate",role))
    stale=result["cases"]["stale"]
    err=read("stale-compiler.stderr").decode()
    require(stale["typecheck"]==1 and stale["diagnostic"]==err and "error[E0609]" in err
            and "no field `branch_cache_source`" in err and stale["literal_selector_sha256"]==SELECTORS["K"]
            and stale["session_layout_sha256"]==result["cases"]["E"]["session_layout_sha256"],
            "earlier field error was not reproduced")
    return result


if __name__=="__main__":
    folder=Path(sys.argv[1])
    verify(lambda name:(folder/name).read_bytes())
