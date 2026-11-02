"""Independently reopen the eight private production wall pairs and their separate hardware visits."""
from fractions import Fraction
from math import comb
from pathlib import Path
from statistics import median
from zipfile import ZipFile
import argparse,hashlib,json,re,struct
HEAD="651801e3029fb35b79768116c57bfe3e8d36d57a"
REG="9746c053f4c503b1254da422fe3fe0d6c240b75801baec7fe987e0f1ae0436bf"
LOCK="58addfb4f602da689af4f716cded474d4642d0c5d7d6998f71a33a0afe968efd"
BOOT="0b7e6589-e885-4ab4-b223-6f3e66d0e99d"
RUN,JOB=41447094828,125282818505
ROLES=("S","F")
SOURCE={"S":"10d56274a98801b5ef8f80aab734e835749458e1","F":"ac67101cb973e35ce8ff044cc8014c2c76bab69e"}
ORDERS=("SF","FS","FS","SF","FS","SF","SF","FS")
KEYS=("wall","uv_client","sum_two","uv_configuration","whole")
LABELS=("uv_client","uv_configuration")
ARGS=["/tmp/uv-workflow-search/sdk/bin/cargo","check","-p","uv-client","--locked","--offline","-j8"]
def sha(path):
    with Path(path).open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def sd(raw):return hashlib.sha256(raw).hexdigest()
def score(rows):
    assert len(rows)==8 and all(len(p)==2 and all(type(x)is int and x>0 for x in p)for p in rows)
    speed=[Fraction(a,b)for a,b in rows];cost=[1/v for v in speed];wins=sum(v>2 for v in speed);non_ties=sum(v!=2 for v in speed)
    return {"raw":rows,"stock_median":median([a for a,b in rows]),"full_median":median([b for a,b in rows]),
        "paired_speedups":list(map(float,speed)),"paired_median_speedup":float(median(speed)),
        "paired_cost_ratios":list(map(float,cost)),"paired_median_cost_ratio":float(median(cost)),
        "both_hold_median_speedups":[float(median(v))for v in (speed[:4],speed[4:])],
        "order_statistic_99_21875_percent_speed_interval":[float(min(speed)),float(max(speed))],
        "strict_over_two":wins,"strict_primary_predicate":wins==8 and all(median(x)>2 for x in (speed[:4],speed[4:])),
        "exact_one_sided_sign_at_two":sum(comb(non_ties,i)for i in range(wins,non_ties+1))/2**non_ties if non_ties else 1}
def controls():
    assert score([[201,100]]*8)["strict_primary_predicate"] and score([[201,100]]*8)["exact_one_sided_sign_at_two"]==1/256
    assert not score([[200,100]]+[[201,100]]*7)["strict_primary_predicate"]
    for bad in ([[201,100]]*7,[[100,0]]*8,[[100,True]]*8):
        try:score(bad)
        except AssertionError:continue
        raise ValueError("invalid paired data accepted")
def execution_images(capture):
    import os
    rows=capture["events"]
    exits={row[0]:os.WEXITSTATUS(row[1])for row in rows if len(row)==2 and os.WIFEXITED(row[1])}
    images=[]
    for row in rows:
        if len(row)!=4:continue
        pid,status,event_pid,info=row
        assert status>>16==4 and os.WIFSTOPPED(status) and pid>0 and event_pid>0
        if info is not None:images.append((pid,info))
    assert exits[capture["root"]]==0
    return images,exits

