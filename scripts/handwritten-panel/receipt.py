"""Compare a native metadata equality receipt to its exact writes through JSON."""
import json

def canonical(value):
    return json.dumps(value,separators=(",",":"),sort_keys=True,allow_nan=False).encode("utf-8")

def normalized(record):
    assert isinstance(record,dict) and set(record)=={"all_70_roots_and_deps_equal","actual_downstream","raw_drift","deep"}
    deep={}
    for product,row in record["deep"].items():
        projection=row["projection"]
        header=projection["header"]
        tags=header["allocation_tags"]
        count=header["allocation_records"]
        assert type(tags) is dict and type(count) is int and count>=0
        assert all(type(tag) is int and 0<=tag<5 and type(n) is int and n>0 for tag,n in tags.items())
        assert sum(tags.values())==count
        public=dict(header,allocation_tags={str(tag):n for tag,n in tags.items()})
        deep[product]=dict(row,projection=dict(projection,header=public))
    result=dict(record,deep=deep)
    assert canonical(record)==canonical(result)
    return result

def matches(native,stored):
    converted=normalized(native)
    return converted==stored and canonical(converted)==canonical(stored)
