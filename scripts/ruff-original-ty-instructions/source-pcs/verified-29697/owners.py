"""Resolve both changed real old-map keys from the signed alloc metadata."""
import gzip,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from alloc_schema import decode
root=Path(__file__).resolve().parent
s=json.loads(gzip.decompress((root/"metadata-schema.json.gz").read_bytes()));assert hashlib.sha256((root/"metadata-schema.json.gz").read_bytes()).hexdigest()=="236f4a0f399c405ddde4b5112d5b75983916b6ce5a3ee8056274c2dcc9047c5e"
source=json.loads((root/"source.json").read_bytes());f,=(Path(sys.argv[1])/"lib/rustlib/x86_64-unknown-linux-gnu/lib").glob("liballoc-*.rmeta");raw=f.read_bytes();assert hashlib.sha256(raw).hexdigest()==source["alloc_rmeta_sha256"]
version=b"rustc 1.99.0-dev (d57fd1515 2026-11-02) (ohm-1.99.0-23) (Ohm metadata 3)"
assert raw[17:17+len(version)]==version
info,defs,*_=decode(raw,s["symbols"],s["tables"],"alloc",version.decode());assert len(defs)==source["alloc_definitions"]
resolved={}
for fingerprint,expected in source["owners"].items():
    crate,local=bytes.fromhex(fingerprint[:16]),bytes.fromhex(fingerprint[16:]);assert crate[::-1].hex()==info["stable"]
    name="alloc::"+defs[local[::-1].hex()][0];assert name==expected;resolved[fingerprint]=name
print(json.dumps(resolved,sort_keys=True))
