"""Reproduce this projection from the original GitHub Actions artifact archives."""
import argparse,gzip,hashlib,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import provider,ruff,ci_profile
from chain import inspect
D=Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__);p.add_argument('provider',type=Path);p.add_argument('pilots',type=Path);p.add_argument('terminal',type=Path);a=p.parse_args()
assert ci_profile.inspect(a.terminal)==json.loads((D/'ci-profile.json').read_bytes())
assert inspect([a.provider,a.pilots,a.terminal])==json.loads((D/'custody.json').read_bytes())
with tempfile.TemporaryDirectory() as td:
 p=Path(td);provider.main(a.provider,p)
 for n in ('provider.json','provider-observations.json.gz'):
  assert (D/n).read_bytes()==(p/n).read_bytes()
assert ruff.analyze(a.terminal)==json.loads(gzip.decompress((D/'ruff-observations.json.gz').read_bytes()))
print('physical inputs, provider native work, full products, bundled controls and all raw clocks match this projection')
