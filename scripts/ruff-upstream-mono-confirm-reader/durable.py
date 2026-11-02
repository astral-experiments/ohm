"""Retain and verify the original six-boot clock records and native evidence identities."""
import argparse
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import aggregate
import evidence
import packets as p

def compact(result):
    summary=p.load(result/"summary.json"); registration=p.load(result/"enrollment.json")
    p.need(summary["admitted"] and not summary["errors"] and registration["conclusion"]=="success","unadmitted source cohort")
    packet={"schema":"normal-ruff-mono-owner-clocks-v1","study":registration["run"],"head":registration["head"],
            "qualifier":registration["normal_qualification"],"factory":summary["factory"],"compiler_commits":summary["compiler_commits"],
            "ruff":summary["ruff_source"],"registry":{"shared":239,"private":35,
            "roster_sha256":"1543d3b84184059d74c9a48c65375d85d16013a357fd4f92316544876d545be1"},
            "whole_cargo":summary["phase"], "edited_improved_on_all_six":summary["edited_improved_on_all_six"],
            "cross_boot_native":p.load(result/"cross-boot-native.json"),"ranks":[]}
    for rank in range(6):
        d=result/f"rank-{rank}";r=p.load(d/"evidence.json");delta=p.load(d/"cohort-and-resources.json")
        job=registration["jobs"][str(rank)]; artifact=registration["artifacts"][str(rank)]
        row={"rank":rank,"order":r["order"],"boot":r["identity"]["boot"],"cpus":r["identity"]["cpus"],
             "job":job,"artifact":artifact,"source_archive_url":f"https://github.com/{p.REPO}/actions/runs/{p.SOURCE_RUN}/artifacts/{artifact['id']}",
             "job_log_sha256":p.load(d/"job-upload.json")["log_sha256"],"native":r["native"],"arms":{},
             "C_minus_P_edit_storage":delta["C_minus_P_storage"]["A"],"C_minus_P_edit_graph":delta["C_minus_P_graph"]}
        for arm in "PC":
            a=r["arms"][arm]
            row["arms"][arm]={"clock":{phase:a["phases"][phase]["clock"] for phase in evidence.PHASES},
                "whole":{phase:a["phases"][phase]["whole"] for phase in (*evidence.PHASES,"repair")},
                "storage":{phase:a["phases"][phase]["storage"] for phase in (*evidence.PHASES,"repair")},
                "dirty":{phase:a["phases"][phase]["dirty"] for phase in (*evidence.PHASES,"repair")},
                "objects_sha256":a["objects_sha256"],"named_roster_sha256":evidence.canonical(a["named"]),
                "donors":{owner:len(groups["donor"]) for owner,groups in a["named"].items()}}
        packet["ranks"].append(row)
    return packet

def verify(q):
    p.need((q["schema"],q["study"],q["head"],q["qualifier"],q["factory"],q["compiler_commits"]) ==
           ("normal-ruff-mono-owner-clocks-v1",p.SOURCE_RUN,p.HEAD,p.QUALIFIER,p.FACTORY,evidence.SOURCE),"wrong experiment")
    p.need(q["registry"]=={"shared":239,"private":35,
           "roster_sha256":"1543d3b84184059d74c9a48c65375d85d16013a357fd4f92316544876d545be1"} and
           [(s["A"],s["B"]) for s in q["ruff"]]==[("b5dba861cc38e3f7fb4524c9ceba3e01a474ea13",
           "7b13f01ba1569887a25670820764b24c206da8e5")],"wrong source or registry roster")
    rows=sorted(q["ranks"],key=lambda r:r["rank"])
    p.need([r["rank"] for r in rows]==list(range(6)) and [r["order"] for r in rows]==["PC","CP"]*3 and
           len({r["boot"] for r in rows})==len({r["job"]["id"] for r in rows})==len({r["artifact"]["id"] for r in rows})==6,
           "wrong independent pairs")
    for row in rows:
        i=row["rank"];artifact=row["artifact"]
        p.need(row["job"]["name"]==f"ordinary ({i})" and row["job"]["conclusion"]=="success" and
               artifact["name"]==p.NAME+str(i) and re.fullmatch("sha256:[a-f0-9]{64}",artifact["digest"]) and
               row["source_archive_url"].endswith(f"/actions/runs/{p.SOURCE_RUN}/artifacts/{artifact['id']}"),"wrong original archive")
        for arm in "PC":
            a=row["arms"][arm]
            p.need(set(a["clock"])==set(evidence.PHASES) and set(a["whole"])=={*evidence.PHASES,"repair"},
                   "wrong phase inventory")
            for phase,c in a["clock"].items():
                p.need(c["code"]==c["event_errno"]==0 and c["instructions"]>0 and c["enabled"]==c["running"]>0
                       and c["stop"]>c["start"],"invalid hardware window")
            for phase,native in a["whole"].items():
                ref=row["native"]["B" if phase=="B" else "A"]
                p.need(native=={"reader":ref["reader"],"cli":ref["refs"][arm]},"different complete native reference")
    for phase in evidence.PHASES:
        counts=[tuple(row["arms"][arm]["clock"][phase]["instructions"] for arm in "PC") for row in rows]
        p.need(aggregate.distribution(counts,True)==q["whole_cargo"][phase],"different raw-clock inference: "+phase)
    p.need(q["edited_improved_on_all_six"]==all(r["P"]>r["C"] for r in q["whole_cargo"]["A"]["pairs"]),
           "different primary direction")
    p.need(set(q["cross_boot_native"])=={f"0-vs-{i}-{rev}" for i in range(1,6) for rev in "AB"},"missing cross-boot proof")
    for i in range(1,6):
        for rev in "AB":
            item=q["cross_boot_native"][f"0-vs-{i}-{rev}"]
            pair=[rows[j]["native"][rev]["refs"]["P"] for j in (0,i)]
            p.need(item["shas"]==pair and item["revision"]==rev and
                   (item["proof"]=={"identical":True} if pair[0]==pair[1] else
                    set(item["proof"])=={"debug","ranges","old","new","strings"}),"wrong parent reference family")
    return q["whole_cargo"]["A"]

if __name__=="__main__":
    a=argparse.ArgumentParser(description=__doc__);a.add_argument("file",type=Path);a.add_argument("--from-results",type=Path)
    args=a.parse_args()
    packet=compact(args.from_results) if args.from_results else p.load(args.file)
    primary=verify(packet)
    if args.from_results:p.save(args.file,packet)
    print(json.dumps(primary,indent=2))
