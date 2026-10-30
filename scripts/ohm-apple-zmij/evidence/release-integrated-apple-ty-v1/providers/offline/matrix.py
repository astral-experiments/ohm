"""Offline verification of ordinary provider insertion, replacement, removal, recovery and receiver migration."""
import argparse
from pathlib import Path
import gzip
import hashlib
import json
import sys
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native import C,P,compact,digestfile,pretty,sha,write
from protocol import AWARE, CASES, HARD, V1, V2, Receiver, sources

ORDINARY=("lower","unchanged-lower","higher-no-rust","higher-rust-edit","malformed-no-rust","malformed-rust-edit","repair-before-missing","missing-no-rust","missing-rust-edit","restored-rust-edit","restored-unchanged")
STAMP=("original-higher","repeat-higher","overwrite-same-stamp","repeat-replacement","restore-same-stamp")
UNWATCHED={"higher-no-rust","malformed-no-rust","missing-no-rust","repair-before-missing"}
MIGRATION=(("legacy-lower","lower",7),("upgrade-higher","higher",7),("upgrade-unchanged","higher",7),
           ("upgrade-malformed","malformed",7),("upgrade-repair","higher",7),("downgrade-lower","lower",7),
           ("downgrade-missing","missing",7),("downgrade-edit-repair","higher",11),("downgrade-repeat","higher",11))
STATES={"lower":17,"higher":29,"malformed":None,"missing":None}

def verify_binding(binding,expected,subjects):
    x=subjects["cargo"][expected]
    assert (binding["name"],binding["source"],binding["binary"]["sha256"])==(expected,x["source"],x["sha"])
    assert x["source"] in binding["version"] and "aarch64-apple-darwin" in binding["version"]
    assert binding["binary"]["ino"]>0 and binding["binary"]["size"]>0

def depfile(v,row,marker):
    found={}
    for path,orig in row["marker"].items():
        body=v.gz("edge-markers/"+orig["sha256"]+".d.gz");assert sha(body)==orig["sha256"]
        lines=body.decode().splitlines()
        if not any(l.endswith(":") for l in lines):continue
        fake=[l[:-1] for l in lines if l.startswith("/dev/null/ohm-") and l.endswith(":")]
        assert fake==[marker]
        rules=[l.split(": ",1) for l in lines if not l.startswith("#") and ": " in l]
        assert marker in rules[0][1].split()
        ordinary=[vs for nm,vs in rules if nm.endswith(".d")]
        assert len(ordinary)==1 and all(m not in ordinary[0].split() for m in (V1,V2,HARD))
        found[path]=orig["sha256"]
    assert found
    return found

def standard(v,name,subjects):
    fac=v.providers();base="provider-matrix/"
    reg=v.js(base+"registration.json");bind=v.js(base+"versioned-receiver.json");end=v.js(base+"terminal.json")
    assert reg["rust"]==bind["rust"]=={"P":P,"C":C} and reg["cargo"]==CASES[name] and end["commands"]==392
    verify_binding(bind["cargo"],name,subjects)
    assert 'asm!("mov fp, fp", options(nomem, nostack, preserves_flags))' in reg["barrier"] and reg["barrier"].count("asm!")==1
    coll=sorted(k.split("/")[-2] for k in v.names if k.startswith(v.prefix+v.root+"/") and k.count("/")==v.root.count("/")+2 and k.endswith("/terminal.json"))
    assert len(coll)==20 and sorted(end["wrong_or_image_mismatch"])==coll
    phases={};judgments={};seen={};marker_counts={};cargos=set()
    for case in coll:
        who,place,watch,mode=case.split("-")
        rows=v.case(case)
        assert tuple(v.js(base+case+"/inputs.json")["steps"][i][0] for i in range(len(rows)))==(STAMP if "stamp" in who else ORDINARY)
        assert v.js(base+case+"/inputs.json")["driver"]["sha256"]==subjects["rust"][who[0]]["driver"]
        required_failed=[];off=[];allmarkers=0;last={}
        for phase in STAMP if "stamp" in who else ORDINARY:
            by=rows[phase];w,e=by["warm"],by["empty"]
            required=mode=="default" or watch=="declared" or phase not in UNWATCHED
            if not by["same_verdict"] or by["same_checked_image"] is False:(required_failed if required else off).append(phase)
            assert any([w["status"]==0 and w["answer"], w["status"]==101 and w["error"]]),(name,case,phase)
            for slot,one in (("warm",w),("empty",e)):
                cargos.add(one["cargo_cdhash"])
                if mode=="default" and one["status"]==0:
                    tag=case+"/"+phase+"/"+slot
                    files=depfile(v,v.js(base+tag+"/verified.json"),HARD if who[0]=="P" else V2)
                    assert set(bind["marker_evidence"][tag][j][0] for j in range(len(files)))==set(files)
                    seen[tag]=files;allmarkers+=1
            hit=bool(last.get("raw") and w["raw"] and w["ld"]==0 and w["driver_processes"] and w["raw"] in w["receipt_products"] and set(w["seals"])&set(last["seals"]))
            phases[case+"/"+phase]={"same_required":required,"verdict_equal":by["same_verdict"],"raw_equal":by["same_raw"],"checked":by["same_checked_image"],"warm":w,"empty":e,"hit":hit,"providers":by["input"],"Rust_source_sha":by["trigger"]}
            if "stamp" in by:phases[case+"/"+phase]["replacement"]=by["stamp"]
            last=w
        assert required_failed==end["wrong_or_image_mismatch"][case];judgments[case]={"required_failed":required_failed,"opt_out_unwatched":off};marker_counts[case]=allmarkers
    assert len(cargos)==1 and set(seen)==set(bind["marker_evidence"]) and end["passed"]==all(not x["required_failed"] for x in judgments.values())
    assert len(phases)==196 and all(k[1]==subjects["stock_ld"] for k in v.lds)
    return dict(cargo=bind["cargo"],kernel_cargo=cargos.pop(),factory=fac,commands=2*len(phases),passed=end["passed"],judgments=judgments,
                physical_xcode=sorted(v.lds),complete_images=len(v.images),unique_objects=len(v.image_proofs.objs),distinct_recipes=len(v.image_proofs.recipes),
                true_producer_rows=sum(marker_counts.values()),prior_seal_hits=sum(x["hit"] for x in phases.values())),phases

