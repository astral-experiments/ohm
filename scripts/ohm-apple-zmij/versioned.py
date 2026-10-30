"""Run native Apple compatibility tests before the separately registered ordinary developer workload."""
import argparse
import errno
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import fixed_crc
import provider_edges as edge
from execs import ExecTrace
from measure import capture, native_rows, select, typed
from study import PARENT, CHILD, check_host, compress_bytes, digest, env_for, load, need, physical, run, save, sdk_id, sha
from versioned_select import AWARE, CLASSIC, CARGOS, choose, current

V1="/dev/null/ohm-recheck-dependent-links"
V2=V1+"-v2"
HARD="/dev/null/ohm-untracked-relink-inputs"
MIGRATIONS=(("legacy-lower","lower",7),("upgrade-higher","higher",7),("upgrade-unchanged","higher",7),
            ("upgrade-malformed","malformed",7),("upgrade-repair","higher",7),("downgrade-lower","lower",7),
            ("downgrade-missing","missing",7),("downgrade-edit-repair","higher",11),("downgrade-repeat","higher",11))
CAGES=("none","v1","v2","both")
def stamp(p):
    st=p.stat()
    return [st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns,sha(p)]
def marker_rules(root, row):
    found=[]
    for rel,meta in row["marker"].items():
        data=gzip.decompress((root/"receipts/edge-markers"/(meta["sha256"]+".d.gz")).read_bytes())
        need(hashlib.sha256(data).hexdigest()==meta["sha256"],"altered Rust depfile")
        lines=data.decode().splitlines()
        # Discard only Cargo's exported one-rule merge. The independent original rustc
        # file always includes the exact fake rule and the source-only depfile target.
        if not any(l.endswith(":") for l in lines):continue
        fake=[l[:-1] for l in lines if l.endswith(":") and l.startswith("/dev/null/ohm-")]
        found.append((rel,fake))
    return found

def standard(root,name):
    check_host(root,8)
    before=choose(root,name)
    fixed_crc.providers(root)
    matrix=root/"receipts/provider-matrix"
    verdict=load(matrix/"terminal.json")
    need(verdict["commands"]==392, "incomplete receiver case matrix")
    exact={}
    for phase in sorted(matrix.glob("*/*/*/verified.json")):
        row=load(phase); parts=phase.relative_to(matrix).parts
        role=parts[0][0]
        if row["status"] or not parts[0].endswith("-default"):continue
        rules=marker_rules(root,row)
        expected=HARD if role=="P" else V2
        # A successful prior link can return while the original compiler depfile stays unchanged.
        need(rules and all(v==[expected] for _,v in rules), "wrong real compiler rule: "+str((parts,rules)))
        exact["/".join(parts[:-1])]=rules
    save(matrix/"versioned-receiver.json",{"cargo":before,"rust":{"P":PARENT,"C":CHILD},"marker_evidence":exact})
    need(current(root)==before and len(exact)>100, "receiver or marker evidence missing")
    if name!="aware":
        new=root/"receipts/versioned"/name;new.mkdir(parents=True,exist_ok=True);matrix.rename(new/"provider-matrix")
    # Native provider code, object and archive bytes have been copied into this receiver's receipts.
    (root/"provider-factory").rename(root/("versioned-factory-"+name))
    need(verdict["passed"],"a required warm provider result disagreed with independently empty Cargo: "+str(verdict))

