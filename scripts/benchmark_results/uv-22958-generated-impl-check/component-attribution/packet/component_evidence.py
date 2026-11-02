"""Replay component attribution from the raw native and PMU records of all eight production trios."""
from fractions import Fraction
from math import comb
from pathlib import Path
from statistics import median
from zipfile import ZipFile
import argparse,gzip,hashlib,json,re,struct
from zipfile import ZIP_DEFLATED, ZipInfo
REG="5871772a0a844bd11c83c1326e2310bd1bf15f1b488d4e68fced3ad124d2c166"
ROLES=("S","P","F")
SOURCE={"S":"10d56274a98801b5ef8f80aab734e835749458e1","P":"77ce0545653df71f43e601c28dde01a5e4f02b09","F":"ac67101cb973e35ce8ff044cc8014c2c76bab69e"}
EPOCHS={"S":(43310,3),"P":(43317,3),"F":(43319,43319)}
ORDERS=("SPF","FPS","PFS","SFP","FSP","PSF","SPF","FPS")
PAIRS=(("S","P"),("S","F"),("P","F"))
HERE=Path(__file__).resolve().parent
KEYS=("wall","uv_client","sum_two","uv_configuration","whole")
LABELS=("uv_client","uv_configuration")
ARGS=["/tmp/uv-workflow-search/sdk/bin/cargo","check","-p","uv-client","--locked","--offline","-j8"]
def sha(path):
    with Path(path).open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def sd(raw):return hashlib.sha256(raw).hexdigest()
def score(rows):
    assert len(rows)==8 and all(len(p)==2 and all(type(x)is int and x>0 for x in p)for p in rows)
    speed=[Fraction(a,b)for a,b in rows];cost=[1/v for v in speed];wins=sum(v>2 for v in speed);non_ties=sum(v!=2 for v in speed)
    return {"raw":rows,"control_median":median([a for a,b in rows]),"treatment_median":median([b for a,b in rows]), "qualifies_20pct_in_all_eight":all(5*b<=4*a for a,b in rows), "exact_speedups":[str(v)for v in speed],
        "paired_speedups":list(map(float,speed)),"paired_median_speedup":float(median(speed)),
        "paired_cost_ratios":list(map(float,cost)),"paired_median_cost_ratio":float(median(cost)),
        "both_hold_median_speedups":[float(median(v))for v in (speed[:4],speed[4:])],
        "order_statistic_99_21875_percent_speed_interval":[float(min(speed)),float(max(speed))],
        "strict_over_two":wins,"strict_primary_predicate":wins==8 and all(median(x)>2 for x in (speed[:4],speed[4:])),
        "exact_one_sided_sign_at_two":sum(comb(non_ties,i)for i in range(wins,non_ties+1))/2**non_ties if non_ties else 1}
def controls():
    assert score([[201,100]]*8)["strict_primary_predicate"] and score([[201,100]]*8)["exact_one_sided_sign_at_two"]==1/256
    assert not score([[200,100]]+[[201,100]]*7)["strict_primary_predicate"]
    assert score([[100,80]]*8)["qualifies_20pct_in_all_eight"]
    assert not score([[100,80]]*7+[[100,81]])["qualifies_20pct_in_all_eight"]
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

def verify_all_compilers(z,roles=ROLES):
    assert roles and len(roles)==len(set(roles)) and set(roles)<=set(ROLES)
    traces=[]
    for role in roles:
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
                if kind=="threads":
                    thread=json.loads(z.read(prefix+"per-rustc.json")); request=json.loads(z.read(f"native-22958/{visit}/scoped-request.json"));assert thread["root"]==json.loads(raw)["root"] and set(thread["targets"])==set(request["selectors"])==set(LABELS)
                    for label,target in thread["targets"].items():
                        match,=[img for pid,img in observed if pid==target["pid"] and img.get("argv")==request["selectors"][label]]
                        assert exits[target["pid"]]==0 and all(match[k]==target[k]for k in ("argv","exe","file")) and tuple(match["file"])==identity
                assert sorted(units)==([]if kind.startswith("noedit")else sorted(LABELS))
                if prefix+"rustc-executions.json" in z.namelist():
                    assert json.loads(z.read(prefix+"rustc-executions.json"))=={"total":len(units),"probes":[]}
                traces.append({"trace":prefix+"kernel-events.json","sha256":sd(raw),"units":sorted(units)})
    assert len(traces)==19*len(roles) and sum(len(v["units"])for v in traces)==34*len(roles)
    return traces

