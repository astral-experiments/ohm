"""All-crate interpretation of the pinned reader, including exact ordered allocations."""
import hashlib
import json
from pathlib import Path
import types

READER_SHA="ead2a0c863595f0e4c1a10a1d14acd33cf526054eaf56851125c7d604354a0eb"
def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":")).encode()
def h(raw):return hashlib.sha256(raw).hexdigest()
def parser(source):
    raw=source.read_bytes();assert h(raw)==READER_SHA
    # The historical parser hard-coded terminal "uv". Its decoding algorithm and all other
    # assertions stay byte-for-byte intact; bind the actual Cargo-owned crate name instead.
    a,b=b"def parse(arg):",b'def parse(arg, expected_name):'
    x,y=b'root["crate_name"]=="uv","not terminal GNU uv"',b'root["crate_name"]==expected_name,"unexpected GNU crate"'
    assert raw.count(a)==raw.count(x)==1
    m=types.ModuleType("all_checked_workspace_metadata");m.__file__=str(source.resolve())
    exec(compile(raw.replace(a,b).replace(x,y),str(source),"exec"),m.__dict__)
    original=m.blob
    def bounded(arg):
        if isinstance(arg,bytes):
            assert 0<len(arg)<=m.LIMIT
            return arg
        return original(arg)
    m.blob=bounded
    return m.parse
def project(parse,path,name):
    header,defs,expansions,allocs,_=parse(path if isinstance(path,bytes) else str(path),name)
    header=dict(header);header.pop("raw_sha256");header.pop("bytes")
    resolved=[]
    for key,(raw,parent,kind,symbol,disambiguator) in sorted(defs.items()):
        value=bytes.fromhex(raw)
        assert len(value)<=17 and (not any(value) or value[0]==1)
        resolved.append([key,value.ljust(17,b"\0").hex(),parent,kind,symbol,disambiguator])
    assert len(resolved)==header["definition_count"] and len(expansions)==header["reachable_expansions"]
    assert sum(allocs.values())==header["allocation_records"] and len(allocs)==header["distinct_allocation_records"]
    return {"header":header,"all_definitions":h(canonical(resolved)),
        "reachable_definitions":sum(any(bytes.fromhex(v[1])) for v in resolved),
        "all_reachable_expansions":h(canonical(expansions)),"allocation_content_counts":h(canonical(allocs))}
