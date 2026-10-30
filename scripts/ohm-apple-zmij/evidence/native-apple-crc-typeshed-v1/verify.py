"""Independently validate real Ruff edits, test executables, Cargo clocks and allocated storage."""
import argparse
from contextlib import contextmanager
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
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from packet import Packet

P="444c0273a2e2bc0b161e988d43c882349bc2d7a6"
C="82911b516fb35608fd70ada4deb6f8429277f410"
A="ccba26cc3af909b7f19060f48f53daeab5070f9d"
B="d8dac4cb576bd091a8b6cdc60a65c770ea75a96e"
QUAL="f68ab333d084321a2744e86378eb7d4a24c05734645c8dd73f50c3ce275020d1"
CMD=["cargo","+ohm","test","-p","ty_vendored","--lib","--features","deflate","--no-run","--locked","--offline","-j4","--message-format=json"]
TESTS=["tests::typeshed_vfs_consistent_with_vendored_stubs","tests::typeshed_zip_created_at_build_time"]
STUBS=["source_commit.txt","stdlib/typing.pyi","stdlib/typing_extensions.pyi"]
BLOBS={
    A: ["49e328911d6c629cb156d2787672ca2a50d6a14b","4658b51127f2e98ce7961fdf71ac538f89770c16","188dad756d348156ac4e27f5314bb30163f83537"],
    B: ["c68a63382cfaff6bb53d6f5f82ba55c2eb868238","8259a612e8bddfca52456b6470c79ecdca4e4934","4667538cb91df1bafc3e0e83f65670f90e150466"],
}
PHASES=("edit","repeat-1","repeat-2")


def h(b):return hashlib.sha256(b).hexdigest()
def rec(z,n):return json.loads(z.read(n))
def raw(z,n):return z.read(n) if isinstance(z, Packet) else gzip.decompress(z.read(n))


@contextmanager
def auth(path,v):
    if path.suffix==".xz":
        yield Packet(path,v)
        return
    with path.open("rb") as f:assert hashlib.file_digest(f,"sha256").hexdigest()==v
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None and len(z.namelist())==len(set(z.namelist()))
        yield z


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


