"""Reopen every original timed trio, complete products and both raw diagnostic timelines."""
from fractions import Fraction
import gzip
import json
from itertools import permutations
from math import comb
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import core as c
import cargo_log
import timeline
import wire_shape
from products import comparable
from screen import output_controls

m=c.m


def metrics(rows,control,candidate,threshold):
    ratios=[Fraction(r["ns"][control],r["ns"][candidate]) for r in rows]
    n=len(ratios);above=sum(v>threshold for v in ratios)
    need=c.guard
    need(n==12 and len(set(tuple(r["order"]) for r in rows))==6,"twelve balanced trios")
    return {"control":control,"treatment":candidate,"threshold":threshold,"n":n,
            "median_paired_ratio":float(median(ratios)),"min":float(min(ratios)),"max":float(max(ratios)),
            "descriptive_order_statistic_interval":[float(sorted(ratios)[2]),float(sorted(ratios)[9])],
            "hold_medians":[float(median(ratios[:6])),float(median(ratios[6:]))],
            "order_strata":{" / ".join(order):float(median(x for x,r in zip(ratios,rows) if r["order"]==list(order)))
                            for order in permutations(c.ROLES)},
            "above_parity":sum(v>1 for v in ratios),"above_double":sum(v>2 for v in ratios),"above_threshold":above,
            "one_sided_sign_p":float(Fraction(sum(comb(n,i) for i in range(above,n+1)),2**n)),
            "paired_ratios":[float(v) for v in ratios]}


