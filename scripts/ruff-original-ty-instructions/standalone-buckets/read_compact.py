"""Recompute results from the enrolled raw control streams without large native downloads."""
import argparse
import hashlib
import json
import re
import resource
import statistics
import subprocess
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from compact import hash_bytes, selected
from confirm import ORDERS, OLD_ELF, NEW_ELF, must, series
from member_names import native_identity

LAUNCH=["cargo","+ohm","build","-p","ty_ide","--lib","--locked","--offline","-j4","--message-format=json"]
OLD_OUTPUT=b"scripts=1\nscripts=1\nvendored-paths=3\n"
NEW_OUTPUT=b"scripts=0\nscripts=1\nvendored-paths=3\n"


def read(path,assets,summary):
    source=json.loads(assets.read_bytes())
    claims=json.loads(summary.read_bytes())
    data={};index=None
    limit=128*2**20
    with tempfile.TemporaryFile() as target:
        subprocess.run(["zstd","-qdc",path],stdout=target,check=True,preexec_fn=lambda:resource.setrlimit(resource.RLIMIT_FSIZE,(limit,limit)))
        target.seek(0)
        with tarfile.open(fileobj=target,mode="r|") as t:
            for h in t:
                must(h.isfile() and 0<=h.size<=16*2**20,"unexpected member")
                body=t.extractfile(h).read()
                if h.name=="index.json":
                    must(index is None,"duplicate index");index=json.loads(body)
                else:
                    sha=hash_bytes(body);must(h.name=="b/"+sha and sha not in data,"bad original control");data[sha]=body
    must(set(index)==set(map(str,range(6))) and set(data)=={h for row in index.values() for h in row["files"].values()},"control archive coverage")
    ratios=[];boots=set();native=0;full_pairs=[];totals={"primary":[],"cold":[],"noop":[],"allocated_unique_bytes":[],"logical_unique_bytes":[],"physical_files":[]}
    for slot,order in enumerate(ORDERS):
        row=index[str(slot)];files=row["files"]
        must(all(selected(k) for k in files),"unregistered attachment")
        raw=lambda n:data[files[n]]
        j=lambda n:json.loads(raw(n))
        public=j("public-transitions.json")
        reg=j("registration.json");time=j("sequence.json");factory=j("factory-consumed.json")["binding"]
        declared=claims["pairs"][slot]
        asset,=[x for x in source["assets"] if x["name"].endswith(f"-{slot}")]
        must(row["original_sha256"]==asset["digest"]=="sha256:"+declared["original"]["sha256"],"unbound original")
        must(reg["command"]==LAUNCH and reg["slot"]==slot and reg["order"]==order and reg["factory"]==factory,"different toolchain, entry or slot")
        boot=str(uuid.UUID(reg["kernel_boot"]));must(boot not in boots and boot==declared["boot"],"duplicate boot");boots.add(boot)
        must("".join(x["role"] for x in time)==order and time[0]["begin_ns"]<time[0]["end_ns"]<=time[1]["begin_ns"]<time[1]["end_ns"],"order was not executed")
        must(public["equal_stable_identities_and_edit_key_sets"],"changed public metadata transition")
        terminal=j("terminal.json");cost={};resources={}
        for role in ("P","C"):
            g=j(role+"/unit-graph.json");root,=g["roots"]
            must(len(g["units"])==283 and g["units"][root]["target"]["name"]=="ty_ide","resolution")
            tool=j(role+"/tools.json");must(tool["driver"]["sha256"]==factory["driver"][role],"source role")
            phases={};snap={};counts={};roster=None
            for phase in ("old","edit","unchanged","repair","observed-old","observed-edit","observed-unchanged","independent-clean"):
                p=role+"/"+phase+"/";result=j(p+"result.json")
                events=[json.loads(x) for x in raw(p+"stdout.jsonl").splitlines()]
                artifacts=[x for x in events if x["reason"]=="compiler-artifact"]
                keys=sorted((a["package_id"],a["target"]["name"],a["target"]["kind"],a["features"],json.dumps(a["profile"],sort_keys=True)) for a in artifacts)
                must(len(keys)==259 and (roster is None or roster==keys) and events[-1]=={"reason":"build-finished","success":True},"cargo roster")
                roster=keys;dirty=sorted(a["target"]["name"] for a in artifacts if not a["fresh"]);must(dirty==result["dirty"],"status mismatch")
                if phase in ("old","independent-clean"):must(len(dirty)==259,"partially warm cold control")
                if phase in ("edit","observed-edit"):must(dirty==["ty_ide","ty_project"],"different edit")
                if "unchanged"in phase:must(not dirty,"unexpected unchanged work")
                if phase.startswith("observed"):
                    seen=[]
                    ids=tool["physical"]
                    for event in raw(p+"tasks/epochs.tsv").splitlines():
                        fields=event.split()
                        if fields[0]!=b"I" or fields[5]!=b"exec":continue
                        argv=raw(p+f"tasks/{int(fields[1]):05}.nul").rstrip(b"\0").split(b"\0")
                        must(argv[0]==fields[2],"pid binding")
                        ident=tuple(map(int,argv[1:3]))
                        if ident==tuple(ids["rustc"][name] for name in ("dev","ino")) and b"--crate-name" in argv:
                            seen.append("rustc:"+argv[argv.index(b"--crate-name")+1].decode())
                        if ident==tuple(ids["wild"][name] for name in ("dev","ino")):seen.append("wild")
                    must(seen==result["observed"]["real_execs"],"physical child roster")
                    if phase=="observed-edit":must(sorted(seen)==["rustc:ty_ide","rustc:ty_project"],"wrong native compilation")
                    if phase=="observed-unchanged":must(not seen,"unchanged compiler/link")
                else:
                    hw=j(p+"hardware.json");must(hw["status"]==0 and 0<hw["running"]==hw["enabled"] and 0<hw["instructions"]==result["instructions"],"invalid counter")
                    counts[phase]=hw["instructions"]
                if phase in ("old","edit","repair","independent-clean"):
                    orig=phase=="old";expected=OLD_OUTPUT if orig else NEW_OUTPUT
                    must(raw(p+"oracle/stdout")==expected==result["oracle"]["stdout"].encode() and result["oracle"]["elf"]["sha256"]==(OLD_ELF if orig else NEW_ELF),"native output")
                if p+"native.json" in files:snap[phase]=j(p+"native.json")
            invalid=[json.loads(x) for x in raw(role+"/invalid/stdout.jsonl").splitlines()]
            must(invalid[-1]=={"reason":"build-finished","success":False} and any((a.get("message",{}).get("code") or {}).get("code")=="E0308" for a in invalid if a["reason"]=="compiler-message"),"bad invalid verdict")
            must(b"E0599"in raw(role+"/old/oracle/old-interface.stderr") and raw(role+"/old-client-on-new.stdout")==OLD_OUTPUT,"stale or missing saved interface control")
            for x,y,proof in (("old","edit","retention"),("observed-old","observed-edit","observed-retention")):
                a=snap[x]["objects"];b=snap[y]["objects"]
                must(a.keys()==b.keys() and len(a)==171,"changed incremental inventory")
                for k in a:must(a[k]["sha256"]==b[k]["sha256"] and a[k]["bytes"]==b[k]["bytes"],"changed native body")
                retained=sorted(k for k in a if all(a[k][i]==b[k][i] for i in ("dev","ino","mtime_ns")))
                must(j(role+"/"+proof+".json")=={"retained":retained,"regenerated":sorted(set(a)-set(retained))},"wrong physical donor")
                if x=="old":native_count=len(retained)
            for crate,n,symbols in (("ty_ide",171,4199),("ty_project",245,7276)):
                a=snap["edit"]["members"][crate]["bijection"];b=snap["independent-clean"]["members"][crate]["bijection"]
                must(len(a["members"])==n and a["symbols"]==symbols and native_identity(a)==native_identity(b),"wrong native members, order, or lookup index")
                native+=n
            cost[role]=counts["edit"];qualified=j(role+"/qualified.json")
            must(qualified==next(v for v in terminal["roles"] if v["role"]==role) and native_count==qualified["retained"],"closed process evidence")
            resources[role]={"primary":counts["edit"],"cold":counts["old"],"noop":counts["unchanged"]}|j(role+"/footprint.json")
        ratio=cost["P"]/cost["C"];ratios.append(ratio);must(ratio==declared["speedup"],"wrong pair")
        full_pairs.append([cost["P"],cost["C"]])
        for k in totals:totals[k].append((resources["P"][k],resources["C"][k]))
    must(statistics.median(ratios)==claims["median_speedup"] and [min(ratios),max(ratios)]==claims["speedup_interval"],"incorrect median or interval")
    must({k:series(v) for k,v in totals.items()}==claims["resources"],"wrong storage or control costs")
    must(claims["exact_two_sided_sign_p"]==.03125 and all(r>1 for r in ratios) and claims["coverage_of_median_interval"]==.96875,"sign inference")
    return {"boots":len(boots),"whole_edit_pairs":full_pairs,"warm_fresh_named_native_members":native,"source_control_bytes":sum(map(len,data.values())),"unique_controls":len(data),"median_speedup":statistics.median(ratios)}


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("archive",type=Path);p.add_argument("--assets",type=Path,required=True);p.add_argument("--summary",type=Path,required=True)
    a=p.parse_args();print(json.dumps(read(a.archive,a.assets,a.summary),indent=2,sort_keys=True))