def verify_all_compilers(z):
    traces=[]
    for role in ROLES:
        base=f"native-22958/opening-{role}/initial-kernel/"
        images,_=execution_images(json.loads(z.read(base+"kernel-events.json")))
        ids={tuple(v["file"])for _,v in images if v.get("argv")and Path(v["argv"][0]).name=="rustc"};assert len(ids)==1
        identity,=ids
        for visit in ["opening-"+role,*[str(i)+"-"+role for i in range(1,9)]]:
            pieces=("initial-kernel","noedit-A/kernel","noedit-B/kernel") if visit.startswith("opening") else ("kernel-B","threads")
            for kind in pieces:
                prefix=f"native-22958/{visit}/{kind}/"; raw=z.read(prefix+"kernel-events.json")
                observed,exits=execution_images(json.loads(raw));units=[]
                for pid,img in observed:
                    is_image=tuple(img.get("file")or ())==identity
                    is_compiler=bool(img.get("argv")and Path(img["argv"][0]).name=="rustc")
                    if not(is_image or is_compiler):continue
                    assert is_image and is_compiler and exits[pid]==0
                    args=img["argv"];assert "--crate-name" in args and any(a.startswith("--emit")for a in args)
                    units.append(args[args.index("--crate-name")+1])
                assert sorted(units)==([]if kind.startswith("noedit")else sorted(LABELS))
                if prefix+"rustc-executions.json" in z.namelist():
                    assert json.loads(z.read(prefix+"rustc-executions.json"))=={"total":len(units),"probes":[]}
                traces.append({"trace":prefix+"kernel-events.json","sha256":sd(raw),"units":sorted(units)})
    assert len(traces)==38 and sum(len(v["units"])for v in traces)==68
    return traces

