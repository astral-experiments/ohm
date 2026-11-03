"""First independently admitted normal ty_ide library build pair for Ruff #29697."""
import hashlib,json,os,shutil,subprocess as sp,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;B=HERE.parent/"owner-buckets";sys.path.insert(0,str(B));sys.path.insert(0,str(HERE))
from member_names import read_names, native_identity
from public_states import inspect as inspect_metadata
import pilot as old
from kit import acquire
sys.path.insert(0,str(HERE.parent/"source-pcs/verified-29697"))
from reopen import ar
w=old.w;need=old.require
COMMAND=["cargo","+ohm","build","-p","ty_ide","--lib","--locked","--offline","-j4","--message-format=json"]
FOCUS={"ty_project","ty_ide"}
def blob(path):
    result=old.keep(path);need(result["bytes"]>0,"empty original");return result
def put(path,obj):w.put(path,obj)
def unit_graph(env,directory):
    cmd=COMMAND[:2]+["-Zunstable-options","build","--unit-graph"]+COMMAND[3:]
    p=sp.run(cmd,cwd=w.work,env=env,capture_output=True,check=True);g=json.loads(p.stdout)
    (directory/"unit-graph.json").write_bytes(p.stdout);units=g["units"];i,=g["roots"];u=units[i]
    need(u["target"]["name"]=="ty_ide" and u["target"]["kind"]==["lib"] and u["mode"]=="build","normal root mode")
    direct=[units[x["index"]]["target"]["name"]for x in u["dependencies"]]
    need("ty_project"in direct and not any(x["target"]["name"]in ("ty_server","e2e") or set(x["target"]["kind"])&{"test","bench","example"}for x in units),"different source/dependency closure")
    return hashlib.sha256(p.stdout).hexdigest()
def products(rows):
    out={}
    for k in ("ty_ide","ty_project","ruff_db"):
        row,=(x for x in rows if x["target"]["name"]==k and "lib"in x["target"]["kind"])
        rlibs=[Path(f)for f in row["filenames"]if f.endswith(".rlib")];need(len(rlibs)==1 and rlibs[0].is_file(),("unexpected native library",k,rlibs))
        out[k]={"rlib":rlibs[0],"metadata":[Path(f)for f in row["filenames"]if f.endswith(".rmeta")]}
    return out
def oracle(rows,sdk_env,td,revision):
    libs=products(rows);docs=[json.loads(x)for x in (td/"stdout.jsonl").read_bytes().splitlines()]
    deps=sorted({str(Path(f).parent)for x in rows for f in x["filenames"]})
    native=sorted({f for x in docs if x["reason"]=="build-script-executed"for f in x["linked_paths"]})
    root=w.root/"lib-oracle";root.mkdir(exist_ok=True);fixture=root/"fixture";fixture.mkdir(exist_ok=True)
    project=fixture/"script.py";source=b'#!/usr/bin/env -S uv run --script\n# /// script\n# requires-python = ">=3.11"\n# dependencies = []\n# ///\nprint("fixture")\n';project.write_bytes(source)
    path=root/"client.rs";shutil.copyfile(HERE/"client.rs",path);exe=root/"consumer"
    args=["rustc","+ohm",str(path),"--crate-name","ty_ide_owner_oracle","--edition=2024","-Cdebuginfo=0"]
    for name,files in libs.items():args+=["--extern",name+"="+str(files["rlib"])]
    args+=["-Ldependency="+v for v in deps]+["-L"+v for v in native]
    qa=td/"oracle";qa.mkdir()
    if revision==old.old:
        p=sp.run(args+["--emit=metadata","--error-format=json","-o",str(root/"missing.rmeta")],cwd=w.work,env=sdk_env,capture_output=True)
        (qa/"old-interface.stderr").write_bytes(p.stderr);er=[json.loads(v)for v in p.stderr.splitlines()]
        need(p.returncode==1 and any((v.get("code")or{}).get("code")=="E0599" and "scripts_to_synchronize"in v.get("message","") for v in er),"the new API must genuinely be absent on OLD")
        args+=["--cfg","old_build"]
    args+=["-o",str(exe)];put(qa/"argv.json",args)
    p=sp.run(args,cwd=w.work,env=sdk_env,capture_output=True);(qa/"compile.stderr").write_bytes(p.stderr);need(p.returncode==0,("native consumer compilation",p.stderr.decode(errors="replace")[-1600:]))
    ev=sdk_env|{"UV_OFFLINE":"1","NO_COLOR":"1"}
    p=sp.run([exe,fixture],cwd=root,env=ev,capture_output=True,timeout=60)
    (qa/"stdout").write_bytes(p.stdout);(qa/"stderr").write_bytes(p.stderr)
    want=(b"scripts=1\n"if revision==old.old else b"scripts=0\n")+b"scripts=1\nvendored-paths=3\n"
    need(p.returncode==0 and p.stdout==want,("actual script and path verdict",p.returncode,p.stdout,p.stderr[-700:]))
    found=[]
    with sp.Popen(["nm","--defined-only","--format=posix",exe],stdout=sp.PIPE)as proc:
        for line in proc.stdout:
            fields=line.decode(errors="replace").split()
            if len(fields)>=4 and fields[1] in ("T","t","W","w")and ("map_system_to_vendored"in fields[0] or "scripts_to_synchronize"in fields[0]):found.append(fields)
        need(proc.wait()==0,"native ELF name table")
    need(any("map_system_to_vendored"in x[0] for x in found) and any("scripts_to_synchronize"in x[0]for x in found)==(revision==old.new),"actual linked symbols")
    put(qa/"linked-symbols.json",found);return {"elf":blob(exe),"stdout":p.stdout.decode(),"inputs":{k:old.record_file(v["rlib"])for k,v in libs.items()}}
