"""Independent physical source-compiler archive reader. No rustc, Cargo, probes or compiler/SDK access."""
import ast
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import doc_support
import extern_diff
import shards
import transport as t
import childenv
sys.path.insert(0,str(HERE.parent/"ruff-ldv-needed"))
import reopen
sys.path.insert(0,str(HERE.parent/"ruff-workspace-remat"))
import e2e
sys.path.insert(0,str(HERE.parent/"ruff-workspace-option-edit"))
import study

need=t.need
digest=reopen.digest
PLAN=json.loads((t.STAGE/"confirmation.json").read_bytes())
CHILD=re.compile(r"^(?:clone3?\(|fork\(|vfork\(|<\.\.\. (?:clone3?|fork|vfork) resumed>).* = (\d+)\s*$")
MAGIC={"native-bodies":b"\x7fELF","probe-owners":b"\x7fELF","owner-archives":b"!<arch>\n"}
STORE=re.compile(r"physical/(native-bodies|probe-owners|owner-archives)/([0-9a-f]{64})\.gz")
def read(z,member):
    return json.loads(z.read(member))


def checked_json(z,name,bound):
    b=z.read(name)
    need(digest(b)==bound,("invalid independently reopened JSON",name))
    return json.loads(b)


def verify_bytes(z):
    bodies={k:set() for k in MAGIC}
    for info in z.infolist():
        m=STORE.fullmatch(info.filename)
        if not m:
            continue
        role,key=m.groups()
        value=hashlib.sha256()
        with z.open(info) as f,gzip.GzipFile(fileobj=f) as raw:
            magic=raw.read(len(MAGIC[role]))
            need(magic==MAGIC[role],"incorrect complete native body type")
            value.update(magic)
            size=len(magic)
            while chunk:=raw.read(1<<20):
                value.update(chunk)
                size+=len(chunk)
                need(size<2<<30,"unregistered native body size")
        need(key==value.hexdigest(),"different complete native body")
        bodies[role].add(key)
    return bodies


def source_role(z,role,physical,proof):
    rows=physical["kits"][role]
    need(rows["wild"]["sha"]==t.capsule.REG["signed_cargo"]["members"]["lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"][3]
         and rows["cargo"]["sha"]==t.capsule.REG["signed_cargo"]["members"]["bin/cargo"][3],"wrong stock Cargo/Wild")
    need(all(rows[k]["sha"]==proof["physical"][role][name] for k,name in
             (("front","frontend"),("driver","driver"),("llvm","llvm"))),"wrong actual compiler inputs")
    src=read(z,f"physical/source-receipts/{role}.json")
    need(src["commit"]==PLAN["roles"][role] and all(src["files"][rows[k]["name"]][0]==rows[k]["sha"]
         for k in ("front","driver","llvm")),"different original authenticated source product")
    return rows


def calibration(z):
    d="physical/calibration/"
    events={k:read(z,d+k+".json") for k in ("empty","loop","thread","fork")}
    need(all(v["status"]==0 and v["enabled"]==v["running"]>0 for v in events.values()) and all(
        3_800_000<=events[k]["instructions"]-events["empty"]["instructions"]<=4_400_000 for k in ("loop","thread","fork")),
        "unusable genuine process/thread performance monitor")
    proxy=read(z,d+"cargo-dispatch/accepted.json")
    need(proxy["plain"]==proxy["counted"] and len(proxy["plain"])==2 and proxy["rejected"]!=proxy["counted"] and
         z.read(d+"cargo-dispatch/plain/outer.stdout")==z.read(d+"cargo-dispatch/counted/outer.stdout") and
         digest(z.read(d+"cargo-dispatch/plain/outer.stdout"))==proxy["stdout_sha256"] and
         b"unknown proxy name: '+ohm'" in z.read(d+"cargo-dispatch/rejected/stderr"),"different process dispatch or negative control")
    return {k:v["instructions"] for k,v in events.items()}


