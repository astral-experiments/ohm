"""Derive paired clocks, test outcomes and disk allocation from the actual run streams."""
import argparse
from collections import defaultdict
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import statistics
import zipfile

P="2035696c5316079f5b2e4373aee834839aac97e9"
C="444c0273a2e2bc0b161e988d43c882349bc2d7a6"
A="2d253467b5153f82d26c51d49eb8d4156f1768bf"
B="aa9a1ff88aa83b3f01360ef5b3cb04b2be187206"
PRIOR="795507e5d0bf58e49b4cbb4050fa65e1c62097ec69502b8e7655f9686b427121"
FIX="pull_diagnostics::closing_deleted_file_clears_diagnostics_before_watcher_notification"
CTRL="pull_diagnostics::on_did_open"
PHASES=("edit","repeat-1","repeat-2")


def digest(b):
    return hashlib.sha256(b).hexdigest()


def raw(z,key):
    return gzip.decompress(z.read(key))


def record(z,key):
    return json.loads(z.read(key))


def authenticate(path,expected):
    with path.open("rb") as f:
        assert hashlib.file_digest(f,"sha256").hexdigest()==expected
    z=zipfile.ZipFile(path)
    assert len(z.namelist())==len(set(z.namelist())) and z.testzip() is None
    return z


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


def artifact_signature(source):
    stream = list(map(json.loads, source.splitlines()))
    assert stream[-1] == {"reason": "build-finished", "success": True}
    units = [r for r in stream if r["reason"] == "compiler-artifact"]
    assert len(units) == 304
    unique = sorted(json.dumps([u[k] for k in ("package_id", "target", "features", "profile")],
                               sort_keys=True, separators=(",", ":")) for u in units)
    assert len(set(unique)) == len(units)
    tests = [u for u in units if u["profile"]["test"] and u["executable"] and
             u["target"]["src_path"].endswith("/crates/ty_server/tests/e2e/main.rs")]
    libs = [u for u in units if u["target"]["name"] == "zmij" and u["target"]["kind"] == ["lib"]]
    assert len(tests) == len(libs) == 1 and tests[0]["target"]["name"] == "e2e"
    return {"units": digest(json.dumps(unique).encode()), "dirty": sorted(u["target"]["name"] for u in units if not u["fresh"])}


def subject(signature):
    return [n for n in signature["dirty"] if n in ("e2e", "ty_server", "zmij")]


def refs(z):
    images={}
    signs={}
    for role in "PC":
        top=f"ty-comparison/{role}/focus/"
        for name in ("old","new"):
            p=record(z,top+"empty-"+name+"/clean/verified.json")["e2e"]
            entire=raw(z,"clean-ty-executables/"+p["raw"]+".macho.gz")
            assert digest(entire)==p["raw"] and entire[:8]==bytes.fromhex("cffaedfe0c000001")
            assert len(p["inventory"])==(194 if name=="old" else 195)
            images[role,name]=p
        for step in ("cold",*PHASES):
            q=record(z,top+"visit/"+step+"/verified.json")
            assert q["e2e"]==images[role,"old" if step=="cold" else "new"]
            prefix=top+"visit/"+step+"/"
            blob=raw(z,prefix+"stdout.gz")
            events=raw(z,prefix+"exec.json.gz")
            assert q["streams"]["stdout"]==digest(blob) and q["streams"]["native_events"]==digest(events)
            signs[role,step]=artifact_signature(blob)
            assert signs[role,step]["dirty"]==sorted(q["dirty"])
            physical=json.loads(events)
            actual=[(e["argv"][e["argv"].index("--crate-name")+1],any("link-only" in o for o in e["argv"])) for e in physical
                    if e["path"].endswith("/native/bin/rustc") and "--crate-name" in e["argv"] and not any(x.startswith("--print") for x in e["argv"])]
            links=[e for e in physical if e["path"].endswith("/XcodeDefault.xctoolchain/usr/bin/ld")]
            assert sorted(n for n,relay in actual if not relay)==q["native"]["full"] and sorted(n for n,relay in actual if relay)==q["native"]["link_only"]
            assert len(links)==len(q["native"]["linkers"]) and all(x["stock"] for x in q["native"]["linkers"])
            if step.startswith("repeat"):
                assert sorted(n for n,relay in actual)==(["e2e","zmij"] if role=="P" else []) and len(links)==int(role=="P")
    return images,signs


def sample(z,base,image,reference,step):
    row=record(z,base+"result.json")
    assert row["product"]==image and row["endpoint"]==step
    t=row["cargo"]
    out=raw(z,base+"stdout.gz");err=raw(z,base+"stderr.gz")
    assert t["streams"]=={"stdout":digest(out),"stderr":digest(err)}
    sig=artifact_signature(out)
    assert row["signature"]==sig and sig["units"]==reference["units"] and subject(sig)==subject(reference)
    checks=record(z,base+"validation.json")
    assert checks=={"expected":image,"observed":image,"reference_signature":reference,"actual_signature":sig,
                    "whole_image_equal":True,"roster_equal":True,"subject_equal":True}
    names=sorted(x.removesuffix(": test") for x in raw(z,base+"list-stdout.gz").decode().splitlines())
    assert names==image["inventory"] and (FIX in names)==(step!="cold")
    assert record(z,base+"list-exit.json")==0 and CTRL in names
    for test in [CTRL]+([FIX] if step!="cold" else []):
        label=test.split("::")[-1]
        suite=raw(z,base+label+"-stdout.gz")
        assert ("test "+test+" ... ok").encode() in suite and b"1 passed; 0 failed" in suite and record(z,base+label+"-exit.json")==0
    if step=="cold":
        assert "ns" not in t
        return None
    real,user,system=map(float,re.fullmatch(r"\s*([.0-9]+) real\s+([.0-9]+) user\s+([.0-9]+) sys",z.read(base+"time.txt").splitlines()[0].decode()).groups())
    assert 0<t["ns"]==t["stop_ns"]-t["start_ns"] and (user,system)==(t["user"],t["system"]) and abs(real-t["ns"]/1e9)<0.05
    return t


