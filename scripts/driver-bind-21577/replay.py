"""Derive every endpoint from the original two-PID kernel tree, raw counters, blocking clock and all native bytes."""
from common21577 import *
from fractions import Fraction
from statistics import median
from zipfile import ZipFile
from score import Files,validate_scoped
import birth

def rehash(f):
    entries=f.get("original-index.json")
    members=[n for n in f.z.namelist()if not n.endswith("/")]
    assert set(members)==set(entries)|{"original-index.json"} and len(members)==len(set(members))
    for k,[size,digest] in entries.items():
        assert f.z.getinfo(k).file_size==size and f.sha(k)==digest
    return entries
def native(f,d,role,opened=None):
    ev=f.get(d+"/native.json");initial=f.get(d+"/seed.json")
    assert ev["role"]==role and ev["same_native_B"] and ev["same_held_bare"] and ev["two_forms"]==sorted(NAMES)
    assert initial["workspace_role"]==role and initial["products"]==ev["A"]==f.sha(d+"/cold-A/products.json")
    assert ev["cold_A_seed"]==initial["bytes_sha256"] and initial["bytes_sha256"][0]>1<<20
    assert initial["source"]==ev["source_A"] and ev["source_A"]["branch_index_head"]==ev["source_B"]["branch_index_head"]==WORK["A"]
    for phase,src in (("A",ev["source_A"]),("B",ev["source_B"])):
        expected=read(HERE/("source-"+phase+".json"));assert src["phase"]==phase and src["working_tree"]==expected["actual_tree"] and src["lock"]==expected["lock"] and src["files"]==expected["files"] and src["describe"]==WORK["tag_describe"] and src["real_tag"]==WORK["tag"]
    a=f.get(d+"/cold-A/products.json");b=f.get(d+"/first-B/products.json")
    assert ev["B"]==f.sha(d+"/first-B/products.json")and ev["cold_B"]==f.sha(d+"/cold-B/products.json")and b==f.get(d+"/cold-B/products.json")==f.get(d+"/bare/products.json")
    for src in (a,b):
        assert [len(src[k])for k in("rmeta","sidecars","workspace")]==[39,30,4]
        assert all(src["rmeta"][k]==v for k,v in src["workspace"].items())
    for g in ("A","B"):
        c=f.get(d+"/cold-"+g+"/clean-process.json");assert c["target_initially_absent"] and c["separate_preparation"] and c["command"]==CHECK and c["env"]==ENV and c["exit"]==0 and c["finished_ns"]>c["started_ns"] and sorted(c["checked_or_compiled"])==read(HERE/"cold-roster.json") and c["pid"]>0
        assert sorted(re.findall(r"^\s+(?:Checking|Compiling) (\S+) v",f.raw(d+"/cold-"+g+"/stderr").decode(),re.M))==sorted(c["checked_or_compiled"])
        no=f.get(d+"/unchanged-"+g+"/observed.json"); assert no["rows"]==[] and no["forms"]=={}
        raw=h.EV["decode"](f.get(d+"/unchanged-"+g+"/kernel-events.json"));assert h.forms_from_tree(raw,no["rustc_id"])==({},[]) and len(raw["images"])==1 and raw["images"][0]["argv"]==CHECK
    first=f.get(d+"/first-B/observed.json");first_tree=h.EV["decode"](f.get(d+"/first-B/kernel-events.json"));forms,rows=h.forms_from_tree(first_tree,first["rustc_id"])
    assert first_tree["images"][0]["argv"]==CHECK and forms==first["forms"]and len(rows)==2 and set(forms)==NAMES and first_tree["root"]==first["root_pid"]
    ef=f.get(d+"/first-B/externs.json");assert ev["externs_sha256"]==f.sha(d+"/first-B/externs.json")
    for n,v in forms.items():
        ext={v[i+1].split("=",1)[0]:v[i+1].split("=",1)[1]for i,p in enumerate(v)if p=="--extern"}
        assert ext=={k:q["path"]for k,q in ef[n].items()} and all(q["blob"][0]>0 and len(q["blob"][1])==64 for q in ef[n].values())
    current={"A":a,"B":b,"forms":forms,"externs":ef}
    if opened:assert current==opened and ev["captured_counters"] and ev["matched_previous_opening"]
    else:assert not ev["captured_counters"]
    return current
