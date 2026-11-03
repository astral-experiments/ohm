"""Run one off-clock, source-bound root split pilot on an unchanged ordinary Cargo command."""
import collections
import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import sys

HERE = Path(__file__).resolve().parent
LIB = HERE.parent
sys.path.insert(0,str(LIB))
import study as base
from member_names import native_identity, read_names
w, old, need = base.w, base.old, base.need
COMMAND = base.COMMAND
CRATES = ("ty_project", "ty_ide")
CASES = {
    "29697": (old.old,old.new,old.lock,"PC"),
    "29604": ("3bf4988cf062dc76895ff2f8421acf766172392b","dfe14506d23010aa5dbc4ff6fea702a22ba312bd",
              "46f8a4fa82d5ac6dfd4ebd9eabb399179f02ce5127a7addc1780e8fb4ff9c7d2","CP"),
}
def sessions():
    result={}
    for crate in CRATES:
        leaves=(w.target/"debug/incremental").glob("*/"+crate+"-*/s-*/work-products.bin")
        result[crate]={p.parent for p in leaves if p.is_file() and not p.parent.name.endswith("-working") and (p.parent/"dep-graph.bin").is_file()}
    return result

def snapshot(before, last, rows, directory, role, retain_raw):
    libraries=base.products(rows)
    after=sessions();data={}
    for crate in CRATES:
        changed=after[crate]-before[crate]
        if changed:
            need(len(changed)==1, ("multiple finalized codegen sessions",crate,changed))
            session,=changed
        else:
            session=last.get(crate)
            need(session in after[crate], ("missing previous finalized codegen session",crate,session))
        last[crate]=session
        objs={p.name:old.record_file(p) for p in sorted(session.glob("*.o")) if p.is_file() and not p.is_symlink()}
        lib=libraries[crate]["rlib"];named=read_names(lib,crate)
        actual={r[2]+".o":(r[3],r[4]) for r in named["members"]}
        need({n:(r["sha256"],r["bytes"]) for n,r in objs.items()}==actual and len(objs)>100,
             ("original and emitted physical CGUs disagree",crate))
        raw={}
        if retain_raw:
            data_paths = ["work-products.bin","query-cache.bin","dep-graph.bin"] if crate=="ty_project" else ["work-products.bin"]
            for name in data_paths:
                p=session/name;head=p.open("rb").read(7)
                need(head[:4]==b"RSIC" and int.from_bytes(head[4:6],"little")=={"P":24450,"C":48276}[role],("unregistered incremental format",crate,name,head))
                raw[name]=old.keep(p)
        # Preserve complete edited/fresh/saved native archives for independent byte-level admission.
        lib_digest=old.keep(lib) if retain_raw else {"sha256":w.hf(lib),"bytes":lib.stat().st_size}
        data[crate]={"session":str(session),"new":bool(changed),"objects":objs,"library":lib_digest,
                     "mapping":named,"metadata":[old.keep(p) for p in libraries[crate]["metadata"]]if retain_raw else [],"raw":raw}
    w.put(directory/"native.json",data)
    return data

def delta(before,after):
    a,b=before["objects"],after["objects"]
    groups=collections.defaultdict(list)
    for name in sorted(a.keys()|b.keys()):
        if name not in a: groups["added"].append(name);continue
        if name not in b: groups["removed"].append(name);continue
        older,newer=a[name],b[name];same=older["sha256"]==newer["sha256"] and older["bytes"]==newer["bytes"]
        if (older["dev"],older["ino"])==(newer["dev"],newer["ino"]):
            need(same and older["mtime_ns"]==newer["mtime_ns"],("mutated earlier native object",name))
            groups["retained"].append(name)
        elif same: groups["regenerated_equal"].append(name)
        else: groups["regenerated_changed"].append(name)
    result={cat:{"names":items, "old_bytes":sum(a[k]["bytes"] for k in items if k in a),
                 "new_bytes":sum(b[k]["bytes"] for k in items if k in b)} for cat,items in groups.items()}
    return result