def migration(root):
    top=root/"receipts/versioned/migrations";top.mkdir(parents=True)
    matrix=root/"receipts/provider-matrix";need(matrix.is_dir(),"aware source matrix missing")
    ar={v:(matrix/f"provider-{v}.a").read_bytes() for v in (17,29)}
    trace=ExecTrace();trace.ready()
    reports={}
    try:
        for start in ("signed","classic"):
            for place in ("direct","library"):
                choose(root,start);role="C";sdk=select(root,role);driver,=(sdk/"lib").glob("librustc_driver*.dylib")
                actual=stamp(driver); all_switches=[];it=iter(MIGRATIONS)
                def change(src,state,providers):
                    phase,wanted,value=next(it);need(state==wanted,"out-of-order migration")
                    name=start if phase.startswith(("legacy","downgrade")) else "aware"
                    if current(root)["name"]!=name:choose(root,name)
                    binding=current(root)
                    need(stamp(driver)==actual,"Rust driver changed during Cargo transfer")
                    all_switches.append({"phase":phase,"cargo":binding,"source":str(src),
                        "dev_ino":[src.stat().st_dev,src.stat().st_ino],"driver":actual})
                    return edge.configure(src,state,providers)
                label="transfer-"+start
                rows=edge.run_case(root,trace,role,place,"unwatched",True,ar,visits=MIGRATIONS,change=change,
                                   evidence=fixed_crc.evidence,label=label)
                source=matrix/f"{label}-{place}-unwatched-default"
                for phase,state,rust in MIGRATIONS:
                    val=edge.NATIVE[state];want=[0,[val,rust]] if val is not None else [101,None]
                    need(rows[phase]["warm"][:2]==rows[phase]["empty"][:2]==want and rows[phase]["same_checked_image"] is not False,"incorrect native migration "+str((start,place,phase)))
                    for arm in ("warm","empty"):
                        row=load(source/phase/arm/"verified.json")
                        if row["status"]==0:need(all(v==[V2] for _,v in marker_rules(root,row)) and marker_rules(root,row),"lost v2 original")
                assert all(s["dev_ino"]==all_switches[0]["dev_ino"] for s in all_switches)
                save(source/"cargo-switches.json",all_switches)
                dest=top/(start+"-"+place);source.rename(dest)
                reports[dest.name]={"cases":len(rows)*2,"terminal":sha(dest/"terminal.json"),"switches":sha(dest/"cargo-switches.json")}
    finally:trace.close()
    save(top/"terminal.json",reports);choose(root,"aware")

def named(root):
    from versioned_named import run_named
    choose(root,"aware")
    run_named(root)

def terminal(root):
    rec=root/"receipts";cases={}
    for name in CARGOS:
        p=(rec/"provider-matrix" if name=="aware" else rec/"versioned"/name/"provider-matrix");v=load(p/"terminal.json")
        need(v["passed"] and v["commands"]==392 and not any(v["wrong_or_image_mismatch"].values()), "incomplete native protection")
        identity=load(p/"versioned-receiver.json");need(identity["cargo"]["source"]==CARGOS[name][0] and identity["marker_evidence"],"wrong tested Cargo")
        cases[name]={"terminal":sha(p/"terminal.json"),"binding":sha(p/"versioned-receiver.json")}
    reg=load(rec/"versioned/registry/terminal.json");need(set(reg)==set(CARGOS) and all(v["role"]==PARENT for v in reg.values()), "separate real registry study missing")
    tr=load(rec/"versioned/migrations/terminal.json");nm=load(rec/"versioned/named/terminal.json")
    need(len(tr)==4 and sum(v["cases"] for v in tr.values())==72 and set(nm)==set(CARGOS) and all(set(cs)==set(CAGES) for cs in nm.values()) and current(root)["source"]==AWARE,
         "incomplete transitions, real name collisions or native target receiver")
    for r in "PC":
        sdk=select(root,r);env=env_for(root/"versioned-final-binding",sdk);proof=sdk_id(sdk,env)
        original=load(rec/"pair.json")["products"][r]["runtime"]
        from prepare import role_files
        need(role_files(sdk)=={**original,"bin/cargo":proof["cargo"]["sha256"]},"mixed SDK member")
        from dyld import check as actual_dyld
        actual_dyld(root,r,sdk,rec/"versioned"/("dyld-"+r))
        save(rec/"versioned"/("sdk-"+r+".json"),proof)
    save(rec/"versioned/terminal.json", {"passed":True,"families":cases,"migration":tr,"real_tracked_names":nm,
        "source_parent":PARENT,"source_candidate":CHILD,"cargo":AWARE,"registry_marker_readback":sha(rec/"versioned/registry/terminal.json")})
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("step",choices=("signed","classic","aware","migration","named","terminal"));p.add_argument("root",type=Path);a=p.parse_args()
    root=a.root.resolve();check_host(root,8)
    if a.step in CARGOS:standard(root,a.step)
    else:{"migration":migration,"named":named,"terminal":terminal}[a.step](root)