def migration(v,subjects):
    top="versioned/migrations";record=v.js(top+"/terminal.json");output={};bindings={}
    for legacy in ("signed","classic"):
        for place in ("direct","library"):
            key=legacy+"-"+place;pref=top+"/"+key+"/";cases=v.js(pref+"terminal.json");runs=v.js(pref+"cargo-switches.json")
            assert sha(v.raw(pref+"terminal.json"))==record[key]["terminal"] and sha(v.raw(pref+"cargo-switches.json"))==record[key]["switches"]
            assert len(runs)==len(MIGRATION) and len({tuple(x["dev_ino"]) for x in runs})==len({tuple(x["driver"]) for x in runs})==1
            assert {x["driver"][-1] for x in runs}=={subjects["rust"]["C"]["driver"]};source,={x["source"] for x in runs}
            prior={};rows={}
            for change,(step,state,rust) in zip(runs,MIGRATION):
                assert change["phase"]==step;receiver=("aware" if step.startswith("upgrade") else legacy)
                verify_binding(change["cargo"],receiver,subjects)
                obs={};images={};phase=cases[step];assert phase==v.js(pref+step+"/compared.json") and phase["rust"]==rust
                val=STATES[state]
                for arm in ("warm","empty"):
                    path=pref+step+"/"+arm;one=v.provider_visit(path,place)
                    prior_digest=bindings.setdefault(receiver,one["cargo_cdhash"]);assert prior_digest==one["cargo_cdhash"]
                    assert (one["status"],one["answer"])==((0,[val,rust]) if val else (101,None))
                    assert phase[arm]==[one["status"],one["answer"],one["raw"]]
                    if val:
                        files=depfile(v,v.js(path+"/verified.json"),V2)
                        cert=v.image_proofs.proof(path,"edge-images",prior=prior if arm=="warm" else {})
                        assert files and cert["raw"]==one["raw"];images[arm]=cert
                    else:assert one["error"]
                    obs[arm]=one
                if val:assert v.image_proofs.same(images["warm"],images["empty"]) and phase["same_checked_image"]
                else:assert phase["same_checked_image"] is None
                rows[step]={"receiver":receiver,"warm":obs["warm"],"reference":obs["empty"],"raw_equal":phase["same_raw"],"images_equal":phase["same_checked_image"],
                            "arch":phase["archives"],"rust":rust,"source_sha":phase["trigger_sha256"],"driver":change["driver"]}
            assert record[key]["cases"]==2*len(rows);output[key]=rows
    assert len({s for s in bindings.values()})==3
    return output

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("zip",type=Path);ap.add_argument("dest",type=Path);args=ap.parse_args()
    with ZipFile(args.zip) as z:
        subj=sources(Receiver(z));families={};phases={};report={}
        for name in CASES:
            fam,rows=standard(Receiver(z,name),name,subj);families[name]=fam;phases[name]=rows;print(name,fam["commands"],fam["passed"],fam["prior_seal_hits"],flush=True)
        transitions=migration(Receiver(z),subj)
        assert len({f["kernel_cargo"] for f in families.values()})==3
        terminal=Receiver(z).js("versioned/terminal.json");assert terminal["passed"]==all(x["passed"] for x in families.values())
    report.update(subjects=subj,families=families,archive=digestfile(args.zip),transitions={k:len(v)*2 for k,v in transitions.items()})
    args.dest.mkdir(parents=True,exist_ok=True)
    write(args.dest/"matrix.json",pretty(report))
    write(args.dest/"provider-rows.json.gz",gzip.compress(compact(phases).encode(),mtime=0))
    write(args.dest/"migration-rows.json.gz",gzip.compress(compact(transitions).encode(),mtime=0))
