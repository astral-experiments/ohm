"""Reconstruct the published local-development projection from original hosted ZIPs."""
import argparse,gzip,json,sys,tempfile
from pathlib import Path
D=Path(__file__).resolve().parent;sys.path.insert(0,str(D))
import provider,ruff
from chain import inspect
ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('provider',type=Path);ap.add_argument('pilots',type=Path);ap.add_argument('terminal',type=Path);a=ap.parse_args()
assert inspect([a.provider,a.pilots,a.terminal])==json.loads((D/'custody.json').read_bytes())
with tempfile.TemporaryDirectory() as temp:
    p=Path(temp);provider.main(a.provider,p)
    for n in ('provider.json','provider-observations.json.gz'):
        assert (p/n).read_bytes()==(D/n).read_bytes()
assert ruff.analyze(a.terminal)==json.loads(gzip.decompress((D/'ruff-observations.json.gz').read_bytes()))
print('all original custodied streams, compiled modules, complete images/ZIPs and clock records match')
