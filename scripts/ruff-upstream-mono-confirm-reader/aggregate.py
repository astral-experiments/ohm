"""Six independent physical parent/candidate pairs for the normal-layout Ruff CLI build."""
import argparse
from fractions import Fraction
from math import comb
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import traceback

# -I is supported; only this directory and the explicitly authenticated producer are imported.
sys.path.insert(0,str(Path(__file__).resolve().parent))
import evidence as e
import packets as p

def signed(q):
    return dict(fraction=str(q),percent=100*float(q))

def distribution(pairs, independent):
    values=[Fraction(parent-candidate,parent) for parent,candidate in pairs]
    if not values: return {"pairs": [], "inference":None}
    output={"pairs":[dict(P=a,C=b,reduction=signed(v)) for (a,b),v in zip(pairs,values)],
            "median":signed(statistics.median(values)),"inference":None}
    if independent:
        p.need(len(values)==6,"six distinct boots required for exact inference")
        positive=sum(x>0 for x in values); negative=sum(x<0 for x in values); n=positive+negative
        pval=min(Fraction(1),Fraction(2*sum(comb(n,i) for i in range(min(positive,negative)+1)),2**n))
        output["inference"]={"positive":positive,"negative":negative,"ties":6-n,"two_sided_exact_sign_p":str(pval),
                             "median_interval":{"coverage":"31/32","lower":signed(min(values)),"upper":signed(max(values))}}
    return output

def cohort(row):
    a,b=row["arms"]["P"],row["arms"]["C"]
    owners={}
    for owner in e.OWNERS:
        x,y=a["named"][owner],b["named"][owner]
        sx,sy=set(x["donor"]),set(y["donor"])
        owners[owner]={"P":len(sx),"C":len(sy),"gained":sorted(sy-sx),"lost":sorted(sx-sy),
                       "shared":sorted(sx&sy),"neither":sorted(set().union(*x.values(),*y.values())-(sx|sy))}
    storage={visit:{key:b["phases"][visit]["storage"][key]-a["phases"][visit]["storage"][key]
                   for key in ("bytes","files")} for visit in (*e.PHASES,"repair")}
    process={}
    for phase in e.PHASES:
        pc,cc=(r["phases"][phase]["clock"] for r in (a,b))
        process[phase]={k:cc[k]-pc[k] for k in ("instructions","user_us","system_us")}
        process[phase]["elapsed_ns"]=(cc["stop"]-cc["start"])-(pc["stop"]-pc["start"])
    graph={}
    for owner in e.OWNERS:
        graph[owner]={}
        for visit in ("B","A"):
            pg,cg=a["graphs"][owner][visit],b["graphs"][owner][visit]
            p.need(set(pg)==set(cg),"different available graph kinds")
            graph[owner][visit]={k:{key:cg[k][key]-pg[k][key] for key in pg[k]} for k in pg}
    return dict(owners=owners,C_minus_P_storage=storage,C_minus_P_graph=graph,C_minus_P_process=process)

def summarize(rows, admitted):
    rows=sorted(rows,key=lambda r:r["rank"])
    result={"paired_rank_order":[r["rank"] for r in rows],"phase":{}}
    for phase in e.PHASES:
        pairs=[tuple(r["arms"][arm]["phases"][phase]["clock"]["instructions"] for arm in "PC") for r in rows]
        result["phase"][phase]=distribution(pairs,admitted)
    result["edited_improved_on_all_six"]=(all(x["P"]>x["C"] for x in result["phase"]["A"]["pairs"])
                                          if admitted else None)
    result["per_pair_resources"]=[]
    for r in rows:
        data=cohort(r)
        result["per_pair_resources"].append(dict(rank=r["rank"],order=r["order"],
          native_donors={k:{"P":v["P"],"C":v["C"],"gained":len(v["gained"]),"lost":len(v["lost"])}
                         for k,v in data["owners"].items()},C_minus_P_edit_storage=data["C_minus_P_storage"]["A"],
          C_minus_P_edit_process=data["C_minus_P_process"]["A"]))
    return result

def free_space(work):
    p.need(shutil.disk_usage(work).free>17<<30,"isolation worker needs at least 17 GiB still free")

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run",type=int);parser.add_argument("--producer",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True);parser.add_argument("--work",type=Path)
    parser.add_argument("--register-only",action="store_true");args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    m,reg=e.readers(args.producer.resolve())
    enrollment=p.register(args.run)
    registered=out/"enrollment.json"
    if registered.exists(): p.need(p.load(registered)==enrollment,"previously frozen artifacts or job identities changed")
    else: p.save(registered,enrollment)
    if args.register_only: return 0
    p.need(os.environ.get("GITHUB_ACTIONS")=="true" and args.work,"complete ZIPs require an isolated hosted worker")
    work=args.work.resolve()
    p.need(not work.is_relative_to(out) and not out.is_relative_to(work),"separate output and scratch required")
    work.mkdir(parents=True,exist_ok=True);free_space(work)
    errors={};rows={};roots={};by_boot={};families={}
    def failure(tag,reason):
        errors[tag]=str(reason)
        p.save(out/"errors.json",errors)
    if enrollment["conclusion"]!="success": failure("workflow","terminal conclusion "+enrollment["conclusion"])
    for rank in range(6):
        k=str(rank);job=enrollment["jobs"][k];spec=enrollment["artifacts"].get(k)
        if job["conclusion"]!="success": failure("job-"+k,"terminal conclusion "+str(job["conclusion"]))
        if not spec: failure("artifact-"+k,"missing");continue
        try:
            free_space(work)
            p.save(out/("rank-"+k)/"job-upload.json",p.bind_job(args.run,job,spec))
            zip_path=p.archive(spec,work/"archives")
            root=work/("rank-"+k)
            # Whole archives remain immutable. Extract fresh for a new verification.
            p.unpack(zip_path,root)
            row=e.rank(root,rank,out/("rank-"+k),m,reg)
            p.save(out/("rank-"+k)/"evidence.json",row)
            p.save(out/("rank-"+k)/"cohort-and-resources.json",cohort(row))
            rows[rank]=row;roots[rank]=root
            by_boot.setdefault(row["identity"]["boot"],[]).append(rank)
        except Exception as ex:
            failure("rank-"+k,ex);traceback.print_exc()
    for boot,ranks in by_boot.items():
        if len(ranks)>1:failure("duplicate-boot-"+boot,",".join(map(str,ranks)))
    if 0 in rows:
        for rank in sorted(set(rows)-{0}):
            for rev in "AB":
                item=f"0-vs-{rank}-{rev}"
                try:
                    free_space(work)
                    families[item]=e.cross(roots[0],roots[rank],rev,m,work)
                except Exception as ex:failure(item,ex);traceback.print_exc()
                p.save(out/"cross-boot-native.json",families)
    admitted=(not errors and set(rows)==set(range(6)) and len(by_boot)==6 and len(families)==10)
    summary=summarize(list(rows.values()),admitted)
    summary.update(admitted=admitted,errors=errors,boot_ids=by_boot,source_run=args.run,source_head=p.HEAD,
                   factory=p.FACTORY,compiler_commits=e.SOURCE,ruff_source=reg["source"],registry_shared=239,registry_private=35)
    p.save(out/"summary.json",summary)
    print((out/"summary.json").read_text())
    # A negative, fully qualified experiment is saved as such. CI status reports evidence integrity.
    return 0 if admitted else 1

if __name__=="__main__":
    sys.exit(main())
