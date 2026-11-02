"""Read signed Cargo's unrounded, monotonic raw build-analysis events."""
import json
import math
from pathlib import Path


def need(test,detail):
    if not test:
        raise ValueError(detail)


def cargo_messages(stdout, run_id):
    import cargo_log
    first, separator, remaining = stdout.partition(b"\n")
    need(separator and json.loads(first)=={"reason":"build-started","run_id":run_id},
         "stdout build-started must identify this build-analysis file")
    return cargo_log.cargo_messages(remaining)


def read(raw, argv, workspace, commit, expected, terminal):
    messages=[json.loads(line) for line in raw.splitlines()]
    need(messages and len(raw)<32<<20,"missing or oversized build-analysis log")
    root=messages[0]
    need(root["reason"]=="build-started" and root["command"]==argv and root["cwd"]==root["workspace_root"]==str(workspace)
         and root["jobs"]==8 and root["host"]=="x86_64-unknown-linux-gnu" and root["profile"]=="dev"
         and "commit-hash: "+commit in root["rustc_version_verbose"].splitlines(),"wrong real Cargo invocation")
    need(all(x["run_id"]==root["run_id"] for x in messages),"multiple builds in one file")
    units={}; opened={}; finished={}; ready={}; downstream={}; phases={}
    for row in messages:
        kind=row["reason"]
        if "elapsed" in row:
            secs=row["elapsed"]
            need(type(secs) in (float,int) and math.isfinite(secs) and secs>=0,"elapsed")
        if kind=="unit-registered":
            i=row["index"];need(i not in units,"duplicate unit");units[i]=row
        elif kind in ("unit-started","unit-rmeta-finished","unit-finished"):
            i=row["index"];need(i in units,"unknown unit")
            if kind=="unit-started":
                need(i not in opened,"duplicate start");opened[i]=secs
            else:
                need(i in opened and i not in finished and secs>=opened[i],"completion outside unit")
                edges=row.get("unblocked",[])
                need(len(edges)==len(set(edges)),"duplicate unblocked unit")
                if kind=="unit-rmeta-finished":
                    ready.setdefault(i,[]).append([secs,edges])
                else:
                    finished[i]=secs;downstream[i]=edges
        elif kind in ("resolution-started","resolution-finished","unit-graph-started","unit-graph-finished"):
            need(kind not in phases,"duplicate compilation phase");phases[kind]=secs
    need(opened.keys()==finished.keys(),"incomplete units")
    names={}
    for i in opened:
        r=units[i];name=r["target"]["name"].replace("-","_")
        need(name not in names.values() and r["target"]["kind"]=="lib" and r["mode"]=="check"
             and r["platform"]=="x86_64-unknown-linux-gnu" and r["package_id"].startswith(workspace.as_uri().replace("file:","path+file:",1)+"/"),
             "unexpected dirty compilation unit")
        names[i]=name
    need(set(names.values())==set(expected),"actual started units differ")
    detail={}
    for i,name in names.items():
        def labels(indices):
            need(all(v in units for v in indices),"unregistered unblocked index")
            return [names.get(v,f"other-unit-{v}") for v in indices]
        meta=[{"elapsed":s,"unblocked":labels(v)} for s,v in ready.get(i,[])]
        need(all(opened[i]<=x["elapsed"]<=finished[i] for x in meta),"metadata outside compiler unit")
        detail[name]={"start":opened[i],"finish":finished[i],"metadata":meta,"finished_unblocked":labels(downstream[i])}
    result={"run_id":root["run_id"],"registered":len(units),"phases":phases,"units":detail}
    if expected:
        selected=next(i for i,n in names.items() if n==terminal)
        left=sorted((a,finished[i])for i,a in opened.items());busy=0;lo,hi=left[0]
        for a,b in left[1:]:
            if a>hi: busy+=hi-lo;lo,hi=a,b
            else: hi=max(hi,b)
        busy+=hi-lo
        last_other=max((b for i,b in finished.items() if i!=selected),default=opened[selected])
        result.update(terminal_only_tail_s=max(0,finished[selected]-max(opened[selected],last_other)),
                      terminal_latest_finish=finished[selected]==max(finished.values()),unit_union_s=busy,
                      first_started_s=min(opened.values()),last_finished_s=max(finished.values()))
    return result
