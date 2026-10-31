import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import traceback

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import subjects
from subjects import need,sha,put
import seed
import cell
from cell import PHASES,CRATES
QA_CAL="2f413ca94b84af2dbd6d6231bcf8d860c97ebee8"
QA_OBS="8a659140df8ab27fd6a8cc61f5eb38717b3f8bbc"
WORKLOAD="7292c081de1d8636871a879334439223f4554ce85576eaee12e97e0a818798cb"
ROOT=Path("/tmp/rdr-notebook-getter")
PLAN="ad2bbf1d880e5825e5af65e2d5674dcb178ce48fd82e7bbf5e2d3cce72f1c0be"

def adapter(cal,root):
    packet=cal/"scripts/gnu-renderer-pfc-hardware/packets/adapter.tar.gz"
    need(sha(packet)==WORKLOAD,"ordinary source/setup helpers")
    fresh=root/"workload";fresh.mkdir()
    with tarfile.open(packet,"r:gz") as tf:
        seen=set()
        for item in tf:
            p=Path(item.name)
            need(item.isfile() and item.name not in seen and not p.is_absolute() and ".." not in p.parts,"invalid archive")
            dest=fresh/p;dest.parent.mkdir(parents=True,exist_ok=True)
            with tf.extractfile(item) as src,dest.open("xb") as dst:shutil.copyfileobj(src,dst)
            seen.add(item.name)
    subprocess.run(["sha256sum","--strict","--check","--status","SHA256SUMS"],cwd=fresh,check=True)
    spec=importlib.util.spec_from_file_location("rdr_ordinary_setup",fresh/"workload.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    need(module.HERE==fresh.resolve() and module.environment and module.add_registry,"wrong workload setup")
    return module

def snapshot(d,keys):
    return {k:[Path(d[k]).stat().st_dev,Path(d[k]).stat().st_ino] for k in keys}

def definitions(cas,prod):
    body=gzip.decompress((cas/(prod["defs"]+".gz")).read_bytes())
    need(hashlib.sha256(body).hexdigest()==prod["defs"],"per-item CAS")
    return json.loads(body)

def scope(cas,byphase):
    out={}
    for n in CRATES:
        a=byphase["A0"]["products"][n];b=byphase["B"]["products"][n]
        x,y=definitions(cas,a),definitions(cas,b)
        common=set(x)&set(y)
        swaps={h:[x[h],y[h]] for h in sorted(common) if x[h][1]!=y[h][1]}
        watched={h:{"name":x[h][0],"A":x[h][1],"B":y[h][1]} for h in sorted(common)
                 if any(key in x[h][0] for key in ("NotebookIndex","CellStart","notebook_index","as_notebook","<impl>::metadata","::Notebook::metadata"))}
        out[n]={"common":len(common),"moved":len(swaps),"only_A":len(set(x)-set(y)),"only_B":len(set(y)-set(x)),"observed_scope":watched,
                "public_A":a["public"],"public_B":b["public"],"global_A":a["global"],"global_B":b["global"]}
    return out

def history(root,role,lane,sdks,driver,ruff,registry,proxies,out,plain,lib):
    sdk=root/"sdk"; work=root/"work"
    work.mkdir()
    src=work/"source"
    subprocess.run(["git","clone","--no-checkout","--shared","--quiet",ruff,src],check=True)
    seed.git(src,"checkout","--detach","--quiet",seed.PIN)
    need(seed.sha(src/"Cargo.lock")==seed.LOCK,"lock")
    for n in ("db-accessor","db-neighbor"):shutil.copy2(HERE/(n+".rs"),work/(n+".rs"))
    env=lib.environment(work,sdk,proxies)
    roots=("CARGO_HOME","CARGO_TARGET_DIR","CARGO_BUILD_BUILD_DIR")
    need(all(not Path(env[k]).exists() for k in roots),"nonempty initial Cargo store")
    enrolled=lib.add_registry(src,Path(env["CARGO_HOME"]),registry,True)
    need(enrolled["locked"]==498 and enrolled["complete"],"wrong locked registry")
    need(Path(subprocess.check_output(["rustc","+ohm","--print","sysroot"],text=True,env=env,cwd=src).strip()).resolve()==sdk,"different real compiler")
    need(subjects.inputs.build.manifest({Path(n):sdk/n for n in sdks[role]})==sdks[role],"subject changed before ordinary arm")
    old={str(p):[p.stat().st_dev,p.stat().st_ino,p.stat().st_size,p.stat().st_ctime_ns] for p in (sdk/"bin/rustc",sdk/"bin/rustdoc",sdk/"bin/cargo",sdk/driver,sdk/subjects.inputs.build.WILD)}
    arm=out/"cells"/(role+"-"+lane);arm.mkdir(parents=True)
    put(arm/"subject.json",dict(role=role,lane=lane,source=subjects.inputs.P if role=="P" else subjects.inputs.C,files=sdks[role],identity=old,environment=env))
    result={}
    for label,state in PHASES:
        if label in ("B","A1","Bempty"):
            flags=[] if label=="A1" else ["--reverse"]
            seed.git(src,"apply","--check",*flags,out/"getter.patch");seed.git(src,"apply",*flags,out/"getter.patch")
        if label=="Bempty":
            before=snapshot(env,roots);slot=work/"slot";park=work/"original-slot";slot.rename(park)
            same=lib.environment(work,sdk,proxies)
            need(same==env and all(not Path(env[k]).exists() for k in roots),"independent empty paths")
            e=lib.add_registry(src,Path(env["CARGO_HOME"]),registry,True)
            need(e["available"]==enrolled["available"] and e["physical"]!=enrolled["physical"],"cold registry")
            put(arm/"independent-empty.json",dict(old=before,parked=str(park),new_cargo_home=e["physical"]))
        row=cell.stage(arm,work,src,env,label,state,role,lane,sdk,driver,plain,out/"cas")
        need(row["roster"]==(result["A0"]["roster"] if result else row["roster"]),"changed Cargo graph")
        result[label]=row
        print(role,lane,label,"dirty",len(row["dirty"]),"user instructions",row["counts"],flush=True)
    for n in CRATES:
        for a,b in (("A0","A0r"),("B","Br"),("A1","A1r"),("Bempty","Bemptyr"),("A0","A1")):
            need(result[a]["products"][n]["cas"]==result[b]["products"][n]["cas"],("repeat/repair raw rmeta",n,a,b))
        need(result["A0"]["products"][n]["global"]==result["B"]["products"][n]["global"]==result["A1"]["products"][n]["global"],"global confound in same history")
        b,e=[result[ph]["products"][n] for ph in ("B","Bempty")]
        for key in ("issuer","stamp","filename","stable_id","roster"):need(b[key]==e[key],("warm/empty identity",key,n))
    need(all([p.stat().st_dev,p.stat().st_ino,p.stat().st_size,p.stat().st_ctime_ns]==old[str(p)] for p in map(Path,old)),"tool changed mid-history")
    facts=scope(out/"cas",result)
    put(arm/"complete.json",dict(role=role,lane=lane,phases=list(result),scopes=facts,source_hash=sha(out/"getter.patch"),canonical=str(src),initial_roster=len(result["A0"]["roster"])))
    work.rename(root/(role+"-"+lane+"-work"))
    return result

def main(pos,packaging,observer):
    need(pos in ("01","02"),"bad position")
    out=Path(os.environ["RUNNER_TEMP"])/("rdr-getter-"+pos)/"receipt";out.mkdir(parents=True)
    try:
        need(sha(HERE/"PLAN.md")==PLAN,"prospective registration")
        shutil.copy2(HERE/"PLAN.md",out/"PLAN.md");shutil.copy2(HERE/"PLAN-v1.md",out/"PLAN-v1.md")
        for repo,head in ((packaging,QA_CAL),(observer,QA_OBS)):
            need(seed.git(repo,"rev-parse","HEAD").decode().strip()==head,"different calibrated source")
        root=ROOT;root.mkdir()
        need(root.resolve()==root and shutil.disk_usage(root).free>32*2**30,"native free space")
        caldir=packaging/"scripts/gnu-renderer-pfc-hardware"
        subprocess.run(["sha256sum","--strict","--check","--status","SHA256SUMS"],cwd=caldir,check=True)
        sys.path.insert(0,str(caldir));import calibration
        boot=calibration.host(observer,out)
        put(out/"enrollment.json",{"position":pos,"roles":["P","C"] if pos=="01" else ["C","P"],"boot":boot,"qa":os.environ["GITHUB_SHA"],"run":os.environ["GITHUB_RUN_ID"],"attempt":os.environ["GITHUB_RUN_ATTEMPT"],"job":os.environ["GITHUB_JOB"],"plan":PLAN,"runner":os.environ.get("RUNNER_NAME")})
        plain=calibration.setup(observer,root,out)
        lib=adapter(packaging,root)
        files,driver=subjects.freeze(root,out)
        ruff,registry,proxies=seed.prepare(root,out,root/"parent-sdk",lib)
        (out/"cas").mkdir()
        all_rows={}
        roles=["P","C"] if pos=="01" else ["C","P"]
        # Opposite lane order also counterbalances thermal/cold setup effects across workers.
        lanes=["structural","whole"] if pos=="01" else ["whole","structural"]
        for role in roles:
            donor=root/({"P":"parent","C":"candidate"}[role]+"-sdk")
            donor.rename(root/"sdk")
            for lane in lanes:
                all_rows[role,lane]=history(root,role,lane,files,driver,ruff,registry,proxies,out,plain,lib)
            (root/"sdk").rename(donor)
        for role in roles:
            for name,_ in PHASES:
                t,w=all_rows[role,"structural"][name],all_rows[role,"whole"][name]
                need(t["roster"]==w["roster"] and t["dirty"]==w["dirty"] and t["source"]==w["source"],("physical/control disagreement",role,name))
                need({k:v["exit"] for k,v in t["clients"].items()}=={k:v["exit"] for k,v in w["clients"].items()},"reader disagreement")
        for name,_ in PHASES:
            need(all_rows["P","whole"][name]["roster"]==all_rows["C","whole"][name]["roster"],"different role demand")
        summary={}
        for n in ("A0","A0r","B","Br","A1","A1r","Bempty","Bemptyr"):
            p,c=[all_rows[r,"whole"][n] for r in ("P","C")]
            summary[n]={"P":p["counts"],"C":c["counts"],"ratio":p["counts"]/c["counts"],
                        "P_alloc":p["storage"]["allocated"],"C_alloc":c["storage"]["allocated"],"P_dirty":len(p["dirty"]),"C_dirty":len(c["dirty"])}
        for name,first,repeat in (("historical_cycle","A1","A1r"),("reverse_cycle","B","Br")):
            summed={k:summary[first][k]+summary[repeat][k] for k in ("P","C")};summary[name]=dict(**summed,ratio=summed["P"]/summed["C"])
        acceptable=all(summary[n]["C_alloc"]<=1.05*summary[n]["P_alloc"] and summary[n]["C_dirty"]<=summary[n]["P_dirty"] for n in ("B","Br","A1","A1r"))
        put(out/"complete.json",{"qa":os.environ["GITHUB_SHA"],"run":os.environ["GITHUB_RUN_ID"],"attempt":os.environ["GITHUB_RUN_ATTEMPT"],"plan":PLAN,"position":pos,"boot":boot,"roles":roles,"lanes":lanes,"physical_structural_pass":True,"storage_and_dirty_admissible":acceptable,"within_host_feasible":acceptable and summary["A1"]["ratio"]>=2.0 and summary["historical_cycle"]["ratio"]>=2.0,"whole":summary})
    except BaseException:
        (out/"refusal.txt").write_text(traceback.format_exc());raise

if __name__=="__main__":
    main(sys.argv[1],Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve())