def verify(z, origin):
    controls()
    RUN,JOB,HEAD,BOOT = (origin[k] for k in ("run","job","head","boot"))
    assert type(RUN) is int and type(JOB) is int and RUN>0 and JOB>0 and re.fullmatch(r"[0-9a-f]{40}",HEAD)
    cfg=json.loads((HERE/"release-lock.json").read_bytes());LOCK=sha(HERE/"release-lock.json")
    assert sha(HERE/"component-plan.json")==cfg["registration"]==REG
    assert {k:v["commit"]for k,v in cfg["sources"].items()}==SOURCE
    assert len(z.namelist())==len(set(z.namelist()));read=lambda n:json.loads(z.read(n));base="native-22958/"
    declared=read(base+"score.json");guards=read(base+"all-native-guards.json");boot=read("boot-attestation.json")
    assert declared["complete"]and declared["registered"]==guards["case"]==boot["registered"]==REG and declared["independent_histories"]==guards["independent"]==24
    assert not declared["original_exact_cold_gate_redeemed"]and declared["release_lock"]==boot["release_lock"]==LOCK
    assert declared["actual_signed_Cargo"]==ARGS and {k:v["commit"]for k,v in declared["sources"].items()}==SOURCE
    assert (boot["run"],boot["coordinator"],boot["boot"])==(RUN,HEAD,BOOT)and BOOT not in boot["excluded"]and set(boot["excluded"])=={v["boot"] for v in cfg["excluded"].values()} and len(set(boot["excluded"]))>=25
    assert sd(("\n".join(sorted(boot["excluded"]))+"\n").encode())==cfg["boot_list_sha256"]
    assert ["".join(v)for v in guards["orders"]]==list(ORDERS) and guards["boot"]==BOOT
    for file,tag in (("calibration.json","inherited"),("per-rustc-calibration/calibration.json","threads"),("blocking-clock-pre/verified.json","blocking")):
        assert sd(z.read(file))==boot[tag]
    timer=read("blocking-clock-pre/verified.json");assert timer["eligible_blocking_calibration"]and timer["boot"]==BOOT and timer["affinity"]==boot["affinity"]
    cal=read("calibration.json");assert cal["unmultiplexed_calibration_clocks"]==28 and cal["ready"]["boot"]==BOOT
    current=read("fixed-release-after-study.json");assert current["id"]==430629054 and current["tag_name"]=="ohm-1.99.0-22" and current["immutable"]
    intake=read("intake.json");assert set(intake["installed"])==set(ROLES)and intake["signed_cargo_sha256"]=="3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871"
    for role in ROLES:
        unit=intake["installed"][role];assert unit["source"]["commit"]==SOURCE[role]and unit["files"]==142
        root=base+"opening-"+role+"/";proof=read(root+"independent-cold.json");assert proof["all_guarded"]
        for state in ("A","B"):
            v=read(root+"noedit-"+state+"/verified.json");assert v["same_material"]and v["forms"]=={}
    migration=read("intake/release-migration.json"); proof=migration["native_format_proofs"]
    assert migration["fixtures_only"] and migration["ordinary_benchmark_caches_separate"]
    assert set(proof)=={a+"-"+b for a,b in PAIRS} and len(migration["roles"])==6
    for a,b in PAIRS:
        label=a+"-"+b; inc="intake/format-incremental-"+label+"/passed.json"; meta="intake/format-metadata-"+label+"/passed.json"
        assert proof[label]=={"incremental":sd(z.read(inc)),"metadata":sd(z.read(meta))}
        i,h=read(inc),read(meta); assert i["signed_argv_refusal_both_directions"] and i["same_sdk_self_loaded_before_and_after"] and i["reader_compilations"]==10
        assert i["no_header_edit"] and i["no_compiler_version_override"] and not h["file_edits"] and not h["compiler_version_overrides"]
        assert h["cross_crate_E0514"]==h["own_crate_reads"]==h["own_native_typecheck_errors"]==2
        assert {k:v["metadata_epoch"] for k,v in h["actual_originals"].items()}=={SOURCE[r]:EPOCHS[r][1] for r in (a,b)}
        assert len({v["encoded_version"]for v in h["actual_originals"].values()})==2
    states=[];seen=set();cargo=[];chron=[]
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
        assert all(x[1]<=y[0]for x,y in zip(bounds,bounds[1:])) and [t[2]for t in bounds]==list(ordering);chron.extend(bounds)
        states.append(arms)
    assert len(seen)==24 and all(a[1]<=b[0]for a,b in zip(chron,chron[1:])) and cargo==declared["observed_Cargo_Finished_lines"] and states==declared["raw_by_role"]
    values={}
    for control,treat in PAIRS:
        k=control+"-"+treat; values[k]={scope:score([[row[control][scope],row[treat][scope]] for row in states])for scope in KEYS}
        for scope,row in values[k].items():
            actual=declared["contrasts"][k][scope]
            assert row["raw"]==actual["control_and_treatment"] and row["exact_speedups"]==actual["exact_control_over_treatment"]
            assert row["paired_median_speedup"]==actual["median_speedup"] and row["both_hold_median_speedups"]==actual["half_medians_speedup"]
            assert row["strict_primary_predicate"]==actual["all_eight_strictly_above_2x"] and row["qualifies_20pct_in_all_eight"]==actual["all_eight_at_least_twenty_percent_reduction"]
    execution=verify_all_compilers(z)
    return {"run":RUN,"job":JOB,"head":HEAD,"boot":BOOT,"registration":REG,"source":SOURCE,"service_original":origin["original"],"isolated_336_contrast":"P-F","trios":list(ORDERS),"raw":states,"cumulative_and_marginal":values,"observed_cargo_lines":cargo,"full_kernel_traces":execution,"repeatability_requires_another_worker":True}

