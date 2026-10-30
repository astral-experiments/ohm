from collections import defaultdict
import gzip, hashlib, json, stat
from pathlib import PurePosixPath

def raw(z,k): return gzip.decompress(z.read(k))
def record(z,k): return json.loads(z.read(k))
def digest(b):return hashlib.sha256(b).hexdigest()

def disk(z,prefix):
    blob=raw(z,prefix+"disk-inodes.json.gz")
    summary=record(z,prefix+"disk.json")
    assert digest(blob)==summary["source_sha256"]
    rows=json.loads(blob)
    ids={}
    paths=set()
    sessions=defaultdict(set)
    for name,dev,ino,size,blocks,kind,nlink in rows:
        path=PurePosixPath(name)
        assert name not in paths and path.parts[0] in ("target","shared") and nlink>=1
        paths.add(name)
        item=ids.setdefault((dev,ino),(size,blocks,kind,set()))
        assert item[:3]==(size,blocks,kind)
        item[3].add("incremental" in path.parts)
        if kind==stat.S_IFDIR and path.name.startswith("s-") and path.parent.parent.name=="incremental":
            sessions[str(path.parent)].add(path.name)
    assert len(rows)==summary["entries"] and {k:set(v) for k,v in summary["incremental_sessions"].items()}==sessions
    groups={"all":list(ids.values()),"only_incremental":[x for x in ids.values() if x[3]=={True}],
            "incremental_and_elsewhere":[x for x in ids.values() if x[3]=={True,False}]}
    for group,items in groups.items():
        assert {"bytes":sum(x[0] for x in items),"allocated_bytes":512*sum(x[1] for x in items),"inodes":len(items)}==summary[group]
    return {"allocated":summary["all"]["allocated_bytes"],"logical":summary["all"]["bytes"],
            "inc_only":summary["only_incremental"]["allocated_bytes"],"sessions":sorted(map(len,sessions.values()))}
