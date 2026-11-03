"""Reopen five originals and check every byte outside three complete generated blocks."""
from pathlib import Path
import gzip
import hashlib
import json
import re

ROOT=Path(__file__).resolve().parent
def sha(b):return hashlib.sha256(b).hexdigest()
data=json.loads((ROOT/'upstream-expansions.json').read_bytes())
proof=data['authentication'];all_bodies={}
for subject in sorted(ROOT.glob('*.rs.gz')):
    raw=gzip.decompress(subject.read_bytes());code=sha(raw)
    assert code+'.rs.gz'==subject.name
    blocks=list(re.finditer(rb'^                if let \(::core::prelude::v1::Some\(__a\),.*?^                }\n',raw,re.M|re.S))
    assert len(blocks)==3 and all(a.end()==b.start()for a,b in zip(blocks,blocks[1:]))
    digests=[sha(b[0])for b in blocks];assert digests==proof['permuted_blocks'][subject.name]
    canonical=raw[:blocks[0].start()]+b''.join(sorted(b[0] for b in blocks))+raw[blocks[-1].end():]
    assert sha(canonical)==proof['all_five_normalized']
    pairs=[list(x.decode() for x in re.search(rb'`(\w+)` conflicts with mutually exclusive `(\w+)`',b[0]).groups())for b in blocks]
    all_bodies[code]=pairs
assert len(all_bodies)==data['distinct_expanded']==5 and len(data['runs'])==data['n']==12
for i,row in enumerate(data['runs']):assert row['ordinal']==i and row['order']==all_bodies[row['sha']]
print('12 authentic expansions, five orders, common complete source SHA-256',proof['all_five_normalized'])