def verify(archive,expected,index=ZipFile):
    controls();assert sha(archive)==expected
    with index(archive)as z:
        assert len(z.namelist())==len(set(z.namelist()));read=lambda n:json.loads(z.read(n));base="native-22958/"
        declared=read(base+"score.json");guards=read(base+"all-native-guards.json");boot=read("boot-attestation.json")
        assert declared["complete"]and declared["registered"]==guards["case"]==boot["registered"]==REG and declared["independent_histories"]==guards["independent"]==16
        assert not declared["original_exact_cold_gate_redeemed"]and declared["release_lock"]==boot["release_lock"]==LOCK
        assert declared["actual_signed_Cargo"]==ARGS and {k:v["commit"]for k,v in declared["sources"].items()}==SOURCE
        assert (boot["run"],boot["coordinator"],boot["boot"])==(RUN,HEAD,BOOT)and BOOT not in boot["excluded"]and len(set(boot["excluded"]))==17
        assert sd(("\n".join(sorted(boot["excluded"]))+"\n").encode())=="a4ae4d4e697c0194607498504549ca5b8ab8e2c05ec57145dab66abacdf546e7"
        assert ["".join(v)for v in guards["orders"]]==list(ORDERS) and guards["boot"]==BOOT
        for file,tag in (("calibration.json","inherited"),("per-rustc-calibration/calibration.json","threads"),("blocking-clock-pre/verified.json","blocking")):
            assert sd(z.read(file))==boot[tag]
        timer=read("blocking-clock-pre/verified.json");assert timer["eligible_blocking_calibration"]and timer["boot"]==BOOT and timer["affinity"]==boot["affinity"]
        cal=read("calibration.json");assert cal["unmultiplexed_calibration_clocks"]==28 and cal["ready"]["boot"]==BOOT
        current=read("latest-after-study.json");assert current["id"]==430629054 and current["tag_name"]=="ohm-1.99.0-22" and current["immutable"]
        intake=read("intake.json");assert set(intake["installed"])==set(ROLES)and intake["signed_cargo_sha256"]=="3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871"
        for role in ROLES:
            unit=intake["installed"][role];assert unit["source"]["commit"]==SOURCE[role]and unit["files"]==142
            root=base+"opening-"+role+"/";proof=read(root+"independent-cold.json");assert proof["all_guarded"]
            for state in ("A","B"):
                v=read(root+"noedit-"+state+"/verified.json");assert v["same_material"]and v["forms"]=={}
        nums={k:[]for k in KEYS};seen=set();cargo=[];chron=[]
        for i,ordering in enumerate(ORDERS,1):
            arms={};bounds=[]
            for role in ordering:
                name=base+str(i)+"-"+role+"/";seed=read(name+"seed.json")["sha256"];assert seed not in seen;seen.add(seed)
                proof=read(name+"native-before-score.json");assert proof["same_seed"]and proof["canonical"]
                kernel=read(name+"kernel-B/forms.json");req=read(name+"scoped-request.json")
                assert set(kernel)==set(LABELS) and all(len(v)==1 for v in kernel.values())and req["selectors"]=={k:v[0]for k,v in kernel.items()} and req["command"]==ARGS
                raw=read(name+"kernel-B/products.json");assert raw==read(name+"bare-B/products.json")and len(raw["workspace"])==39 and {k:len(v)for k,v in raw["externs"].items()}=={"uv_client":64,"uv_configuration":30}
                visits=read(name+"visit-order.json");assert [r[0]for r in visits]==["wall","whole","threads"] and all(a[1]<a[2]<=b[1]<b[2]for a,b in zip(visits,visits[1:]))
                bounds.append((visits[0][1],visits[-1][2],role));out={}
                for method in ("wall","whole","threads"):
                    where=name+method+"/";validate=read(where+"verified.json");assert validate["same_seed"]and validate["seed"]==seed and validate["boot"]==BOOT and validate["source"]=="362613dbf38f60fe285cdd6bca53641149a23c04"
                    material=z.read(where+"products.json");assert json.loads(material)==raw and sd(material)==validate["measured"]
                    w=read(where+"native/witness.json");assert w["codes"]["schema"]==[0,[]]and w["codes"]["client-negative"]==[1,["E0308"]]
                thread=read(name+"threads/per-rustc.json");assert set(thread["targets"])==set(LABELS)and thread["scope"]=="retired userspace instructions in the selected process and its threads"
                for k in LABELS:
                    row=thread["targets"][k];n,enabled,running,event=struct.unpack("<4Q",bytes.fromhex(row["raw_hex"]))
                    assert n==row["instructions"]>0 and enabled==running==row["time_enabled_ns"]==row["time_running_ns"]>0 and event==row["event_id"]>0
                    out[k]=n
                out["sum_two"]=sum(out.values());whole=read(name+"whole/whole-clock.json")
                assert whole["code"]==whole["event_errno"]==0 and whole["enabled"]==whole["running"]>0 and whole["instructions"]>0;out["whole"]=whole["instructions"]
                t=read(name+"wall/ordinary.json");assert t["mode"]=="native"and t["exit"]==0 and t["wait"]=="os.waitpid(child.pid, 0)"and t["pid"]>0
                assert t["argv"]==t["invoked"]==ARGS and t["boot"]==BOOT and t["cpus"]==boot["affinity"]
                assert visits[0][1]<=t["start_ns"]<t["end_ns"]<=visits[0][2]and t["ns"]==t["end_ns"]-t["start_ns"]>0
                text=z.read(name+"wall/cargo.stderr");line,=[v for v in text.decode().splitlines()if v.startswith("    Finished `dev` profile [unoptimized + debuginfo] target(s) in ")]
                cargo.append(dict(pair=i,role=role,finished=line,stderr_sha256=sd(text),blocking_ns=t["ns"]));out["wall"]=t["ns"];arms[role]=out
            assert bounds[0][1]<=bounds[1][0]and [t[2]for t in bounds]==list(ordering);chron.extend(bounds)
            for k in KEYS:nums[k].append([arms[r][k]for r in ROLES])
        assert len(seen)==16 and all(a[1]<=b[0]for a,b in zip(chron,chron[1:]))and cargo==declared["observed_Cargo_Finished_lines"]
        values={k:score(x)for k,x in nums.items()}
        for k,x in values.items():
            a=declared["metrics"][k];assert x["raw"]==a["control_and_treatment"]and x["paired_cost_ratios"]==a["paired_treatment_over_control"]and x["paired_speedups"]==a["paired_control_over_treatment"]
            assert x["paired_median_speedup"]==a["median_speedup"]and x["both_hold_median_speedups"]==a["half_medians_speedup"]and x["strict_primary_predicate"]==a["all_eight_strictly_above_2x"]
        assert values["wall"]["strict_primary_predicate"]==declared["primary_wall_twofold_all_eight"]
        return {"run":RUN,"job":JOB,"head":HEAD,"boot":BOOT,"registration":REG,"source":SOURCE,"original_sha256":expected,"corrected_baseline_only":True,
                "primary_wall_twofold_all_eight":values["wall"]["strict_primary_predicate"],"metrics":values,"actual_cargo_lines":cargo,"all_compiler_executions":verify_all_compilers(z)}
if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument("archive",nargs="?");cli.add_argument("--sha256");cli.add_argument("--controls",action="store_true");args=cli.parse_args()
    if args.controls:controls();print("eight strict, exact tie, noninteger, missing and zero inputs verified")
    else:print(json.dumps(verify(args.archive,args.sha256),sort_keys=True,indent=2))
