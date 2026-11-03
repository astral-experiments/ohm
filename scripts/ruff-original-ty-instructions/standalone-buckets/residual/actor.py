"""Attribute the two real compiler invocations from the verified ordinary Ruff library edit."""
import collections
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
LIB=HERE.parent
PC=LIB.parent/"source-pcs"
sys.path.insert(0,str(LIB))
import study as library
w=library.w
old=library.old
need=library.need
put=library.put
spec=importlib.util.spec_from_file_location("qualified_pcs",PC/"study.py")
sys.path.insert(0,str(PC))
pcs=importlib.util.module_from_spec(spec);spec.loader.exec_module(pcs)
registration=json.loads((HERE/"registration.json").read_bytes())
assets=json.loads((LIB/"evidence-29697-six/reopened.json").read_bytes())
want=registration["command"]
need(want==library.COMMAND,"changed native command")


def work_products(crate):
    return {p.parent for p in (w.target/"debug/incremental").glob("*/"+crate+"-*/s-*/work-products.bin")
            if not p.parent.name.endswith("-working") and (p.parent/"dep-graph.bin").is_file()}


def tool_owners(td, tools):
    images={}; deltas=collections.Counter(); threads=collections.defaultdict(set); unclocked=collections.Counter()
    for line in (td/"tasks/epochs.tsv").read_text().splitlines():
        f=line.split()
        if f[0]=="I":
            i,pid,tid,t=map(int,f[1:5]);cells=(td/f"tasks/{i:05}.nul").read_bytes().split(b"\0")
            need(cells.pop()==b"" and int(cells[0])==pid,"original exec vector")
            ident=tuple(map(int,cells[1:3]));argv=[os.fsdecode(a) for a in cells[4:]]
            if ident==tuple(tools["rustc"][x]for x in ("dev","ino")) and "--crate-name"in argv:
                k=argv[argv.index("--crate-name")+1]
            elif ident==tuple(tools["wild"][x]for x in ("dev","ino")):k="wild"
            else:continue
            images[i]={"name":k,"pid":pid,"start_ns":t,"epoch":i,"argv":argv,"reason":f[5]}
        elif f[0]=="C":
            i,pid,tid,c,en,r=map(int,f[1:]);need(en==r and c>=0,"kernel counter multiplexing")
            if c and not en:unclocked[i]+=c
            deltas[i]+=c;threads[i].add(tid)
    owners={}
    for i,v in images.items():
        if v["reason"]!="exec":continue
        k=v["name"];need(k not in owners,"duplicate real rustc")
        owners[k]=v|{"instructions":deltas[i],"threads":sorted(threads[i]),"unclocked":unclocked[i]}
    return owners