def native_oracle(case,rows,env,td,rev):
    if case=="29697":
        return base.oracle(rows,env,td,rev)
    output=td/"oracle";output.mkdir()
    libs=base.products(rows)
    salsa,=(r for r in rows if r["target"]["name"]=="salsa" and r["target"]["kind"]==["lib"])
    sr,=(Path(f) for f in salsa["filenames"] if f.endswith(".rlib"))
    sm,=(Path(f) for f in salsa["filenames"] if f.endswith(".rmeta"))
    need(sr.is_file() and sm.is_file() and sr.stem==sm.stem,"mismatched selected Salsa rlib/rmeta pair")
    root=w.root/"lib-oracle";root.mkdir(exist_ok=True)
    exe=root/"consumer";source=root/"client.rs";shutil.copyfile(HERE/"revision.rs",source)
    deps=sorted({str(Path(f).parent) for row in rows for f in row["filenames"]})
    records=[json.loads(s) for s in (td/"stdout.jsonl").read_bytes().splitlines()]
    links=sorted({d for r in records if r["reason"]=="build-script-executed" for d in r["linked_paths"]})
    args=["rustc","+ohm",str(source),"--crate-name","ty_root_revision_oracle","--edition=2024","-Cdebuginfo=0"]
    for k,p in {**{k:v["rlib"] for k,v in libs.items()},"salsa":sr}.items(): args+=["--extern",k+"="+str(p)]
    args+=["--extern","salsa="+str(sm)]+["-Ldependency="+s for s in deps]+["-L"+s for s in links]+["-o",str(exe)]
    w.put(output/"argv.json",args)
    p=sp.run(args,cwd=w.work,env=env,capture_output=True);(output/"compile.stderr").write_bytes(p.stderr)
    need(p.returncode==0,("source-built held-out consumer",p.stderr[-2000:]))
    p=sp.run([exe],cwd=root,env=env,capture_output=True,timeout=60);(output/"stdout").write_bytes(p.stdout);(output/"stderr").write_bytes(p.stderr)
    expected=b"unrelated-preserved="+(b"false" if rev==old.old else b"true")+b"\nvendored-path=stdlib/os.pyi\n"
    need(p.returncode==0 and p.stdout==expected,("actual held-out source change",rev,p.returncode,p.stdout,p.stderr[-700:]))
    hits=[]
    with sp.Popen(["nm","--defined-only","--format=posix",exe],stdout=sp.PIPE) as name:
        for line in name.stdout:
            fields=line.decode(errors="replace").split()
            if len(fields)>=4 and fields[1] in ("t","T","w","W") and any(x in fields[0] for x in ("map_system_to_vendored","apply_changes","set_diagnostics","replace_index_diagnostics")):hits.append(fields)
        need(name.wait()==0 and all(any(s in f[0] for f in hits)for s in ("apply_changes","map_system_to_vendored")),"wrong private-edit native target")
    w.put(output/"linked-symbols.json",hits)
    return {"elf":old.keep(exe),"stdout":p.stdout.decode()}