def fresh_trace(z,folder,files,sdk,entry):
    generated=[]
    parents={}
    execs={}
    prefix=folder+"/trace/exec."
    for path in files:
        tid=int(path[len(prefix):])
        with reopen.Member(z,path).open() as fp:
            for line in fp:
                m=CHILD.match(line)
                if m:
                    child=int(m[1])
                    need(parents.setdefault(child,tid)==tid,"inconsistent native process hierarchy")
                if line.startswith(("execve(","execveat(")) and line.rstrip().endswith("= 0"):
                    m=reopen.EXEC.fullmatch(line.rstrip())
                    need(m,"unparsed successful kernel exec")
                    exe,args,env=(ast.literal_eval(v) for v in m.groups())
                    keys={s.partition("=")[0]:s.partition("=")[2] for s in env}
                    if childenv.check(keys,sdk):
                        generated.append((tid,exe))
                    execs.setdefault(tid,[]).append((exe,args))
    signed={pid for pid,rows in execs.items() if any(p==str(Path(sdk)/"bin/cargo") for p,_ in rows)}
    return parents,execs,childenv.owners(generated,parents,signed,entry)


def descendant(pid,ancestor,parents):
    seen=set()
    while pid!=ancestor and pid in parents:
        need(pid not in seen,"process ancestry cycle")
        seen.add(pid)
        pid=parents[pid]
    return pid==ancestor


def genuine_counter(z,folder,task,parents,execs,sdk,which,bound):
    if bound is None:
        need(folder+"/pmu.json" not in z.NameToInfo,"unexpected primary counter")
        return None
    pm=checked_json(z,folder+"/pmu.json",bound)
    need(pm["instructions"]>0 and pm["enabled"]==pm["running"]>0 and os.waitstatus_to_exitcode(pm["status"])==0,
         "unqualified retired instruction event")
    ordinary=task["ordinary"]
    a=task["actual"]
    sub=a[a.index("--")+1:]
    counter, target, proxy,*args=sub
    need(Path(counter).name=="count" and Path(target).name=="pmu.json" and args==ordinary and
         (proxy,ordinary) in execs[pm["pid"]],"counter did not start at the ordinary rustup frontend")
    command=sdk+"/bin/cargo"
    within={pid for pid in execs if descendant(pid,pm["pid"],parents)}
    need(any((command,[command,*ordinary[2:]]) in execs[pid] for pid in within),"no actual signed Cargo downstream")
    outside=[(pid,row) for pid,values in execs.items() if pid not in within for row in values]
    need(len(outside)==1 and outside[0][1]==(counter,sub) and parents.get(pm["pid"])==outside[0][0],
         ("native process escaped the event",[(pid,row[0]) for pid,row in outside]))
    return {**pm,"raw_sha256":bound,"phase":which}


def native(z,folder,phase,suite,result,bodies):
    b=z.read(folder+"/outer.stdout")
    artifacts=[]
    errors=[]
    for line in b.splitlines():
        msg=json.loads(line)
        if msg["reason"]=="compiler-artifact":
            artifacts.append(msg)
        elif msg["reason"]=="compiler-message" and (msg.get("message",{}).get("code") or {}).get("code")=="E0308":
            errors.append(msg)
    if phase=="invalid":
        need(result["error"]=="E0308" and errors and "elf" not in result,"wrong failure from actual compiler")
        return
    need(not errors and result["elf"] in bodies["native-bodies"] and artifacts,"missing complete successful native product")
    if suite=="option":
        ar=result["owner_archive"]
        need(ar["sha256"] in bodies["owner-archives"] and ar["bytes"]>0,"missing real output archive")
        d=folder+"/client/"
        field=z.read(d+"field.stdout")
        need(digest(field)==study.EXPECTED[study.OLD if phase=="old" else study.NEW]==result["verdict"] and
             z.read(d+"sibling.stdout") and not z.read(d+"missing.stdout") and
             [read(z,d+n+".json")["exit"] for n in ("compile","field","sibling","missing","invalid")]==[0,0,0,2,1] and
             all(not z.read(d+n+".stderr") for n in ("field","sibling","missing")) and
             any((json.loads(l).get("code") or {}).get("code")=="E0308" for l in z.read(d+"invalid.stderr").splitlines()) and
             read(z,d+"native.json")["elf"]["sha256"]==result["elf"],"wrong real option reader or version rejection")
    else:
        names=e2e.test_names(z.read(folder+"/list.stdout").decode())
        which=e2e.SIBLING if phase=="old" else e2e.ADDED
        wrong=phase=="negative"
        actual=e2e.executed(z.read(folder+"/named.stdout").decode(),z.read(folder+"/named.stderr").decode(),which,wrong)
        need(read(z,folder+"/list.json")["exit"]==0 and read(z,folder+"/named.json")["exit"]==(101 if wrong else 0) and
             result["verdict"]=={"names_sha256":digest(("\n".join(names)+"\n").encode()),"count":len(names),
                "added":e2e.ADDED in names,"negative_left":actual} and len(names)==(151 if phase=="old" else 152) and
             len(names)==len(set(names)),"different actual Ruff e2e listing or tested verdict")
    keys=[e2e.artifact_key(r["package_id"],r["target"],r["features"],r["profile"]["test"]) for r in artifacts]
    need(sorted(keys)==result["inventory"] and sorted(k for k,r in zip(keys,artifacts,strict=True) if not r["fresh"])==result["dirty"],
         "different native Cargo inventory or refresh")
    if phase in ("old","clean-new"):
        need(result["inventory"]==result["dirty"],"an independently empty build reused work")


