"""Independently validate real Ruff edits, test executables, Cargo clocks and allocated storage."""
import argparse
import gzip
import hashlib
import io
import itertools
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import zipfile

P="444c0273a2e2bc0b161e988d43c882349bc2d7a6"
C="82911b516fb35608fd70ada4deb6f8429277f410"
A="ccba26cc3af909b7f19060f48f53daeab5070f9d"
B="d8dac4cb576bd091a8b6cdc60a65c770ea75a96e"
QUAL="f68ab333d084321a2744e86378eb7d4a24c05734645c8dd73f50c3ce275020d1"
CMD=["cargo","+ohm","test","-p","ty_vendored","--lib","--features","deflate","--no-run","--locked","--offline","-j4","--message-format=json"]
TESTS=["tests::typeshed_vfs_consistent_with_vendored_stubs","tests::typeshed_zip_created_at_build_time"]
STUBS=["source_commit.txt","stdlib/typing.pyi","stdlib/typing_extensions.pyi"]
PHASES=("edit","repeat-1","repeat-2")


def h(b):return hashlib.sha256(b).hexdigest()
def rec(z,n):return json.loads(z.read(n))
def raw(z,n):return gzip.decompress(z.read(n))


def auth(path,v):
    with path.open("rb") as f:assert hashlib.file_digest(f,"sha256").hexdigest()==v
    z=zipfile.ZipFile(path)
    assert z.testzip() is None and len(z.namelist())==len(set(z.namelist()))
    return z


def typed(z,prefix):
    stream=raw(z,prefix+"stdout.gz")
    ms=list(map(json.loads,stream.splitlines()))
    assert ms[-1]=={"reason":"build-finished","success":True}
    units=[m for m in ms if m["reason"]=="compiler-artifact"]
    root,=[m for m in units if m["target"]["name"]=="ty_vendored" and m["profile"]["test"] and m["executable"]]
    assert "deflate" in root["features"]
    libs=[m for m in units if m["target"]["name"]=="zlib_rs" and m["target"]["kind"]==["lib"]]
    assert len(libs)==2 and all(m["package_id"].endswith("#zlib-rs@0.5.5") for m in libs)
    roster=sorted(json.dumps([m[k] for k in ("package_id","target","features","profile")],sort_keys=True,separators=(",",":")) for m in units)
    return stream,{"roster":h(json.dumps(roster).encode()),"dirty":sorted(m["target"]["name"] for m in units if not m["fresh"])},[v["fresh"] for v in libs]


def tests(z,prefix):
    listing=sorted(raw(z,prefix+"test-list.gz").decode().splitlines())
    assert listing==[t+": test" for t in TESTS]
    suite=raw(z,prefix+"test-suite.gz").decode().splitlines()
    assert sorted(t for t in suite if t.startswith("test ") and " ... " in t)==["test "+t+" ... ok" for t in TESTS]
    assert any("2 passed; 0 failed; 0 ignored" in l for l in suite)


def disk(z,prefix):
    blob=raw(z,prefix+"disk-inodes.json.gz");s=rec(z,prefix+"disk.json")
    assert h(blob)==s["source_sha256"]
    ids={};paths=set()
    for path,dev,ino,size,blocks,mode,nlink in json.loads(blob):
        assert path not in paths and path.split("/")[0] in ("target","shared") and nlink>=1
        paths.add(path);props=(size,blocks,mode)
        assert ids.setdefault((dev,ino),props)==props
    alloc=sum(v[1]*512 for v in ids.values())
    assert len(paths)==s["entries"] and {"inodes":len(ids),"bytes":sum(v[0] for v in ids.values()),"allocated_bytes":alloc}==s["all"]
    return alloc