def main():
    case=os.environ["OHM_OWNER_CASE"];old.old,old.new,old.lock,order=CASES[case]
    qa=Path(os.environ["GITHUB_WORKSPACE"])/"qa"
    need(os.environ["GITHUB_SHA"]==os.environ["REVIEWED_HEAD"]==sp.check_output(["git","-C",qa,"rev-parse","HEAD"],text=True).strip() and
         os.environ["GITHUB_RUN_ATTEMPT"]=="1" and os.environ["GITHUB_REF_NAME"]=="charlie/qa-ruff-root-owner-lanes-20261103","nonrelease QA source or attempt")
    need(w.git("rev-parse","HEAD")==old.new and w.git("rev-parse","HEAD^")==old.old and not w.git("diff","--name-only",old.old,old.new,"--","crates/ty_ide") and w.hf(w.work/"Cargo.lock")==old.lock,"different source or held client")
    w.guard();cfg=json.loads((HERE/"binding.json").read_bytes())
    w.put(w.proof/"registration.json",{"case":case,"source":[old.old,old.new],"order":order,"lock":old.lock,
      "command":COMMAND,"binding":cfg,"oracle":w.hf((LIB/"client.rs") if case=="29697" else (HERE/"revision.rs")),
      "boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"runner":os.environ["RUNNER_NAME"]})
    token=os.environ["OHM_SDK_READ_TOKEN"];env=w.install();roots=base.acquire(w,cfg,token);del token
    w.sdk.rename(w.root/"original-signed-reference")
    whole=w.root/"whole_count";trace=w.root/"exec_count"
    for tool in (whole,trace):sp.run(["cc","-O2","-Wall","-Wextra","-Werror",LIB.parent/(tool.name+".c"),"-o",tool],check=True)
    loop=w.root/"calibration.c";loop.write_text("#include <stdint.h>\n#include <stdlib.h>\nint main(int n,char **a){if(n!=2)return 2;uint64_t k=strtoull(a[1],0,10);volatile uint64_t v=1;for(uint64_t i=0;i<k;i++)v=3*v+i;return 0;}\n")
    calibration=w.root/"calibration";sp.run(["cc","-O2",loop,"-o",calibration],check=True)
    counts=[]
    for n in (1000000,4000000):
        d=w.proof/("calibration-"+str(n));d.mkdir();counts.append(old.count(whole,d,[calibration,str(n)],env,w.work))
    need(3.8<counts[1]/counts[0]<4.2,"inherited user-instruction calibration")
    state={"roster":None,"graph":None};summaries={};parked={}
    for index,role in enumerate(order):
        w.guard();old.remove_outputs();old.state(old.old);roots[role].rename(w.sdk);hist=w.proof/role;hist.mkdir()
        try:
            driver,=(w.sdk/"lib").glob("librustc_driver-*.so")
            need(w.hf(driver)==cfg["driver"][role],"different driver")
            w.put(hist/"tools.json",{"driver":old.record_file(driver),"cargo":old.record_file(w.sdk/"bin/cargo"),
                  "rustc":old.record_file(w.sdk/"bin/rustc"),"rustc_vV":sp.check_output(["rustc","+ohm","-vV"],env=env,text=True)})
            if index==0:sp.run(["cargo","+ohm","fetch","--locked","--target","x86_64-unknown-linux-gnu"],cwd=w.work,env=env,check=True)
            env["CARGO_NET_OFFLINE"]="true";g=base.unit_graph(env,hist)
            need(state["graph"] is None or state["graph"]==g,"different compiler dependency graph");state["graph"]=g
            last={}
            def phase(tag,revision,*,observer=False,native=False,snap=False,raw=False):
                w.guard();td=hist/tag;td.mkdir();prior=sessions() if snap else None;obs=None
                if observer:
                    tasks=td/"tasks";tasks.mkdir()
                    with (td/"stdout.jsonl").open("xb") as out,(td/"stderr").open("xb") as err:
                        sp.run([trace,tasks,*COMMAND],cwd=w.work,env=env,stdout=out,stderr=err,check=True)
                    obs=old.census(td,env);total=None
                else: total=old.count(whole,td,COMMAND,env,w.work)
                rows,_=old.result_rows(td,True);roster=old.corpus(rows)
                need(state["roster"] is None or state["roster"]==roster,"different Cargo source closure");state["roster"]=roster
                need(w.git("rev-parse","HEAD")==revision and w.hf(w.work/"Cargo.lock")==old.lock,"command source identity")
                products=snapshot(prior,last,rows,td,role,raw) if snap else {}
                out={"instructions":total,"observed":obs,"dirty":sorted(x["target"]["name"]for x in rows if not x["fresh"]),
                     "units":len(roster),"source":revision,"native":native_oracle(case,rows,env,td,revision) if native else None}
                w.put(td/"result.json",out)
                return out,products
            initial,be=phase("old",old.old,native=True,snap=True,raw=True);need(len(initial["dirty"])==len(state["roster"]),"OLD target was not empty")
            old_bytes=old.footprint();w.put(hist/"cold-footprint.json",old_bytes)
            held=w.root/("saved-"+role);shutil.copy2(w.root/"lib-oracle/consumer",held)
            settled,_=phase("old-settled",old.old);need(not settled["dirty"],"OLD no-op performed work")
            old.state(old.new)
            args=[held,w.root/"lib-oracle/fixture"] if case=="29697" else [held]
            p=sp.run(args,cwd=w.root,env=env|{"UV_OFFLINE":"1"},capture_output=True,check=True)
            need(p.stdout==initial["native"]["stdout"].encode(),"saved old program is not the old behavior")
            (hist/"stale-old-on-edited.stdout").write_bytes(p.stdout)
            edit,ae=phase("edit",old.new,native=True,snap=True,raw=True)
            settled,_=phase("unchanged",old.new);need(not settled["dirty"],"edited no-op performed work")
            changed={k:delta(be[k],ae[k])for k in CRATES};w.put(hist/"edit-retention.json",changed);w.put(hist/"edit-footprint.json",old.footprint())
            need(set(edit["dirty"])<={"ty_project","ty_ide"} and "ty_project" in edit["dirty"],"unexpected real edited Cargo roster")
            directory=hist/"invalid";directory.mkdir();path=w.work/"crates/ty_ide/src/lib.rs";saved=path.read_bytes()
            try:
                path.write_bytes(saved+b'\nconst _: u8 = "invalid";\n')
                with (directory/"stdout.jsonl").open("xb")as out,(directory/"stderr").open("xb")as err:
                    p=sp.run(COMMAND,cwd=w.work,env=env,stdout=out,stderr=err)
                _,errors=old.result_rows(directory,False)
                need(p.returncode==101 and any((r.get("message",{}).get("code")or{}).get("code")=="E0308" for r in errors if r["reason"]=="compiler-message"),"unchanged normal Cargo did not catch E0308")
            finally:path.write_bytes(saved)
            repaired,_=phase("repair",old.new,native=True)
            old.remove_outputs();last.clear();clean,ce=phase("independent-clean",old.new,native=True,snap=True,raw=True)
            need(len(clean["dirty"])==len(state["roster"]),"independent control was not fully empty")
            for k in CRATES:need(native_identity(ae[k]["mapping"])==native_identity(ce[k]["mapping"]),("independent clean codegen, member or archive index differs",k))
            need(edit["native"]["elf"]==clean["native"]["elf"]==repaired["native"]["elf"] and initial["native"]["elf"]!=edit["native"]["elf"],"complete native output does not match clean or edit behavior")
            report={"role":role,"primary":edit["instructions"],"cold":initial["instructions"],"cold_new":clean["instructions"],"noop":settled["instructions"],
                    "storage":old_bytes,
                    "native":{phase:item["native"]for phase,item in (("old",initial),("edited",edit),("clean",clean))},
                    "cgu_count":{k:len(ae[k]["objects"])for k in CRATES},"actual_dirty":edit["dirty"]}
            w.put(hist/"admitted.json",report);summaries[role]=report
            parked[role]=[]
            for directory in (w.target,w.shared):
                if not directory.exists() and directory==w.shared:continue
                need(directory.parent==w.root and directory.is_dir() and not directory.is_symlink(),"unsafe ordinary build state")
                directory.rename(w.root/("park-"+role+"-"+directory.name));parked[role].append(directory.name)
        finally:w.sdk.rename(roots[role])
    a,b=(summaries[k]for k in "PC")
    need(a["actual_dirty"]==b["actual_dirty"] and all(a["native"][k]["stdout"]==b["native"][k]["stdout"] for k in a["native"]),"compilers saw different edit or endpoint")
    class PublicMetadata:
        def read(self,name):
            if name.endswith("/native.json"):
                info=json.loads((w.proof/name).read_bytes())
                return json.dumps({"outputs":info}).encode()
            return (w.proof/name).read_bytes()
    public=base.inspect_metadata(PublicMetadata());w.put(w.proof/"public-states.json",public)
    need(public["equal_stable_identities_and_edit_key_sets"],"different consumer-visible source edit")
    for crate in CRATES:
        transition=public["within_role_transitions"][crate+"/edit-to-independent-clean"]
        for row in transition.values():
            need(not any(row["different_keys"]),("warm and fresh metadata changed different keys across compiler roles",crate))
    w.put(w.proof/"result.json",{"case":case,"roles":summaries,"whole_reduction":1-b["primary"]/a["primary"]})
    allowed={"HOME","PATH","USER","LANG","RUSTUP_HOME","CARGO_HOME","CARGO_TARGET_DIR","CARGO_BUILD_BUILD_DIR","CARGO_NET_GIT_FETCH_WITH_CLI","CARGO_NET_OFFLINE"}
    need(set(env)<=allowed,"unexpected field in private native diagnostic setup")
    w.put(w.root/"continuation.json",{"environment":env,"roots":{k:str(v) for k,v in roots.items()},"parked":parked})
if __name__=="__main__":
    main()
