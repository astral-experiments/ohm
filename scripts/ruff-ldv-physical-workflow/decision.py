"""Admission and registered randomized-block analysis. No native binaries run in this reader."""
from fractions import Fraction
from itertools import combinations
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import tempfile
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import raw
from raw import assignment,need,t

PRIMARY=("option","new")


def fetch_slot(run,head,stage,slot,root):
    rows=t.fetch(f"runs/{run}/artifacts?per_page=100")["artifacts"]
    data=t.artifact(rows,f"ldv-physical-{stage}-originals-{slot}")
    result=t.artifact(rows,f"ldv-physical-{stage}-independent-{slot}")
    target=root/f"independent-{slot}.zip"
    fid=t.acquire(result,target,4<<20,floor=128<<20)
    with zipfile.ZipFile(target) as z:
        need(z.namelist()==["reopened.json"] and z.testzip() is None and z.getinfo("reopened.json").file_size<30<<20,
             "unverified independent raw readback")
        v=raw.read(z,"reopened.json")
    need(v["stage"]==stage and v["slot"]==slot and v["qa"]==head and v["run"]==run and
         v["assignment"]==assignment(stage,slot) and v["original_archive"]=={k:data[k] for k in v["original_archive"]} and
         not data["expired"] and v["source_docs"]==json.loads((HERE/"source-equivalence.json").read_bytes())["source_docs"] and v["factory"]==t.BUILD and v["confirmation"]==t.CONFIRM and
         re.fullmatch("[0-9a-f]{64}",v["terminal_sha"]),"incorrect independent original or source enrollment")
    return v,fid


def gate(run,head,root):
    t.run_identity(run,head)
    boots={}
    for i in (1,2):
        v,receipt=fetch_slot(run,head,"admit",i,root)
        suite=v["assignment"]["suites"][0]
        need(v["coverage"]["ordinary"]=={"option":12,"e2e":16}[suite] and
             v["coverage"]["probes"]==12 and not any(v["events"][suite][r] for r in ("P","C")) and
             len(v["bodies"]["native-bodies"])>=2 and (suite=="option" or v["coverage"]["wild"]>0),
             "missing unscored cold/dirty/invalid/clean/counter admissions")
        boots[suite]={"boot":v["boot"],"original":v["original_archive"],"aggregate":v["terminal_sha"],
              "independent":receipt,"coverage":v["coverage"],"roles":v["roles"]}
    need(set(boots)=={"option","e2e"} and len({v["boot"] for v in boots.values()})==2 and
         boots["e2e"]["roles"]==boots["option"]["roles"],"unmatched prior physical admissions")
    return {"run":run,"sha":head,"factory":t.BUILD,"boots":boots,"confirmation":t.CONFIRM}


def observations(z):
    pts={"option":{},"e2e":{}}
    for role in ("P","C"):
        for suite in pts:
            group=z["events"][suite][role]
            need(set(group)=={"old","new","unchanged"} and all(
                 type(row["instructions"]) is int and row["instructions"]>0 and row["enabled"]==row["running"]>0
                 and row["status"]==0 and re.fullmatch("[0-9a-f]{64}",row["raw_sha256"]) for row in group.values()),
                 "missing raw, retired or continuously scheduled hardware event")
            for phase in tuple(group)+("edit_plus_next",):
                n=group[phase]["instructions"] if phase in group else group["new"]["instructions"]+group["unchanged"]["instructions"]
                pts[suite].setdefault(phase,{})[role]=n
    return pts


def ratio_at(result,suite,phase):
    row=observations(result)[suite][phase]
    return Fraction(row["P"],row["C"])


def exact_randomization(rows):
    pairs=[]
    observed=Fraction(1,1)
    for q in rows:
        samples=observations(q)[PRIMARY[0]][PRIMARY[1]]
        order=q["assignment"]["compilers"]
        pairs.append((samples[order[0]],samples[order[1]]))
        observed*=Fraction(samples["P"],samples["C"])
    assignments=list(combinations(range(6),3))
    chosen=sum(math.prod(Fraction(f,s) if i in idx else Fraction(s,f) for i,(f,s) in enumerate(pairs))>=observed
               for idx in assignments)
    need(len(assignments)==20 and 1<=chosen<=20,"invalid restricted randomization distribution")
    return [chosen,20]


def analyze(rows,admissions):
    rows=sorted(rows,key=lambda r:r["slot"])
    need([q["slot"] for q in rows]==list(range(1,7)) and all(q["assignment"]==assignment("score",q["slot"])
         and q["stage"]=="score" and q["factory"]==t.BUILD and q["confirmation"]==t.CONFIRM for q in rows),
         "incomplete or changed chronological assignment")
    need(len({q["qa"] for q in rows})==len({q["run"] for q in rows})==1 and all(
        q["qa"]==admissions["sha"] for q in rows),"mixed execution sources")
    old={v["boot"] for v in admissions["boots"].values()}
    boots={q["boot"] for q in rows}
    need(len(boots)==6 and len(old)==2 and not (boots&old) and len({q["terminal_sha"] for q in rows})==6 and
         all(q["coverage"]["ordinary"]==28 and q["coverage"]["probes"]==24 for q in rows),"reused boot or missing observations")
    need(all(q["roles"]==admissions["boots"]["option"]["roles"] for q in rows),"different physically qualified compilers")
    summary={}
    for suite in ("option","e2e"):
        for phase in ("old","new","unchanged","edit_plus_next"):
            values=[ratio_at(q,suite,phase) for q in rows]
            summary[suite+"/"+phase]={"p_over_c":[float(x) for x in values],"median":float(statistics.median(values)),
                "geomean":math.exp(statistics.fmean(math.log(float(x)) for x in values)),"range":list(map(float,[min(values),max(values)]))}
    vals=[ratio_at(q,*PRIMARY) for q in rows]
    promoted=all(v>1 for v in vals)
    return {"study":"source-built whole-Cargo retired user instructions across six independent boots",
            "primary":"option/new","primary_all_above_one":promoted,"median_interval":summary["option/new"]["range"],
            "median_interval_coverage":"62/64 (96.875%) marginal, primary only; independent continuous paired effects",
            "restricted_one_sided_assignment_p":exact_randomization(rows),"sign_probability_all_positive_if_independent":[1,64] if promoted else None,
            "secondary":"descriptive only, retaining all adverse/null outcomes","results":summary,"admission":admissions,
            "blocks":[{"slot":q["slot"],"order":q["assignment"],"run":q["run"],"boot":q["boot"],"original":q["original_archive"],
                "terminal_sha":q["terminal_sha"],"whole_events":q["events"],"coverage":q["coverage"]} for q in rows]}


def main(kind,prior,output):
    head=os.environ["GITHUB_SHA"]
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        root=Path(tmp)
        admissions=gate(prior,head,root)
        if kind=="gate":
            result=admissions
        else:
            need(kind=="analyze","unknown decision route")
            run=int(os.environ["GITHUB_RUN_ID"])
            t.run_identity(run,head,completed=False)
            folder=root/"score";folder.mkdir()
            rows=[fetch_slot(run,head,"score",i,folder)[0] for i in range(1,7)]
            result=analyze(rows,admissions)
    t.save(output,result)
    print("Verified unscored admission" if kind=="gate" else "All six native/PMU reopeners passed and registered analysis is available",
          t.sha(output),flush=True)


if __name__=="__main__":
    main(sys.argv[1],int(sys.argv[2]),Path(sys.argv[3]))