def references(z,ruff):
    refs={};traces={}; held={}
    for rev in (A,B):
        for role in "PC":
            prefix=f"crc-clock-before/{role}/clean-"+("old" if rev==A else "new")+"/clean/"
            v=rec(z,prefix+"verified.json"); p=v["product"]
            assert v["rev"]==rev and v["command"]==CMD and v["code"]==0 and p["tests"]==TESTS
            exe=raw(z,"crc-programs/"+p["raw"]+".gz"); archive=raw(z,"crc-zips/"+p["zip_sha256"]+".gz")
            assert h(exe)==p["raw"] and exe[:8]==bytes.fromhex("cffaedfe0c000001") and h(archive)==p["zip_sha256"] and archive in exe
            with zipfile.ZipFile(io.BytesIO(archive)) as corpus:
                assert len(corpus.infolist())==len(set(corpus.namelist()))==819 and corpus.testzip() is None
                for name,blob in zip(STUBS,BLOBS[rev],strict=True):
                    data=corpus.read(name)
                    assert hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()==blob
                    assert p["inputs"][name]==h(data) and corpus.getinfo(name).compress_type==zipfile.ZIP_DEFLATED
                    if ruff:
                        assert data==subprocess.check_output(["git","show",rev+":crates/ty_vendored/vendor/typeshed/"+name],cwd=ruff)
            refs[role,rev]=p;tests(z,prefix)
    for role in "PC":
        assert refs[role,A]["raw"]!=refs[role,B]["raw"] and refs[role,A]["zip_sha256"]!=refs[role,B]["zip_sha256"]
        for step in ("cold",*PHASES,"invalid","repair"):
            prefix=f"crc-clock-before/{role}/visits/{step}/"
            v=rec(z,prefix+"verified.json");rev=A if step=="cold" else B
            assert v["command"]==CMD and v["rev"]==rev
            if step=="invalid":
                assert v["code"]==101 and v["product"] is None and not v["root_link_argv"]
                out=raw(z,prefix+"stdout.gz"); messages=list(map(json.loads,out.splitlines()))
                assert messages[-1]=={"reason":"build-finished","success":False}
                assert any(m.get("reason")=="compiler-message" and (m["message"].get("code") or {}).get("code")=="E0425"
                           and "ohm_crc_missing_rust_name" in m["message"]["message"] for m in messages)
                assert not any(m.get("reason")=="compiler-artifact" and m["target"]["name"]=="ty_vendored" and m.get("executable") for m in messages)
            else:
                assert v["code"]==0 and v["product"]==refs[role,rev]
                out,sig,_=typed(z,prefix);traces[role,step]=sig
                tests(z,prefix)
            data=raw(z,prefix+"exec.json.gz")
            assert v["streams"]["streams"]=={"stdout":h(out),"stderr":h(raw(z,prefix+"stderr.gz")),"native_events":h(data)}
            cmds=json.loads(data)
            cc=[m["argv"][m["argv"].index("--crate-name")+1] for m in cmds if m["path"].endswith("/bin/rustc") and "--crate-name" in m["argv"] and m["argv"][m["argv"].index("--crate-name")+1]!="___"]
            ld=[m["argv"] for m in cmds if m["path"].endswith("/XcodeDefault.xctoolchain/usr/bin/ld")]
            if step!="cold":
                build=sum("/ty_vendored/" in m["path"] and m["path"].endswith("/build_script_build") for m in cmds)
                assert build==int(role=="P" or not step.startswith("repeat"))
                if role=="P":
                    assert sorted(cc)==["build_script_build","ty_vendored","zlib_rs","zlib_rs"] and len(ld)==(1 if step=="invalid" else 2)
                elif step.startswith("repeat"):
                    assert not cc and not ld
                else:
                    assert cc==["ty_vendored"] and len(ld)==int(step!="invalid")
            held[role,step]=[len(cc),len(ld)]
    transport=rec(z,"crc-source-transport.json")
    assert (transport["parent"],transport["child"])==(P,C)
    runmake=rec(z,"run-make.json")
    assert runmake["source"]==C and h(z.read("run-make.log"))==runmake["log"] and b"1 passed; 0 failed" in z.read("run-make.log")
    for role in "PC":
        outputs={}
        for step,value in (("initial",17),("unchanged",17),("replace",29),("malformed",None),("missing",None),("repair",29),("empty-reference",29)):
            prefix=f"native-input/{role}/{step}/"
            v=rec(z,prefix+"verified.json"); out=raw(z,prefix+"stdout.gz")
            assert v["streams"]["streams"]=={"stdout":h(out),"stderr":h(raw(z,prefix+"stderr.gz")),"native_events":h(raw(z,prefix+"exec.json.gz"))}
            msgs=list(map(json.loads,out.splitlines()))
            assert msgs[-1]=={"reason":"build-finished","success":value is not None}
            assert v["cargo_exit"]==(101 if value is None else 0)
            if value is None:
                phrase="could not find native static library" if step=="missing" else "Unsupported archive identifier"
                assert any(m.get("reason")=="compiler-message" and phrase in m["message"]["message"] for m in msgs)
            else:
                assert v["value"]==value
                dep=raw(z,prefix+"bundled-library.dep.gz")
                assert h(dep)==v["bundled_dep_sha256"] and b"ohm-untracked-relink-inputs" in dep
                outputs[step]=v["executable"]
        assert outputs["initial"]==outputs["unchanged"]!=outputs["replace"]==outputs["repair"]==outputs["empty-reference"]
    return refs,traces,held


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
    top="crc-clock-screen/" if mode=="screen" else ""
    reg=rec(z,top+"registered.json");report=rec(z,top+"result.json")
    assert reg["argv"]==CMD and reg["eligible"]["rust"]==[P,C] and reg["eligible"]["ruff"]==[A,B] and reg["eligible"]["sha256"]==QUAL
    assert reg["harness"]==report["harness"] and (expected_harness is None or reg["harness"]==expected_harness)
    alloc=int(h(("crc typeshed n12 v1 / "+P+C+A+B).encode()),16)%924
    subset=list(itertools.combinations(range(12),6))[alloc]
    order=["PC","CP"] if mode=="screen" else ["PC" if i in subset else "CP" for i in range(12)]
    assert reg["assignment"]==alloc and reg["order"]==report["order"]==order
    rows={k:[] for k in (*PHASES,"edit+repeat-1")}; dis=[]; last=-1
    for i,roles in enumerate(order,1):
        pair={};ds={}
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
                if step!="cold":assert fresh==[role=="C"]*2
                tests(z,p)
                if step!="cold":
                    real,user,sys=map(float,re.fullmatch(r"\s*([.0-9]+) real\s+([.0-9]+) user\s+([.0-9]+) sys",z.read(p+"time.txt").splitlines()[0].decode()).groups())
                    assert last<c["start_ns"] and 0<c["ns"]==c["stop_ns"]-c["start_ns"] and abs(c["ns"]/1e9-real)<.05 and (user,sys)==(c["user"],c["system"])
                    last=c["stop_ns"];times[step]=c["ns"]
            times["edit+repeat-1"]=times["edit"]+times["repeat-1"];pair[role]=times
            ds[role]=disk(z,base+"steady-disk/")
        for step in rows:rows[step].append([pair["P"][step],pair["C"][step]])
        dis.append([ds["P"],ds["C"]])
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
    return {"phases":table,"disk":dis,"passed":passed,"order":order},reg["harness"]


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("pilot",type=Path);ap.add_argument("pilot_sha");ap.add_argument("output",type=Path)
    ap.add_argument("--ruff",type=Path);ap.add_argument("--confirm",type=Path);ap.add_argument("--confirm-sha")
    a=ap.parse_args()
    with auth(a.pilot,a.pilot_sha) as z:
        ref,traces,native=references(z,a.ruff);screen,harness=results(z,"screen",ref,traces)
    data={"screen":screen,"native":{r+"/"+k:v for (r,k),v in native.items()}}
    if a.confirm:
        assert screen["passed"]
        with auth(a.confirm,a.confirm_sha) as z:data["confirmation"]=results(z,"confirmation",ref,traces,harness)[0]
    with a.output.open("x") as f:json.dump(data,f,indent=2);f.write("\n")
    for group in ("screen","confirmation"):
        if group in data:print(group,[(k,v["seconds"],v["paired"]) for k,v in data[group]["phases"].items()])