BRANCH = "charlie/codex-22958-component-attribution"
BOOT_NAME = "uv-22958-component-attribution-boot"
ORIGINAL_NAME = "uv-22958-component-attribution-eight-trios"
CAP = 512 << 20
PACKET_CAP = 32 << 20

def enrolled(folder, reviewed):
    doc=lambda name:json.loads((folder/name).read_bytes())
    run,jobs,arts=(doc(name) for name in ("run.json","jobs.json","artifacts.json"))
    job,=jobs["jobs"]
    assert jobs["total_count"]==1 and job["run_id"]==run["id"] and run["run_attempt"]==job["run_attempt"]==1
    assert run["head_branch"]==BRANCH and run["head_sha"]==job["head_sha"]==reviewed and re.fullmatch(r"[0-9a-f]{40}",reviewed)
    assert run["repository"]["id"]==run["head_repository"]["id"]==1319437234
    assert run["event"]=="workflow_dispatch" and run["status"]==job["status"]=="completed" and run["conclusion"]==job["conclusion"]=="success"
    assert arts["total_count"]==len(arts["artifacts"])==2
    service={x["name"]:x for x in arts["artifacts"]};assert set(service)=={BOOT_NAME,ORIGINAL_NAME}
    for a in service.values():
        member=a["workflow_run"]
        assert member["id"]==run["id"] and member["head_sha"]==reviewed and member["repository_id"]==member["head_repository_id"]==1319437234
        assert a["digest"].startswith("sha256:") and a["size_in_bytes"]>0
    b,raw=service[BOOT_NAME],service[ORIGINAL_NAME];early=folder/"boot.zip"
    assert b["size_in_bytes"]==early.stat().st_size<32768 and b["digest"]=="sha256:"+sha(early) and raw["size_in_bytes"]<=CAP
    with ZipFile(early)as z:
        files=[v for v in z.infolist() if not v.is_dir()];f,=files;assert f.filename=="boot-attestation.json" and f.file_size<32768
        boot_bytes=z.read(f);boot=json.loads(boot_bytes);assert boot["coordinator"]==reviewed and boot["run"]==run["id"] and boot["boot"]not in boot["excluded"]
    return {"head":reviewed,"run":run["id"],"job":job["id"],"boot":boot["boot"],"original":{"id":raw["id"],"sha256":raw["digest"][7:],"bytes":raw["size_in_bytes"]},"early":{"id":b["id"],"sha256":b["digest"][7:],"entry":sd(boot_bytes)}}

class Touched:
    def __init__(self,z):self.z=z;self.names=set()
    def read(self,key):self.names.add(key);return self.z.read(key)
    def namelist(self):return self.z.namelist()

