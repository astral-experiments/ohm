"""Derive every endpoint from the original two-PID kernel tree, raw counters, blocking clock and all native bytes."""
from common21577 import *
from fractions import Fraction
from statistics import median
from zipfile import ZipFile
from score import Files,validate_scoped
import birth
import source_intake as production
import source_surface
ROLES=production.ROLES

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
def hardware_summary(data,baseline,treatment):
    result={}
    for name in ("uv_warnings","uv_errors","both_rustcs","whole","wall_ns"):
        rows=[(q[baseline][name],q[treatment][name])for q in data]
        gains=[Fraction(b-t,b)for b,t in rows]
        speed=[Fraction(b,t)for b,t in rows]
        result[name]={"raw_pairs":rows,"paired_reductions":[float(v)for v in gains],"baseline_median":median(b for b,t in rows),
            "treatment_median":median(t for b,t in rows),"paired_median_reduction":float(median(gains)),
            "paired_median_speedup":float(median(speed)),"n_faster":sum(g>0 for g in gains),
            "n_20pct":sum(g>=Fraction(1,5)for g in gains),"n_twice_as_fast":sum(v>=2 for v in speed),
            "halves_median_reduction":[float(median(h))for h in (gains[:4],gains[4:])],
            "halves_median_speedup":[float(median(h))for h in (speed[:4],speed[4:])]}
    return result