def library_custody(z,folder,rows,rusts,physical):
    for s in rusts:
        pid=str(s["pid"])
        m=rows[pid]
        need(set(m)=={"driver","llvm"},"one actual required compiler DSO missing")
        seen=set()
        with reopen.Member(z,folder+"/trace/exec."+pid).open() as file:
            for line in file:
                line=line.rstrip("\n")
                if "O_RDONLY" in line and re.search(r" = [0-9]+</",line):
                    observed=digest(line.encode())
                    for name,entries in m.items():
                        for v in entries:
                            if v["raw_sha"]==observed:
                                need(v["sha"]==physical[name]["sha"] and v["dev_ino"]==physical[name]["id"][:2] and
                                     line.endswith("= "+str(v["fd"])+"<"+v["path"]+">"),"wrong actual owner-opened library")
                                seen.add(name)
        need(seen==set(m),"claimed compiler opens were not present")


def assignment(stage,slot):
    if stage=="score":
        need(1<=slot<=6,"unknown scored slot")
        return PLAN["assignments"][slot-1]
    need(stage=="admit" and slot in (1,2),"unknown native slot")
    return {"slot":slot,"compilers":["P","C"] if slot==1 else ["C","P"],"suites":["option" if slot==1 else "e2e"]}


def phase_read(z,folder,phase,suite,stage,role,obs,actual_role,sdk,bodies,files):
    native(z,folder,phase,suite,obs,bodies)
    k=checked_json(z,folder+"/kernel.json",obs["kernel_sha256"])
    links=checked_json(z,folder+"/linker-argv.json",obs["linker_argv_sha256"])
    opened=checked_json(z,folder+"/actual-libraries.json",obs["source_libraries_sha"])
    need(read(z,folder+"/result.json")==obs and {"rustc":k["rustc"],"linkers":k["linkers"]}==obs["raw_roster"],"different phase/roster")
    entry=read(z,folder+"/command.json")["environment"]
    parents,executions,exports=fresh_trace(z,folder,files,sdk,entry)
    need(exports==read(z,folder+"/build-script-flags.json"),"different Cargo build script exports")
    need(parents=={int(c):p for c,p in k["tree"]["parents"].items()} and
         Counter((pid,p) for pid,rs in executions.items() for p,_ in rs)==
         Counter((e["pid"],e["path"]) for e in k["tree"]["processes"]),"unreported actual exec or process hierarchy")
    actual_front=sdk+"/bin/rustc"
    rusts=k["compilers"]
    need(Counter((r["pid"],r["exec"],tuple(r["argv"])) for r in rusts)==Counter(
         (pid,p,tuple(a)) for pid,rs in executions.items() for p,a in rs if p==actual_front),"unaccounted/mutated SDK rustc invocation")
    for r in links:
        need((r["path"],r["argv"]) in executions[r["pid"]] and (not r["signed_wild"] or r["sha256"]==actual_role["wild"]["sha"]),
            "different actual linker or arguments")
    need(Counter((r["pid"],r["path"]) for r in links)==
         Counter((r["pid"],r["path"]) for r in k["tree"]["linkers"]),"unreported linker")
    def is_linker(path):
        n=Path(path).name
        return n in {"ld","ld.wild","wild","rust-lld","ld.lld","ld.bfd","ld.gold","mold"} or n.endswith(
                       ("-ld","-ld.wild","-ld.bfd","-ld.lld","-ld.gold"))
    need(Counter((pid,p,tuple(a)) for pid,rs in executions.items() for p,a in rs if is_linker(p))==
         Counter((r["pid"],r["path"],tuple(r["argv"])) for r in links),"missing physical linker invocation")
    ranks=Counter()
    for r in rusts:
        a=r["argv"]
        name=a[a.index("--crate-name")+1] if "--crate-name" in a else ""
        probe=any(v in ("--print","-vV","-V","--version") or v.startswith("--print=") for v in a)
        link=any(re.fullmatch(r"(?:-Z)?link-only(?:=.+)?",v) for v in a)
        kind="probe" if probe else ("link-only" if link else ("full" if name else "other"))
        need([r["name"],r["kind"]]==[name,kind],"incorrect physical rustc classification")
        ranks[kind,name]+=1
    need(sorted([a,b,n] for (a,b),n in ranks.items())==k["rustc"],"different actual signed rustc kinds")
    owners={"ruff_workspace"} if suite=="option" else {"ty_server","e2e"}
    roots=[r for r in rusts if r["kind"] in ("full","link-only") and r["name"] in owners]
    need(sorted([r["name"],r["argv"]] for r in roots)==obs["root_argv"],"different actual public command owner argv")
    if phase=="new":
        need({r["name"] for r in roots}==owners and len(roots)==len(owners) and
             all(r["kind"]=="full" and ("--test" in r["argv"])==(r["name"]=="e2e") for r in roots),"wrong real source edit")
        for r in roots:
            opts={a if a!="-C" else "-C"+r["argv"][i+1] for i,a in enumerate(r["argv"]) if a.startswith("-C")}
            need({"-Clto=off","-Cdebuginfo=line-tables-only","-Copt-level=1"}<=opts and not
                 any("llvm-plugins" in a or "llvm-args" in a or "-Cpasses=" in a for a in r["argv"]),"different codegen setting")
    if phase in ("new","unchanged"):
        expected=[] if suite=="option" else [["signed-Wild","e2e",1]]
        need(k["linkers"]==expected,"changed ordinary native link")
    if phase=="unchanged":
        need(k["rustc"]==([] if suite=="option" else [["link-only","e2e",1]]),"changed ordinary repeat")
    if stage=="admit" and phase=="new":
        need(set(opened)=={str(r["pid"]) for r in roots},"missing physical executing library coverage")
        library_custody(z,folder,opened,roots,actual_role)
    else:
        need(not opened,"unregistered DSO observation")
    orig=read(z,folder+"/probes.json")
    need(orig==obs["physical_autocfg"],"different physical autocfg projection")
    if phase in ("old","clean-new"):
        need(Counter(p["equivalence"]["suffix"] for p in orig)=={"0":2,"1":1},"unrecognised native autocfg roster")
    else:
        need(not orig,"unexpected source-less native probe")
    for p in orig:
        row,=[r for r in rusts if r["pid"]==p["pid"] and r["name"]==p["actual_crate"]]
        eq=p["equivalence"]
        reopen.physical_probe(z,folder,row,eq,bodies["probe-owners"])
        owner_pids={pid for pid,rs in executions.items() if any(path==eq["owner"] for path,_ in rs)}
        need(any(descendant(row["pid"],pid,parents) for pid in owner_pids),"wrong actual build-script owner of the nonce")
    counts=Counter((r["kind"],r["name"]) for r in rusts)
    for row in orig:
        counts["full",row["actual_crate"]]-=1
    physical={"rustc":[[a,b,n] for (a,b),n in sorted(counts.items()) if n],"linkers":k["linkers"]}
    if orig:
        physical["autocfg"]=sorted((r["equivalence"] for r in orig),key=lambda r:json.dumps(r,sort_keys=True))
    need(physical==obs["roster"],"different complete source-bound cold/settled physical roster")
    expected=PLAN["suites"][suite]["source"]
    physical=read(z,folder+"/source.json")
    need(physical["base"]==expected["OLD"] and physical["invalid"]==(phase=="invalid"),"wrong actual historical source")
    if suite=="option":
        need(physical["effective"]==expected["OLD" if phase=="old" else "NEW"],"not the enrolled option edit")
    else:
        need(physical["effective"]=={p:(expected["OLD"] if phase=="old" or (phase=="negative" and p==e2e.SESSION)
             else expected["NEW"]) for p in e2e.PATHS},"not the enrolled Ruff e2e edit or independent contrary assertion")
    task=read(z,folder+"/command.json")
    _,_,ns=shards.project(obs,task["environment"])
    need(ns==obs["compiler_namespace"],"different original shared-workspace proof")
    if stage=="admit" and phase=="new":
        files=read(z,folder+"/shared-extern-files.json")
        need(set(files)==set(ns["shared_owner_extern_paths"]) and all(len(v["identity"])==5 and
             v["identity"][1]>0 and v["identity"][2]>0 and re.fullmatch(r"[0-9a-f]{64}",v["sha256"]) for v in files.values()),
             "different filenames or invalid physical provenance for the owners' shared registry inputs")
    need(task["ordinary"]==PLAN["suites"][suite]["cargo"],"altered original public Cargo command")
    wanted=stage=="score" and phase in ("old","new","unchanged")
    need(wanted==(obs["counter_member_sha"] is not None),"unexpected or missing hardware event")
    pm=genuine_counter(z,folder,task,parents,executions,sdk,phase,obs["counter_member_sha"])
    return {"compilers":sum(ranks.values()),"wild":sum(r["signed_wild"] for r in links),"probes":len(orig),"pm":pm}


