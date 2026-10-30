"""Extract the admitted raw observations into a compact, offline-replayable record."""

import gzip
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from read_ordinary import ARMS, Archive, PHASES, cohort, installation, qualify_inputs

PARENT = "b676a640c76193a0e241d2517a64e37e156659b9"
CHILD = "eb15cd3dc0ab0404f8ad18589569e05a70a4d401"
HEAD = "c6768ffeb54071ea77b3c056b27f179967f77c44"
RAW_SHA = "6b57edb09de2a77f6dbec1fe4bb0b80c9aac845bbc7a001b3019f62e76570218"


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(body):
    return hashlib.sha256(body).hexdigest()


def project(path):
    with open(path, "rb") as source:
        assert hashlib.file_digest(source, "sha256").hexdigest() == RAW_SHA
    a = Archive(path)
    assert len(a.z.namelist()) == 7677 and a.z.testzip() is None
    clean = qualify_inputs(a, HEAD)
    result = {"schema": 1, "run": 41049570613, "artifact": 12975716252, "archive_sha256": RAW_SHA,
              "qa": HEAD, "rust": {r:a.record(r+".json") for r in "PC"}, "enrolled": a.record("enrolled.json"),
              "storage_mode":a.raw("storage-mode.txt").decode().strip(),
              "provider": a.record("native-guard/verified.json"), "clean": {}, "mechanism": {}}
    for (arm, state), entry in clean.items():
        result["clean"][f"{arm}/{state}"] = {k:entry[k] for k in ("typed_size","reader_sha256")}
        result["clean"][f"{arm}/{state}"]["archive_index"] = digest(a.raw(f"references/{arm}-{state}/archive-index.json.gz"))
    for arm in ARMS:
        base = "mechanism-"+arm
        installation(a,clean,base,arm,traced=True)
        result["mechanism"][arm] = {}
        for p in ("return-A","return-B","unchanged-B"):
            record=a.record(f"{base}/{p}/native-execs.json.gz")
            result["mechanism"][arm][p] = {
                "rustcs": sorted(r["crate"] for r in record["rustcs"]), "wild": record["wild"],
                "cargo": record["real_cargo"], "exec_sha": digest(a.raw(f"{base}/{p}/native-execs.json.gz")),
            }
    for stage in ("screen","confirm"):
        order=a.record(stage+"/plan.json")["orders"]
        independent=cohort(a,clean,stage)
        assert independent["over_two_and_smaller"]
        pairs=[]
        for i, roles in enumerate(order,1):
            visits={}
            for role in roles:
                base=f"{stage}/triplet-{i:02}-{role}"
                rows=a.record(base+"/installation.json")
                doses={}
                for p in PHASES:
                    prefix=base+"/"+p+"/"
                    clock=a.record(prefix+"cargo.json")
                    actual=json.loads(a.raw(prefix+"cargo.stdout").splitlines()[-1])
                    d={"wall_ns":clock["wall_ns"],"exit":clock["exit"],"success":actual["success"],
                       "stdout_sha": digest(a.raw(prefix+"cargo.stdout"))}
                    if p!="invalid":
                        row=rows[p]
                        d.update({k:row[k] for k in ("branch","dirty","executable","expr","packed_objects","allocated")})
                        d["du"]=[int(line.split()[0]) for line in a.record(prefix+"allocated.json")["du"]]
                        d["archive_index"]=digest(a.raw(prefix+"archive-index.json.gz"))
                        d["archive_members_differing_from_clean"] = sorted({n for names in row["metadata_differences"].values() for n in names})
                    doses[p]=d
                visits[role]=doses
            pairs.append(visits)
        result[stage]={"orders": order,"pairs":pairs}
    return result


if __name__ == "__main__":
    source, dest = sys.argv[1:]
    with Path(dest).open("xb") as f:
        f.write(gzip.compress(encoded(project(source)), compresslevel=9, mtime=0))
