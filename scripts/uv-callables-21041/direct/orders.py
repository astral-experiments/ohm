"""Verify actual monotonic execution order separately from the measurements."""
import json


def observe(panel, raw, outer, study, registration):
    roles=study["roles"]
    half=registration["enrollment"]["balanced_orders_within_each_hold"]
    if half!=["PC","CP","CP","PC"] or len(raw)!=8 or len(outer)!=48:
        raise ValueError("wrong prespecified held order or missing visits")
    wanted=[[roles["PC".index(c)] for c in row] for row in half*2]
    if wanted!=study["orders"]:raise ValueError("carried an earlier sequence into this study")
    read=lambda p:json.loads(p.read_bytes())
    last=0;cold_count=0;ix=0
    for i,pair in enumerate(wanted):
        row=raw[i];modes=study["mode_orders"][i]
        if (row["pair"],row["hold"],row["order"],row["modes"])!=(i,i//4,pair,modes):raise ValueError("different raw pair assignment")
        for role in pair:
            seed=read(panel/f"opening-{i}-{role}"/"ordinary-A/ordinary.json")
            if not last<seed["start_ns"]<seed["end_ns"] or seed["exit"]!=0:raise ValueError("cold parent order changed or overlaps an earlier visit")
            last=seed["end_ns"];cold_count+=1
        for role in pair:
            for mode in modes:
                stamp=outer[ix];ix+=1
                if len(stamp)!=5 or stamp[:3]!=[i,role,mode]:raise ValueError("actual physical acquisition order differs")
                begin,end=stamp[3:]
                if not(type(begin)is int and type(end)is int and last<begin<end):raise ValueError("overlap, negative or reordered outer observations")
                if mode in ("wall","clock"):
                    rec=read(panel/f"pair-{i}-{role}"/mode/"ordinary.json")
                    if not(begin<=rec["start_ns"]<rec["end_ns"]<=end and rec["ns"]==rec["end_ns"]-rec["start_ns"]):raise ValueError("independently timed native command is outside its corresponding observation")
                if mode=="scoped" and not row["values"][role]["scoped"]["qualified"]:raise ValueError("scheduled scoped compiler capture failed")
                last=end
    return {"observed_ordinary_A_builds":cold_count,"observed_separate_acquisitions":ix,
            "literal_orders":["".join("PC"[roles.index(x)]for x in v)for v in wanted],"scoring_inputs_from_outer_watch":False}
