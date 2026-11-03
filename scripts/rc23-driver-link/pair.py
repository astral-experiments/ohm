"""Read both same-run QA artifacts and compare the observed ELF effects on shared exports."""
import gzip
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import gate as g
import policy

def pair(folders):
    roles={};native={};corpus={};scopes={}
    for arm,p in folders.items():
        product=g.read(p/"role.json");src=g.read(p/"source.json")
        assert product["role"]==src["role"]==arm and src["coordinator"]==os.environ["GITHUB_SHA"]
        assert product["source_sha256"]==g.sha(p/"source.json")
        proofs=g.read(p/"native-proofs.json")
        for name,sha in proofs.items():assert g.sha(p/name)==sha,name
        for name,sha in product["qa"].items():assert g.sha(p/name)==sha
        strat=g.read(p/"capacity/summary.json")
        assert strat["full_role_recipe_and_original_qa_completed"] is True
        assert product["execution_pgo"]==g.PGO and product["effective_cargo"]==g.SIGNED["cargo"]
        assert src["release_files"]==g.POLICY["release_files"]
        rows=json.loads(gzip.decompress((p/"driver-witness/installed.json.gz").read_bytes()))
        ex=set()
        for rule in product["policy_evidence"]["policies"].values():
            row=policy.exports(policy.untar(rule["exceptions"],p/"driver-witness"))
            if ex:assert row==ex
            ex=row
        assert bool(ex)==(arm=="T") and src["original"]["source_trees"]==g.POLICY["sources"]
        roles[arm]={"source":src["commit"],"tree":src["tree"],"archive_sha256":product["archive_sha256"],"archive_bytes":product["archive_bytes"],"role_sha256":g.sha(p/"role.json"),"driver":product["driver"],"whole_inventory":product["sdk_inventory_sha256"],"capacity":g.sha(p/"capacity/summary.json")}
        native[arm]=product;corpus[arm]=rows;scopes[arm]=ex
    assert roles["R"]["source"]==g.BASE and roles["T"]["source"]==g.read(g.HERE/"source.json")["commit"]
    R,T=(corpus[x] for x in ("R","T"));ex=scopes["T"]
    rsy={x[0]:x[1:] for x in R["symbols"]};tsy={x[0]:x[1:] for x in T["symbols"]}
    common=set(rsy)&set(tsy)
    shared={n for n in common if rsy[n]==tsy[n]==[1,2,0,True] and n.startswith("_R")}
    before=R["own_strong_v0_slots"];after=T["own_strong_v0_slots"]
    selected={n for n in shared if n in before and n not in ex}
    protected={n for n in shared if n in before and n in ex}
    assert len(selected)>1000 and not any(n in after for n in selected)
    # A remaining real foreign row must exercise the contrasting dynamic route.
    assert len([n for n in protected if n in after])>5
    for arm,v in native.items():
        test=v["policy_evidence"]["live_preload"]["preloaded"]
        assert test["foreign"]["overridden"] and test["compiler"]["overridden"]==(arm=="R")
    return {"roles":roles,"signed_cargo":g.SIGNED["cargo"],"common_dynamic_names":len(common),"shared_v0_global_functions":len(shared),
            "previously_named_proven_local_functions":len(selected),"previously_named_proven_local_slots":sum(before[n] for n in selected),
            "still_named_local_slots":sum(after.get(n,0) for n in selected),"previously_named_exception_functions":len(protected),
            "still_named_exception_functions":sum(n in after for n in protected),"shared_name_differences":sorted(n for n in common if rsy[n]!=tsy[n]),
            "R_only":len(set(rsy)-common),"T_only":len(set(tsy)-common),"performance_samples":0}
if __name__=="__main__":
    w=g.checkout("pair");out=w/"pair-evidence";out.mkdir()
    result=pair({a:w/"incoming"/a for a in ("R","T")})
    g.save(out/"pair.json",result)
