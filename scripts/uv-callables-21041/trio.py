"""Controls shared by the precise three-compiler wall panel and its independent reader."""
import json
import os
from pathlib import Path
import shutil
import core as c
import history as h
import products as prod
import typed21041
import wall_clock as timer
import timeline
m=c.m


def calibrate_host(w,tmp):
    mask=timer.physical_cores()
    os.sched_setaffinity(0,mask)
    out=w/"trait-results"
    r=timer.calibrate(out/"clock-pre",tmp/"trio-wall-probe")
    machine=r["machine"]
    c.guard(len(machine["cpus"])==8 and machine["boot"] not in {v["boot"] for v in c.PAIR["prior_boots"].values()},
            "physical machine has already been enrolled")
    timer.save(out/"boot.json",dict(machine=machine,calibration=m.filesha(out/"clock-pre/passed.json"),
                 plan=c.PAIR["plan"],prior_boots=c.PAIR["prior_boots"],run=int(os.environ["GITHUB_RUN_ID"]),
                 head=os.environ["GITHUB_SHA"],runner=os.environ["RUNNER_NAME"],attempt=int(os.environ["GITHUB_RUN_ATTEMPT"])))


def accept_host(out):
    receipt=m.read(out/"boot.json");ready=receipt["machine"]
    c.guard(receipt["plan"]==c.PAIR["plan"] and receipt["prior_boots"]==c.PAIR["prior_boots"] and
            receipt["calibration"]==m.filesha(out/"clock-pre/passed.json") and
            ready["boot"] not in {r["boot"]for r in c.PAIR["prior_boots"].values()} and
            ready["cpus"]==timer.physical_cores() and Path("/sys/fs/cgroup/cpu.max").read_text().strip().startswith("max "),
            "unqualified native clock or worker")
    os.sched_setaffinity(0,ready["cpus"])
    c.guard(ready==timer.current(),"machine changed since calibration")
    return ready


def cross(panel,hold):
    for phase in ("ordinary-A","warm-B","cold-B"):
        rows=[m.read(panel/f"hold-{hold}-{r}"/phase/"products.json") for r in c.ROLES]
        same=all(q["structural"]==rows[0]["structural"] for q in rows)
        m.save(panel/f"hold-{hold}-{phase}-cross-role.json",{"passed":same,"roles":c.ROLES,
               "shape":{r:m.digest(m.canon(q["structural"])) for r,q in zip(c.ROLES,rows)}})
        c.guard(same,"cross-compiler rooted identities or reachable set differ")


def bare(roleout,seed,seal,member,atime,expected,streams,products,controls,ready):
    state=h.restore(seed,seal,member,atime)
    path=roleout/"wall"
    r=timer.command(path,c.CHECK,"native-blocking",m.SRC,m.ENV)
    c.guard(r["boot"]==ready["boot"] and r["cpus"]==ready["cpus"] and r["ns"]==r["end_ns"]-r["start_ns"],
            "different machine or clock")
    m.save(path/"source.json",state)
    actual=products(path)
    c.guard(prod.compare(path/"same-seed-equivalence.json",expected,actual,True),"independently restored bytes")
    post=controls(path);m.save(path/"ordinary-controls.json",post)
    c.guard(post==streams and h.state("B")==state,"diagnostics or actual B differ during native time")
    return {"ns":r["ns"],"checkpoint_sha256":seal["sha256"],"receipt_sha256":m.filesha(path/"ordinary.json")}


def audit_treatment(panel,hold,histories,baseline,sdks,bank,atime,products,controls):
    role=c.ROLES[-1];m.choose(role,bank,sdks)
    seed,seal,member=histories[role];expected,streams=baseline[role]
    q=panel/f"hold-{hold}-{role}";expected_argv=m.read(q/"typed-B/roster.json")["commands"]
    out=q/"build-analysis";out.mkdir();logdir=m.CARGO_HOME/"log"
    for tag,verbose,changed in [("plain-B",False,True),("typed-B",True,True),("settled-B",True,False)]:
        if changed: state=h.restore(seed,seal,member,atime)
        else: state=h.state("B")
        before=set(logdir.glob("*.jsonl"))
        p=out/tag;args=[*c.CHECK,"-Zbuild-analysis",*(["-vv","--message-format=json"] if verbose else [])]
        rec=timer.command(p,args,"diagnostic-build-analysis",m.SRC,m.ENV|{"CARGO_BUILD_ANALYSIS_ENABLED":"true"})
        now=set(logdir.glob("*.jsonl"))
        c.guard(before<=now and len(now-before)==1,"ambiguous signed Cargo session")
        source,=now-before
        c.guard(source.is_file() and not source.is_symlink() and 0<source.stat().st_size<32<<20,"regular bounded raw log")
        shutil.copyfile(source,p/"cargo-analysis.jsonl")
        study=timeline.read((p/"cargo-analysis.jsonl").read_bytes(),args,m.SRC,c.PAIR["arms"][role]["source"]["commit"],
                            c.P["edited_workspace_roster"] if changed else [],"uv_client")
        c.guard(source.name==study["run_id"]+".jsonl","log filename and internal build ID")
        m.save(p/"timeline.json",study);m.save(p/"source.json",state)
        if verbose:
            proof=typed21041.validate(p,"B",timeline.cargo_messages((p/"cargo.stdout").read_bytes(),study["run_id"]),
                                      (p/"cargo.stderr").read_bytes(),changed)
            c.guard(sorted(proof["commands"])==sorted(expected_argv if changed else []),"actual compiler argv differs from native")
        else:
            c.guard(controls(p)==streams,"Cargo logger changed ordinary scheduler roster or diagnostics")
        c.guard(prod.compare(p/"same-seed-equivalence.json",expected,products(p),True) and h.state("B")==state,
                "log visit changed metadata, sidecars or source")
