"""Recheck the published dictionary. With the original inputs, independently reopen both histories."""
import argparse
import collections
import gzip
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reopen


def read(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def checksum(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def check(frozen=None, previous=None, llvm_dis=None, cxxfilt=None):
    saved = read(HERE / "results/names-v1.json.gz")
    q = read(HERE / "results/qualification-v1.json.gz")
    selection = json.loads((HERE / "keys.json").read_bytes())
    primary = saved["primary"]
    assert len(primary) == 30 and sum(len(v["selection"]) for v in primary) == 49
    assert len(saved["context"]) == 1396 and {(r["kind"], r["key"]) for r in primary+saved["context"]} == {tuple(k) for k in selection["context"]}
    assert len(saved["negative_swaps"]) == len(set(tuple(a) for a in saved["negative_swaps"])) == 4
    for row in primary:
        assert row["status"] == "unique" and len(row["names"]) == 1 and len(row["rows"]) == 2
        assert {r["branch"] for r in row["rows"] if r["item"] == row["names"][0]["raw"]} == {"A", "B"}
        for r in row["rows"]:
            assert r["key"] == row["key"] and r["kind"] == row["kind"]
            assert r["graph"] == saved["states"][r["branch"]]["graph"]["sha256"]
            for pick in row["selection"]:
                source = pick["node"]
                expected = source["previous_value"] if r["branch"] == "B" else source["current_value"]
                assert r["value"] == expected
    count = collections.Counter(len({r["branch"] for r in n["rows"] if r["item"]}) for n in saved["context"])
    assert count == {0:110,2:1286}
    assert q["stable_occurrences"] == {"empty ordinary item":3, "erased lifetimes only":4, "concrete generic type or const":27, "drop glue":1}
    if frozen:
        actual = reopen.inspect(frozen)
        for k in ("states","primary","context","selection","selection_sha256","status"):
            assert actual[k] == saved[k], k
        assert [row[:3] for row in actual["negative_cross_inputs"]] == saved["negative_swaps"]
    if previous:
        custody=q["checked_official"]
        assert checksum(previous) == custody["included_unprofiled_sha256"]
        with zipfile.ZipFile(previous) as z:
            for b in ("A","B"):
                src=json.loads(gzip.decompress(z.read("reference/"+b+"/native.json.gz")))
                if frozen:
                    got=read(frozen/b/"native.json.gz")
                    assert src["reader"] == got["reader"] and src["typed"] == got["typed"]
                    assert src["cli"]["executable"] == got["cli"]["executable"] and src["cli"]["loads"] == got["cli"]["loads"]
                    assert src["cli_cases"] == got["cli_cases"] and src["fstring_cases"] == got["fstring_cases"]
                    assert sorted(k for k,v in src["cli"]["sections"].items() if v["sha256"] != got["cli"]["sections"][k]["sha256"]) == q["source_and_native"][b]["actual_section_content_changes"]
                assert src["cli"]["whole"] == q["source_and_native"][b]["prior_cli"]
            if llvm_dis:
                emitted = json.loads(z.read("diagnostic-empty/A/cgus.json"))["ruff_workspace"]["emitted"]
                index = {k.rsplit(".",1)[1]:entry["sha256"] for k,entry in emitted.items()}
                for v in q["instances"].values():
                    for cgu, witness in v.get("corroborated_in",{}).items():
                        digest=index[cgu]
                        assert digest == witness["bitcode"]
                        bc=gzip.decompress(z.read("cgu-originals/"+digest+".gz"))
                        assert hashlib.sha256(bc).hexdigest() == digest
                        ir=subprocess.check_output([llvm_dis,"-o","-","-"],input=bc)
                        sym=witness["mangled"].encode()
                        assert b"@"+sym+b"(" in ir or b'@"'+sym+b'"(' in ir
                        full=subprocess.check_output([cxxfilt,"-s","rust","-n",witness["mangled"]],text=True).strip()
                        assert re.sub(r'\[[a-f0-9]{4,16}\]',"",full) == v["concrete_declaration"]
    print("30/30 identities, 60/60 output fingerprints, 1,286 additional identities in both cold builds")
    print("35 ABI/symbol occurrences",q["stable_occurrences"])


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("artifact",nargs="?",type=Path,help="extracted complete diagnostic artifact")
    p.add_argument("--unprofiled-artifact",type=Path,help="complete first-A original ZIP from run 41362345812")
    p.add_argument("--llvm-dis",help="compatible CI LLVM 22 llvm-dis")
    p.add_argument("--cxxfilt",default="c++filt")
    args=p.parse_args()
    if args.llvm_dis and not args.unprofiled_artifact:
        p.error("--llvm-dis requires --unprofiled-artifact")
    check(args.artifact,args.unprofiled_artifact,args.llvm_dis,args.cxxfilt)