def scan(z,run,head,stage,slot):
    need(z.testzip() is None,"corrupt raw member CRC")
    infos=z.infolist()
    need(len(infos)==len(set(i.filename for i in infos)) and sum(i.file_size for i in infos)<80<<30 and all(
         i.file_size<8<<30 for i in infos),"unbounded/duplicate actual raw member")
    idx={}
    for name in z.namelist():
        f,sep,tid=name.rpartition("/trace/exec.")
        if sep and tid.isdigit():
            idx.setdefault(f,[]).append(name)
    end=read(z,"physical/complete.json")
    start=checked_json(z,"physical/entry.json",end["entry"])
    need(start["run"]==run and start["qa"]==head and start["stage"]==stage and start["assignment"]==assignment(stage,slot) and
         start["confirmation"]==t.CONFIRM and start["factory"]==t.BUILD and len(set(start["cpus"]))==4 and
         re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",start["boot"]),"incorrect measured assignment")
    roles=checked_json(z,"physical/physical-roles.json",end["physical"])
    proof=checked_json(z,"physical/source-qualification.json",start["source_qualification"])
    need(proof["build"]==t.BUILD and proof["build_qa"]==t.BUILD_QA and proof["confirmation"]==t.CONFIRM and
         proof["tar_sha"]==t.ARCHIVE and proof["source"]==t.capsule.REG["roles"]==start["roles"] and
         proof["contact"]==json.loads((HERE/"worker.json").read_bytes())["contact"] and
         roles["versions"]["P"]==roles["versions"]["C"] and roles["source_qualification"]==start["source_qualification"],
         "incorrect physical source, common version, or contact receipt")
    docs=checked_json(z,"physical/docs-qualification.json",start["documentation"])
    spec=json.loads((HERE/"source-equivalence.json").read_bytes())["source_docs"]
    need(docs["immutable"]==spec and [docs["archive"][k] for k in ("id","digest","size_in_bytes")]==spec["artifact"],
         "wrong original source documentation artifact")
    for role in ("P","C"):
        source=read(z,f"physical/source-receipts/{role}.json")
        original=(json.dumps(docs["actual"][role],sort_keys=True,indent=2)+"\n").encode()
        need(digest(original)==spec["receipts"][role],"documentation receipt disagrees with factory")
        key,_=doc_support.qualification(role,docs["actual"][role],source)
        observed=roles["documentation"][role]
        need(observed["rustdoc"]==key and observed["version"]==docs["actual"][role]["version"] and
             observed["source"]==digest(doc_support.DOC_SOURCE) and z.read(f"physical/doc-control-{role}/doc_input.rs")==doc_support.DOC_SOURCE and
             observed["html"]==digest(z.read(f"physical/doc-control-{role}/actual.html")) and all(
             observed["actual_libs"][k]["sha"]==roles["kits"][role][k]["sha"] for k in ("driver","llvm")),
             "different source documentation or HTML subject")
    for n,key in proof["receipt_hashes"].items():
        need(digest(z.read("physical/source-receipts/"+n))==key,"changed original source proof")
    hardware=calibration(z)
    bodies=verify_bytes(z)
    stats={}
    counts={}
    registry_input_audits={}
    total=Counter()
    for suite in start["assignment"]["suites"]:
        d="physical/"+suite+"/"
        st=end["suites"][suite]
        result=checked_json(z,d+"acquired.json",st["acquired"])
        reg=checked_json(z,d+"registry.json",st["registry"])
        need(set(result)=={"P","C"} and st["command"]==PLAN["suites"][suite]["cargo"] and reg["autocfg-1.5.0.crate"]==
             json.loads((HERE/"worker.json").read_bytes())["autocfg"],"different compiler/workload/registry")
        stats[suite]={}
        counts[suite]={}
        phases=("old","new","unchanged","invalid","repair","clean-new",*(("negative","restored-new") if suite=="e2e" else ()))
        need(st["phases"]==len(phases)*2,"unreported ordinary visits")
        for role in ("P","C"):
            enrolled=source_role(z,role,roles,proof)
            vals=result[role]
            need(set(vals)==set(phases),"incomplete independent native controls")
            en={}
            for phase in phases:
                history="edit" if phase in ("old","new","unchanged","invalid","repair") else "clean"
                folder=d+role+"-"+history+"/"+phase
                now=phase_read(z,folder,phase,suite,stage,role,vals[phase],enrolled,roles["sdk"],bodies,idx[folder])
                for n in ("compilers","wild","probes"):
                    total[n]+=now[n]
                total["ordinary"]+=1
                if now["pm"] is not None:
                    en[phase]=now["pm"]
            need(set(en)==({"old","new","unchanged"} if stage=="score" else set()),"wrong count window")
            counts[suite][role]=en
            for phase in ("new","unchanged","repair",*(("restored-new",) if suite=="e2e" else ())):
                need(all(vals[phase][n]==vals["clean-new"][n] for n in ("elf","verdict","inventory")),"different independent clean binary or verdict")
            need(vals["old"]["elf"]!=vals["new"]["elf"],"no observable real source change")
            stats[suite][role]={p:{n:vals[p][n] for n in ("dirty","raw_roster","elf","verdict","error") if n in vals[p]} for p in phases}
        groups={r:{s for v in rs.values() for s in v["compiler_namespace"]["ids"]} for r,rs in result.items()}
        need(len(groups["P"])==len(groups["C"])==1 and groups["P"]!=groups["C"],"missing stable role-specific compiler identity")
        for phase in phases:
            parent,candidate=result["P"][phase],result["C"][phase]
            dirs=parent["compiler_namespace"]["paths"]
            need(dirs==candidate["compiler_namespace"]["paths"] and
                 shards.comparable(parent,dirs)==shards.comparable(candidate,dirs),
                 "changed behavior/argv/roster outside the verified compiler identity")
        need(read(z,d+"cross-role.json")=={"shards":{r:sorted(v) for r,v in groups.items()},"mismatches":[],"own_clean_mismatches":[]},
             "different source-role comparison")
        if stage=="admit":
            registry_input_audits[suite]=extern_diff.scan(z,suite,dirs,{r:next(iter(v)) for r,v in groups.items()})
    return {"stage":stage,"slot":slot,"qa":head,"run":run,"factory":t.BUILD,"confirmation":t.CONFIRM,"boot":start["boot"],
            "assignment":start["assignment"],"terminal_sha":digest(z.read("physical/complete.json")),"roles":proof["physical"],
            "coverage":dict(total),"inputs":{s:end["suites"][s]["source"] for s in end["suites"]},"source_docs":spec,"comparison_of_role_generated_inputs":registry_input_audits,"behavior":stats,
            "bodies":{k:sorted(v) for k,v in bodies.items()},"calibration":hardware,"events":counts}


def main(stage,slot,output):
    run=int(os.environ["GITHUB_RUN_ID"]); head=os.environ["GITHUB_SHA"]
    t.run_identity(run,head,completed=False)
    arts=t.fetch(f"runs/{run}/artifacts?per_page=100")["artifacts"]
    rec=t.artifact(arts,f"ldv-physical-{stage}-originals-{slot}")
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        arc=Path(tmp)/"original.zip"
        row=t.acquire(rec,arc,8<<30)
        with zipfile.ZipFile(arc) as z:
            verdict=scan(z,run,head,stage,slot)
    t.save(output,{**verdict,"original_archive":row})
    print("Reopened all original physical source/ELF/command/event gates",stage,slot,verdict["coverage"],flush=True)


if __name__=="__main__":
    main(sys.argv[1],int(sys.argv[2]),Path(sys.argv[3]))