def results(z,mode,refs,traces,expected_harness=None):
    top="crc-clock-"+mode+"/"
    reg=rec(z,top+"registered.json");report=rec(z,top+"result.json")
    assert reg["argv"]==CMD and reg["eligible"]["rust"]==[P,C] and reg["eligible"]["ruff"]==[A,B] and reg["eligible"]["cargo"]=="735e1528ed741015c57676dccf05dbdc0ff7bed1" and reg["eligible"]["structural"] is True
    assert reg["harness"]==report["harness"] and (expected_harness is None or reg["harness"]==expected_harness)
    alloc=int(h(("crc typeshed on exact 735e1528, inclusive complete-compile 12 v2 / "+P+C+A+B).encode()),16)%924
    subset=list(itertools.combinations(range(12),6))[alloc]
    order=["PC","CP"] if mode=="screen" else ["PC" if i in subset else "CP" for i in range(12)]
    assert reg["assignment"]==alloc and reg["order"]==report["order"]==order
    rows={k:[] for k in (*PHASES,"edit+repeat-1")}; dis=[]; cpu={step:[] for step in PHASES}; clocks=[]; last=-1
    for i,roles in enumerate(order,1):
        pair={};ds={};cp={}
        for role in roles:
            base=top+f"pair-{i:02}/{role}/"; times={}
            for step in ("cold",*PHASES):
                p=base+step+"/";v=rec(z,p+"result.json");c=v["cargo"]
                assert v["phase"]==step and v["product"]==refs[role,A if step=="cold" else B]
                stream,sig,fresh=typed(z,p)
                assert sig==traces[role,step]==v["signature"] and c["streams"]=={"stdout":h(stream),"stderr":h(raw(z,p+"stderr.gz"))}
                assert len(v["zlib_dep_sha"])==2
                for n,sha in enumerate(v["zlib_dep_sha"]):
                    dep=raw(z,p+f"zlib-{n}.dep.gz")
                    assert h(dep)==sha and b"zlib-rs-0.5.5/src/" in dep
                    assert (b"ohm-untracked-relink-inputs" in dep)==(role=="P") and (role=="P" or b"/dev/null/ohm-recheck-dependent-links" in dep)
                assert len(fresh)==2
                tests(z,p)
                if step!="cold":
                    real,user,sys=map(float,re.fullmatch(r"\s*([.0-9]+) real\s+([.0-9]+) user\s+([.0-9]+) sys",z.read(p+"time.txt").splitlines()[0].decode()).groups())
                    assert last<c["start_ns"] and 0<c["ns"]==c["stop_ns"]-c["start_ns"] and abs(c["ns"]/1e9-real)<.05 and (user,sys)==(c["user"],c["system"])
                    last=c["stop_ns"];times[step]=c["ns"];cp[role,step]=[user,sys]
                    clocks.append({'pair':i,'role':role,'step':step,'start_ns':c['start_ns'],'stop_ns':c['stop_ns'],
                         'ns':c['ns'],'user':user,'system':sys,'stdout':c['streams']['stdout'],'stderr':c['streams']['stderr'],
                         'time_l':h(z.read(p+'time.txt')),'program':v['product']['raw'],'zip':v['product']['zip_sha256']})
            times["edit+repeat-1"]=times["edit"]+times["repeat-1"];pair[role]=times
            ds[role]=disk(z,base+"steady-disk/")
        for step in rows:rows[step].append([pair["P"][step],pair["C"][step]])
        dis.append([ds["P"],ds["C"]])
        for stage in PHASES:cpu[stage].append([cp["P",stage],cp["C",stage]])
    if mode=="confirmation":
        for role in "PC":
            root=top+"terminal-clean/"+role+"/"
            v=rec(z,root+"verified.json");assert v["product"]==refs[role,B] and v["rev"]==B and len(v["root_link_argv"])==1
            tests(z,root)
    table={}
    for phase,values in rows.items():
        ratios=[a/b for a,b in values]
        s={"seconds":[statistics.median(c)/1e9 for c in zip(*values)],"raw_ns":values,"paired":statistics.median(ratios),"min":min(ratios),"max":max(ratios)}
        if phase in PHASES:
            reported=report["wall"][phase]
            assert values==reported["raw_PC"] and s["paired"]==reported["median_ratio"]
        if len(order)==12:
            s["ci"]=[sorted(ratios)[2],sorted(ratios)[-3]]
            log=[math.log(x/2) for x in ratios]; signed=[x*(1 if o=="PC" else -1) for x,o in zip(log,order)]
            s["p_2x"]=sum(sum(x if i in assigned else -x for i,x in enumerate(signed))>=sum(log)-1.2e-11 for assigned in itertools.combinations(range(12),6))/924
            if phase in PHASES:assert s["ci"]==reported["median_CI_96.14pct"] and s["p_2x"]==reported["one_sided_balanced_sharp_2x_p"]
        table[phase]=s
    primary=table["repeat-1"]
    passed=primary["min"]>2 if mode=="screen" else primary["ci"][0]>2 and primary["p_2x"]<=.05
    assert passed==report["passed"]
    return {"phases":table,"disk":dis,"passed":passed,"valid":report["valid"],"order":order,"cpu":cpu,"raw_clocks":clocks},reg["harness"]


