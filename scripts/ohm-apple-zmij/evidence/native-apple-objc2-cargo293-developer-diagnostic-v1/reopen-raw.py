"""Reproduce the compact ordinary Apple CLI records using its original artifacts."""
import argparse, gzip, json, sys, tempfile
from pathlib import Path
from zipfile import ZipFile
D=Path(__file__).resolve().parent
sys.path.insert(0,str(D))
import application, chain, provider, root_measure_objc2
from native import Dataset, digestfile
ap=argparse.ArgumentParser(description=__doc__)
for name in ('provider','native','pilot','terminal'):ap.add_argument(name,type=Path)
a=ap.parse_args()
assert chain.inspect([a.provider,a.native,a.pilot,a.terminal])==json.loads((D/'custody.json').read_bytes())
with tempfile.TemporaryDirectory() as td:
    p=Path(td);provider.main(a.provider,p)
    for name in ('provider.json','provider-observations.json.gz'):
        assert (p/name).read_bytes()==(D/name).read_bytes()
with ZipFile(a.native) as z:
    v=Dataset(z);rows,refs,images,env=application.reopen(v)
    data={'source':provider.sources(v),'archive':digestfile(a.native),'rows':rows,'images':images,'environment':env}
    assert data==json.loads(gzip.decompress((D/'application.json.gz').read_bytes()))
for label,path in [('screen',a.pilot),('confirmation',a.terminal)]:
    assert root_measure_objc2.check(path,digestfile(path),label)==json.loads(gzip.decompress((D/(label+'.json.gz')).read_bytes()))
print('all four original ZIPs, complete CLI and provider bytes, native observations and all paired clocks match')
