"""Recompute native compiler instruction totals from the complete sequence of Callgrind self costs."""
import gzip
import hashlib
import json
from pathlib import Path
import re


def decode(encoded):
    shift,total=0,0
    for b in encoded:
        total|=(b&127)<<shift
        if b<128:
            yield total
            shift,total=0,0
        else:
            shift+=7
            assert shift<70
    assert not shift


def main():
    root=Path(__file__).resolve().parent
    defs=json.loads((root/"counts.json").read_bytes())
    assert defs["host"]=="x86_64-unknown-linux-gnu" and defs["target"]=="aarch64-apple-darwin"
    assert defs["product_patch_used"] is False and defs["estimated_speedup"] is None
    assert len(defs["counts"])==2
    ledger=json.loads((root/"self-cost-index.json").read_bytes())
    for slot,install in defs["counts"].items():
        assert install["real_compilers"]==3 and install["native_linkers"]==0 and install["typed"]==39
        assert sorted(install["crates"])==["compact_str","ruff_python_ast","zmij"]
        accrued=0
        for crate,r in install["crates"].items():
            key=slot+"-"+crate; entry=ledger[key]
            p=root/(key+".uleb128.gz")
            assert hashlib.sha256(p.read_bytes()).hexdigest()==entry["compressed_self_cost_sha256"]
            data=list(decode(gzip.decompress(p.read_bytes())))
            root_event=entry["original_valgrind_collected"]
            field,=re.findall(r"Collected\s+:\s+([\d,]+)$",root_event)
            assert len(data)==entry["self_rows"] and sum(data)==int(field.replace(",",""))==entry["callgrind_totals"]==r["Ir"]
            assert r["profile_sha256"]==entry["original_profile_sha256"] and r["log_sha256"]==entry["original_log_sha256"]
            accrued+=sum(data)
        assert accrued==install["sum"]
        print(slot,accrued)


if __name__=="__main__":
    main()