def member_index(z):
    names=[v.filename for v in z.infolist() if not v.is_dir()]
    assert len(names)==len(set(names)) and all(not n.startswith('/') and '..' not in n.split('/') for n in names)
    result={}
    for key in sorted(names):
        with z.open(key)as f:result[key]=hashlib.file_digest(f,'sha256').hexdigest()
    return result

def save(path,row):
    with path.open('xb')as f:f.write(json.dumps(row,sort_keys=True,indent=1).encode()+b'\n')

def write_packet(original, service, out, head):
    import shutil
    origin=enrolled(service,head);assert original.stat().st_size==origin['original']['bytes'] and sha(original)==origin['original']['sha256']
    out.mkdir(); destinations=['run.json','jobs.json','artifacts.json','boot.zip']
    for n in destinations:shutil.copyfile(service/n,out/n)
    for n in ['component_evidence.py','release-lock.json','component-plan.json']:shutil.copyfile(HERE/n,out/n)
    sums=['all-members.sha256.gz','raw-members.zip','verified.json','origin.json','component_evidence.py','component-plan.json','release-lock.json',*destinations]
    with ZipFile(original)as z:
        raw=Touched(z); result=verify(raw,origin); index=member_index(z)
        assert all(name in index for name in raw.names)
        save(out/'verified.json',result);save(out/'origin.json',origin)
        (out/'all-members.sha256.gz').write_bytes(gzip.compress((''.join(h+'  '+n+'\n' for n,h in index.items())).encode(),mtime=0))
        room=PACKET_CAP-sum(p.stat().st_size for p in out.iterdir())-sum(67+len(n.encode()) for n in sums)
        assert room>0
        class LimitedZip:
            def __init__(self,fp):self.fp=fp
            def __getattr__(self,attr):return getattr(self.fp,attr)
            def write(self,data):
                if self.fp.tell()+len(data)>room:raise ValueError('32 MiB compact packet limit')
                return self.fp.write(data)
        with (out/'raw-members.zip').open('xb')as file, ZipFile(LimitedZip(file),'w',ZIP_DEFLATED,compresslevel=7)as packet:
            for name in sorted(raw.names):packet.writestr(ZipInfo(name,(1980,1,1,0,0,0)),z.read(name),compress_type=ZIP_DEFLATED,compresslevel=7)
    (out/'SHA256SUMS').write_text(''.join(sha(out/n)+'  '+n+'\n' for n in sorted(sums)))
    size=sum(f.stat().st_size for f in out.iterdir());assert size<=PACKET_CAP
    return {'full_members':len(index),'retained':len(raw.names),'packet_bytes':size}


def replay_packet(folder, original=None):
    assert sum(p.stat().st_size for p in folder.iterdir())<=PACKET_CAP
    manifest=(folder/'SHA256SUMS').read_text().splitlines();assert len(manifest)==11
    assert {line[66:] for line in manifest}=={p.name for p in folder.iterdir()}-{'SHA256SUMS'}
    assert all(line==sha(folder/line[66:])+'  '+line[66:] for line in manifest)
    origin=json.loads((folder/'origin.json').read_bytes());assert origin==enrolled(folder,origin['head'])
    rows=gzip.decompress((folder/'all-members.sha256.gz').read_bytes()).decode().splitlines()
    index={n[66:]:n[:64] for n in rows};assert len(rows)==len(index)
    with ZipFile(folder/'raw-members.zip')as z:
        assert all(index[k]==v for k,v in member_index(z).items());t=Touched(z);data=verify(t,origin);assert set(z.namelist())==t.names
    assert data==json.loads((folder/'verified.json').read_bytes())
    if original:
        assert sha(original)==origin['original']['sha256'] and original.stat().st_size==origin['original']['bytes']
        with ZipFile(original)as z:assert member_index(z)==index
    return data

if __name__=='__main__':
    import sys
    if sys.argv[1:]==['controls']:controls()
    elif len(sys.argv)==6 and sys.argv[1]=='pack':print(write_packet(Path(sys.argv[2]),Path(sys.argv[3]),Path(sys.argv[4]),sys.argv[5]))
    elif len(sys.argv)in(2,3)and sys.argv[1]=='replay':print(json.dumps(replay_packet(HERE,Path(sys.argv[2])if len(sys.argv)==3 else None),indent=1))
    else:raise SystemExit('controls | pack ORIGINAL SERVICE_DIR EMPTY_PACKET REVIEWED_HEAD | replay [ORIGINAL]')
