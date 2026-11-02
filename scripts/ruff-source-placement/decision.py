"""Acquire only this pilot's checked receipts, verify both native boots, then report all paired ratios."""
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import HERE, REPO, enrollment, need, save, sha
from receiver import FACTORY, archive, api


def get(run,head,stage,i,root,current):
    fname=f"placement-{stage}-verified-{i}";zfile=root/(fname+".zip")
    rec=archive(run,head,fname,zfile,8<<20,current=current)
    with zipfile.ZipFile(zfile) as z:
        need(z.namelist()==["reopened.json"] and z.getinfo("reopened.json").file_size<64<<20,"wrong portable receipt")
        v=json.loads(z.read("reopened.json"))
    rows=api(f"repos/{REPO}/actions/runs/{run}/artifacts?per_page=100")["artifacts"]
    raw,=[a for a in rows if a["name"]==f"placement-{stage}-raw-{i}"]
    need(not raw["expired"] and v["raw"]=={k:raw[k] for k in v["raw"]} and raw["workflow_run"]["id"]==run and
         (v["qa"],v["run"],v["stage"],v["slot"])==(head,run,stage,i) and v["source"]==enrollment()["roles"] and
         set(v["roles"])=={"P","C"} and len(v["raw_consumer_bodies"]["native-bodies"])>=2,"different enrolled/custodied input")
    return v,rec


def gate(run,head,root):
    seen={};boots={};refs={};kit=None;roles=None
    for i,s in enumerate(("option","e2e"),1):
        v,receipt=get(run,head,"admit",i,root,False)
        need(v["suites"]==[s] and v["order"]==(["P","C"] if i==1 else ["C","P"]) and all(not x for x in v["pmu"][s].values()),
             "wrong native or scored admission")
        need(all(set(x)>={"old","new","unchanged","invalid","repair","clean-new"} for x in v["native"][s].values()),"missing ordinary native transitions")
        if s=="option":
            need(v["native"][s]["C"]["new"]["hits"].get("ruff_workspace",0)>0 and
                 set(v["durable"])=={"round-trip","object-corrupt","optional-corrupt","independent-empty-old"} and
                 set(v["check_handoff"])=={"P","C"},"missing witnessed real hash-corrupt, reverse or check→build history")
        else:
            need(all(v["native"][s][r]["new"]["wild"]==v["native"][s][r]["unchanged"]["wild"]==1 for r in ("P","C")),"missing e2e stock links")
        role_shas={r:{k:a["sha"] for k,a in ks.items()} for r,ks in v["roles"].items()}
        need(roles is None or role_shas==roles,"different physical file content across boots")
        roles=role_shas
        need(kit is None or v["kit"]==kit,"different SDK across admissions")
        kit=v["kit"];boots[s]=v["boot"];refs[s]={"checked":receipt,"raw":v["raw"],"terminal":v["terminal_sha256"]}
    need(len(set(boots.values()))==2,"both admissions used one boot")
    return {"qa":head,"run":run,"factory":FACTORY,"kit":kit,"source":enrollment()["roles"],"boots":boots,"original":refs}


def decide(run,head,prior,root):
    native=gate(prior,head,root)
    groups={};boots=set(native["boots"].values());wanted=json.loads((HERE/"protocol.json").read_bytes())["assignments"]
    for i in (1,2):
        v,receipt=get(run,head,"score",i,root,True);schedule=wanted[i-1]
        need(v["suites"]==schedule["suites"] and v["order"]==schedule["roles"] and v["boot"] not in boots and v["kit"]==native["kit"],"wrong matched pair or reused boot")
        boots.add(v["boot"]);groups[i]={"boot":v["boot"],"independent":receipt,"raw":v["raw"],"visits":{}}
        for s in v["suites"]:
            group={}
            for phase in ("old","new","unchanged"):
                x={r:v["pmu"][s][r][phase] for r in ("P","C")}
                need(all(a["instructions"]>0 and a["enabled"]==a["running"]>0 and a["status"]==0 for a in x.values()),"bad actual hardware sample")
                group[phase]={"parent":x["P"]["instructions"],"candidate":x["C"]["instructions"],"ratio":x["P"]["instructions"]/x["C"]["instructions"],
                              "disk":{r:v["native"][s][r][phase]["disk"] for r in ("P","C")},"rss":{r:v["native"][s][r][phase]["rss"] for r in ("P","C")}}
            groups[i]["visits"][s]=group
    return {"source":native["source"],"native":native,"pairs":groups,"two_pair_primary_screen":all(v["visits"]["option"]["new"]["ratio"]>2 for v in groups.values()),
            "scope":"Two reversed pairs; all whole-command retired userspace counts retained separately. No significance test, elapsed claim or effect pooling."}


if __name__=="__main__":
    mode,prior,dest=sys.argv[1:];head=os.environ["GITHUB_SHA"]
    with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as d:
        r=gate(int(prior),head,Path(d)) if mode=="gate" else decide(int(os.environ["GITHUB_RUN_ID"]),head,int(prior),Path(d))
    save(Path(dest),r)