def wheel(path,boot,head,native_only=False):
    f=Files(path);members=rehash(f);att=f.get("boot-attestation.json");assert att==boot and att["head"]==head and att["protocol"]==sha(HERE/"protocol.json")
    label=att["series"];assert label in PLAN["orders"] and f.get("panel/complete.json")["order"]==PLAN["orders"][label] and f.get("panel/complete.json")["protocol"]==sha(HERE/"protocol.json")
    assert all(f.sha(p)==att[n]for n,p in (("blocking","blocking-clock-pre/verified.json"),("inherited","calibration.json"),("threads","per-rustc-calibration/calibration.json")))
    for when in ("pre","post"):
        gate=f.get("blocking-clock-"+when+"/verified.json");assert gate["eligible_blocking_calibration"] and gate["boot"]==att["boot"] and gate["affinity"]==att["affinity"]
    cal=f.get("calibration.json");assert cal["ready"]["boot"]==att["boot"] and cal["ready"]["affinity"]==att["affinity"] and len(att["affinity"])==8 and cal["unmultiplexed_calibration_clocks"]==28
    assert f.get("registry.json")["all_archives_checked"]==682 and f.get("registry.json")["manifest_sha256"]==sha(HERE/"registry.json")
    orig=read(HERE/"signed-sdk.json");lock=read(HERE/"source-sdk-lock.json")
    assert f.sha("intake/pair.json")==lock["pair_sha256"]==sha(HERE/"source-sdk-pair.json")
    assert lock["refusals"] and lock["performance_samples"]==0
    service=f.get("intake/source-producer-service.json")
    assert set(service)==set(lock["roles"])=={"R","T"}
    for role,actual in service.items():
        src=lock["roles"][role];run=actual["run"];job=actual["job"];arts=actual["artifacts"]["artifacts"]
        assert run["id"]==src["run"] and job["id"]==src["job"]and run["head_sha"]==job["head_sha"]==src["coordinator"] and job["conclusion"]=="success"
        assert run["repository"]["id"]==run["head_repository"]["id"]==PLAN["repo_id"] and run["run_attempt"]==1
        for flavor in ("sdk","qa"):
            want=src[flavor];a,=[i for i in arts if i["id"]==want["id"]]
            assert a["name"]==want["name"] and a["digest"]=="sha256:"+want["sha256"] and a["size_in_bytes"]==want["bytes"] and a["workflow_run"]["head_sha"]==run["head_sha"]
    sels={}
    for role in ROLES:
        sel=sels[role]=f.get("panel/selected-"+role+".json")
        if role=="S":inv=orig
        else:
            r=lock["roles"][role];inv=f.get(f"intake/{role}-sdk-inventory.json")
            product=f.get(f"intake/{role}-role.json");src=f.get(f"intake/{role}-source.json")
            assert src["commit"]==r["source_commit"]==production.SOURCE[role] and src["tree"]==r["source_tree"]==production.TREES[role]
            assert src["coordinator"]==r["coordinator"] and src["role"]==product["role"]==role
            assert f.sha(f"intake/{role}-sdk-inventory.json")==r["inventory_sha256"]==product["sdk_inventory_sha256"]
            assert f.sha(f"intake/{role}-role.json")==r["role_sha256"] and product["archive_sha256"]==r["archive_sha256"]
            assert f.sha(f"intake/{role}-source.json")==product["source_sha256"] and r["source_commit"] in sel["native_banners"]["rustc"]
        want={k:[v["bytes"],v["sha256"],v["mode"]]for k,v in inv.items()};cargo=orig["bin/cargo"]
        want["bin/cargo"]=[cargo["bytes"],cargo["sha256"],cargo["mode"]]
        driver,=[n for n in want if n.startswith("lib/librustc_driver-")and n.endswith(".so")]
        assert sel["role"]==role and sel["count"]==142 and sel["cargo"]==production.SIGNED_CARGO and sel["driver"]==want[driver][1]
        llvm,=[n for n in want if n.startswith("lib/libLLVM.so.")]
        assert sel["loaded_driver"]==str(SDK/driver) and sel["loaded_llvm"]==str(SDK/llvm) and sel["llvm"]==want[llvm][1]
        assert sel["full_members"]==f.get("intake/effective-"+role+".json")==want
    assert f.get("intake/signed/registered.json")["source"]==read(HERE/"signed-native.json")["source"]
    original_meta=f.get("intake/published.json")
    for phase in ("before","after"):
        z=f.get("latest-"+phase+".json");assert z["id"]==original_meta["id"]and z["tag_name"]=="ohm-1.99.0-23" and z["immutable"] and not z["draft"] and not z["prerelease"]
    assert f.get("intake/verify.json")["statement"]==f.get("intake/verify-asset.json")["statement"]
    opens={};seenfiles=set();usedseeds=set();native_receipts={}
    for role in ROLES:
        d="panel/opening-"+role;opens[role]=native(f,d,role)
        native_receipts[d]=f.sha(d+"/native.json")
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
    joint=source_surface.joint(opens,sels,lambda n:f.raw("blobs/"+n),
        lambda role,digest:f.raw(f"panel/opening-{role}/native-reader/{digest}.gz"))
    assert joint==f.get("panel/cross-role-metadata.json")
    source_surface.require_equal(joint)
    receipt=f.get("panel/joint.json")
    assert receipt["roles"]==list(ROLES) and receipt["native_digest"]==f.sha("panel/cross-role-metadata.json") and all(receipt[n]for n in ("all_39_native_item_inventories","all_30_sidecars_bound_to_native_root","same_kernel_argv_and_direct_extern_interfaces"))
    outputs=[{phase:f.get(f"panel/opening-{role}/behavior/passed.json")[phase]["output"]for phase in "AB"}for role in ROLES]
    assert all(v==receipt["positive_A_B_outputs"]for v in outputs)
    pairs=[]
    for i,order in enumerate(PLAN["orders"][label],1):
        roles={}
        for role in order.split("/"):
            d=f"panel/{i}-{role}";v=native(f,d,role,opens[role]);c=f.get(d+"/cold-A/clean-process.json");seed=(c["pid"],c["started_ns"]);assert seed not in usedseeds;usedseeds.add(seed)
            for n in ("whole","per-rustc"):assert f.get(d+"/"+n+"/products.json")==v["B"]
            req=f.get(d+"/request.json");assert req=={"command":CHECK,"environment":ENV,"cwd":str(SRC),"compiler_path":str(h.RUSTC),"selectors":v["forms"]}
            native_receipts[d]=f.sha(d+"/native.json")
            if native_only:
                roles[role]=native_receipts[d]
                continue
            tree=h.EV["decode"](f.get(d+"/per-rustc/kernel-events.json"));count=f.get(d+"/per-rustc/per-rustc.json");images=f.get(d+"/per-rustc/observed.json")
            assert tree["images"][0]["argv"]==CHECK and tree["images"][0]["file"]==images["cargo_id"]
            bound=validate_scoped(tree,count,v["forms"],images["rustc_id"]);assert set(bound)==NAMES and len(images["all_actual_images"])==2
            vals={n:count["targets"][n]["instructions"]for n in NAMES}; assert all(v>0 for v in vals.values())
            whole=f.get(d+"/whole/raw.json");assert whole["code"]==0 and whole["event_errno"]==0 and whole["enabled"]==whole["running"]>0 and whole["instructions"]>0 and b"Finished" in f.raw(d+"/whole/stderr")
            bare=f.get(d+"/bare/clock.json");assert bare["argv"]==CHECK and bare["exit"]==0 and bare["wait"]=="os.waitpid(child.pid, 0)" and bare["end_ns"]-bare["start_ns"]==bare["ns"]>0 and b"Finished" in f.raw(d+"/bare/stderr")
            roles[role]={"uv_warnings":vals["uv_warnings"],"uv_errors":vals["uv_errors"],"both_rustcs":sum(vals.values()),"whole":whole["instructions"],"wall_ns":bare["ns"],"cold_A_process":list(seed),"pids":{n:count["targets"][n]["pid"]for n in NAMES},"raw_digests":{t:f.sha(d+"/"+t)for t in("bare/clock.json","whole/raw.json","per-rustc/per-rustc.json","per-rustc/kernel-events.json","native.json")}}
        pairs.append(roles)
    assert len(usedseeds)==24 and len(pairs)==8 and all(set(p)==set(ROLES)for p in pairs)
    assert len(native_receipts)==27
    if native_only:
        return {"native_receipts":native_receipts,"cross_role":f.sha("panel/cross-role-metadata.json"),"original_sha256":sha(path),"verified_native_blobs":len(seenfiles)}
    summaries={b+"_to_"+t:hardware_summary(pairs,b,t)for b,t in (("S","R"),("S","T"),("R","T"))}
    primary=all(summaries[c]["uv_warnings"]["n_20pct"]==8 and min(summaries[c]["uv_warnings"]["halves_median_reduction"])>=0.2 for c in ("S_to_T","R_to_T"))
    wall=all(summaries[c]["wall_ns"]["n_twice_as_fast"]==8 and min(summaries[c]["wall_ns"]["halves_median_speedup"])>=2 for c in ("S_to_T","R_to_T"))
    return {"run":att["run"],"job":att["job"],"head":head,"label":label,"boot":att["boot"],"runner_id":att["runner_id"],"plan":att["protocol"],"original_sha256":sha(path),"members":len(members)+1,"verified_native_blobs":len(seenfiles),"pairs":pairs,"comparisons":summaries,"primary_qualified":primary,"whole_wall_2x":wall}