def score(out,parser,commit_source,timer_source,probe_source):
    roles=c.ROLES; panel=out/"uv-client";plan=m.read(c.HERE/"measurement-plan.json")
    c.guard(roles==plan["roles"] and all(set(map(tuple,plan["orders"][offset:offset+6]))==set(permutations(roles))
                                        for offset in (0,6)),"all six role orders under each independently built history")
    c.guard(plan["holds"]==[0]*6+[1]*6,"independent halves")
    host=m.read(out/"boot.json");machine=host["machine"]
    c.guard(host["calibration"]==m.filesha(out/"clock-pre/passed.json") and host["plan"]==c.PAIR["plan"] and
            machine["boot"] not in {v["boot"] for v in plan["prior_boots"].values()} and len(machine["cpus"])==8,
            "specific calibrated machine")
    def calibrated(which):
        d=out/which;r=m.read(d/"passed.json")
        c.guard(r["clock_source"]==timer_source and r["source"]==probe_source and r["machine"]==machine,"calibration provenance")
        samples=[]
        for i in range(5):
            for delay in (0,3,13,31,53):
                p=d/f"probe-{i}-{delay}";a,b=map(int,(p/"cargo.stdout").read_bytes().split());s=m.read(p/"ordinary.json")
                overhead=s["ns"]-(b-a)
                c.guard(s["start_ns"]<=a<=b<=s["end_ns"] and s["ns"]==s["end_ns"]-s["start_ns"] and
                        not s["deadline_fired"] and s["exit"]==0 and b-a>=delay*1_000_000 and 0<=overhead<=12_000_000,
                        "real short-child calibration")
                samples.append({"ms":delay,"internal_ns":b-a,"external_ns":s["ns"],"enclosing_overhead_ns":overhead})
        c.guard(samples==r["samples"] and median(x["enclosing_overhead_ns"] for x in samples)<=4_000_000,"median precision")
        bad=m.read(d/"nonzero/ordinary.json");dead=m.read(d/"deadline/ordinary.json")
        c.guard(bad["exit"]==r["nonzero_exit"]==17 and not bad["deadline_fired"] and
                dead["exit"]==r["deadline_exit"]==-9 and dead["deadline_fired"] and
                60_000_000<=dead["ns"]==r["deadline_ns"]<1_000_000_000 and not (d/"deadline/cargo.stdout").read_bytes(),
                "known exit and independently killed child")
        return {"median_enclosing_overhead_ns":median(x["enclosing_overhead_ns"] for x in samples),
                "max_enclosing_overhead_ns":max(x["enclosing_overhead_ns"] for x in samples),
                "pass_sha256":m.filesha(d/"passed.json")}
    cal={k:calibrated(k) for k in ("clock-pre","clock-post")}
    checked={};baseline={};streams={};seeds={};argv=None
    def product(path):
        obj=m.read(path/"products.json")
        c.guard(len(obj["raw"])==37 and obj["semantic"].keys()==obj["structural"].keys()==obj["raw"].keys() and
                obj["relative_paths"].keys()==obj["raw"].keys()and len(obj["public_sidecars"])==415,"all real products")
        for key,(size,digest) in obj["raw"].items():
            if digest not in checked:
                raw=gzip.decompress((out/"rmeta-by-content"/(digest+".gz")).read_bytes())
                c.guard(m.digest(raw)==digest and size==len(raw),"original metadata bytes")
                name=key.split("@")[0];dec=parser(raw,name)
                checked[digest]=(m.canon(c.deep.project(lambda *_:dec,raw,name)),wire_shape.shape(*dec[:2]))
            semantic,shape=checked[digest]
            c.guard(semantic==m.canon(obj["semantic"][key]) and shape==obj["structural"][key],"complete cold native semantics")
        return obj
    timeline_rows={}
    for hold in (0,1):
        by_phase={}
        for role in roles:
            q=panel/f"hold-{hold}-{role}"
            states={l:product(q/l) for l in ("ordinary-A","settled-A","typed-fresh-A","warm-B","settled-B","typed-fresh-B","cold-B","typed-B")}
            c.guard(states["ordinary-A"]==states["settled-A"]==states["typed-fresh-A"] and
                    states["warm-B"]==states["settled-B"]==states["typed-fresh-B"]==states["typed-B"] and
                    comparable(states["cold-B"])==comparable(states["warm-B"]),"native, diagnostic and cold guard")
            for label in ("typed-fresh-A","typed-fresh-B"):
                v=m.read(q/label/"roster.json")
                c.guard(v["commands"]==[] and not v["artifact_crates"] and not v["diagnostics"],"settled check worked")
            v=m.read(q/"typed-B/roster.json");sel=sorted(v["commands"])
            c.guard(len(sel)==8 and sorted(x[x.index("--crate-name")+1] for x in sel)==sorted(c.P["edited_workspace_roster"])
                    and not v["diagnostics"] and v["completed"]["success"],"actual eight commands")
            if argv is None: argv=sel
            c.guard(argv==sel and m.digest(m.canon(sel))==c.P["prior_actual_argv_sha256"],"cross-role compiler argv")
            if hold==0:
                a,b,g=(m.read(q/l/"witness.json") for l in ("behavior-A","behavior-B","behavior-cold-B"))
                c.guard(a["exact"] and b["exact"] and g["exact"] and a["output_sha256"]==b["output_sha256"]==g["output_sha256"]
                        and a["state"]["source"]==c.P["A_file"] and b["state"]["source"]==g["state"]["source"]==c.P["B_file"]
                        and a["fixture_sha256"]==b["fixture_sha256"]==g["fixture_sha256"]==m.filesha(c.HERE/"witness.rs")
                        and a["inputs"]["uv_pypi_types"]!=b["inputs"]["uv_pypi_types"],"linked real parser behavior")
            for ph in ("ordinary-A","warm-B","cold-B"):by_phase.setdefault(ph,[]).append(states[ph]["structural"])
            baseline[hold,role]=states["warm-B"];streams[hold,role]=output_controls(q/"warm-B");seeds[hold,role]=m.read(q/"checkpoint.json")["sha256"]
        c.guard(all(all(q==v[0] for q in v) for v in by_phase.values()),"cross-compiler definition identities")
        role=roles[-1];q=panel/f"hold-{hold}-{role}/build-analysis";timeline_rows[str(hold)]={}
        for label in ("plain-B","typed-B","settled-B"):
            p=q/label;clock=m.read(p/"ordinary.json");args=[*c.CHECK,"-Zbuild-analysis",*(["-vv","--message-format=json"]if label!="plain-B"else [])]
            c.guard(clock["argv"]==args and clock["env"]==m.ENV|{"CARGO_BUILD_ANALYSIS_ENABLED":"true"} and clock["exit"]==0 and
                    product(p)==baseline[hold,role],"logging altered compilation")
            x=timeline.read((p/"cargo-analysis.jsonl").read_bytes(),args,m.SRC,commit_source,c.P["edited_workspace_roster"] if label!="settled-B" else [],"uv_client")
            c.guard(x==m.read(p/"timeline.json"),"replayed unrounded timeline differs")
            if label=="plain-B":c.guard(output_controls(p)==streams[hold,role],"logger altered native diagnostics")
            else:
                events=timeline.cargo_messages((p/"cargo.stdout").read_bytes(),x["run_id"])
                active=sorted(row["target"]["name"].replace("-","_") for row in events
                              if row["reason"]=="compiler-artifact" and not row["fresh"])
                c.guard(events[-1]["success"] and sum(row["reason"]=="compiler-artifact" for row in events)==486 and
                        active==(sorted(c.P["edited_workspace_roster"]) if label=="typed-B" else []) and
                        sorted(cargo_log.running_rustcs((p/"cargo.stderr").read_bytes(),m.RUSTC))==(argv if label=="typed-B" else []),
                        "real logged compiler argv or zero unchanged launches")
            timeline_rows[str(hold)][label]=x
    c.guard(all(seeds[0,r]!=seeds[1,r] for r in roles),"second A history is not independent")
    raw=m.read(panel/"raw-trios.json");c.guard(len(raw)==12,"incomplete native trios")
    previous=0;result=[]
    for i,item in enumerate(raw):
        hold=plan["holds"][i];order=plan["orders"][i];values={}
        c.guard(item["trio"]==i and item["hold"]==hold and item["order"]==order,"trio order")
        for role in order:
            p=panel/f"trio-{i}-{role}/wall";v=m.read(p/"ordinary.json");s=m.read(p/"source.json")
            c.guard(v["argv"]==v["invoked"]==c.CHECK and v["env"]==m.ENV and v["mode"]=="native-blocking" and
                    v["boot"]==machine["boot"] and v["cpus"]==machine["cpus"] and not v["deadline_fired"] and v["exit"]==0 and
                    previous<v["start_ns"]<v["end_ns"] and v["ns"]==v["end_ns"]-v["start_ns"],"native clock or chronology")
            previous=v["end_ns"]
            c.guard(s["head"]==c.P["A"] and s["working_tree"]==c.P["B_tree"] and s["source"]==c.P["B_file"] and s["lock"]==c.P["lock_sha256"] and
                    product(p)==baseline[hold,role] and output_controls(p)==streams[hold,role] and
                    item["values"][role]=={"ns":v["ns"],"checkpoint_sha256":seeds[hold,role],"receipt_sha256":m.filesha(p/"ordinary.json")},
                    "same real edit, carried outputs, and native receipts")
            values[role]=v["ns"]
        result.append({"trio":i,"hold":hold,"order":order,"ns":values})
    family=[metrics(result,l,r,t) for l,r,t in plan["hypotheses"]];last=0
    for index,entry in enumerate(sorted(family,key=lambda x:x["one_sided_sign_p"])):
        last=max(last,min(1,(2-index)*entry["one_sided_sign_p"]))
        entry["holm_p"]=last
        entry["qualified"]=last<=.05 and min(entry["hold_medians"])>entry["threshold"]
    return {"design":"12 restored native trios in two independently built histories; all six orders in each",
            "boot":machine,"clock":cal,"raw_trios":result,"paired_metrics":family,
            "unique_native_products_verified":len(checked),"diagnostic_timelines":timeline_rows}


if __name__=="__main__":
    w,tmp=c.host();out=w/"trait-results"
    reader=c.deep.parser(tmp/"uv22874-readers/check-root-20261101/ctfe-root-attribution/metadata.py")
    result=score(out,reader,c.PAIR["arms"][c.ROLES[-1]]["source"]["commit"],
                 m.filesha(c.HERE/"wall_clock.py"),m.filesha(c.HERE/"wall_probe.c"))
    m.save(out/"uv-client/trio-score.json",result)
    print(json.dumps(result["paired_metrics"],sort_keys=True),flush=True)
