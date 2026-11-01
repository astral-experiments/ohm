"""Read whole-root PMU and native-wall pairs separately, using only raw retained clocks."""
from fractions import Fraction
import json,re,sys
from pathlib import Path
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import material as m
ROLES=("stock_ctfe318","fa7a_stack_ctfe318")
def positive(v):return type(v) is int and v>0
def counter(p):
    r=m.read(p)
    m.guard(set(r)=={"code","instructions","event_errno","start","stop","enabled","running","user_us","system_us"} and
       all(type(v) is int for v in r.values()) and r["code"]==r["event_errno"]==0 and positive(r["instructions"]) and
       positive(r["running"]) and r["running"]==r["enabled"] and positive(r["start"]) and r["stop"]>r["start"] and
       min(r["user_us"],r["system_us"])>=0 and r["user_us"]+r["system_us"]>0,"invalid or multiplexed whole-process PMU")
    return r["instructions"]
def median(vals):
    xs=sorted(map(Fraction,vals));n=len(xs);return (xs[n//2]+xs[(n-1)//2])/2
def num(v):return {"value":float(v),"fraction":f"{v.numerator}/{v.denominator}"}
def estimate(pairs,*,orders=None,roles=ROLES):
    orders=m.P["orders"] if orders is None else orders
    m.guard(len(pairs)==len(orders)==12 and len(set(roles))==2,"incomplete or rerolled panel");metrics={}
    for metric in ("user_instructions","wall_nanoseconds"):
        ratios=[];holds={};strata={}
        for row,expected in zip(pairs,orders,strict=True):
            m.guard(row["design"]==expected and set(row["values"])==set(roles)==set(expected["roles"]),"pair identity/order")
            v=[row["values"][r][metric] for r in roles];m.guard(all(positive(n) for n in v),"invalid arm value")
            x=Fraction(*v);ratios.append(x);holds.setdefault(expected["hold"],[]).append(x);strata.setdefault(expected["roles"][0],[]).append(x)
        m.guard(all(len(v)==6 for v in [*holds.values(),*strata.values()]) and len(holds)==len(strata)==2,"unbalanced holdout/order")
        x=sorted(ratios);hm={k:median(v) for k,v in holds.items()};sm={k:median(v) for k,v in strata.items()}
        metrics[metric]={"paired_ratios":[num(a) for a in ratios],"median":num(median(x)),"interval_order_2_11":[num(x[1]),num(x[10])],
          "median_interval_coverage_pct":99.365234375,"hold_medians":{str(k):num(v) for k,v in hm.items()},"first_role_medians":{k:num(v) for k,v in sm.items()},
          "wins_over_parity":sum(v>1 for v in x),"wins_over_double":sum(v>2 for v in x),"repeatable_above_parity":min(x[1],*hm.values(),*sm.values())>1,
          "repeatable_above_double":min(x[1],*hm.values(),*sm.values())>2}
    return metrics
def raw(path):
    with ZipFile(path/"workspace-rmeta.zip") as z:
        exp=m.read(path/"workspace-products.json");m.guard(set(z.namelist())==set(exp)==set(m.shape()[1]) and len(z.infolist())==70,"raw file inventory")
        for n in z.namelist():
            b=z.read(n);m.guard([len(b),m.digest(b)]==exp[n],"raw hash mismatch")
    return exp
def fixture(path,state):
    r=m.read(path/"receipt.json");want=m.CASE["fixture"][state];rows=re.findall(r"^test (workspace::tests::exclude_package\w*) \.\.\. ok$",(path/"stdout").read_text(),re.M)
    m.guard(r["tree"]==m.CASE[state+"_tree"] and r["exit"]==0 and sorted(rows)==r["passed"]==want,"real source witness")
def semantic(r,left,right,shape):
    expected={k for k in left if left[k]!=right[k]};terminal,=[k for k,v in shape.items() if v["name"]=="uv"]
    m.guard(r["all_70_roots_and_deps_equal"] is True and r["actual_downstream"] and set(r["raw_drift"])==expected and
            set(r["deep"])==expected|{terminal},"cold proof coverage")
    for rel,v in r["deep"].items():
        p=v["projection"];h=p["header"]
        m.guard(v["raw_equal"]==(rel not in expected) and h["crate_name"]==shape[rel]["name"] and
           all(re.fullmatch("[a-f0-9]{64}",p[k]) for k in ("all_definitions","all_reachable_expansions","allocation_content_counts")) and
           re.fullmatch("[a-f0-9]{64}",h["allocation_order_sha256"]) and 0<=p["reachable_definitions"]<=h["definition_count"] and
           h["allocation_records"]>=h["distinct_allocation_records"]>=0,"incomplete allocations or per-item metadata")
def qualifications(out,shape):
    baselines={};qual={}
    for role in ROLES:
        q=out/("qualification-"+role);r=m.read(q/"four-state.json");m.guard((r["role"],r["A_tree"],r["B_tree"])==(role,m.CASE["A_tree"],m.CASE["B_tree"]),"role four-state")
        for state in ("A","B"):fixture(q/("fixture-"+state),state)
        a={i:raw(q/i) for i in ("ordinary-A","A-to-B","cold-B1","cold-B2")}
        for key,l,h in (("cold-B1","A-to-B","cold-B1"),("cold-B2","A-to-B","cold-B2"),("both-independent-cold","cold-B1","cold-B2")):
            semantic(r["comparisons"][key],a[l],a[h],shape)
        baselines[role]=a["cold-B1"];qual[role]=m.filesha(q/"four-state.json")
    return baselines,qual
def report(out):
    m.guard(not (out/"refusal.txt").exists(),"ineligible refused run");ref=m.reference();shape=m.shape()[1]
    sdk=m.read(out/"intake.json");cal=m.read(out/"calibration.json");ready=cal["ready"];host=m.read(out/"host.json")
    m.guard(sdk["signed_cargo_sha256"]==m.P["signed_cargo_sha256"] and set(sdk["installed"])==set(ROLES) and
       all(sdk["installed"][r]["source"]==m.P["roles"][r] and sdk["installed"][r]["runtime"]["bin/cargo"]==m.P["signed_cargo_sha256"] for r in ROLES) and
       m.filesha(out/"intake/sdk-lock.json")==sdk["sdk_lock_sha256"],"different SDK enrollment")
    cfiles=sorted((out/"pmu-calibration/calibration").glob("whole-*-*.json"))
    m.guard(len(cfiles)==cal["unmultiplexed_calibration_clocks"]==28 and host["boot"]==ready["boot"] and host["cpus"]==ready["affinity"],"uncalibrated PMU")
    for c in cfiles:counter(c)
    m.guard(m.filesha(out/"pmu-calibration/observers/plain")==cal["plain_sha256"] and m.read(out/"pmu-calibration/meter-ready.json")==ready,"observer changed")
    baselines,qual=qualifications(out,shape);prev=0;rows=[]
    for design in m.P["orders"]:
        values={}
        for role in design["roles"]:
            path=out/f"hold{design['hold']}-pair{design['pair']:02d}-{role}";a=m.read(path/"accepted.json")
            m.guard((a["role"],a["pair"],a["hold"],a["mode_order"])==(role,design["pair"],design["hold"],design["modes"]) and
                    a["A"]==m.CASE["A_tree"] and a["B"]==m.CASE["B_tree"] and a["workspace"]==sorted(shape),"misassigned seed")
            seed=m.read(path/"A-snapshot.json");m.guard(a["A_snapshot"]==seed["tree_sha256"] and positive(seed["regular_bytes"]) and
                len(seed["actual_incremental_headers"])>=4 and all(e==m.P["roles"][role]["epoch"] for _,e,_ in seed["actual_incremental_headers"]),"wrong A seed or cache epoch")
            counts={}
            for mode in design["modes"]:
                p=path/mode;r=m.read(p/"ordinary.json")
                m.guard(r["mode"]==mode and r["argv"]==m.ARGS and r["exit"]==0 and r["env"]==m.ENV and r["boot"]==host["boot"] and
                   r["cpus"]==host["cpus"] and prev<r["start_ns"]<r["end_ns"] and r["ns"]==r["end_ns"]-r["start_ns"],"scored visit/clock order")
                prev=r["end_ns"]
                m.guard(not (p/"cargo.stdout").read_bytes() and sorted(x.decode() for x in re.findall(rb"^\s*(?:Checking|Compiling) ([\w-]+) v",(p/"cargo.stderr").read_bytes(),re.M))==ref["edit"]["progress"],"plain first-edit progress")
                if mode=="native":
                    m.guard(r["invoked"]==m.ARGS and not (p/"whole-clock.json").exists(),"wall under observation");counts["wall_nanoseconds"]=r["ns"]
                else:
                    observer=Path(r["invoked"][1]);m.guard(r["invoked"]==[ready["plain"],str(observer),*m.ARGS] and
                       observer.parts[-3:]==(path.name,"pmu","whole-clock.json"),"wrong PMU boundary");counts["user_instructions"]=counter(p/"whole-clock.json")
            t=m.read(path/"typed/observed.json");m.guard(t["argv"]==ref["argv"] and t["details"]==ref["edit"] and
                    (t["rows"],t["build_scripts"],t["workspace"],t["diagnostics"])==(641,51,70,[]),"typed events/arguments")
            t=m.read(path/"scoped/parsed.json");kids=[r for r in t["tree"]["exec"] if r["path"]==str(m.RUSTC)]
            m.guard(t["score"] is False and t["command"]==m.ARGS and len({r["pid"] for r in kids})==len(kids)==18 and sorted(r["argv"] for r in kids)==ref["argv"],"genuine rustc PIDs/arguments")
            same=raw(path/"native");m.guard(all(m.read(path/k/"workspace-products.json")==same for k in ("typed","pmu","scoped")) and
                m.digest(m.canon(same))==a["same_seed_raw_sha256"],"same-seed raw mismatch")
            semantic(a["independent_cold"],same,baselines[role],shape);values[role]=counts
        rows.append({"design":design,"values":values})
    m.guard(len(list(out.glob("hold*-pair*-*/accepted.json")))==24,"extra enrolled visits")
    return {"classification":"two corrected production compilers, real uv #20988 root, one calibrated host","metric_orientation":"corrected stock divided by corrected #296+#306",
      "protocol_sha256":m.filesha(m.HERE/"protocol.json"),"source":m.CASE,"signed_cargo":sdk["signed_cargo_sha256"],"sdk_lock":sdk["sdk_lock_sha256"],
      "boot":host["boot"],"affinity":host["cpus"],"qualification":qual,"pairs":rows,"metrics":estimate(rows)}
if __name__=="__main__":print(json.dumps(report(Path(sys.argv[1]).resolve()),sort_keys=True,indent=2))