def analyze(z,stage,images,signatures):
    prefix="ty-clock-screen/" if stage=="screen" else ""
    reg=record(z,prefix+"registration.json"); end=record(z,prefix+"result.json")
    schedule=reg["order"]
    assert reg["sources"]==[P,C,A,B] and reg["primary"]=="repeat-1" and reg["unscored_prior"]==PRIOR
    assert end["harness"]==reg["harness"] and end["order"]==schedule and end["source"]==[P,C]
    alloc=int(digest(("ty_server e2e/native v1/"+PRIOR).encode()),16)%924
    subset=list(itertools.combinations(range(12),6))[alloc]
    assert reg["assignment"]==alloc and schedule==(["PC","CP"] if stage=="screen" else ["PC" if i in subset else "CP" for i in range(12)])
    assert reg["work_eligibility"]=="fixed complete unit graph and dirty states for e2e, ty_server, zmij; retain and charge unrelated compiler work in either arm"
    times=defaultdict(list);disks=defaultdict(list);last=-1
    incidental=[]
    for i,roles in enumerate(schedule,1):
        tt={};dd={}
        for role in roles:
            base=prefix+f"pair-{i:02}/{role}/"; tt[role]={}
            for step in ("cold",*PHASES):
                record_time=sample(z,base+step+"/",images[role,"old" if step=="cold" else "new"],signatures[role,step],step)
                actual=record(z,base+step+"/result.json")["signature"]["dirty"]
                baseline=signatures[role,step]["dirty"]
                if actual!=baseline:
                    from collections import Counter
                    inc=Counter(actual)-Counter(baseline); skipped=Counter(baseline)-Counter(actual)
                    incidental.append({"pair":i,"role":role,"step":step,"added":sorted(inc.elements()),"removed":sorted(skipped.elements())})
                if record_time:
                    assert last<record_time["start_ns"]
                    last=record_time["stop_ns"]
                    tt[role][step]=record_time["ns"]
            tt[role]["edit+repeat-1"]=tt[role]["edit"]+tt[role]["repeat-1"]
            dd[role]=disk(z,base+"steady-disk/")
        for step in tt["P"]:
            times[step].append([tt["P"][step],tt["C"][step]])
        for key in dd["P"]:
            disks[key].append([dd["P"][key],dd["C"][key]])
    if stage=="confirmation":
        for role in "PC":
            anchor=record(z,"terminal-clean/"+role+"/verified.json")
            assert anchor["e2e"]==images[role,"new"] and anchor["e2e_links"]==1 and len(anchor["binary_roster"])==1
    table={}
    for step,rows in times.items():
        ratios=[a/b for a,b in rows]
        table[step]={"median_seconds":[statistics.median(side)/1e9 for side in zip(*rows)],"paired_median":statistics.median(ratios),"ratios":ratios}
        if step in PHASES:
            result=end["elapsed"][step]
            assert result["median_ratio"]==statistics.median(ratios) and result["raw_PC"]==rows
        if len(rows)==12:
            ci=[sorted(ratios)[2],sorted(ratios)[-3]]
            signed=[math.log(r/2)*(1 if order=="PC" else -1) for r,order in zip(ratios,schedule)]
            obs=sum(math.log(r/2) for r in ratios)/12
            p=sum(sum(x if i in allocation else -x for i,x in enumerate(signed))/12>=obs-1e-12 for allocation in itertools.combinations(range(12),6))/924
            table[step].update(interval=ci,sharp_p=p)
            if step in PHASES:
                assert ci==result["median_CI_96.14pct"] and p==result["one_sided_balanced_sharp_2x_p"]
    primary=table["repeat-1"]
    accepted=(min(primary["ratios"])>2 if stage=="screen" else primary["interval"][0]>2 and primary["sharp_p"]<=.05)
    assert accepted==end["passed"]
    return {"stage":stage,"paired":table,"disk":dict(disks),"passed":accepted,"order":schedule,"incidental":incidental}


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("pilot",type=Path);p.add_argument("pilot_sha");p.add_argument("out",type=Path)
    p.add_argument("--confirmation",type=Path);p.add_argument("--confirmation-sha")
    a=p.parse_args()
    with authenticate(a.pilot,a.pilot_sha) as z:
        im,sig=refs(z);table={"screen":analyze(z,"screen",im,sig)}
    if a.confirmation:
        assert table["screen"]["passed"]
        with authenticate(a.confirmation,a.confirmation_sha) as z:
            table["confirmation"]=analyze(z,"confirmation",im,sig)
    with a.out.open("x") as out:
        json.dump(table,out,indent=2);out.write("\n")
    for stage,data in table.items():
        print(stage,data["passed"],{k:[v["median_seconds"],v["paired_median"]] for k,v in data["paired"].items()})
        print("allocated MiB per role:",[statistics.median(v)/2**20 for v in zip(*data["disk"]["allocated"])])
