"""Recompute the registered six-pair endpoints from the permanent raw kernel clock records."""
from pathlib import Path
import json
import sys

BASE=Path(__file__).resolve().parent;sys.path.insert(0,str(BASE.parent))
from aggregate import paired
from confirmation_plan import registration
r=json.loads((BASE/"six-pair-results.json").read_bytes())
clocks=json.loads((BASE/"kernel-clocks.json").read_bytes())
admit=json.loads((BASE/"originals.json").read_bytes())
ranked=json.loads((BASE/"confirmation-runs.json").read_bytes())
assert len(set(admit["boots"]))==len({v["runner_id"]for v in admit["originals"]})==len(clocks)==6
measured={}
for rank,(s,k,a)in enumerate(zip(r["scopes"],clocks,admit["originals"])):
    assert s["transport"]==a and k["run"]==ranked["runs"][rank]==a["run"] and s["order"]==registration(rank)["spec"]["ranks"][rank]
    assert s["boot"]==admit["boots"][rank] and k["source_sha256"]==a["sha256"] and s["qualified"]
    records=k["records"]
    def legacy(path):
        rr=records[path+"/hardware.json"];assert rr["enabled"]==rr["running"]>0 and rr["status"]==0
        return rr["instructions"]
    def inherited(path):
        rr=records[path+".epochs/epochs.tsv"];t=rr["terminal"].split()
        assert len(t)==7 and t[0:2]==["F","0"] and t[-1]==t[-2] and int(t[-1])>0 and int(t[4])>0
        return int(t[4])
    values={}
    for i,role in enumerate(s["order"],1):
        b=f"visit-{i}-{role}/";values[role]=dict(edited_rustc=inherited(b+"owner/edit"),edited_cargo=legacy(b+"plain/edit"),edited_independent_cargo=inherited(b+"whole/edit"),parser_rustc=inherited(b+"parser/owner"),parser_cold=legacy(b+"parser/cold"),cold_cargo=legacy(b+"cold"),unchanged_cargo=legacy(b+"plain/new-idle"))
        assert s["native"][role]==registration(rank)["spec"]["pilot"]["native"] and s["zip"]==registration(rank)["spec"]["pilot"]["zip"]
        if role=="P":
            for endpoint,suffix in (("fixed_rustc","run"),("nonincremental_rustc","nonincremental")):
                p,c,pp=[inherited(b+f"fixed-operand/{j}{v}/{suffix}")for j,v in enumerate("PCP",1)]
                observed=min(1-c/p,1-c/pp);measured.setdefault(endpoint,[]).append(observed)
    for end,p in values["P"].items():measured.setdefault(end,[]).append(1-values["C"][end]/p)
assert {k:paired(v)for k,v in measured.items()}==r["estimators"] and r["qualified"]
for k in ("edited_rustc","edited_cargo","fixed_rustc","nonincremental_rustc"):
    x=r["estimators"][k];print(f"{k:<23} {x['median']:>8.4%}   {x['median_interval_96_875'][0]:.4%}–{x['median_interval_96_875'][1]:.4%}   p={x['two_sided_sign_p']}")
