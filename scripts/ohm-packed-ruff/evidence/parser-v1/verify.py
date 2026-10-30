"""Recompute disk costs and paired time ratios without a compiler or a runner account."""

import argparse
import gzip
import itertools
import json
from pathlib import Path
import random
import statistics
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from project import CHILD, HEAD, PARENT, RAW_SHA, digest, encoded, project

ARMS = ("Off", "Full", "Packed")
SWITCHES = ("first-B","return-A","return-B")
MIB = 2**20


def interval(xs):
    ordered=sorted(xs)
    return {"median":statistics.median(xs),"pointwise_96_14": [ordered[2],ordered[-3]]}


def verify(data):
    assert data["schema"]==1 and data["archive_sha256"]==RAW_SHA and data["qa"]==HEAD
    assert data["storage_mode"]=="runner-filesystem" and data["rust"]["P"]["commit"]==PARENT and data["rust"]["C"]["commit"]==CHILD
    p,c=(data["rust"][r] for r in "PC")
    assert p["files"].keys()==c["files"].keys() and len(p["files"])==63
    changed={n for n in p["files"] if p["files"][n]!=c["files"][n]}
    assert changed==set(data["enrolled"]["changes"]) and len(changed)==1 and next(iter(changed)).startswith("lib/librustc_driver-")
    guard=data["provider"]
    assert guard["first"]["result"]==17 and all(guard[k]["result"]==29 for k in ("change","repair","clean"))
    assert guard["truncated"]["error"] is True
    assert guard["first"]["executable_sha256"]!=guard["change"]["executable_sha256"]==guard["repair"]["executable_sha256"]==guard["clean"]["executable_sha256"]
    for arm in ARMS:
        for ph, row in data["mechanism"][arm].items():
            assert row["cargo"]==1 and row["wild"]==0 and row["rustcs"]==([] if ph=="unchanged-B" else ["ruff_python_ast","ruff_python_parser"])
    schedule=list(map(list,itertools.permutations(ARMS)))*2
    random.Random(0x28335020).shuffle(schedule)
    report={}
    for stage, expected in (("screen",[list(ARMS),list(reversed(ARMS))]),("confirm",schedule)):
        part=data[stage]
        assert part["orders"]==expected and len(part["pairs"])==len(expected)
        for arms in part["pairs"]:
            assert set(arms)==set(ARMS)
            for arm, rows in arms.items():
                for ph, row in rows.items():
                    assert type(row["wall_ns"]) is int and row["wall_ns"]>0
                    assert row["success"]==(ph!="invalid") and row["exit"]==(101 if ph=="invalid" else 0)
                    if ph=="invalid":
                        continue
                    state="B-as-A" if ph=="dirty-B-as-A" else "A" if ph in ("empty-A","return-A") else "B"
                    ref=data["clean"][arm+"/"+state]
                    assert row["expr"]==ref["typed_size"]==(56 if state=="B" else 64)
                    assert row["executable"]==ref["reader_sha256"] and set(row["archive_members_differing_from_clean"])<={"lib.rmeta"}
                    assert sum(row["du"])==row["allocated"] and row["allocated"]>0
                    if ph in (*SWITCHES,"unchanged-B"):
                        assert (row["packed_objects"]>0)==(arm=="Packed")
                    if ph.startswith("return-"):
                        assert row["dirty"]==["ruff_python_ast","ruff_python_parser"]
                    if ph=="unchanged-B":
                        assert not row["dirty"]
        for ph in SWITCHES:
            assert all(group["Full"][ph]["allocated"]>group["Packed"][ph]["allocated"] for group in part["pairs"])
        for ph in ("return-A","return-B"):
            ratios=[group["Off"][ph]["wall_ns"]/group["Packed"][ph]["wall_ns"] for group in part["pairs"]]
            assert sorted(ratios)[0 if stage=="screen" else 2]>2
        if stage=="screen":
            continue
        for label, phases in {**{p:(p,) for p in ("empty-A",*SWITCHES,"unchanged-B","dirty-B-as-A","restored-B")},
                              "first switch plus return":("first-B","return-A")}.items():
            samples=part["pairs"]
            times={r:[sum(g[r][ph]["wall_ns"] for ph in phases) for g in samples] for r in ARMS}
            result={"ms":{r:statistics.median(xs)/1e6 for r,xs in times.items()}}
            for l,r in (("Off","Packed"),("Full","Packed")):
                result[l+"_over_"+r]=interval([a/b for a,b in zip(times[l],times[r])])
            if len(phases)==1:
                ph=phases[0]
                sizes={r:[g[r][ph]["allocated"]/MIB for g in samples] for r in ARMS}
                result["MiB"]={r:statistics.median(xs) for r,xs in sizes.items()}
                for l,r in (("Full","Off"),("Packed","Off"),("Full","Packed")):
                    result[l+"_minus_"+r+"_MiB"]=interval([a-b for a,b in zip(sizes[l],sizes[r])])
            report[label]=result
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--raw",type=Path,help="Rebuild observations from the 30 MB GitHub Actions ZIP")
    args=parser.parse_args()
    raw=gzip.decompress((HERE/"observations.json.gz").read_bytes())
    data=json.loads(raw)
    assert encoded(data)==raw
    if args.raw:
        assert encoded(project(args.raw))==raw
    print(json.dumps(verify(data),indent=2,sort_keys=True))