def ratio(s,p):
    return {"signed":s,"prototype":p,"ratio_S_over_P":s/p,"reduction":1-p/s}
def wheel(path,boot,head):
    f=Files(path);members=rehash(f);att=f.get("boot-attestation.json");assert att==boot and att["head"]==head and att["protocol"]==sha(HERE/"protocol.json")
    label=att["series"];assert label in PLAN["orders"] and f.get("panel/complete.json")["order"]==PLAN["orders"][label] and f.get("panel/complete.json")["protocol"]==sha(HERE/"protocol.json")
    assert all(f.sha(p)==att[n]for n,p in (("blocking","blocking-clock-pre/verified.json"),("inherited","calibration.json"),("threads","per-rustc-calibration/calibration.json")))
    for when in ("pre","post"):
        gate=f.get("blocking-clock-"+when+"/verified.json");assert gate["eligible_blocking_calibration"] and gate["boot"]==att["boot"] and gate["affinity"]==att["affinity"]
    cal=f.get("calibration.json");assert cal["ready"]["boot"]==att["boot"] and cal["ready"]["affinity"]==att["affinity"] and len(att["affinity"])==8 and cal["unmultiplexed_calibration_clocks"]==28
    assert f.get("registry.json")["all_archives_checked"]==682 and f.get("registry.json")["manifest_sha256"]==sha(HERE/"registry.json")
    orig=read(HERE/"signed-sdk.json");driver=read(HERE/"layout.json")["driver"]
    for role in ("S","P"):
        sel=f.get("panel/selected-"+role+".json");want={k:[v["bytes"],(PLAN["prototype"]if role=="P"and k==driver else v["sha256"]),v["mode"]]for k,v in orig.items()}
        assert sel["role"]==role and sel["full_members"]==want and sel["driver"]==want[driver][1] and sel["cargo"]==orig["bin/cargo"]["sha256"] and sel["count"]==142
    srole=f.get("intake/signed/registered.json");assert srole["source"]==read(HERE/"signed-native.json")["source"] and f.get("intake/transformation.json")["round_trip"]==PLAN["signed"] and f.get("intake/transformation.json")["prototype"]==PLAN["prototype"]
    original_meta=f.get("intake/published.json")
    for phase in ("before","after"):
        z=f.get("latest-"+phase+".json");assert z["id"]==original_meta["id"]and z["tag_name"]=="ohm-1.99.0-23" and z["immutable"] and not z["draft"] and not z["prerelease"]
    assert f.get("intake/verify.json")["statement"]==f.get("intake/verify-asset.json")["statement"]
    opens={};seenfiles=set();usedseeds=set()
    for role in "SP":
        d="panel/opening-"+role;opens[role]=native(f,d,role)
        witness=f.get(d+"/behavior/passed.json")
        for state in "AB":
            out=f.raw(d+"/behavior/"+state+"/stderr");assert not f.raw(d+"/behavior/"+state+"/stdout") and out.decode()==witness[state]["output"] and all(out.count(x)==1 for x in (b"original warning",b"general-last",b"specific-first"))
            assert (out.index(b"general-last")<out.index(b"specific-first"))==(state=="A") and witness[state]["test"]==sha(HERE/("behavior-"+state+".rs")) and set(witness[state]["linked"])==NAMES
        for phase in "AB":
            surf=opens[role][phase]
            for kind,suffix in (("rmeta",".gz"),("sidecars",".public-api-hash")):
                for size,digest in surf[kind].values():
                    name="blobs/"+digest+suffix
                    if name in seenfiles:continue
                    blob=f.raw(name);raw=gzip.decompress(blob)if suffix==".gz"else blob;assert len(raw)==size and hashlib.sha256(raw).hexdigest()==digest;seenfiles.add(name)
    assert opens["S"]==opens["P"] and all(f.get("panel/joint.json")[n]for n in ("both_full_native_cohorts_identical","all_39_raw_rmeta_and_30_public","both_two_argv_and_extern_material_agree"))
    pairs=[]
    for i,order in enumerate(PLAN["orders"][label],1):
        roles={}
        for role in order.split("/"):
            d=f"panel/{i}-{role}";v=native(f,d,role,opens[role]);c=f.get(d+"/cold-A/clean-process.json");seed=(c["pid"],c["started_ns"]);assert seed not in usedseeds;usedseeds.add(seed)
            for n in ("whole","per-rustc"):assert f.get(d+"/"+n+"/products.json")==v["B"]
            req=f.get(d+"/request.json");assert req=={"command":CHECK,"environment":ENV,"cwd":str(SRC),"compiler_path":str(h.RUSTC),"selectors":v["forms"]}
            tree=h.EV["decode"](f.get(d+"/per-rustc/kernel-events.json"));count=f.get(d+"/per-rustc/per-rustc.json");images=f.get(d+"/per-rustc/observed.json")
            assert tree["images"][0]["argv"]==CHECK and tree["images"][0]["file"]==images["cargo_id"]
            bound=validate_scoped(tree,count,v["forms"],images["rustc_id"]);assert set(bound)==NAMES and len(images["all_actual_images"])==2
            vals={n:count["targets"][n]["instructions"]for n in NAMES}; assert all(v>0 for v in vals.values())
            whole=f.get(d+"/whole/raw.json");assert whole["code"]==0 and whole["event_errno"]==0 and whole["enabled"]==whole["running"]>0 and whole["instructions"]>0 and b"Finished" in f.raw(d+"/whole/stderr")
            bare=f.get(d+"/bare/clock.json");assert bare["argv"]==CHECK and bare["exit"]==0 and bare["wait"]=="os.waitpid(child.pid, 0)" and bare["end_ns"]-bare["start_ns"]==bare["ns"]>0 and b"Finished" in f.raw(d+"/bare/stderr")
            roles[role]={"uv_warnings":vals["uv_warnings"],"uv_errors":vals["uv_errors"],"both_rustcs":sum(vals.values()),"whole":whole["instructions"],"wall_ns":bare["ns"],"cold_A_process":list(seed),"pids":{n:count["targets"][n]["pid"]for n in NAMES},"raw_digests":{t:f.sha(d+"/"+t)for t in("bare/clock.json","whole/raw.json","per-rustc/per-rustc.json","per-rustc/kernel-events.json","native.json")}}
        pairs.append(roles)
    assert len(usedseeds)==16
    summaries={}
    for name in("uv_warnings","uv_errors","both_rustcs","whole","wall_ns"):
        vec=[(r["S"][name],r["P"][name])for r in pairs];gains=[Fraction(s-p,s) for s,p in vec]
        summaries[name]={"paired":[ratio(s,p)for s,p in vec],"signed_median":median(s for s,p in vec),"prototype_median":median(p for s,p in vec),"paired_median_speedup":float(median(Fraction(s,p)for s,p in vec)),"paired_median_reduction":float(median(gains)),"number_20pct":sum(x>=Fraction(1,5) for x in gains),"all_eight_at_least_20pct":all(x>=Fraction(1,5)for x in gains),"halves_at_least_20pct":[median(h)>=Fraction(1,5)for h in(gains[:4],gains[4:])]}
    primary=summaries["uv_warnings"];return {"run":att["run"],"job":att["job"],"head":head,"label":label,"boot":att["boot"],"runner_id":att["runner_id"],"plan":att["protocol"],"original_sha256":sha(path),"members":len(members)+1,"verified_native_blobs":len(seenfiles),"pairs":pairs,"endpoints":summaries,"primary_qualified":primary["all_eight_at_least_20pct"]and all(primary["halves_at_least_20pct"])}