def main():
    need(os.environ["GITHUB_REF_NAME"]==registration["branch"] and os.environ["GITHUB_SHA"]==os.environ["REVIEWED_HEAD"]
         and os.environ["GITHUB_RUN_ATTEMPT"]=="1","unregistered nonrelease worker")
    need(w.git("rev-parse","HEAD")==old.new and w.git("rev-parse","HEAD^")==old.old and not w.git("diff","--name-only",old.old,old.new,"--","crates/ty_ide"),"genuine edit/source")
    need(subprocess.check_output(["git","-C",Path(os.environ["GITHUB_WORKSPACE"])/"qa","rev-parse","HEAD"],text=True).strip()==os.environ["GITHUB_SHA"],"receiver source")
    cfg=json.loads((library.B/"binding.json").read_bytes());w.guard();token=os.environ["OHM_SDK_READ_TOKEN"]
    env=w.install();roots=library.acquire(w,cfg,token);del token
    w.sdk.rename(w.root/"signed-reference");roots["C"].rename(w.sdk)
    driver,=(w.sdk/"lib").glob("librustc_driver-*.so")
    tools={k:old.record_file(p) for k,p in {"driver":driver,"rustc":w.sdk/"bin/rustc","cargo":w.sdk/"bin/cargo","wild":w.sdk/"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"}.items()}
    need(tools["driver"]["sha256"]==registration["candidate_driver"]==cfg["driver"]["C"],"wrong measured source-built driver")
    tools["driver"]["path"]=str(driver)
    put(w.proof/"registered.json",registration|{"sha":os.environ["GITHUB_SHA"],"boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"tools":tools})
    trace=w.root/"exec_count";subprocess.run(["cc","-O2","-Wall","-Wextra","-Werror",LIB.parent/"exec_count.c","-o",trace],check=True)
    old.remove_outputs();old.state(old.old)
    subprocess.run(["cargo","+ohm","fetch","--locked","--target","x86_64-unknown-linux-gnu"],cwd=w.work,env=env,check=True)
    env["CARGO_NET_OFFLINE"]="true";need(set(env)<={"HOME","PATH","USER","LANG","RUSTUP_HOME","CARGO_HOME","CARGO_TARGET_DIR","CARGO_BUILD_BUILD_DIR","CARGO_NET_GIT_FETCH_WITH_CLI","CARGO_NET_OFFLINE"},"unexpected original environment")
    graph=library.unit_graph(env,w.proof);need(w.hf(w.proof/"unit-graph.json")==registration["graph_sha256"],"different graph")
    perf=pcs.prepare(w,env,trace);raw=w.root/"actual-compiled-edit.perf"
    membership=None;stages={};owners_by_stage={}
    def phase(group,name,revision,kind="plain",snapshot=True,verify_client=True):
        nonlocal membership
        w.guard();td=w.proof/group/name;td.mkdir(parents=True);key=group+"/"+name
        before={k:work_products(k)for k in ("ty_ide","ty_project")} if snapshot else {}
        command=want
        if kind!="plain":
            tasks=td/"tasks";tasks.mkdir();command=[trace,tasks,*want]
        if kind=="sampled":command=pcs.record(perf,raw,env,command)
        with (td/"stdout.jsonl").open("xb")as out,(td/"stderr").open("xb")as err:
            subprocess.run(command,cwd=w.work,env=env,stdout=out,stderr=err,check=True)
        if kind=="sampled":pcs.preserve_profile(w,raw)
        rows,_=old.result_rows(td,True);current=sorted((r["package_id"],r["target"]["name"],r["target"]["kind"],sorted(r["features"]),json.dumps(r["profile"],sort_keys=True))for r in rows)
        need(len(current)==259 and (membership is None or membership==current),"different typed native build");membership=current
        dirty=sorted(r["target"]["name"]for r in rows if not r["fresh"])
        if name=="edit":need(dirty==["ty_ide","ty_project"],"different edit")
        if group=="empty" or (group=="ordinary" and name=="old"):need(len(dirty)==259,"expected genuine empty build")
        if name=="unchanged":need(not dirty,"unexpected unchanged work")
        need(w.git("rev-parse","HEAD")==revision,"wrong commit")
        detail={"dirty":dirty,"source":revision}
        if snapshot:
            library.snapshot({str(p):p for p in before["ty_ide"]},rows,td)
            project,=work_products("ty_project")-before["ty_project"]
            objects={p.name:old.record_file(p) for p in sorted(project.glob("*.o")) if not p.is_symlink()}
            need(len(objects)==245,"project native inventory")
            j={"objects":objects,"session":str(project)}
            if name in ("old","edit"):
                j["raw"]={n:old.keep(project/n)for n in ("dep-graph.bin","work-products.bin")}
            put(td/"project-session.json",j)
        if verify_client:
            detail["oracle"]=library.oracle(rows,env,td,revision)
            need(detail["oracle"]["elf"]["sha256"]==registration["old_elf" if revision==old.old else "new_elf"],"wrong complete public client")
        if kind!="plain":
            obs=old.census(td,env);detail["observed"]=obs
            own=tool_owners(td,tools);put(td/"actual-processes.json",own)
            if name=="edit":need(set(own)=={"ty_ide","ty_project"} and sorted(obs["real_execs"])==["rustc:ty_ide","rustc:ty_project"],"unexpected native compile or link")
            if name=="unchanged":need(not own and not obs["real_execs"],"unexpected native unchanged")
            owners_by_stage[key]=own
        put(td/"result.json",detail);stages[key]=detail
    phase("ordinary","old",old.old)
    old.state(old.new);phase("ordinary","edit",old.new,"trace");phase("ordinary","unchanged",old.new,"trace",False,False)
    old.state(old.old);phase("sampled","old",old.old)
    old.state(old.new);phase("sampled","edit",old.new,"sampled");phase("sampled","unchanged",old.new,"trace",False,False)
    before=owners_by_stage["ordinary/edit"];after=owners_by_stage["sampled/edit"]
    for k in before:
        need(before[k]["argv"]==after[k]["argv"] and before[k]["unclocked"]==after[k]["unclocked"]==0,"noncomparable clock/driver argv")
        need(abs(after[k]["instructions"]/before[k]["instructions"]-1)<.04 and abs(before[k]["instructions"]/registration["approximate_process_instruction_baselines"][k]-1)<.05,"different work envelope")
    invalid=w.proof/"invalid";invalid.mkdir();file=w.work/"crates/ty_ide/src/lib.rs";saved=file.read_bytes()
    try:
        file.write_bytes(saved+b'\nconst _: u8 = "invalid";\n')
        with (invalid/"stdout.jsonl").open("xb")as out,(invalid/"stderr").open("xb")as err:
            rc=subprocess.run(want,cwd=w.work,env=env,stdout=out,stderr=err).returncode
        _,fail=old.result_rows(invalid,False);need(rc==101 and any((x.get("message",{}).get("code")or{}).get("code")=="E0308"for x in fail if x["reason"]=="compiler-message"),"invalid verdict")
    finally:file.write_bytes(saved)
    phase("sampled","repair",old.new,snapshot=False)
    old.remove_outputs();phase("empty","independent-clean",old.new)
    load=lambda p:json.loads((w.proof/p).read_bytes())
    retention={}
    for group in ("ordinary","sampled"):
        a=load(group+"/old/native.json");b=load(group+"/edit/native.json");fresh=load("empty/independent-clean/native.json")
        for crate,ns in (("ty_ide",(171,4199)),("ty_project",(245,7276))):
            old_m=a["members"][crate]["bijection"];new_m=b["members"][crate]["bijection"];clean_m=fresh["members"][crate]["bijection"]
            need((len(new_m["members"]),new_m["symbols"])==ns and library.native_identity(clean_m)==library.native_identity(new_m),"changed native member/lookup")
            x,y=(s["objects"]for s in ([a,b] if crate=="ty_ide"else [load(group+"/"+n+"/project-session.json")for n in ("old","edit")]))
            need(x.keys()==y.keys(),"different CGU set")
            changed=[n for n in x if x[n]["sha256"]!=y[n]["sha256"]]
            kept=[n for n in x if (x[n]["dev"],x[n]["ino"],x[n]["mtime_ns"],x[n]["sha256"])==(y[n]["dev"],y[n]["ino"],y[n]["mtime_ns"],y[n]["sha256"])]
            need(len(changed)==(0 if crate=="ty_ide"else 2) and (crate!="ty_ide" or len(kept)==171),"wrong physical cohort")
            retention[group,crate]={"kept":sorted(kept),"different_native":sorted(changed),"recompiled":sorted(set(x)-set(kept))}
        if group=="sampled":
            for crate in ("ty_ide","ty_project"):need(retention["ordinary",crate]==retention["sampled",crate],"changed sampled donors")
    class Paths:
        def read(self,name):
            if name.startswith(("P/","C/")):
                r,n,f=name.split("/");name=("empty" if n=="independent-clean" else {"P":"ordinary","C":"sampled"}[r])+"/"+n+"/"+f
            return (w.proof/name).read_bytes()
    metadata=library.inspect_metadata(Paths());put(w.proof/"public-transitions.json",metadata);need(metadata["equal_stable_identities_and_edit_key_sets"],"different real public changes")
    for crate in ("ty_project","ty_ide"):
        for g in ("ordinary","sampled"):
            info=load(g+"/edit/native.json");m=info["members"][crate]["bijection"];need(len(m["members"])in(171,245),"warm actual member custody")
    put(w.proof/"native-admission.json",{"retention":{"/".join(k):v for k,v in retention.items()},"raw":w.hf(raw),"owners":{r:{k:v["instructions"]for k,v in owners_by_stage[r+"/edit"].items()}for r in ("ordinary","sampled")},"client":[registration["old_elf"],registration["new_elf"]],"stage_roster":{k:v["dirty"] for k,v in stages.items()}})
    cap=w.proof/"pc-readback";n=pcs.perf.decode(perf,raw,cap)
    out=subprocess.run([*pcs.perf.private_argv(perf),"buildid-list","--with-hits","-i",raw],env=pcs.perf.clean_subprocess(),capture_output=True,check=True)
    (cap/"buildids.txt").write_bytes(out.stdout);(cap/"buildids.stderr").write_bytes(out.stderr)
    for k,min_samples in (("ty_project",10000),("ty_ide",3000)):
        dest=cap/k;dest.mkdir();(dest/"exec").mkdir()
        shutil.copyfile(w.proof/"sampled/edit/tasks/epochs.tsv",dest/"exec/epochs.tsv")
        for f in ("record-counts.json","samples.ndjson.gz","buildids.txt"):(dest/f).hardlink_to(cap/f)
        put(dest/"owner-epochs.json",{k:after[k]})
        pcs.semantic_pcs.analyze(raw,dest,{"driver":tools["driver"]},min_samples,owner=k)
    put(w.proof/"closed.json",{"sample_count":n,"driver":tools["driver"]["sha256"],"two_compilers":True,"all_native_and_source_controls":True})


if __name__=="__main__":
    main()