def snapshot(gen,rows,td):
    s=old.sessions();diff=set(s)-set(gen);need(len(diff)==1,("actual finalized ty_ide session",sorted(diff)))
    base=s[diff.pop()];o={x.name:old.record_file(x)for x in sorted(base.glob("*.o"))if not x.is_symlink()}
    need(len(o)>20,"missing genuine standalone codegen units")
    idx={x.name:old.record_file(x)for x in sorted(base.glob("*.bin"))};libs=products(rows)
    hashed={k:{"rlib":blob(v["rlib"]),"metadata":[blob(p)for p in v["metadata"]]}for k,v in libs.items()if k in FOCUS}
    if td.name in ("old","edit"):
        for n in ("dep-graph.bin","work-products.bin"):need(blob(base/n)["sha256"]==idx[n]["sha256"],"unstable CGU graph");idx[n]["body"]=idx[n]["sha256"]+".zst"
    members={}
    if td.name in ("old","edit","independent-clean"):
        for key in FOCUS:
            library=libs[key]["rlib"];counts=ar(library)
            names=sp.check_output(["ar","t",library]).decode().splitlines()
            join=read_names(library,key)
            need(names==[v[0]for v in join["metadata"]]+[v[0]for v in join["members"]],"literal archive names")
            if key=="ty_ide":
                need({v[2]+".o":(v[3],v[4])for v in join["members"]}=={n:(b["sha256"],b["bytes"])for n,b in o.items()},"named native objects differ from physical ty_ide session")
            members[key]={"names":names,"native_content":sorted((sha,size,n)for (sha,size),n in counts.items()),"bijection":join}
    put(td/"native.json",{"session":str(base),"objects":o,"indices":idx,"outputs":hashed,"members":members});return o
