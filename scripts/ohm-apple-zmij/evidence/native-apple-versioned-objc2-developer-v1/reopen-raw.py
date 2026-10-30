"""Verify and reproduce all derived data directly from the four original native Actions archives."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from chain import inspect
from native import compact
from root_measure_objc2 import check

def invoke(module,*args):
    subprocess.run([sys.executable,"-IB",str(HERE/module),*map(str,args)],check=True)
def packed(p):return json.loads(gzip.decompress(p.read_bytes()))
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives",nargs=4,type=Path,metavar="ZIP")
    parser.add_argument("--b3sum",default=shutil.which("b3sum"))
    args=parser.parse_args();assert args.b3sum
    paths=[p.resolve(strict=True) for p in args.archives]
    expected=json.loads((HERE/"custody.json").read_bytes())
    assert inspect(paths)==expected
    from terminal_clocks import calculate
    assert calculate(paths[-1],expected[-1]["sha256"])==packed(HERE/"independent-clocks.json.gz")
    with tempfile.TemporaryDirectory() as tmp:
        out=Path(tmp)
        invoke("matrix.py",paths[0],out)
        invoke("symbols.py",paths[0],out,"--b3sum",args.b3sum)
        for key in ("provider-rows","migration-rows"):assert (out/(key+".json.gz")).read_bytes()==(HERE/(key+".json.gz")).read_bytes()
        assert json.loads((out/"matrix.json").read_bytes())==json.loads((HERE/"matrix.json").read_bytes())
        for key in ("registry","named"):assert json.loads((out/(key+".json")).read_bytes())==packed(HERE/(key+".json.gz"))
        invoke("application.py",paths[1],out)
        assert json.loads((out/"application.json").read_bytes())==packed(HERE/"application.json.gz")
        for idx,stage in enumerate(("screen","confirmation"),2):
            assert check(paths[idx],expected[idx]["sha256"],stage)==packed(HERE/(stage+".json.gz"))
    print("Reopened all four cumulative artifact streams and reproduced the complete sealed projections.")
if __name__=="__main__":main()