def main():
    need(os.environ["GITHUB_SHA"]==os.environ["REVIEWED_HEAD"] and os.environ["GITHUB_RUN_ATTEMPT"]=="1"and os.environ["GITHUB_REF_NAME"]=="charlie/qa-ruff-ty-ide-lib-29697-20261103","unregistered hosted target")
    qa=Path(os.environ["GITHUB_WORKSPACE"])/"qa";need(sp.check_output(["git","-C",qa,"rev-parse","HEAD"],text=True).strip()==os.environ["GITHUB_SHA"],"unregistered local sources")
    need(w.git("rev-parse","HEAD")==old.new and w.git("rev-parse","HEAD^")==old.old and not w.git("diff","--name-only",old.old,old.new,"--","crates/ty_ide"),"different historical edit")
    cfg=json.loads((B/"binding.json").read_bytes());w.guard()
    slot=int(os.environ["OHM_29697_LIB_SLOT"]);order=os.environ["OHM_29697_LIB_ORDER"]
    need(0<=slot<6 and order==("PC","CP","CP","PC","PC","CP")[slot],"unregistered physical order")
    timeline=[]
    put(w.proof/"registration.json",{"command":COMMAND,"slot":slot,"order":order,"runner":os.environ["RUNNER_NAME"],"run_id":int(os.environ["GITHUB_RUN_ID"]),"old":old.old,"new":old.new,"lock":old.lock,"factory":cfg,"kernel_boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"client":w.hf(HERE/"client.rs")})
    tok=os.environ["OHM_SDK_READ_TOKEN"];env=w.install();roots=acquire(w,cfg,tok);del tok;w.sdk.rename(w.root/"original-signed-reference")
    whole=w.root/"whole_count";trace=w.root/"exec_count"
    for tool in (whole,trace):sp.run(["cc","-O2","-Wall","-Wextra","-Werror",HERE.parent/(tool.name+".c"),"-o",tool],check=True)
    actor=w.root/"counter.c";actor.write_text('#include <stdlib.h>\n#include <stdint.h>\nint main(int n,char **a){if(n!=2)return 125;uint64_t k=strtoull(a[1],0,10);volatile uint64_t x=1;for(uint64_t i=0;i<k;i++)x=3*x+i;return 0;}\n')
    exe=w.root/"calibration";sp.run(["cc","-O2",actor,"-o",exe],check=True)
    controls=[]
    for n in (1000000,4000000):
        td=w.proof/("calibration-"+str(n));td.mkdir();controls.append(old.count(whole,td,[exe,str(n)],env,w.work))
    need(3.8<controls[1]/controls[0]<4.2,"calibration");roster=graph=None;records=[]
    for idx,role in enumerate(order):
        start=time.monotonic_ns()
        w.guard();old.remove_outputs();old.state(old.old);roots[role].rename(w.sdk)
        hist=w.proof/role;hist.mkdir()
        try:
            files={"rustc":w.sdk/"bin/rustc","cargo":w.sdk/"bin/cargo","wild":w.sdk/"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"}
            driver,=(w.sdk/"lib").glob("librustc_driver-*.so");need(w.hf(driver)==cfg["driver"][role],"unregistered driver")
            put(hist/"tools.json",{"driver":old.record_file(driver),"physical":{k:old.record_file(p)for k,p in files.items()},"versions":{k:sp.check_output([k,"+ohm","-vV"],cwd=w.work,env=env,text=True)for k in ("rustc","cargo")}})
            if idx==0:sp.run(["cargo","+ohm","fetch","--locked","--target","x86_64-unknown-linux-gnu"],cwd=w.work,env=env,check=True)
            env["CARGO_NET_OFFLINE"]="true"
            g=unit_graph(env,hist);need(graph is None or g==graph,"different normal P/C dependency resolution");graph=g
            def phase(n,revision,mode="whole",snap=False,native=False):
                nonlocal roster
                w.guard();td=hist/n;td.mkdir();before=old.sessions()if snap else {}
                if mode=="whole":instructions=old.count(whole,td,COMMAND,env,w.work);obs=None
                else:
                    instructions=None;tasks=td/"tasks";tasks.mkdir()
                    with (td/"stdout.jsonl").open("xb")as out,(td/"stderr").open("xb")as err:sp.run([trace,tasks,*COMMAND],cwd=w.work,env=env,stdout=out,stderr=err,check=True)
                    obs=old.census(td,env)
                rows,_=old.result_rows(td,True);u=sorted((r["package_id"],r["target"]["name"],r["target"]["kind"],sorted(r["features"]),json.dumps(r["profile"],sort_keys=True))for r in rows);need(roster is None or u==roster,"different physical Cargo roster");roster=u
                need({"ty_project","ty_ide","ruff_db"}<={r["target"]["name"]for r in rows} and not ({"e2e","ty_server"}&{r["target"]["name"]for r in rows}),"standalone normal Cargo closure")
                dirty=sorted(r["target"]["name"]for r in rows if not r["fresh"]);o=snapshot(before,rows,td)if snap else None
                r={"instructions":instructions,"observed":obs,"dirty":dirty,"units":len(u),"source":w.git("rev-parse","HEAD"),"oracle":oracle(rows,env,td,revision)if native else None}
                need(r["source"]==revision,n+" source");put(td/"result.json",r);return r,o
            initial,be=phase("old",old.old,snap=True,native=True);need(len(initial["dirty"])==len(roster),"OLD target not empty")
            held=w.root/("held-"+role);shutil.copy2(w.root/"lib-oracle/consumer",held);old.state(old.new)
            check=sp.run([held,w.root/"lib-oracle/fixture"],cwd=w.root,env=env|{"UV_OFFLINE":"1"},capture_output=True,check=True);(hist/"old-client-on-new.stdout").write_bytes(check.stdout);need(check.stdout==b"scripts=1\nscripts=1\nvendored-paths=3\n","stale observable")
            updated,ae=phase("edit",old.new,snap=True,native=True);noop,_=phase("unchanged",old.new);need(set(updated["dirty"])==FOCUS and not noop["dirty"],"standalone changed/noop roster")
            contact=old.classifier(be,ae);put(hist/"retention.json",contact);put(hist/"footprint.json",old.footprint())
            invalid=hist/"invalid";invalid.mkdir();source=w.work/"crates/ty_ide/src/lib.rs";saved=source.read_bytes()
            try:
                source.write_bytes(saved+b'\nconst _: u8 = "invalid";\n')
                with (invalid/"stdout.jsonl").open("xb")as out,(invalid/"stderr").open("xb")as err:p=sp.run(COMMAND,cwd=w.work,env=env,stdout=out,stderr=err)
                _,errors=old.result_rows(invalid,False);need(p.returncode==101 and any((r.get("message",{}).get("code")or{}).get("code")=="E0308"for r in errors if r["reason"]=="compiler-message"),"real E0308")
            finally:source.write_bytes(saved)
            repair,_=phase("repair",old.new,native=True);old.state(old.old);op,ob=phase("observed-old",old.old,"trace",snap=True);old.state(old.new);oc,oa=phase("observed-edit",old.new,"trace",snap=True)
            need(sorted(oc["observed"]["real_execs"])==["rustc:ty_ide","rustc:ty_project"],"the normal library build must run two actual compilers and no native linker")
            confirmed=old.classifier(ob,oa);put(hist/"observed-retention.json",confirmed);co,_=phase("observed-unchanged",old.new,"trace");need(not co["dirty"] and not co["observed"]["real_execs"],"physical unchanged work")
            old.remove_outputs();fresh,fo=phase("independent-clean",old.new,snap=True,native=True)
            need(len(fresh["dirty"])==len(roster) and ae.keys()==fo.keys() and all(ae[n]["sha256"]==fo[n]["sha256"]for n in ae),"fresh physical standalone native output")
            warm=json.loads((hist/"edit/native.json").read_bytes())["members"];empty=json.loads((hist/"independent-clean/native.json").read_bytes())["members"]
            for crate in sorted(FOCUS):
                need(warm[crate]["native_content"]==empty[crate]["native_content"] and native_identity(warm[crate]["bijection"])==native_identity(empty[crate]["bijection"]),"actual named native members, link records, symbol maps or order differ from empty")
            need(updated["oracle"]["elf"]==repair["oracle"]["elf"]==fresh["oracle"]["elf"] and initial["oracle"]["elf"]!=updated["oracle"]["elf"],"complete standalone client differs from empty or repair")
            report={"role":role,"primary":updated["instructions"],"cold":initial["instructions"],"noop":noop["instructions"],"old":initial["oracle"]["elf"],"new":updated["oracle"]["elf"],"retained":len(contact["retained"]),"objects":len(ae),"units":len(roster),"same_observed_retention":contact==confirmed,"observed":oc["observed"]};put(hist/"qualified.json",report);records.append(report)
        finally:w.sdk.rename(roots[role])
        timeline.append({"role":role,"begin_ns":start,"end_ns":time.monotonic_ns()})
    put(w.proof/"sequence.json",timeline)
    by_role={r["role"]:r for r in records};p,c=by_role["P"],by_role["C"];need(p["old"]==c["old"] and p["new"]==c["new"],"complete native consumer differs across source compilers")
    need(p["old"]["sha256"]=="2407856bb255264e0dca8dbd9ef31ccfbaffeb1c2bfe800543d98b899db2ca6a" and p["new"]["sha256"]=="3755b8bab1d87e837a2d671d4a6c2333059d05f877e2f7e0940cf3b276d7e24f","mismatch with the calibrated actual clients")
    class Directory:
        def read(self, name):
            return (w.proof/name).read_bytes()
    public=inspect_metadata(Directory());put(w.proof/"public-transitions.json",public)
    need(public["equal_stable_identities_and_edit_key_sets"],"different logical edit in source-matched roles")
    for role in order:
        for phase in ("edit","independent-clean"):
            named=json.loads((w.proof/role/phase/"native.json").read_bytes())["members"]
            for crate,expected in (("ty_ide",(171,4199)),("ty_project",(245,7276))):
                m=named[crate]["bijection"];need((len(m["members"]),m["symbols"])==expected,"different native archive/codegen unit closure")
    put(w.proof/"terminal.json",{"roles":records,"reduction":1-c["primary"]/p["primary"],"additional_objects":c["retained"]-p["retained"]})
if __name__=="__main__":main()
